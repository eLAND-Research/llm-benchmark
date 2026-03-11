"""JSON snapshot exporter for the qual pipeline.

Exports all pipeline artefacts (dataset, responses, scores, QA report) as
a collection of JSON files in a single output directory, plus a computed
``summary.json`` for quick inspection.
"""

from __future__ import annotations

import json
import logging
import os
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any

from llmbench.qual.schemas import (
    BenchmarkDataset,
    JudgeScore,
    LLMResponse,
    QAReport,
)

logger = logging.getLogger(__name__)


def _write_json(path: str, data: Any) -> None:
    """Write *data* as pretty-printed JSON to *path*."""
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2, default=str)
    logger.debug("Wrote %s", path)


def _build_summary(
    dataset: BenchmarkDataset,
    responses: list[LLMResponse],
    scores: list[JudgeScore],
    report: QAReport,
) -> dict[str, Any]:
    """Compute a quick summary dict.

    Contents:
    - ``total_items``: number of benchmark items
    - ``total_responses``: number of LLM responses
    - ``total_scores``: number of judge scores
    - ``pass``: overall pass/fail from the QA report
    - ``per_model``: { model_name -> { avg_score, count } }
    - ``per_task_type``: { task_type -> { avg_score, count } }
    - ``generated_at``: ISO timestamp
    """
    # ---- per-model aggregation ----
    model_scores: dict[str, list[int]] = defaultdict(list)
    for sc in scores:
        model_scores[sc.model_name].append(sc.score)

    per_model: dict[str, dict[str, Any]] = {}
    for model, score_list in sorted(model_scores.items()):
        per_model[model] = {
            "avg_score": round(sum(score_list) / len(score_list), 3),
            "count": len(score_list),
        }

    # ---- per-task_type aggregation ----
    # Build item_id -> task_type lookup from dataset
    item_task: dict[str, str] = {
        item.id: item.task_type.value for item in dataset.items
    }

    task_scores: dict[str, list[int]] = defaultdict(list)
    for sc in scores:
        task_type = item_task.get(sc.benchmark_item_id, "unknown")
        task_scores[task_type].append(sc.score)

    per_task_type: dict[str, dict[str, Any]] = {}
    for task, score_list in sorted(task_scores.items()):
        per_task_type[task] = {
            "avg_score": round(sum(score_list) / len(score_list), 3),
            "count": len(score_list),
        }

    return {
        "total_items": len(dataset.items),
        "total_responses": len(responses),
        "total_scores": len(scores),
        "pass": report.pass_,
        "per_model": per_model,
        "per_task_type": per_task_type,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


class Exporter:
    """Export qual pipeline artefacts as a JSON snapshot."""

    @staticmethod
    async def export_json_snapshot(
        output_dir: str,
        dataset: BenchmarkDataset,
        responses: list[LLMResponse],
        scores: list[JudgeScore],
        report: QAReport,
    ) -> str:
        """Write all artefacts to *output_dir* and return the directory path.

        Files created:
        - ``dataset.json``   -- full :class:`BenchmarkDataset`
        - ``responses.json`` -- list of :class:`LLMResponse`
        - ``scores.json``    -- list of :class:`JudgeScore`
        - ``qa_report.json`` -- :class:`QAReport`
        - ``summary.json``   -- quick aggregate summary

        Parameters
        ----------
        output_dir:
            Directory to write JSON files into (created if absent).
        dataset:
            The benchmark dataset produced by the Designer.
        responses:
            All LLM responses collected by the Executor.
        scores:
            All judge scores assigned by the Judge.
        report:
            The QA report produced by the QA Tester.

        Returns
        -------
        str
            Absolute path of *output_dir*.
        """
        os.makedirs(output_dir, exist_ok=True)
        logger.info("Exporting JSON snapshot to %s", output_dir)

        # Serialize via Pydantic's .model_dump() for consistent output
        _write_json(
            os.path.join(output_dir, "dataset.json"),
            dataset.model_dump(mode="json"),
        )

        _write_json(
            os.path.join(output_dir, "responses.json"),
            [r.model_dump(mode="json") for r in responses],
        )

        _write_json(
            os.path.join(output_dir, "scores.json"),
            [s.model_dump(mode="json") for s in scores],
        )

        _write_json(
            os.path.join(output_dir, "qa_report.json"),
            report.model_dump(mode="json", by_alias=True),
        )

        summary = _build_summary(dataset, responses, scores, report)
        _write_json(
            os.path.join(output_dir, "summary.json"),
            summary,
        )

        logger.info(
            "Snapshot exported: %d items, %d responses, %d scores, pass=%s",
            len(dataset.items),
            len(responses),
            len(scores),
            report.pass_,
        )
        return os.path.abspath(output_dir)
