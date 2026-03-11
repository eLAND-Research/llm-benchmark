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


class DataSourceConfig(BaseModel):
    """TDS MCP data-source configuration."""

    mcp_url: str = "http://172.18.10.41:8888/sse"
    searches: List[SearchConfig]


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
    max_concurrent: int = 5


class QualConfig(BaseModel):
    """Top-level qual pipeline configuration."""

    data_source: DataSourceConfig
    task_types: List[str] = Field(
        default_factory=lambda: ["summarization", "sentiment", "classification", "qa"],
    )
    items_per_task: int = 10
    models_under_test: List[ModelConfig]
    judge: JudgeConfig
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
