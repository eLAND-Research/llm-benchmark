"""Config loader for YAML -> Pydantic RootConfig."""
from __future__ import annotations
import yaml
from pathlib import Path
from .schema import RootConfig
from typing import Any, Dict


def _read_yaml(path: Path) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def load_config(path: str | Path) -> RootConfig:
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"Config file not found: {p}")
    data = _read_yaml(p)
    return RootConfig(**data)


def load_config_from_dict(data: Dict[str, Any]) -> RootConfig:
    return RootConfig(**data)

