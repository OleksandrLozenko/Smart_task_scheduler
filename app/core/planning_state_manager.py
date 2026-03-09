from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class PlanningStateManager:
    def __init__(self, path: str | Path = "planner_state.json") -> None:
        self._path = Path(path)

    def load(self) -> dict[str, Any]:
        default: dict[str, Any] = {"tasks": [], "excluded_cells": {}}
        if not self._path.exists():
            self.save(default)
            return default
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            self.save(default)
            return default
        if not isinstance(raw, dict):
            self.save(default)
            return default

        tasks = raw.get("tasks", [])
        excluded_cells = raw.get("excluded_cells", {})
        if not isinstance(tasks, list):
            tasks = []
        if not isinstance(excluded_cells, dict):
            excluded_cells = {}

        normalized = {"tasks": tasks, "excluded_cells": excluded_cells}
        self.save(normalized)
        return normalized

    def save(self, data: dict[str, Any]) -> None:
        self._path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
