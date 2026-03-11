"""QA Tester agent -- verifies pipeline correctness via rule checks and LLM spot-checks.

The QA Tester combines deterministic rule-based checks with LLM-assisted
spot-checks to produce a :class:`~llmbench.qual.schemas.QAReport`.

Rule checks (pure Python):
  1. Dataset quality: empty items, duplicates, missing reference answers, task
     type distribution.
  2. Response completeness: errors, missing model responses, empty responses.
  3. Scoring consistency: score distribution, standard deviation, missing scores.

LLM-assisted checks (sampled):
  4. Judge scoring reasonableness via :data:`QA_CHECK_PROMPT`.
  5. Dataset / reference answer quality via :data:`DATASET_QUALITY_PROMPT`.
"""

from __future__ import annotations

import json
import logging
import random
import statistics
from collections import Counter
from typing import Any, Dict, List, Optional

from openai import AsyncOpenAI

from llmbench.qual.config import QualConfig
from llmbench.qual.prompts.qa_tester import DATASET_QUALITY_PROMPT, QA_CHECK_PROMPT
from llmbench.qual.schemas import (
    BenchmarkDataset,
    BenchmarkItem,
    JudgeScore,
    LLMResponse,
    QAReport,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Number of JudgeScore samples to spot-check with the LLM.
_DEFAULT_SCORE_SAMPLE_SIZE = 5

# Number of BenchmarkItem samples to spot-check for dataset quality.
_DEFAULT_DATASET_SAMPLE_SIZE = 3

# Scoring standard deviation below this threshold is considered suspicious
# (i.e. the judge might not be discriminating between quality levels).
_MIN_STD_THRESHOLD = 0.3


# ---------------------------------------------------------------------------
# QA Tester agent
# ---------------------------------------------------------------------------


class QATester:
    """Quality-assurance agent that verifies pipeline outputs.

    Parameters
    ----------
    config:
        The top-level :class:`QualConfig`.  The judge model configuration
        is reused for LLM-assisted spot-checks.
    """

    def __init__(self, config: QualConfig) -> None:
        self.config = config

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def verify(
        self,
        dataset: BenchmarkDataset,
        responses: list[LLMResponse],
        scores: list[JudgeScore],
    ) -> QAReport:
        """Run all rule checks and LLM spot-checks, then return a :class:`QAReport`.

        Parameters
        ----------
        dataset:
            The benchmark dataset produced by the Designer.
        responses:
            All LLM responses collected by the Executor.
        scores:
            All judge scores produced by the Judge.

        Returns
        -------
        QAReport
            Aggregated quality report with ``pass_=True`` when no critical
            issues are found.
        """
        issues: list[str] = []

        # -- Rule-based checks ------------------------------------------
        logger.info("QATester: running dataset quality checks ...")
        dataset_quality = self._check_dataset_quality(dataset, issues)

        logger.info("QATester: running response completeness checks ...")
        self._check_response_completeness(dataset, responses, issues)

        logger.info("QATester: running scoring consistency checks ...")
        scoring_consistency = self._check_scoring_consistency(scores, issues)

        # -- LLM-assisted spot-checks -----------------------------------
        logger.info("QATester: running LLM-assisted judge spot-checks ...")
        await self._llm_check_judge_scores(dataset, responses, scores, issues)

        logger.info("QATester: running LLM-assisted dataset quality spot-checks ...")
        await self._llm_check_dataset_quality(dataset, issues)

        # -- Determine overall pass/fail --------------------------------
        passed = self._determine_pass(dataset, responses, scores, issues)

        report = QAReport(
            dataset_quality=dataset_quality,
            scoring_consistency=scoring_consistency,
            issues=issues,
            **{"pass": passed},
        )

        logger.info(
            "QATester: verification complete -- pass=%s, %d issue(s) found.",
            passed,
            len(issues),
        )
        return report

    # ------------------------------------------------------------------
    # 1. Dataset quality (rule-based)
    # ------------------------------------------------------------------

    def _check_dataset_quality(
        self,
        dataset: BenchmarkDataset,
        issues: list[str],
    ) -> Dict[str, Any]:
        """Check dataset for empty items, duplicates, and task type coverage.

        Mutates *issues* in-place when problems are discovered.
        """
        total_items = len(dataset.items)

        # Empty title or content
        empty_count = 0
        for item in dataset.items:
            if not item.source_material.title.strip() or not item.source_material.content.strip():
                empty_count += 1
        if empty_count:
            issues.append(
                f"[Dataset] {empty_count} item(s) have empty title or content."
            )

        # Duplicate items (same source title)
        title_counter: Counter[str] = Counter(
            item.source_material.title for item in dataset.items
        )
        duplicate_count = sum(1 for count in title_counter.values() if count > 1)
        if duplicate_count:
            issues.append(
                f"[Dataset] {duplicate_count} source title(s) appear more than once."
            )

        # Missing reference answers
        missing_ref = sum(
            1 for item in dataset.items if not (item.reference_answer or "").strip()
        )
        if missing_ref:
            issues.append(
                f"[Dataset] {missing_ref} item(s) have no reference answer."
            )

        # Task type distribution
        task_type_counts: Dict[str, int] = Counter(
            item.task_type.value for item in dataset.items
        )
        expected_per_task = self.config.items_per_task
        task_type_issues: list[str] = []
        for tt in self.config.task_types:
            actual = task_type_counts.get(tt, 0)
            if actual != expected_per_task:
                task_type_issues.append(
                    f"{tt}: expected {expected_per_task}, got {actual}"
                )
        if task_type_issues:
            issues.append(
                "[Dataset] Task type count mismatch: " + "; ".join(task_type_issues)
            )

        quality_info: Dict[str, Any] = {
            "total_items": total_items,
            "empty_count": empty_count,
            "duplicate_count": duplicate_count,
            "missing_reference_answer": missing_ref,
            "task_type_distribution": dict(task_type_counts),
        }
        logger.info("QATester: dataset quality = %s", quality_info)
        return quality_info

    # ------------------------------------------------------------------
    # 2. Response completeness (rule-based)
    # ------------------------------------------------------------------

    def _check_response_completeness(
        self,
        dataset: BenchmarkDataset,
        responses: list[LLMResponse],
        issues: list[str],
    ) -> None:
        """Verify that every (item, model) pair has a non-error response."""
        error_responses = [r for r in responses if r.error]
        if error_responses:
            issues.append(
                f"[Response] {len(error_responses)} response(s) contain errors."
            )

        # Build a set of (item_id, model_name) pairs we expect
        model_names = {m.name for m in self.config.models_under_test}
        item_ids = {item.id for item in dataset.items}
        expected_pairs = {
            (item_id, model_name)
            for item_id in item_ids
            for model_name in model_names
        }
        actual_pairs = {
            (r.benchmark_item_id, r.model_name) for r in responses
        }
        missing_pairs = expected_pairs - actual_pairs
        if missing_pairs:
            issues.append(
                f"[Response] {len(missing_pairs)} (item, model) pair(s) have no response."
            )
            # Log a few examples for debugging.
            for pair in list(missing_pairs)[:5]:
                logger.warning(
                    "QATester: missing response for item=%s model=%s",
                    pair[0],
                    pair[1],
                )

        # Empty response text (excluding error entries since those are already flagged)
        empty_responses = [
            r for r in responses if not r.error and not r.response_text.strip()
        ]
        if empty_responses:
            issues.append(
                f"[Response] {len(empty_responses)} non-error response(s) have empty text."
            )

    # ------------------------------------------------------------------
    # 3. Scoring consistency (rule-based)
    # ------------------------------------------------------------------

    def _check_scoring_consistency(
        self,
        scores: list[JudgeScore],
        issues: list[str],
    ) -> Dict[str, Any]:
        """Analyse the score distribution for anomalies."""
        if not scores:
            issues.append("[Scoring] No scores available to analyse.")
            return {
                "count": 0,
                "mean": 0.0,
                "std": 0.0,
                "distribution": {},
            }

        values = [s.score for s in scores]
        mean = statistics.mean(values)
        std = statistics.stdev(values) if len(values) >= 2 else 0.0

        distribution: Dict[int, int] = Counter(values)

        # All identical scores -- highly suspicious
        if std == 0.0 and len(values) >= 2:
            issues.append(
                f"[Scoring] All {len(values)} scores are identical ({values[0]}). "
                "The judge may not be discriminating quality."
            )

        # Very low standard deviation
        if 0 < std < _MIN_STD_THRESHOLD:
            issues.append(
                f"[Scoring] Score standard deviation is very low ({std:.3f} < {_MIN_STD_THRESHOLD}). "
                "The judge may lack discriminating power."
            )

        # Distribution heavily skewed to one extreme
        total = len(values)
        max_score_count = distribution.get(5, 0)
        min_score_count = distribution.get(1, 0)
        if max_score_count / total > 0.9:
            issues.append(
                f"[Scoring] {max_score_count}/{total} scores are 5/5. "
                "Distribution is suspiciously skewed to the maximum."
            )
        if min_score_count / total > 0.9:
            issues.append(
                f"[Scoring] {min_score_count}/{total} scores are 1/5. "
                "Distribution is suspiciously skewed to the minimum."
            )

        # Check that every score has an associated item
        # (A score referencing a non-existent item_id is not checked here
        #  because it depends on the dataset, handled in the pass logic.)

        consistency_info: Dict[str, Any] = {
            "count": len(values),
            "mean": round(mean, 3),
            "std": round(std, 3),
            "min": min(values),
            "max": max(values),
            "distribution": {str(k): v for k, v in sorted(distribution.items())},
        }
        logger.info("QATester: scoring consistency = %s", consistency_info)
        return consistency_info

    # ------------------------------------------------------------------
    # 4. LLM-assisted: Judge score spot-check
    # ------------------------------------------------------------------

    async def _llm_check_judge_scores(
        self,
        dataset: BenchmarkDataset,
        responses: list[LLMResponse],
        scores: list[JudgeScore],
        issues: list[str],
    ) -> None:
        """Sample a few (score, response, item) tuples and ask the LLM
        whether the judge's assessment is reasonable.
        """
        if not scores:
            logger.info("QATester: no scores to spot-check, skipping.")
            return

        sample_size = min(_DEFAULT_SCORE_SAMPLE_SIZE, len(scores))
        sampled_scores = random.sample(scores, sample_size)

        # Build lookup maps
        item_map: Dict[str, BenchmarkItem] = {
            item.id: item for item in dataset.items
        }
        response_map: Dict[str, LLMResponse] = {}
        for r in responses:
            key = f"{r.benchmark_item_id}|{r.model_name}"
            response_map[key] = r

        client = self._build_llm_client()

        for idx, score in enumerate(sampled_scores, 1):
            item = item_map.get(score.benchmark_item_id)
            resp_key = f"{score.benchmark_item_id}|{score.model_name}"
            response = response_map.get(resp_key)

            if item is None or response is None:
                logger.warning(
                    "QATester: skipping score spot-check %d/%d -- "
                    "item or response not found (item_id=%s model=%s)",
                    idx,
                    sample_size,
                    score.benchmark_item_id,
                    score.model_name,
                )
                continue

            prompt_text = QA_CHECK_PROMPT.format(
                item_prompt=item.prompt,
                response=response.response_text,
                score=score.score,
                reasoning=score.reasoning,
            )

            result = await self._call_llm(client, prompt_text)
            if result is None:
                logger.warning(
                    "QATester: LLM spot-check %d/%d returned no result, skipping.",
                    idx,
                    sample_size,
                )
                continue

            is_reasonable = result.get("is_reasonable", True)
            issue_text = result.get("issue", "")

            if not is_reasonable:
                msg = (
                    f"[Judge Spot-Check] Score for item={score.benchmark_item_id} "
                    f"model={score.model_name} (score={score.score}/5) "
                    f"deemed unreasonable: {issue_text}"
                )
                issues.append(msg)
                logger.warning("QATester: %s", msg)
            else:
                logger.info(
                    "QATester: score spot-check %d/%d passed (item=%s model=%s score=%d).",
                    idx,
                    sample_size,
                    score.benchmark_item_id,
                    score.model_name,
                    score.score,
                )

    # ------------------------------------------------------------------
    # 5. LLM-assisted: Dataset quality spot-check
    # ------------------------------------------------------------------

    async def _llm_check_dataset_quality(
        self,
        dataset: BenchmarkDataset,
        issues: list[str],
    ) -> None:
        """Sample a few benchmark items and ask the LLM to evaluate dataset
        quality (prompt clarity, reference answer correctness, rubric quality).
        """
        if not dataset.items:
            logger.info("QATester: empty dataset, skipping quality spot-check.")
            return

        sample_size = min(_DEFAULT_DATASET_SAMPLE_SIZE, len(dataset.items))
        sampled_items = random.sample(dataset.items, sample_size)

        client = self._build_llm_client()

        for idx, item in enumerate(sampled_items, 1):
            prompt_text = DATASET_QUALITY_PROMPT.format(
                task_type=item.task_type.value,
                title=item.source_material.title,
                content=item.source_material.content,
                item_prompt=item.prompt,
                reference_answer=item.reference_answer or "(none)",
                scoring_rubric=item.scoring_rubric,
            )

            result = await self._call_llm(client, prompt_text)
            if result is None:
                logger.warning(
                    "QATester: LLM dataset quality check %d/%d returned no result, skipping.",
                    idx,
                    sample_size,
                )
                continue

            quality_score = result.get("quality_score", 5)
            ds_pass = result.get("pass", True)
            ds_issues = result.get("issues", [])

            if not ds_pass:
                formatted_issues = "; ".join(ds_issues) if ds_issues else "no detail"
                msg = (
                    f"[Dataset Spot-Check] Item {item.id} "
                    f"(task={item.task_type.value}) quality_score={quality_score}/5: "
                    f"{formatted_issues}"
                )
                issues.append(msg)
                logger.warning("QATester: %s", msg)
            else:
                logger.info(
                    "QATester: dataset quality check %d/%d passed "
                    "(item=%s quality_score=%d).",
                    idx,
                    sample_size,
                    item.id,
                    quality_score,
                )

    # ------------------------------------------------------------------
    # Pass/Fail determination
    # ------------------------------------------------------------------

    @staticmethod
    def _determine_pass(
        dataset: BenchmarkDataset,
        responses: list[LLMResponse],
        scores: list[JudgeScore],
        issues: list[str],
    ) -> bool:
        """Return ``False`` if any critical issue is detected.

        Critical conditions:
        - Empty dataset (no items)
        - All responses are errors
        - Score distribution is completely uniform (std == 0 with 2+ scores)
        - More than 90% of scores are at one extreme (all 1 or all 5)
        """
        # Empty dataset
        if not dataset.items:
            logger.warning("QATester: FAIL -- dataset is empty.")
            return False

        # All responses failed
        if responses and all(r.error for r in responses):
            logger.warning("QATester: FAIL -- every response contains an error.")
            return False

        # No scores at all (when there should be some)
        if not scores and responses:
            logger.warning("QATester: FAIL -- no scores produced.")
            return False

        # Score distribution pathology
        if len(scores) >= 2:
            values = [s.score for s in scores]
            std = statistics.stdev(values)
            total = len(values)
            dist = Counter(values)

            if std == 0.0:
                logger.warning("QATester: FAIL -- all scores identical.")
                return False

            if dist.get(5, 0) / total > 0.9:
                logger.warning("QATester: FAIL -- >90%% of scores are 5/5.")
                return False
            if dist.get(1, 0) / total > 0.9:
                logger.warning("QATester: FAIL -- >90%% of scores are 1/5.")
                return False

        return True

    # ------------------------------------------------------------------
    # LLM client helpers
    # ------------------------------------------------------------------

    def _build_llm_client(self) -> AsyncOpenAI:
        """Create an :class:`AsyncOpenAI` client from the judge model config."""
        judge_model_cfg = self.config.judge.model
        api_key = judge_model_cfg.api_key if judge_model_cfg.api_key else "not-needed"
        return AsyncOpenAI(
            base_url=judge_model_cfg.base_url,
            api_key=api_key,
        )

    async def _call_llm(
        self,
        client: AsyncOpenAI,
        prompt: str,
    ) -> Optional[Dict[str, Any]]:
        """Send a prompt to the judge model and parse the JSON response.

        Returns ``None`` when the call fails or the response is not valid JSON.
        """
        model = self.config.judge.model.model
        try:
            completion = await client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.0,
            )
            text = (completion.choices[0].message.content or "").strip()

            # Strip optional markdown fences (```json ... ```)
            if text.startswith("```"):
                lines = text.splitlines()
                # Remove first and last lines that are fences
                if lines and lines[0].startswith("```"):
                    lines = lines[1:]
                if lines and lines[-1].strip() == "```":
                    lines = lines[:-1]
                text = "\n".join(lines).strip()

            return json.loads(text)

        except json.JSONDecodeError as exc:
            logger.warning(
                "QATester: LLM returned non-JSON response: %s (raw: %s)",
                exc,
                text[:200] if "text" in dir() else "<unavailable>",
            )
            return None
        except Exception as exc:  # noqa: BLE001
            logger.warning("QATester: LLM call failed: %s", exc)
            return None
