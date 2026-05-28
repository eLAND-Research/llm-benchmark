"""Configuration schema and loader for the qual (quality evaluation) pipeline."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml
from pydantic import BaseModel, Field, field_validator


# ---------------------------------------------------------------------------
# Pydantic v2 models
# ---------------------------------------------------------------------------


class SearchConfig(BaseModel):
    """Single search definition for data retrieval."""

    categories: List[str] = Field(description='e.g. ["news", "facebook", "dcard"]')
    keyword: str = Field(description='Search keyword, e.g. "川普 & 關稅"')
    top_k: int = 20
    month_range: Optional[Dict[str, str]] = Field(
        default=None,
        description='Optional date range, e.g. {"start": "202501", "end": "202502"}',
    )
    sort_by: str = "time"


class OpViewMCPConfig(BaseModel):
    """OpView MCP data-source accessed via LiteLLM proxy (HTTPS + Bearer Token).

    Rate limits (shared quota):  rpm=30, tpm=200K, max_parallel=5
    """

    litellm_url: str = "https://llmgw.elandai.cloud"
    litellm_api_key: str = "env:LITELLM_MCP_API_KEY"
    mcp_alias: str = "opview_tds"
    timeout: int = 30
    max_parallel: int = 5  # match shared quota: max_parallel=5

    @field_validator("litellm_api_key")
    @classmethod
    def resolve_env(cls, v: str) -> str:
        if v and v.startswith("env:"):
            env_key = v.split("env:", 1)[1]
            return os.getenv(env_key) or ""
        return v


class ChallengeSourceConfig(BaseModel):
    """Use a challenge's JSONL data as qual pipeline source material.

    Each JSONL line should contain at least a ``text`` field.
    Optional fields: ``title``, ``source_category``, ``keyword``, ``month``.
    """

    data_jsonl: str = Field(description="Raw JSONL content from a challenge")
    keyword: str = ""


class ThreadsSourceConfig(BaseModel):
    """Local Threads scraper data source.

    Reads JSON files produced by the threads-scraper project from a local
    directory.
    """

    directory: str = Field(description="Path to directory containing *.json scraper output files")
    keyword: str = ""
    include_replies: bool = False
    combine_replies: bool = False
    min_like_count: int = 0
    min_replies_count: int = 0
    min_repost_count: int = 0
    date_start: Optional[str] = None
    date_end: Optional[str] = None
    text_contains: Optional[str] = None
    min_text_length: int = 0
    exclude_emoji_only: bool = False
    limit: Optional[int] = None


class TaiwanMdSourceConfig(BaseModel):
    """Taiwan.md open knowledge base data source (CC BY-SA 4.0).

    Fetches articles from https://github.com/frank890417/taiwan-md
    """

    categories: Optional[List[str]] = Field(
        default=None,
        description='Categories to include, e.g. ["Technology", "History"]. None = all.',
    )
    lang: str = Field(default="zh-TW", description='"zh-TW" or "en"')
    limit: Optional[int] = None
    timeout: int = 15


class SchoolQASourceConfig(BaseModel):
    """Taiwanese elementary (國小) / middle school (國中) curriculum data source.

    Uses built-in curriculum knowledge materials to generate exam-style
    benchmark items (選擇題、填充題、問答題).  Optionally loads from a
    custom JSONL file instead of built-in materials.
    """

    level: str = Field(
        default="both",
        description='"elementary" (國小), "middle_school" (國中), or "both".',
    )
    subjects: Optional[List[str]] = Field(
        default=None,
        description='Subject names to include, e.g. ["數學", "理化"]. None = all.',
    )
    data_jsonl: Optional[str] = Field(
        default=None,
        description=(
            "Path to a custom JSONL file. Each line: "
            '{"level": ..., "subject": ..., "title": ..., "content": ...}. '
            "When set, built-in materials are not used."
        ),
    )
    limit: Optional[int] = None


class ExamBankSourceConfig(BaseModel):
    """Taiwanese school exam bank data source.

    Downloads exam PDFs listed in a manifest CSV/JSON and/or extracts PDFs
    from local zip archives.  Each PDF is parsed with ``pdfplumber`` and
    converted into a :class:`RawMaterial` for the school_qa pipeline.

    Requires ``pdfplumber`` (``uv add pdfplumber`` / ``pip install pdfplumber``).
    """

    manifest: Optional[str] = Field(
        default=None,
        description="Path to manifest CSV or JSON (columns: file_url, subject, grade, school, ...).",
    )
    zip_archives: Optional[List[str]] = Field(
        default=None,
        description="Paths to local .zip archives containing exam PDFs.",
    )
    level: str = Field(
        default="both",
        description='"elementary" (國小), "middle_school" (國中), or "both".',
    )
    subjects: Optional[List[str]] = Field(
        default=None,
        description='Subject filter, e.g. ["國文", "數學"]. None = all.',
    )
    grades: Optional[List[str]] = Field(
        default=None,
        description='Grade filter, e.g. ["5", "6"]. None = all.',
    )
    cache_dir: str = Field(
        default="data/exam_bank/pdf_cache",
        description="Directory for caching downloaded PDFs.",
    )
    limit: Optional[int] = None
    download_timeout: int = 30
    max_download_workers: int = 4
    parse_questions: bool = Field(
        default=False,
        description=(
            "When True, directly parse MCQ questions from PDFs and match with answer sheets. "
            "The Designer LLM is bypassed — each parsed question becomes a BenchmarkItem directly. "
            "When False (default), the full PDF text is treated as an article for the Designer to generate questions from."
        ),
    )


class DataSourceConfig(BaseModel):
    """TDS MCP data-source configuration.

    Supports backends (priority: challenge > taiwan_md > school_qa > threads > opview_mcp > mcp_url):
    - ``school_qa``: Built-in Taiwanese elementary/middle school curriculum materials
    - ``taiwan_md``: Taiwan.md open knowledge base (GitHub)
    - ``threads``: Local Threads scraper JSON files
    - ``opview_mcp``: OpView MCP via LiteLLM proxy (HTTPS + Bearer Token)
    - ``mcp_url``: SSE-based MCP server (original)
    """

    mcp_url: str = "http://172.18.10.41:8888/sse"
    opview_mcp: Optional[OpViewMCPConfig] = None
    threads: Optional[List[ThreadsSourceConfig]] = None
    challenge: Optional[ChallengeSourceConfig] = None
    taiwan_md: Optional[TaiwanMdSourceConfig] = None
    school_qa: Optional[SchoolQASourceConfig] = None
    exam_bank: Optional[ExamBankSourceConfig] = None
    searches: List[SearchConfig] = Field(default_factory=list)


class ModelConfig(BaseModel):
    """LLM model configuration (model-under-test or judge)."""

    name: str
    base_url: str
    api_key: str = ""
    model: str

    @field_validator("api_key")
    @classmethod
    def resolve_env(cls, v: str) -> str:
        """Resolve ``env:VAR_NAME`` references to environment variables."""
        if v and v.startswith("env:"):
            env_key = v.split("env:", 1)[1]
            return os.getenv(env_key) or ""
        return v


class JudgeConfig(BaseModel):
    """Judge (evaluator) configuration."""

    model: ModelConfig
    max_concurrent: int = 4
    min_request_interval_sec: float = 2.1


class QualConfig(BaseModel):
    """Top-level qual pipeline configuration."""

    data_source: DataSourceConfig
    task_types: List[str] = Field(
        default_factory=lambda: ["summarization", "sentiment", "classification", "qa"],
    )
    items_per_task: int = 10
    questions_per_article: int = 10  # for true_false: how many questions to generate per article
    models_under_test: List[ModelConfig]
    judge: JudgeConfig
    executor_max_concurrent: int = 4
    output_dir: str = "results/qual"
    db_path: str = "llmbench_qual.db"


# ---------------------------------------------------------------------------
# YAML helpers
# ---------------------------------------------------------------------------


def _resolve_env_vars(obj: Any) -> Any:
    """Recursively walk a parsed YAML structure and resolve ``env:VAR`` strings.

    This mirrors the approach used by the existing config system where
    ``field_validator`` handles top-level fields, but nested / dynamic values
    also need resolution before Pydantic sees them.
    """
    if isinstance(obj, str):
        if obj.startswith("env:"):
            env_key = obj.split("env:", 1)[1]
            return os.getenv(env_key, "")
        return obj
    if isinstance(obj, dict):
        return {k: _resolve_env_vars(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_resolve_env_vars(item) for item in obj]
    return obj


def _read_yaml(path: Path) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


# ---------------------------------------------------------------------------
# Public loader
# ---------------------------------------------------------------------------


def load_qual_config(path: str | Path) -> QualConfig:
    """Load a :class:`QualConfig` from a YAML file.

    The YAML file is expected to contain the qual settings under a top-level
    ``qual:`` key::

        qual:
          data_source:
            searches:
              - categories: ["news"]
                keyword: "example"
          models_under_test:
            - name: gpt-4o
              base_url: https://api.openai.com/v1
              api_key: "env:OPENAI_API_KEY"
              model: gpt-4o
          judge:
            model:
              name: gpt-4o
              base_url: https://api.openai.com/v1
              api_key: "env:OPENAI_API_KEY"
              model: gpt-4o

    Parameters
    ----------
    path:
        Filesystem path to the YAML config file.

    Returns
    -------
    QualConfig
        Validated configuration object.

    Raises
    ------
    FileNotFoundError
        If *path* does not exist.
    KeyError
        If the YAML file does not contain a ``qual`` key.
    """
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"Config file not found: {p}")

    data = _read_yaml(p)

    if "qual" not in data:
        raise KeyError(
            f"Config file {p} does not contain a 'qual' key at the top level."
        )

    qual_data = _resolve_env_vars(data["qual"])
    return QualConfig(**qual_data)
