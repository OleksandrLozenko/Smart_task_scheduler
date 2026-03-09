from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class PlanningStateManager:
    def __init__(self, path: str | Path = "planner_state.json") -> None:
        self._path = Path(path)

    def load(self) -> dict[str, Any]:
        default: dict[str, Any] = {
            "tasks": [],
            "excluded_cells": {},
            "planned_cells": {},
            "done_cells": {},
            "weekly_targets": {},
            "selected_task_id": None,
            "selected_day_index": None,
        }
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
        planned_cells = raw.get("planned_cells", {})
        done_cells = raw.get("done_cells", {})
        weekly_targets = raw.get("weekly_targets", {})
        selected_task_id = raw.get("selected_task_id")
        selected_day_index = raw.get("selected_day_index")
        if not isinstance(tasks, list):
            tasks = []
        if not isinstance(excluded_cells, dict):
            excluded_cells = {}
        if not isinstance(planned_cells, dict):
            planned_cells = {}
        if not isinstance(done_cells, dict):
            done_cells = {}
        if not isinstance(weekly_targets, dict):
            weekly_targets = {}
        if selected_task_id is not None and not isinstance(selected_task_id, str):
            selected_task_id = None
        if not isinstance(selected_day_index, int) or not 0 <= int(selected_day_index) <= 6:
            selected_day_index = None

        normalized = {
            "tasks": tasks,
            "excluded_cells": excluded_cells,
            "planned_cells": planned_cells,
            "done_cells": done_cells,
            "weekly_targets": weekly_targets,
            "selected_task_id": selected_task_id,
            "selected_day_index": selected_day_index,
        }
        self.save(normalized)
        return normalized

    def save(self, data: dict[str, Any]) -> None:
        self._path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
