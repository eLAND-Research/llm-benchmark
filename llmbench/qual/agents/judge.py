"""Judge agent -- uses a strong LLM to score Executor responses.

The Judge is an LLM-powered agent.  For every :class:`LLMResponse` it
constructs a structured prompt (system + scoring rubric) and asks the
judge model to return a ``{"score": int, "reasoning": str}`` JSON object.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Dict, List

from openai import AsyncOpenAI
from openai import RateLimitError

from llmbench.qual.config import JudgeConfig
from llmbench.qual.prompts.judge import JUDGE_SCORE_PROMPT, JUDGE_SYSTEM_PROMPT
from llmbench.qual.schemas import (
    BenchmarkDataset,
    BenchmarkItem,
    JudgeScore,
    LLMResponse,
)

logger = logging.getLogger(__name__)

# Fallback score when the judge model returns unparseable output after retry.
_DEFAULT_SCORE = 3


_DEFAULT_REASONING = "Judge 模型回傳格式無法解析，給予預設分數。"
_RATE_LIMIT_REASONING = "Judge 模型遇到 rate limit，給予預設分數。"
_MAX_RAW_PREVIEW = 300
_RATE_LIMIT_RETRIES = 2


@dataclass
class _JudgeCallResult:
    score: int | None
    reasoning: str
    should_retry: bool = False


def _rule_score_true_false(
    item: BenchmarkItem,
    response: LLMResponse,
) -> "_JudgeCallResult | None":
    """Rule-based scoring for true_false — no LLM call needed."""
    import re as _re
    from llmbench.qual.schemas import TaskType
    if item.task_type != TaskType.TRUE_FALSE or not item.reference_answer:
        return None
    try:
        ref = json.loads(item.reference_answer)
    except Exception:
        return None
    correct = str(ref.get("answer") or "").strip().upper()
    if correct not in ("TRUE", "FALSE"):
        return None

    raw = (response.response_text or response.error or "").strip().upper()
    m = _re.search(r"\b(TRUE|FALSE)\b", raw)
    answered = m.group(1) if m else ""

    if not answered:
        return _JudgeCallResult(score=1, reasoning=f"模型未作答或格式錯誤（回答：{raw[:50]}）")
    if answered == correct:
        return _JudgeCallResult(score=5, reasoning=f"正確（{correct}）")
    return _JudgeCallResult(score=1, reasoning=f"錯誤（回答 {answered}，正確答案 {correct}）")


def _rule_score_school_qa(
    item: BenchmarkItem,
    response: LLMResponse,
) -> "_JudgeCallResult | None":
    """Rule-based scoring for school_qa MCQ — no LLM call needed."""
    import re as _re
    from llmbench.qual.schemas import TaskType
    if item.task_type != TaskType.SCHOOL_QA or not item.reference_answer:
        return None
    try:
        ref = json.loads(item.reference_answer)
    except Exception:
        return None
    if ref.get("type") != "選擇題":
        return None
    correct = str(ref.get("answer") or "").strip().upper()
    if not correct or correct not in "ABCD":
        return None

    raw_resp = (response.response_text or response.error or "").strip()
    m = _re.search(r"\b([A-Da-d])\b", raw_resp)
    answered = m.group(1).upper() if m else ""

    if not answered:
        return _JudgeCallResult(score=1, reasoning=f"模型未作答或格式錯誤（回答：{raw_resp[:50]}）")
    if answered == correct:
        return _JudgeCallResult(score=5, reasoning=f"答案正確（{correct}）")
    return _JudgeCallResult(score=1, reasoning=f"答案錯誤（回答 {answered}，正確答案 {correct}）")


def _preview_text(text: str, limit: int = _MAX_RAW_PREVIEW) -> str:
    raw = (text or "").strip().replace("\r", "\\r").replace("\n", "\\n")
    if len(raw) <= limit:
        return raw
    return raw[:limit] + "..."


class Judge:
    """Evaluate LLM responses using a judge model.

    Parameters
    ----------
    config:
        :class:`JudgeConfig` containing the judge model settings and
        concurrency limit.
    """

    def __init__(self, config: JudgeConfig) -> None:
        self.config = config
        self._request_lock = asyncio.Lock()
        self._last_request_started_at = 0.0

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def evaluate(
        self,
        dataset: BenchmarkDataset,
        responses: List[LLMResponse],
    ) -> List[JudgeScore]:
        """Score every response in *responses* against the dataset items.

        Concurrency is controlled by ``config.max_concurrent``.

        Returns
        -------
        list[JudgeScore]
            One score per response (skipping responses that have errors).
        """
        item_map: Dict[str, BenchmarkItem] = {item.id: item for item in dataset.items}

        model_cfg = self.config.model
        api_key = model_cfg.api_key if model_cfg.api_key else "not-needed"
        client = AsyncOpenAI(
            base_url=model_cfg.base_url,
            api_key=api_key,
            max_retries=0,
        )
        semaphore = asyncio.Semaphore(self.config.max_concurrent)

        logger.info(
            "Judge: evaluating %d responses with model %s (concurrency=%d, min_interval=%.2fs)",
            len(responses),
            model_cfg.name,
            self.config.max_concurrent,
            self.config.min_request_interval_sec,
        )

        tasks = [
            self._evaluate_one(client, item_map, response, semaphore)
            for response in responses
        ]
        scores = await asyncio.gather(*tasks, return_exceptions=False)

        logger.info("Judge: finished -- %d scores produced", len(scores))
        return scores

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _evaluate_one(
        self,
        client: AsyncOpenAI,
        item_map: Dict[str, BenchmarkItem],
        response: LLMResponse,
        semaphore: asyncio.Semaphore,
    ) -> JudgeScore:
        """Score a single :class:`LLMResponse`.

        If the response itself recorded an error, it is still sent to the
        judge (with the error text as the response) so every entry gets a
        score.
        """
        item = item_map[response.benchmark_item_id]

        # Fast rule-based scoring — no LLM call needed
        rule_score = _rule_score_true_false(item, response) or _rule_score_school_qa(item, response)
        if rule_score is not None:
            return JudgeScore(
                benchmark_item_id=response.benchmark_item_id,
                model_name=response.model_name,
                score=rule_score.score,
                reasoning=rule_score.reasoning,
                judge_model="rule-based",
            )

        messages = self._build_messages(item, response)
        model_name = self.config.model.model
        judge_display_name = self.config.model.name

        async with semaphore:
            # First attempt
            result = await self._call_judge(client, model_name, messages)

            # Retry once on parse failure
            if result.should_retry:
                logger.warning(
                    "Judge: retry for item=%s model=%s (first attempt unparseable)",
                    response.benchmark_item_id,
                    response.model_name,
                )
                result = await self._call_judge(client, model_name, messages)

            # Final fallback
            if result.score is None:
                logger.error(
                    "Judge: giving default score for item=%s model=%s",
                    response.benchmark_item_id,
                    response.model_name,
                )
                result.score = _DEFAULT_SCORE
                result.reasoning = result.reasoning or _DEFAULT_REASONING

            logger.debug(
                "Judge: item=%s model=%s score=%d",
                response.benchmark_item_id,
                response.model_name,
                result.score,
            )

            return JudgeScore(
                benchmark_item_id=response.benchmark_item_id,
                model_name=response.model_name,
                score=result.score,
                reasoning=result.reasoning,
                judge_model=judge_display_name,
            )

    # ------------------------------------------------------------------
    # Prompt construction
    # ------------------------------------------------------------------

    @staticmethod
    def _build_messages(
        item: BenchmarkItem,
        response: LLMResponse,
    ) -> list[dict[str, str]]:
        """Assemble the chat messages list for the judge call."""
        reference = item.reference_answer or "（無參考答案）"
        response_text = response.response_text if response.response_text else (
            f"（呼叫失敗：{response.error}）"
        )

        user_content = JUDGE_SCORE_PROMPT.format(
            task_type=item.task_type.value,
            prompt=item.prompt,
            reference_answer=reference,
            response=response_text,
            scoring_rubric=item.scoring_rubric,
        )

        return [
            {"role": "system", "content": JUDGE_SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
        ]

    # ------------------------------------------------------------------
    # LLM call + JSON parsing
    # ------------------------------------------------------------------

    async def _call_judge(
        self,
        client: AsyncOpenAI,
        model: str,
        messages: list[dict[str, str]],
    ) -> _JudgeCallResult:
        """Call the judge model and try to parse the JSON response.

        Retries are only useful for malformed JSON. API failures such as 429
        should not be retried immediately because they consume time without
        increasing the chance of success.
        """
        raw = ""
        for attempt in range(_RATE_LIMIT_RETRIES + 1):
            try:
                await self._await_request_slot()
                completion = await client.chat.completions.create(
                    model=model,
                    messages=messages,
                    temperature=0.0,
                    max_completion_tokens=300,
                )
                raw = completion.choices[0].message.content or ""
                break
            except RateLimitError as exc:
                logger.error("Judge: API rate limit hit (attempt %d): %s", attempt + 1, exc)
                if attempt >= _RATE_LIMIT_RETRIES:
                    return _JudgeCallResult(
                        score=None,
                        reasoning=_RATE_LIMIT_REASONING,
                        should_retry=False,
                    )
                delay = _extract_rate_limit_delay(str(exc))
                await asyncio.sleep(delay)
            except Exception as exc:  # noqa: BLE001
                logger.error("Judge: API call failed: %s", exc)
                return _JudgeCallResult(score=None, reasoning="", should_retry=False)

        score, reasoning = _parse_judge_response(raw)
        return _JudgeCallResult(
            score=score,
            reasoning=reasoning,
            should_retry=(score is None),
        )

    async def _await_request_slot(self) -> None:
        """Throttle judge calls so the shared API key stays below RPM limits."""
        async with self._request_lock:
            interval = max(0.0, float(self.config.min_request_interval_sec))
            now = time.monotonic()
            wait_time = interval - (now - self._last_request_started_at)
            if wait_time > 0:
                await asyncio.sleep(wait_time)
            self._last_request_started_at = time.monotonic()


# ------------------------------------------------------------------
# Module-level helpers
# ------------------------------------------------------------------


def _parse_judge_response(raw: str) -> tuple[int | None, str]:
    """Parse the raw judge output into ``(score, reasoning)``.

    The expected format is::

        {"score": <1-5>, "reasoning": "<text>"}

    Handles common quirks such as markdown fences around the JSON.
    """
    text = raw.strip()

    # Strip optional markdown code fences
    if text.startswith("```"):
        # Remove opening fence (possibly with language tag)
        first_newline = text.index("\n") if "\n" in text else 3
        text = text[first_newline + 1:]
    if text.endswith("```"):
        text = text[:-3]
    text = text.strip()

    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        preview = _preview_text(text)
        logger.warning("Judge: failed to parse JSON: %s", preview)
        return None, f"{_DEFAULT_REASONING} 原始回傳：{preview}"

    score_raw = data.get("score")
    reasoning = data.get("reasoning", "")

    if score_raw is None:
        preview = _preview_text(text)
        logger.warning("Judge: JSON missing 'score' key: %s", preview)
        return None, f"{_DEFAULT_REASONING} 缺少 score 欄位。原始回傳：{preview}"

    try:
        score = int(score_raw)
    except (ValueError, TypeError):
        logger.warning("Judge: score is not an int: %r", score_raw)
        preview = _preview_text(text)
        return None, f"{_DEFAULT_REASONING} score 不是整數。原始回傳：{preview}"

    # Clamp to valid range
    score = max(1, min(5, score))

    return score, str(reasoning)


def _extract_rate_limit_delay(error_text: str) -> float:
    """Return a conservative sleep duration for a 429 error."""
    marker = "Limit resets at:"
    if marker in error_text:
        reset_text = error_text.split(marker, 1)[1].strip().rstrip("'").rstrip("}")
        if reset_text.endswith("UTC"):
            reset_text = reset_text[:-3].strip()
        try:
            reset_at = datetime.strptime(reset_text, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
            delay = (reset_at - datetime.now(timezone.utc)).total_seconds() + 1.0
            return max(1.0, min(delay, 30.0))
        except ValueError:
            pass
    return 5.0
