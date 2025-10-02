"""Scenario abstractions."""
from __future__ import annotations
from abc import ABC, abstractmethod
from typing import Any, Dict, List
from pathlib import Path
import json


class Scenario(ABC):
    def __init__(self, name: str, raw_config: Dict[str, Any]):
        self.name = name
        self.raw_config = raw_config

    @abstractmethod
    def load_inputs(self) -> List[Dict[str, Any]]:
        """Return a list of request payload specifications (e.g., messages)."""


class ChatScenario(Scenario):
    def __init__(self, name: str, raw_config: Dict[str, Any]):
        super().__init__(name, raw_config)
        self.prompts_file = raw_config.get("prompts_file")

    def load_inputs(self) -> List[Dict[str, Any]]:
        if not self.prompts_file:
            return []
        path = Path(self.prompts_file)
        if not path.exists():
            raise FileNotFoundError(f"Prompts file not found: {path}")
        items: List[Dict[str, Any]] = []
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                    items.append(obj)
                except json.JSONDecodeError:
                    items.append({"role": "user", "content": line})
        return items


def build_scenario(s_cfg: Dict[str, Any]) -> Scenario:
    stype = s_cfg.get("type")
    name = s_cfg.get("name", stype)
    if stype in ("chat_short", "chat_long", "chat"):
        return ChatScenario(name, s_cfg)
    raise ValueError(f"Unsupported scenario type: {stype}")

