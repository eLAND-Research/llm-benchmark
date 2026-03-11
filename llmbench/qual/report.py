"""Markdown report generator for the LLM quality validation pipeline.

Produces a human-readable ``report.md`` in Traditional Chinese that
summarises the benchmark results, per-model and per-task breakdowns,
score distributions, QA verification outcomes, and a detailed sample
of individual scoring records.
"""

from __future__ import annotations

import logging
import os
import statistics
from collections import Counter, defaultdict
from datetime import datetime
from typing import Any, Dict, List

from .schemas import (
    BenchmarkDataset,
    JudgeScore,
    LLMResponse,
    QAReport,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Task type display names (Traditional Chinese)
# ---------------------------------------------------------------------------

_TASK_TYPE_DISPLAY: Dict[str, str] = {
    "summarization": "摘要生成",
    "sentiment": "情感分析",
    "classification": "主題分類",
    "qa": "問答理解",
}

# Maximum number of detailed scoring records to include in the report.
_DETAIL_LIMIT = 10


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _fmt_score(value: float) -> str:
    """Format a floating-point score to two decimal places."""
    return f"{value:.2f}"


def _pct(count: int, total: int) -> str:
    """Return a percentage string (e.g. ``'42.5%'``), safe for *total* == 0."""
    if total == 0:
        return "0.0%"
    return f"{count / total * 100:.1f}%"


def _task_display(task_type: str) -> str:
    """Return the Traditional Chinese display name for a task type."""
    return _TASK_TYPE_DISPLAY.get(task_type, task_type)


def _build_item_map(dataset: BenchmarkDataset) -> Dict[str, Any]:
    """Build ``{item_id: BenchmarkItem}`` lookup from a dataset."""
    return {item.id: item for item in dataset.items}


def _model_names_from_scores(scores: List[JudgeScore]) -> List[str]:
    """Return a sorted list of unique model names appearing in *scores*."""
    return sorted({s.model_name for s in scores})


def _task_types_from_dataset(dataset: BenchmarkDataset) -> List[str]:
    """Return a sorted list of unique task type values in the dataset."""
    return sorted({item.task_type.value for item in dataset.items})


# ---------------------------------------------------------------------------
# Section builders
# ---------------------------------------------------------------------------


def _section_model_overview(
    dataset: BenchmarkDataset,
    scores: List[JudgeScore],
) -> str:
    """Build the per-model score overview table."""
    item_map = _build_item_map(dataset)
    model_names = _model_names_from_scores(scores)
    task_types = _task_types_from_dataset(dataset)

    # Accumulate scores: model -> task_type -> list[int]
    model_task_scores: Dict[str, Dict[str, List[int]]] = defaultdict(
        lambda: defaultdict(list)
    )
    model_all_scores: Dict[str, List[int]] = defaultdict(list)

    for sc in scores:
        item = item_map.get(sc.benchmark_item_id)
        task_type = item.task_type.value if item else "unknown"
        model_task_scores[sc.model_name][task_type].append(sc.score)
        model_all_scores[sc.model_name].append(sc.score)

    # Build header row with task type columns
    header_cols = ["模型", "平均分"]
    for tt in task_types:
        header_cols.append(_task_display(tt))
    header = "| " + " | ".join(header_cols) + " |"
    separator = "| " + " | ".join(["---"] * len(header_cols)) + " |"

    rows: List[str] = []
    for model in model_names:
        all_scores = model_all_scores.get(model, [])
        avg = statistics.mean(all_scores) if all_scores else 0.0
        cols = [model, _fmt_score(avg)]
        for tt in task_types:
            tt_scores = model_task_scores[model].get(tt, [])
            tt_avg = statistics.mean(tt_scores) if tt_scores else 0.0
            cols.append(_fmt_score(tt_avg))
        rows.append("| " + " | ".join(cols) + " |")

    lines = [
        "## 各模型評分總覽",
        "",
        header,
        separator,
        *rows,
        "",
    ]
    return "\n".join(lines)


def _section_task_analysis(
    dataset: BenchmarkDataset,
    scores: List[JudgeScore],
) -> str:
    """Build a per-task-type analysis section with sub-tables."""
    item_map = _build_item_map(dataset)
    task_types = _task_types_from_dataset(dataset)
    model_names = _model_names_from_scores(scores)

    # Accumulate: task_type -> model -> list[int]
    task_model_scores: Dict[str, Dict[str, List[int]]] = defaultdict(
        lambda: defaultdict(list)
    )
    for sc in scores:
        item = item_map.get(sc.benchmark_item_id)
        task_type = item.task_type.value if item else "unknown"
        task_model_scores[task_type][sc.model_name].append(sc.score)

    lines = ["## 各任務類型分析", ""]

    for tt in task_types:
        display = _task_display(tt)
        lines.append(f"### {display}")
        lines.append("")
        lines.append("| 模型 | 平均分 | 最高分 | 最低分 | 題數 |")
        lines.append("| --- | --- | --- | --- | --- |")

        for model in model_names:
            s_list = task_model_scores[tt].get(model, [])
            if not s_list:
                lines.append(f"| {model} | - | - | - | 0 |")
                continue
            avg = statistics.mean(s_list)
            mx = max(s_list)
            mn = min(s_list)
            lines.append(
                f"| {model} | {_fmt_score(avg)} | {mx} | {mn} | {len(s_list)} |"
            )

        lines.append("")

    return "\n".join(lines)


def _section_score_distribution(scores: List[JudgeScore]) -> str:
    """Build the overall score distribution section."""
    total = len(scores)
    dist: Counter[int] = Counter(s.score for s in scores)

    lines = [
        "## 評分分佈",
        "",
        "| 分數 | 數量 | 比例 |",
        "| --- | --- | --- |",
    ]

    for score_val in range(1, 6):
        count = dist.get(score_val, 0)
        lines.append(f"| {score_val} | {count} | {_pct(count, total)} |")

    lines.append("")

    # Text summary
    if total > 0:
        mean_score = statistics.mean([s.score for s in scores])
        lines.append(f"- **平均分**: {_fmt_score(mean_score)}")
        lines.append(f"- **評分總數**: {total}")
        if total >= 2:
            std = statistics.stdev([s.score for s in scores])
            lines.append(f"- **標準差**: {std:.3f}")
        lines.append("")

    return "\n".join(lines)


def _section_qa_results(report: QAReport) -> str:
    """Build the QA verification results section."""
    lines = [
        "## QA 驗收結果",
        "",
        f"**整體結果**: {'通過' if report.pass_ else '未通過'}",
        "",
    ]

    # Dataset quality summary
    dq = report.dataset_quality
    lines.append("### 資料集品質")
    lines.append("")
    lines.append(f"- 題目總數: {dq.get('total_items', 'N/A')}")
    lines.append(f"- 空白題目: {dq.get('empty_count', 0)}")
    lines.append(f"- 重複來源: {dq.get('duplicate_count', 0)}")
    lines.append(f"- 缺少參考答案: {dq.get('missing_reference_answer', 0)}")

    task_dist = dq.get("task_type_distribution", {})
    if task_dist:
        lines.append("- 任務類型分佈:")
        for tt, count in sorted(task_dist.items()):
            lines.append(f"  - {_task_display(tt)}: {count}")
    lines.append("")

    # Scoring consistency summary
    sc = report.scoring_consistency
    lines.append("### 評分一致性")
    lines.append("")
    lines.append(f"- 評分數量: {sc.get('count', 0)}")
    lines.append(f"- 平均分: {sc.get('mean', 0.0)}")
    lines.append(f"- 標準差: {sc.get('std', 0.0)}")

    sc_dist = sc.get("distribution", {})
    if sc_dist:
        lines.append("- 分佈: " + ", ".join(
            f"{k}分={v}筆" for k, v in sorted(sc_dist.items())
        ))
    lines.append("")

    # Issues
    issues = report.issues
    if issues:
        lines.append("### 發現的問題")
        lines.append("")
        for idx, issue in enumerate(issues, 1):
            lines.append(f"{idx}. {issue}")
        lines.append("")
    else:
        lines.append("### 發現的問題")
        lines.append("")
        lines.append("無")
        lines.append("")

    return "\n".join(lines)


def _section_detail_records(
    dataset: BenchmarkDataset,
    scores: List[JudgeScore],
    limit: int = _DETAIL_LIMIT,
) -> str:
    """Build the detailed scoring records table (first *limit* entries)."""
    item_map = _build_item_map(dataset)

    lines = [
        f"## 詳細評分記錄（前 {limit} 筆）",
        "",
        "| # | 任務類型 | 模型 | 分數 | 理由摘要 |",
        "| --- | --- | --- | --- | --- |",
    ]

    for idx, sc in enumerate(scores[:limit], 1):
        item = item_map.get(sc.benchmark_item_id)
        task_type = _task_display(item.task_type.value) if item else "N/A"
        # Truncate reasoning to keep the table readable
        reasoning_brief = sc.reasoning.replace("\n", " ").strip()
        if len(reasoning_brief) > 80:
            reasoning_brief = reasoning_brief[:77] + "..."
        lines.append(
            f"| {idx} | {task_type} | {sc.model_name} | {sc.score}/5 | {reasoning_brief} |"
        )

    lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def generate_report(
    output_dir: str,
    dataset: BenchmarkDataset,
    responses: List[LLMResponse],
    scores: List[JudgeScore],
    report: QAReport,
) -> str:
    """Generate a Markdown quality report and write it to *output_dir*.

    The report is written in Traditional Chinese and saved as
    ``{output_dir}/report.md``.

    Parameters
    ----------
    output_dir:
        Target directory (created if absent).
    dataset:
        The benchmark dataset produced by the Designer.
    responses:
        All LLM responses from the Executor.
    scores:
        All judge scores from the Judge.
    report:
        The QA report from the QA Tester.

    Returns
    -------
    str
        Absolute path to the generated ``report.md``.
    """
    os.makedirs(output_dir, exist_ok=True)

    # We need model names for the header; extract from scores.
    model_names = _model_names_from_scores(scores)

    # Build the header section (patching in the model count from scores)
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    status = "通過" if report.pass_ else "未通過"

    header = "\n".join([
        "# LLM 品質驗證報告",
        "",
        "## 摘要",
        "",
        f"- **測試日期**: {now}",
        f"- **Benchmark 題目數**: {len(dataset.items)}",
        f"- **待測模型數**: {len(model_names)}",
        f"- **整體驗收結果**: {status}",
        "",
    ])

    sections = [
        header,
        _section_model_overview(dataset, scores),
        _section_task_analysis(dataset, scores),
        _section_score_distribution(scores),
        _section_qa_results(report),
        _section_detail_records(dataset, scores),
    ]

    content = "\n".join(sections)

    report_path = os.path.join(output_dir, "report.md")
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(content)

    abs_path = os.path.abspath(report_path)
    logger.info("Markdown report written to %s", abs_path)
    return abs_path


async def generate_report_from_dir(result_dir: str) -> str:
    """Re-generate a Markdown report from an existing JSON snapshot directory.

    Reads ``dataset.json``, ``responses.json``, ``scores.json``, and
    ``qa_report.json`` from *result_dir* and produces a fresh ``report.md``.

    Parameters
    ----------
    result_dir:
        Path to a directory containing the JSON snapshot files.

    Returns
    -------
    str
        Absolute path to the generated ``report.md``.
    """
    import json as _json

    def _read(name: str) -> dict | list:
        path = os.path.join(result_dir, name)
        with open(path, "r", encoding="utf-8") as fh:
            return _json.load(fh)

    dataset = BenchmarkDataset.model_validate(_read("dataset.json"))
    responses = [LLMResponse.model_validate(r) for r in _read("responses.json")]
    scores_data = _read("scores.json")
    score_list = [JudgeScore.model_validate(s) for s in scores_data]
    qa_data = _read("qa_report.json")
    qa_report = QAReport.model_validate(qa_data)

    return await generate_report(result_dir, dataset, responses, score_list, qa_report)
