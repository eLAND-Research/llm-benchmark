"""SQLite storage layer for the qual pipeline using aiosqlite.

Provides async CRUD operations for qual pipeline runs, benchmark items,
LLM responses, judge scores, and QA reports. Uses WAL mode for better
concurrent read performance.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

import aiosqlite

from llmbench.qual.schemas import (
    BenchmarkDataset,
    BenchmarkItem,
    JudgeScore,
    LLMResponse,
    QAReport,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# SQL DDL
# ---------------------------------------------------------------------------

_CREATE_TABLES_SQL = """
CREATE TABLE IF NOT EXISTS qual_runs (
    id          TEXT PRIMARY KEY,
    created_at  TEXT NOT NULL,
    config_json TEXT NOT NULL DEFAULT '{}',
    status      TEXT NOT NULL DEFAULT 'pending'
);

CREATE TABLE IF NOT EXISTS benchmark_items (
    id               TEXT PRIMARY KEY,
    run_id           TEXT NOT NULL,
    task_type        TEXT NOT NULL,
    source_category  TEXT NOT NULL,
    title            TEXT NOT NULL,
    content          TEXT NOT NULL,
    prompt           TEXT NOT NULL,
    reference_answer TEXT,
    scoring_rubric   TEXT NOT NULL,
    FOREIGN KEY (run_id) REFERENCES qual_runs(id)
);

CREATE TABLE IF NOT EXISTS llm_responses (
    id                TEXT PRIMARY KEY,
    run_id            TEXT NOT NULL,
    benchmark_item_id TEXT NOT NULL,
    model_name        TEXT NOT NULL,
    response_text     TEXT NOT NULL,
    latency_ms        REAL NOT NULL,
    token_count       INTEGER NOT NULL,
    error             TEXT,
    FOREIGN KEY (run_id)            REFERENCES qual_runs(id),
    FOREIGN KEY (benchmark_item_id) REFERENCES benchmark_items(id)
);

CREATE TABLE IF NOT EXISTS judge_scores (
    id                TEXT PRIMARY KEY,
    run_id            TEXT NOT NULL,
    benchmark_item_id TEXT NOT NULL,
    model_name        TEXT NOT NULL,
    score             INTEGER NOT NULL,
    reasoning         TEXT NOT NULL,
    judge_model       TEXT NOT NULL,
    FOREIGN KEY (run_id)            REFERENCES qual_runs(id),
    FOREIGN KEY (benchmark_item_id) REFERENCES benchmark_items(id)
);

CREATE TABLE IF NOT EXISTS qa_reports (
    id                       TEXT PRIMARY KEY,
    run_id                   TEXT NOT NULL UNIQUE,
    dataset_quality_json     TEXT NOT NULL,
    scoring_consistency_json TEXT NOT NULL,
    issues_json              TEXT NOT NULL,
    pass_                    INTEGER NOT NULL,
    FOREIGN KEY (run_id) REFERENCES qual_runs(id)
);

CREATE INDEX IF NOT EXISTS idx_benchmark_items_run
    ON benchmark_items(run_id);
CREATE INDEX IF NOT EXISTS idx_llm_responses_run
    ON llm_responses(run_id);
CREATE INDEX IF NOT EXISTS idx_llm_responses_item
    ON llm_responses(benchmark_item_id);
CREATE INDEX IF NOT EXISTS idx_judge_scores_run
    ON judge_scores(run_id);
CREATE INDEX IF NOT EXISTS idx_judge_scores_item
    ON judge_scores(benchmark_item_id);
