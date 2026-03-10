from __future__ import annotations

from uuid import uuid4

from app.core.planner_models import TaskUnit


class PlannerController:
    """Owns task-unit detail layer and keeps it in sync with planning grid values."""

    def __init__(self) -> None:
        self._task_units_by_week: dict[str, list[TaskUnit]] = {}

    def has_any_units(self) -> bool:
        return any(units for units in self._task_units_by_week.values())

    def week_keys(self) -> set[str]:
        return set(self._task_units_by_week.keys())

    def has_unit(self, *, week_start_iso: str, unit_id: str) -> bool:
        if not unit_id:
            return False
        for unit in self._task_units_by_week.get(week_start_iso, []):
            if unit.id == unit_id:
                return True
        return False

    def get_unit(self, *, week_start_iso: str, unit_id: str) -> TaskUnit | None:
        if not unit_id:
            return None
        for unit in self._task_units_by_week.get(week_start_iso, []):
            if unit.id == unit_id:
                return unit
        return None

    def units_for_day(self, *, week_start_iso: str, day_index: int) -> list[TaskUnit]:
        if not 0 <= int(day_index) <= 6:
            return []
        units = [
            unit
            for unit in self._task_units_by_week.get(week_start_iso, [])
            if unit.day_index == day_index
        ]
        units.sort(key=lambda unit: (unit.order_index, unit.id))
        return units

    def set_unit_custom_title(self, *, week_start_iso: str, unit_id: str, custom_title: str) -> bool:
        cleaned = str(custom_title).strip()
        units = self._task_units_by_week.get(week_start_iso, [])
        for unit in units:
            if unit.id == unit_id:
                unit.custom_title = cleaned
                return True
        return False

    def move_unit_within_day(
        self,
        *,
        week_start_iso: str,
        day_index: int,
        unit_id: str,
        delta: int,
    ) -> bool:
        if delta == 0 or not 0 <= int(day_index) <= 6:
            return False

        units = self._task_units_by_week.get(week_start_iso, [])
        if not units:
            return False

        day_units = [unit for unit in units if unit.day_index == day_index]
        day_units.sort(key=lambda unit: (unit.order_index, unit.id))
        if len(day_units) < 2:
            return False

        current_idx = next((idx for idx, unit in enumerate(day_units) if unit.id == unit_id), -1)
        if current_idx < 0:
            return False
        target_idx = current_idx + int(delta)
        if not 0 <= target_idx < len(day_units):
            return False

        ordered_ids = [unit.id for unit in day_units]
        moved = ordered_ids.pop(current_idx)
        ordered_ids.insert(target_idx, moved)
        id_to_pos = {uid: idx for idx, uid in enumerate(ordered_ids)}
        for unit in day_units:
            unit.order_index = id_to_pos.get(unit.id, unit.order_index)

        self._task_units_by_week[week_start_iso] = self._sort_and_reindex(units)
        return True

    def reorder_day_units(
        self,
        *,
        week_start_iso: str,
        day_index: int,
        ordered_unit_ids: list[str],
    ) -> bool:
        if not 0 <= int(day_index) <= 6:
            return False

        units = self._task_units_by_week.get(week_start_iso, [])
        if not units:
            return False

        day_units = [unit for unit in units if unit.day_index == day_index]
        if not day_units:
            return False

        normalized_order = [str(uid) for uid in ordered_unit_ids if str(uid)]
        day_ids = [unit.id for unit in day_units]
        if len(normalized_order) != len(day_ids):
            return False
        if set(normalized_order) != set(day_ids):
            return False

        index_map = {unit_id: idx for idx, unit_id in enumerate(normalized_order)}
        changed = False
        for unit in day_units:
            new_index = index_map.get(unit.id, unit.order_index)
            if unit.order_index != new_index:
                changed = True
            unit.order_index = new_index

        if not changed:
            return False

        self._task_units_by_week[week_start_iso] = self._sort_and_reindex(units)
        return True

    def load_task_units_by_week(self, raw: object) -> None:
        normalized: dict[str, list[TaskUnit]] = {}
        if isinstance(raw, dict):
            for week_key, raw_units in raw.items():
                if not isinstance(raw_units, list):
                    continue
                week_id = str(week_key).strip()
                if not week_id:
                    continue
                units: list[TaskUnit] = []
                for item in raw_units:
                    if not isinstance(item, dict):
                        continue
                    unit = TaskUnit.from_dict(item)
                    if unit is None:
                        continue
                    if unit.week_start_iso != week_id:
                        unit.week_start_iso = week_id
                    units.append(unit)
                if units:
                    normalized[week_id] = self._sort_and_reindex(units)
        self._task_units_by_week = normalized

    def dump_task_units_by_week(self) -> dict[str, list[dict[str, object]]]:
        serialized: dict[str, list[dict[str, object]]] = {}
        for week_key, units in self._task_units_by_week.items():
            if not units:
                continue
            sorted_units = self._sort_and_reindex(list(units))
            serialized[week_key] = [unit.to_dict() for unit in sorted_units]
            self._task_units_by_week[week_key] = sorted_units
        return serialized

    def remove_task(self, task_id: str) -> None:
        for week_key in list(self._task_units_by_week.keys()):
            survivors = [unit for unit in self._task_units_by_week[week_key] if unit.parent_task_id != task_id]
            if survivors:
                self._task_units_by_week[week_key] = self._sort_and_reindex(survivors)
            else:
                self._task_units_by_week.pop(week_key, None)

    def bootstrap_from_legacy(
        self,
        *,
        task_ids: set[str],
        planned_by_week: dict[str, dict[str, list[int]]],
        done_by_week: dict[str, dict[str, list[int]]],
    ) -> None:
        if self.has_any_units():
            return

        week_keys = set(planned_by_week.keys()) | set(done_by_week.keys())
        for week_key in week_keys:
            planned_week = planned_by_week.get(week_key, {})
            done_week = done_by_week.get(week_key, {})
            if not isinstance(planned_week, dict):
                planned_week = {}
            if not isinstance(done_week, dict):
                done_week = {}
            generated: list[TaskUnit] = []
            for task_id in task_ids:
                planned_values = self._normalize_day_values(planned_week.get(task_id))
                done_values = self._normalize_day_values(done_week.get(task_id))
                for day_index in range(7):
                    planned = planned_values[day_index]
                    done = max(0, done_values[day_index])
                    effective = max(planned, done)
                    if effective <= 0:
                        continue
                    for idx in range(effective):
                        generated.append(
                            TaskUnit(
                                id=uuid4().hex,
                                parent_task_id=task_id,
                                week_start_iso=week_key,
                                day_index=day_index,
                                order_index=idx,
                                custom_title="",
                                status="done" if idx < done else "pending",
                                created_from_plan=True,
                            )
                        )
            if generated:
                self._task_units_by_week[week_key] = self._sort_and_reindex(generated)

    def reconcile_week(
        self,
        *,
        week_start_iso: str,
        task_ids: set[str],
        planned_cells_week: dict[str, list[int]],
        excluded_cells_week: dict[str, set[int]],
    ) -> dict[str, list[int]]:
        cleaned_planned: dict[str, list[int]] = {
            task_id: self._normalize_day_values(planned_cells_week.get(task_id))
            for task_id in task_ids
        }
        planned_cells_week.clear()
        planned_cells_week.update(cleaned_planned)

        cleaned_excluded: dict[str, set[int]] = {}
        for task_id in task_ids:
            raw_days = excluded_cells_week.get(task_id, set())
            normalized_days = {int(v) for v in raw_days if isinstance(v, int) and 0 <= int(v) <= 6}
            if normalized_days:
                cleaned_excluded[task_id] = normalized_days
        excluded_cells_week.clear()
        excluded_cells_week.update(cleaned_excluded)

        current_units = self._sort_and_reindex(
            [
            unit
            for unit in self._task_units_by_week.get(week_start_iso, [])
            if unit.parent_task_id in task_ids and unit.week_start_iso == week_start_iso and 0 <= unit.day_index <= 6
            ]
        )

        grouped_by_day: dict[int, list[TaskUnit]] = {day: [] for day in range(7)}
        for unit in current_units:
            grouped_by_day[unit.day_index].append(unit)

        for day_index in range(7):
            day_units = list(grouped_by_day.get(day_index, []))
            if day_units:
                day_units.sort(key=lambda unit: (unit.order_index, unit.id))

            # Preserve user ordering as much as possible: iterate tasks in first appearance order.
            seen_task_ids: set[str] = set()
            task_order: list[str] = []
            for unit in day_units:
                if unit.parent_task_id not in seen_task_ids:
                    seen_task_ids.add(unit.parent_task_id)
                    task_order.append(unit.parent_task_id)
            for task_id in sorted(task_ids):
                if task_id not in seen_task_ids:
                    task_order.append(task_id)

            for task_id in task_order:
                planned_values = planned_cells_week.setdefault(task_id, [0] * 7)
                excluded_days = excluded_cells_week.get(task_id, set())
                task_day_units = [unit for unit in day_units if unit.parent_task_id == task_id]
                done_count = sum(1 for unit in task_day_units if unit.status == "done")

                if day_index in excluded_days:
                    # v1 rule: keep done units, remove pending units, lock plan to done count.
                    keep_ids = {unit.id for unit in task_day_units if unit.status == "done"}
                    day_units = [
                        unit
                        for unit in day_units
                        if unit.parent_task_id != task_id or unit.id in keep_ids
                    ]
                    planned_values[day_index] = len(keep_ids) if keep_ids else 0
                    continue

                desired = max(0, int(planned_values[day_index]))
                effective_desired = max(desired, done_count)
                current_count = len(task_day_units)

                if current_count < effective_desired:
                    missing = effective_desired - current_count
                    insert_pos = self._insert_position_for_task(day_units, task_id)
                    created: list[TaskUnit] = []
                    for _ in range(missing):
                        created.append(
                            TaskUnit(
                                id=uuid4().hex,
                                parent_task_id=task_id,
                                week_start_iso=week_start_iso,
                                day_index=day_index,
                                order_index=0,
                                custom_title="",
                                status="pending",
                                created_from_plan=True,
                            )
                        )
                    day_units[insert_pos:insert_pos] = created
                elif current_count > effective_desired:
                    candidates = self._pending_removal_candidates(day_units, task_day_units)
                    remove_count = current_count - effective_desired
                    remove_ids = {unit.id for unit in candidates[:remove_count]}
                    if remove_ids:
                        day_units = [unit for unit in day_units if unit.id not in remove_ids]

            for idx, unit in enumerate(day_units):
                unit.order_index = idx
            grouped_by_day[day_index] = day_units

        merged: list[TaskUnit] = []
        for day_index in range(7):
            merged.extend(grouped_by_day.get(day_index, []))

        if merged:
            self._task_units_by_week[week_start_iso] = self._sort_and_reindex(merged)
        else:
            self._task_units_by_week.pop(week_start_iso, None)

        return self.done_by_day_for_week(week_start_iso=week_start_iso, task_ids=task_ids)

    def done_by_day_for_week(self, *, week_start_iso: str, task_ids: set[str]) -> dict[str, list[int]]:
        done_map: dict[str, list[int]] = {task_id: [0] * 7 for task_id in task_ids}
        for unit in self._task_units_by_week.get(week_start_iso, []):
            if unit.parent_task_id not in done_map or unit.status != "done":
                continue
            done_map[unit.parent_task_id][unit.day_index] += 1
        return done_map

    def complete_next_pending(
        self,
        *,
        week_start_iso: str,
        task_id: str,
        day_index: int,
        selected_unit_id: str | None = None,
    ) -> TaskUnit | None:
        if not 0 <= int(day_index) <= 6:
            return None

        units = self._task_units_by_week.get(week_start_iso, [])
        if not units:
            return None

        if selected_unit_id:
            for unit in units:
                if unit.id != selected_unit_id:
                    continue
                if (
                    unit.parent_task_id == task_id
                    and unit.day_index == day_index
                    and unit.status == "pending"
                ):
                    unit.status = "done"
                    self._task_units_by_week[week_start_iso] = self._sort_and_reindex(units)
                    return unit
                # Explicit unit selected: do not fallback to another unit.
                return None
            # Explicit unit selected but not found in this week.
            return None

        pending = [
            unit
            for unit in units
            if unit.parent_task_id == task_id and unit.day_index == day_index and unit.status == "pending"
        ]
        if not pending:
            return None
        pending.sort(key=lambda unit: (unit.order_index, unit.id))
        completed = pending[0]
        completed.status = "done"
        self._task_units_by_week[week_start_iso] = self._sort_and_reindex(units)
        return completed

    def _insert_position_for_task(self, day_units: list[TaskUnit], task_id: str) -> int:
        last_idx = -1
        for idx, unit in enumerate(day_units):
            if unit.parent_task_id == task_id:
                last_idx = idx
        if last_idx >= 0:
            return last_idx + 1
        return len(day_units)

    def _pending_removal_candidates(
        self,
        day_units: list[TaskUnit],
        task_day_units: list[TaskUnit],
    ) -> list[TaskUnit]:
        day_pos = {unit.id: idx for idx, unit in enumerate(day_units)}
        pending_without_title = sorted(
            [unit for unit in task_day_units if unit.status == "pending" and not unit.custom_title.strip()],
            key=lambda unit: (-day_pos.get(unit.id, -1), unit.id),
        )
        pending_with_title = sorted(
            [unit for unit in task_day_units if unit.status == "pending" and unit.custom_title.strip()],
            key=lambda unit: (-day_pos.get(unit.id, -1), unit.id),
        )
        return pending_without_title + pending_with_title

    def _sort_and_reindex(self, units: list[TaskUnit]) -> list[TaskUnit]:
        units.sort(key=lambda unit: (unit.day_index, unit.order_index, unit.id))
        grouped: dict[int, list[TaskUnit]] = {day: [] for day in range(7)}
        for unit in units:
            grouped[unit.day_index].append(unit)
        normalized: list[TaskUnit] = []
        for day_index in range(7):
            day_units = sorted(grouped[day_index], key=lambda unit: (unit.order_index, unit.id))
            for idx, unit in enumerate(day_units):
                unit.order_index = idx
            normalized.extend(day_units)
        return normalized

    def _normalize_day_values(self, values: object) -> list[int]:
        if not isinstance(values, list):
            return [0] * 7
        normalized = [0] * 7
        for idx, value in enumerate(values[:7]):
            try:
                normalized[idx] = max(0, int(value))
            except (TypeError, ValueError):
                normalized[idx] = 0
        return normalized
