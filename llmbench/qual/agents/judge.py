"""Judge agent -- uses a strong LLM to score Executor responses.

The Judge is an LLM-powered agent.  For every :class:`LLMResponse` it
constructs a structured prompt (system + scoring rubric) and asks the
judge model to return a ``{"score": int, "reasoning": str}`` JSON object.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Dict, List

from openai import AsyncOpenAI

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
        )
        semaphore = asyncio.Semaphore(self.config.max_concurrent)

        logger.info(
            "Judge: evaluating %d responses with model %s (concurrency=%d)",
            len(responses),
            model_cfg.name,
            self.config.max_concurrent,
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
        messages = self._build_messages(item, response)
        model_name = self.config.model.model
        judge_display_name = self.config.model.name

        async with semaphore:
            # First attempt
            score, reasoning = await self._call_judge(client, model_name, messages)

            # Retry once on parse failure
            if score is None:
                logger.warning(
                    "Judge: retry for item=%s model=%s (first attempt unparseable)",
                    response.benchmark_item_id,
                    response.model_name,
                )
                score, reasoning = await self._call_judge(client, model_name, messages)

            # Final fallback
            if score is None:
                logger.error(
                    "Judge: giving default score for item=%s model=%s",
                    response.benchmark_item_id,
                    response.model_name,
                )
                score = _DEFAULT_SCORE
                reasoning = _DEFAULT_REASONING

            logger.debug(
                "Judge: item=%s model=%s score=%d",
                response.benchmark_item_id,
                response.model_name,
                score,
            )

            return JudgeScore(
                benchmark_item_id=response.benchmark_item_id,
                model_name=response.model_name,
                score=score,
                reasoning=reasoning,
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

    @staticmethod
    async def _call_judge(
        client: AsyncOpenAI,
        model: str,
        messages: list[dict[str, str]],
    ) -> tuple[int | None, str]:
        """Call the judge model and try to parse the JSON response.

        Returns ``(score, reasoning)`` on success or ``(None, "")`` when the
        response cannot be parsed.
        """
        try:
            completion = await client.chat.completions.create(
                model=model,
                messages=messages,
                temperature=0.0,
            )
            raw = completion.choices[0].message.content or ""
        except Exception as exc:  # noqa: BLE001
            logger.error("Judge: API call failed: %s", exc)
            return None, ""

        return _parse_judge_response(raw)


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
        logger.warning("Judge: failed to parse JSON: %s", text[:200])
        return None, ""

    score_raw = data.get("score")
    reasoning = data.get("reasoning", "")

    if score_raw is None:
        logger.warning("Judge: JSON missing 'score' key: %s", text[:200])
        return None, ""

    try:
        score = int(score_raw)
    except (ValueError, TypeError):
        logger.warning("Judge: score is not an int: %r", score_raw)
        return None, ""

    # Clamp to valid range
    score = max(1, min(5, score))

    return score, str(reasoning)