"""


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _gen_id() -> str:
    import uuid
    return str(uuid.uuid4())


class QualDB:
    """Lightweight async SQLite storage for qual pipeline data.

    Uses *aiosqlite* directly (no ORM) for minimal dependencies.
    """

    def __init__(self, db_path: str = "llmbench_qual.db") -> None:
        self.db_path = db_path

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def init(self) -> None:
        """Create tables and enable WAL mode (idempotent)."""
        logger.info("Initialising QualDB at %s", self.db_path)
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("PRAGMA journal_mode=WAL")
            await db.execute("PRAGMA foreign_keys=ON")
            await db.executescript(_CREATE_TABLES_SQL)
            await db.commit()
        logger.info("QualDB tables ready")

    # ------------------------------------------------------------------
    # Run management
    # ------------------------------------------------------------------

    async def create_run(
        self,
        run_id: str,
        config_json: dict[str, Any] | None = None,
        status: str = "pending",
    ) -> str:
        """Insert a new qual_runs row and return its *run_id*."""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("PRAGMA foreign_keys=ON")
            await db.execute(
                "INSERT INTO qual_runs (id, created_at, config_json, status) "
                "VALUES (?, ?, ?, ?)",
                (
                    run_id,
                    _now_iso(),
                    json.dumps(config_json or {}, ensure_ascii=False),
                    status,
                ),
            )
            await db.commit()
        logger.debug("Created run %s", run_id)
        return run_id

    async def update_run_status(self, run_id: str, status: str) -> None:
        """Update the status column of an existing run."""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "UPDATE qual_runs SET status = ? WHERE id = ?",
                (status, run_id),
            )
            await db.commit()
        logger.debug("Run %s status -> %s", run_id, status)

    async def get_run(self, run_id: str) -> dict[str, Any] | None:
        """Return a single run as a dict, or ``None`` if not found."""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT * FROM qual_runs WHERE id = ?", (run_id,)
            )
            row = await cursor.fetchone()
            if row is None:
                return None
            return {
                "id": row["id"],
                "created_at": row["created_at"],
                "config_json": json.loads(row["config_json"]),
                "status": row["status"],
            }

    async def list_runs(self) -> list[dict[str, Any]]:
        """Return all runs ordered by creation time (newest first)."""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT * FROM qual_runs ORDER BY created_at DESC"
            )
            rows = await cursor.fetchall()
            return [
                {
                    "id": r["id"],
                    "created_at": r["created_at"],
                    "config_json": json.loads(r["config_json"]),
                    "status": r["status"],
                }
                for r in rows
            ]

    # ------------------------------------------------------------------
    # Dataset (BenchmarkDataset -> benchmark_items)
    # ------------------------------------------------------------------

    async def save_dataset(
        self, run_id: str, dataset: BenchmarkDataset
    ) -> None:
        """Persist all :class:`BenchmarkItem` rows for the given run."""
        logger.info(
            "Saving dataset (%d items) for run %s", len(dataset.items), run_id
        )
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("PRAGMA foreign_keys=ON")
            for item in dataset.items:
                await db.execute(
                    "INSERT OR REPLACE INTO benchmark_items "
                    "(id, run_id, task_type, source_category, title, "
                    " content, prompt, reference_answer, scoring_rubric) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        item.id,
                        run_id,
                        item.task_type.value,
                        item.source_material.source_category,
                        item.source_material.title,
                        item.source_material.content,
                        item.prompt,
                        item.reference_answer,
                        item.scoring_rubric,
                    ),
                )
            await db.commit()
        logger.debug("Dataset saved for run %s", run_id)

    async def get_dataset_items(
        self, run_id: str
    ) -> list[dict[str, Any]]:
        """Return all benchmark items for a run."""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT * FROM benchmark_items WHERE run_id = ?", (run_id,)
            )
            rows = await cursor.fetchall()
            return [dict(r) for r in rows]

    # ------------------------------------------------------------------
    # LLM responses
    # ------------------------------------------------------------------

    async def save_responses(
        self, run_id: str, responses: list[LLMResponse]
    ) -> None:
        """Persist a batch of :class:`LLMResponse` rows."""
        logger.info(
            "Saving %d LLM responses for run %s", len(responses), run_id
        )
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("PRAGMA foreign_keys=ON")
            for resp in responses:
                await db.execute(
                    "INSERT INTO llm_responses "
                    "(id, run_id, benchmark_item_id, model_name, "
                    " response_text, latency_ms, token_count, error) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        _gen_id(),
                        run_id,
                        resp.benchmark_item_id,
                        resp.model_name,
                        resp.response_text,
                        resp.latency_ms,
                        resp.token_count,
                        resp.error,
                    ),
                )
            await db.commit()
        logger.debug("Responses saved for run %s", run_id)

    async def get_responses(
        self, run_id: str
    ) -> list[dict[str, Any]]:
        """Return all LLM responses for a run."""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT * FROM llm_responses WHERE run_id = ?", (run_id,)
            )
            rows = await cursor.fetchall()
            return [dict(r) for r in rows]

    # ------------------------------------------------------------------
    # Judge scores
    # ------------------------------------------------------------------

    async def save_scores(
        self, run_id: str, scores: list[JudgeScore]
    ) -> None:
        """Persist a batch of :class:`JudgeScore` rows."""
        logger.info(
            "Saving %d judge scores for run %s", len(scores), run_id
        )
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("PRAGMA foreign_keys=ON")
            for sc in scores:
                await db.execute(
                    "INSERT INTO judge_scores "
                    "(id, run_id, benchmark_item_id, model_name, "
                    " score, reasoning, judge_model) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (
                        _gen_id(),
                        run_id,
                        sc.benchmark_item_id,
                        sc.model_name,
                        sc.score,
                        sc.reasoning,
                        sc.judge_model,
                    ),
                )
            await db.commit()
        logger.debug("Scores saved for run %s", run_id)

    async def get_scores(
        self, run_id: str
    ) -> list[dict[str, Any]]:
        """Return all judge scores for a run."""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT * FROM judge_scores WHERE run_id = ?", (run_id,)
            )
            rows = await cursor.fetchall()
            return [dict(r) for r in rows]

    # ------------------------------------------------------------------
    # QA report
    # ------------------------------------------------------------------

    async def save_report(self, run_id: str, report: QAReport) -> None:
        """Persist the :class:`QAReport` for a run (one report per run)."""
        logger.info("Saving QA report for run %s", run_id)
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("PRAGMA foreign_keys=ON")
            await db.execute(
                "INSERT OR REPLACE INTO qa_reports "
                "(id, run_id, dataset_quality_json, scoring_consistency_json, "
                " issues_json, pass_) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (
                    _gen_id(),
                    run_id,
                    json.dumps(
                        report.dataset_quality, ensure_ascii=False
                    ),
                    json.dumps(
                        report.scoring_consistency, ensure_ascii=False
                    ),
                    json.dumps(report.issues, ensure_ascii=False),
                    int(report.pass_),
                ),
            )
            await db.commit()
        logger.debug("QA report saved for run %s", run_id)

    async def get_report(self, run_id: str) -> dict[str, Any] | None:
        """Return the QA report for a run, or ``None``."""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT * FROM qa_reports WHERE run_id = ?", (run_id,)
            )
            row = await cursor.fetchone()
            if row is None:
                return None
            return {
                "id": row["id"],
                "run_id": row["run_id"],
                "dataset_quality": json.loads(row["dataset_quality_json"]),
                "scoring_consistency": json.loads(
                    row["scoring_consistency_json"]
                ),
                "issues": json.loads(row["issues_json"]),
                "pass_": bool(row["pass_"]),
            }
