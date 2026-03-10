from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal


TaskUnitStatus = Literal["pending", "done"]


@dataclass(slots=True)
class TaskUnit:
    id: str
    parent_task_id: str
    week_start_iso: str
    day_index: int
    order_index: int
    custom_title: str
    status: TaskUnitStatus
    created_from_plan: bool

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> TaskUnit | None:
        if not isinstance(raw, dict):
            return None

        unit_id = str(raw.get("id") or "").strip()
        task_id = str(raw.get("parent_task_id") or "").strip()
        week_start_iso = str(raw.get("week_start_iso") or "").strip()
        if not unit_id or not task_id or not week_start_iso:
            return None

        try:
            day_index = int(raw.get("day_index"))
            order_index = int(raw.get("order_index"))
        except (TypeError, ValueError):
            return None
        if not 0 <= day_index <= 6:
            return None

        status_raw = str(raw.get("status") or "pending").strip().lower()
        status: TaskUnitStatus = "done" if status_raw == "done" else "pending"

        custom_title = str(raw.get("custom_title") or "").strip()
        created_from_plan = bool(raw.get("created_from_plan", True))

        return cls(
            id=unit_id,
            parent_task_id=task_id,
            week_start_iso=week_start_iso,
            day_index=day_index,
            order_index=max(0, order_index),
            custom_title=custom_title,
            status=status,
            created_from_plan=created_from_plan,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "parent_task_id": self.parent_task_id,
            "week_start_iso": self.week_start_iso,
            "day_index": self.day_index,
            "order_index": self.order_index,
            "custom_title": self.custom_title,
            "status": self.status,
            "created_from_plan": self.created_from_plan,
        }

