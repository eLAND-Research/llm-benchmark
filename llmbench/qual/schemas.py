"""Pydantic v2 schemas for the LLM quality validation pipeline.

Defines data structures for every stage of the qual pipeline:
RawMaterial (Researcher) -> BenchmarkItem/Dataset (Designer) ->
LLMResponse (Executor) -> JudgeScore (Judge) -> QAReport (QA Tester) ->
QualRunResult (final output).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class TaskType(str, Enum):
    SUMMARIZATION = "summarization"
    SENTIMENT = "sentiment"
    CLASSIFICATION = "classification"
    QA = "qa"


class SentimentLabel(str, Enum):
    POSITIVE = "positive"
    NEGATIVE = "negative"
    NEUTRAL = "neutral"


class TopicCategory(str, Enum):
    POLITICS = "politics"
    TECHNOLOGY = "technology"
    FINANCE = "finance"
    ENTERTAINMENT = "entertainment"
    SPORTS = "sports"
    SOCIETY = "society"
    INTERNATIONAL = "international"
    OTHER = "other"


# ---------------------------------------------------------------------------
# 1. RawMaterial -- Researcher output
# ---------------------------------------------------------------------------
class RawMaterial(BaseModel):
    """Source material collected by the Researcher agent."""

    source_category: str  # "news" / "facebook" / "dcard"
    title: str
    content: str
    keyword: str  # keyword used for retrieval
    month_range: Dict[str, str]  # {"start": "YYYYMM", "end": "YYYYMM"}


# ---------------------------------------------------------------------------
# 2. BenchmarkItem -- single item produced by Designer
# ---------------------------------------------------------------------------
class BenchmarkItem(BaseModel):
    """A single benchmark question/task created by the Designer agent."""

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    task_type: TaskType
    source_material: RawMaterial
    prompt: str  # full prompt sent to the LLM under test
    reference_answer: Optional[str] = None  # reference answer from Designer
    scoring_rubric: str  # scoring criteria description


# ---------------------------------------------------------------------------
# 3. BenchmarkDataset -- full dataset of benchmark items
# ---------------------------------------------------------------------------
class BenchmarkDataset(BaseModel):
    """Complete benchmark dataset containing multiple items."""

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    created_at: datetime = Field(default_factory=datetime.now)
    task_types: List[TaskType]
    items: List[BenchmarkItem]
    metadata: Dict[str, Any] = Field(default_factory=dict)  # e.g. config fingerprint


# ---------------------------------------------------------------------------
# 4. LLMResponse -- Executor output
# ---------------------------------------------------------------------------
class LLMResponse(BaseModel):
    """Response captured from the LLM under test by the Executor."""

    model_config = {"protected_namespaces": ()}

    benchmark_item_id: str
    model_name: str
    response_text: str
    latency_ms: float
    token_count: int
    error: Optional[str] = None  # populated when the call fails


# ---------------------------------------------------------------------------
# 5. JudgeScore -- Judge output
# ---------------------------------------------------------------------------
class JudgeScore(BaseModel):
    """Score assigned by the Judge model for a single response."""

    model_config = {"protected_namespaces": ()}

    benchmark_item_id: str
    model_name: str
    score: int = Field(ge=1, le=5)  # 1-5 scale
    reasoning: str  # justification for the score
    judge_model: str  # which model served as judge


# ---------------------------------------------------------------------------
# 6. QAReport -- QA Tester output
# ---------------------------------------------------------------------------
class QAReport(BaseModel):
    """Quality assurance report produced by the QA Tester."""

    dataset_quality: Dict[str, Any]  # dataset quality indicators
    scoring_consistency: Dict[str, Any]  # scoring consistency indicators
    issues: List[str] = Field(default_factory=list)
    pass_: bool = Field(alias="pass")  # overall pass/fail

    model_config = {"populate_by_name": True}


# ---------------------------------------------------------------------------
# 7. QualRunResult -- final pipeline output
# ---------------------------------------------------------------------------
class QualRunResult(BaseModel):
    """End-to-end result of a complete qual pipeline run."""

    run_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    created_at: datetime = Field(default_factory=datetime.now)
    dataset: BenchmarkDataset
    responses: List[LLMResponse]
    scores: List[JudgeScore]
    qa_report: QAReport
