"""Main pipeline orchestrator for the LLM quality validation pipeline.

Connects all four phases of the qual pipeline:

    Phase 1: Study    -- Researcher fetches raw materials from TDS MCP
    Phase 2: Design   -- Designer generates benchmark dataset via LLM
    Phase 3: Implement -- Executor runs models-under-test, Judge scores responses
    Phase 4: UAT      -- QA Tester verifies pipeline outputs

Each phase's outputs are persisted to SQLite so that future extensions can
resume from a checkpoint.  After all phases complete, the pipeline exports a
JSON snapshot and a Markdown report.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime
from pathlib import Path
from typing import List

from .agents.designer import Designer
from .agents.executor import Executor
from .agents.judge import Judge
from .agents.qa_tester import QATester
from .agents.researcher import Researcher
from .config import QualConfig
from .schemas import (
    BenchmarkDataset,
    JudgeScore,
    LLMResponse,
    QAReport,
    QualRunResult,
    RawMaterial,
)
from .storage.db import QualDB
from .storage.exporter import Exporter

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Full pipeline
# ---------------------------------------------------------------------------


async def run_qual_pipeline(config: QualConfig) -> QualRunResult:
    """Execute the complete LLM quality validation pipeline.

    Phase 1: Study     -- Researcher fetches raw materials from TDS MCP.
    Phase 2: Design    -- Designer generates a benchmark dataset.
    Phase 3: Implement -- Executor calls models-under-test; Judge scores them.
    Phase 4: UAT       -- QA Tester verifies the overall quality.

    Every phase's output is persisted to SQLite via :class:`QualDB`.
    On completion, a JSON snapshot and Markdown report are written to the
    configured output directory.

    Parameters
    ----------
    config:
        A validated :class:`QualConfig`.

    Returns
    -------
    QualRunResult
        The aggregated result containing dataset, responses, scores, and
        QA report.

    Raises
    ------
    Exception
        Re-raises any exception after recording the failure in the DB.
    """
    run_id = str(uuid.uuid4())

    # Resolve db_path to absolute so aiosqlite worker thread can find it
    db_path = str(Path(config.db_path).resolve())
    db = QualDB(db_path)
    await db.init()
    await db.create_run(run_id, config.model_dump_json(), "running")

    try:
        # Phase 1: Study ---------------------------------------------------
        logger.info("=== Phase 1: Study (Researcher) ===")
        researcher = Researcher(config.data_source)
        materials = await researcher.fetch()
        logger.info("Phase 1 complete: %d raw materials collected", len(materials))

        # Phase 2: Design --------------------------------------------------
        logger.info("=== Phase 2: Design (Designer) ===")
        designer = Designer(config)
        dataset = await designer.generate(materials)
        await db.save_dataset(run_id, dataset)
        logger.info("Phase 2 complete: %d benchmark items generated", len(dataset.items))

        # Phase 3: Implement -----------------------------------------------
        logger.info("=== Phase 3: Implement (Executor + Judge) ===")
        executor = Executor(
            config.models_under_test,
            max_concurrent=config.executor_max_concurrent,
        )
        responses = await executor.run(dataset)
        await db.save_responses(run_id, responses)
        logger.info("Executor done: %d LLM responses collected", len(responses))

        judge = Judge(config.judge)
        scores = await judge.evaluate(dataset, responses)
        await db.save_scores(run_id, scores)
        logger.info("Judge done: %d scores produced", len(scores))

        # Phase 4: UAT -----------------------------------------------------
        logger.info("=== Phase 4: UAT (QA Tester) ===")
        qa = QATester(config)
        report = await qa.verify(dataset, responses, scores)
        await db.save_report(run_id, report)
        logger.info(
            "Phase 4 complete: %s",
            "PASS" if report.pass_ else "FAIL",
        )

        # Export ------------------------------------------------------------
        timestamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
        output_dir = f"{config.output_dir}/{timestamp}"

        await Exporter.export_json_snapshot(
            output_dir, dataset, responses, scores, report,
        )

        from .report import generate_report

        await generate_report(output_dir, dataset, responses, scores, report)

        # Update run status
        status = "completed" if report.pass_ else "completed_with_issues"
        await db.update_run_status(run_id, status)

        result = QualRunResult(
            run_id=run_id,
            dataset=dataset,
            responses=responses,
            scores=scores,
            qa_report=report,
        )
        logger.info("Pipeline finished. Output: %s", output_dir)
        return result

    except Exception as e:
        logger.error("Pipeline failed: %s", e)
        await db.update_run_status(run_id, f"failed: {e}")
        raise


# ---------------------------------------------------------------------------
# Per-phase helpers (useful for CLI debugging)
# ---------------------------------------------------------------------------


async def run_fetch(config: QualConfig) -> List[RawMaterial]:
    """Run Phase 1 only -- fetch raw materials from TDS MCP.

    Parameters
    ----------
    config:
        A validated :class:`QualConfig`.

    Returns
    -------
    list[RawMaterial]
        Deduplicated raw materials collected by the Researcher.
    """
    logger.info("=== run_fetch: Phase 1 only ===")
    researcher = Researcher(config.data_source)
    materials = await researcher.fetch()
    logger.info("run_fetch: %d raw materials collected", len(materials))
    return materials


async def run_design(config: QualConfig) -> BenchmarkDataset:
    """Run Phases 1 + 2 -- fetch materials then generate the benchmark dataset.

    Parameters
    ----------
    config:
        A validated :class:`QualConfig`.

    Returns
    -------
    BenchmarkDataset
        The generated benchmark dataset.
    """
    logger.info("=== run_design: Phases 1 + 2 ===")
    materials = await run_fetch(config)

    designer = Designer(config)
    dataset = await designer.generate(materials)
    logger.info("run_design: %d benchmark items generated", len(dataset.items))
    return dataset


async def run_execute(
    config: QualConfig,
) -> tuple[BenchmarkDataset, List[LLMResponse]]:
    """Run Phases 1 + 2 + 3a -- fetch, design, and execute (no judging).

    Parameters
    ----------
    config:
        A validated :class:`QualConfig`.

    Returns
    -------
    tuple[BenchmarkDataset, list[LLMResponse]]
        The dataset and all collected LLM responses.
    """
    logger.info("=== run_execute: Phases 1 + 2 + 3a ===")
    dataset = await run_design(config)

    executor = Executor(
        config.models_under_test,
        max_concurrent=config.executor_max_concurrent,
    )
    responses = await executor.run(dataset)
    logger.info("run_execute: %d LLM responses collected", len(responses))
    return dataset, responses


async def run_judge(
    config: QualConfig,
) -> tuple[BenchmarkDataset, List[LLMResponse], List[JudgeScore]]:
    """Run Phases 1 + 2 + 3 -- fetch, design, execute, and judge.

    Parameters
    ----------
    config:
        A validated :class:`QualConfig`.

    Returns
    -------
    tuple[BenchmarkDataset, list[LLMResponse], list[JudgeScore]]
        The dataset, responses, and judge scores.
    """
    logger.info("=== run_judge: Phases 1 + 2 + 3 ===")
    dataset, responses = await run_execute(config)

    judge = Judge(config.judge)
    scores = await judge.evaluate(dataset, responses)
    logger.info("run_judge: %d scores produced", len(scores))
    return dataset, responses, scores


async def run_qa(
    config: QualConfig,
) -> tuple[BenchmarkDataset, List[LLMResponse], List[JudgeScore], QAReport]:
    """Run all four phases without DB persistence or file export.

    This is equivalent to :func:`run_qual_pipeline` but without the SQLite
    storage, JSON export, or Markdown report steps.  Useful for quick
    end-to-end testing from the CLI.

    Parameters
    ----------
    config:
        A validated :class:`QualConfig`.

    Returns
    -------
    tuple[BenchmarkDataset, list[LLMResponse], list[JudgeScore], QAReport]
        All pipeline outputs.
    """
    logger.info("=== run_qa: Phases 1 + 2 + 3 + 4 (no persistence) ===")
    dataset, responses, scores = await run_judge(config)

    qa = QATester(config)
    report = await qa.verify(dataset, responses, scores)
    logger.info("run_qa: %s", "PASS" if report.pass_ else "FAIL")
    return dataset, responses, scores, report
