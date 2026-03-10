from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from app.core.app_version import DEFAULT_UPDATE_MANIFEST_URL
from app.core.app_paths import get_app_paths
from app.core.file_io import atomic_write_text


@dataclass(slots=True)
class AppSettings:
    pomodoro_minutes: int = 25
    short_break_minutes: int = 5
    long_break_minutes: int = 15
    long_break_interval: int = 3
    theme_name: str = "ocean"
    launch_maximized: bool = True
    show_sidebar_icons: bool = True
    ui_scale_percent: int = 100
    main_start_button_height: int = 48
    main_timer_scale_percent: int = 106
    main_card_opacity_percent: int = 94
    planning_progress_view: str = "fraction"
    planning_visual_style: str = "circle"
    planning_cell_style: str = "soft"
    planning_visual_max_symbols: int = 6
    planning_row_height: int = 52
    planning_table_font_size: int = 16
    planning_auto_switch_to_timer_on_select: bool = True
    planning_today_highlight_percent: int = 82
    planning_task_column_width: int = 190
    planning_total_column_width: int = 94
    planning_daily_limit: int = 16
    planning_weekly_limit: int = 112
    planning_confirm_before_timer_switch: bool = True
    planning_follow_tasks_queue: bool = True
    tasks_units_compact_mode: bool = False
    updates_manifest_url: str = DEFAULT_UPDATE_MANIFEST_URL
    auto_check_updates_on_start: bool = True
    update_check_interval_hours: int = 12
    last_update_check_attempt_at: str = ""
    last_update_check_success_at: str = ""
    dismissed_update_version: str = ""
    timer_sound_id: str = "alarm_classic"
    timer_sound_volume_percent: int = 90
    always_on_top_default: bool = False
    floating_opacity_percent: int = 96
    floating_pin_button_size: int = 34
    floating_blink_enabled: bool = True
    floating_blink_threshold_seconds: int = 8
    auto_start_breaks: bool = False
    auto_start_pomodoros: bool = False


class SettingsManager:
    def __init__(self, path: str | Path | None = None) -> None:
        resolved_path = get_app_paths().settings_path if path is None else Path(path)
        self._path = Path(resolved_path)
        self._path.parent.mkdir(parents=True, exist_ok=True)

    @property
    def path(self) -> Path:
        return self._path

    def load(self) -> AppSettings:
        if not self._path.exists():
            settings = AppSettings()
            self.save(settings)
            return settings

        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            settings = AppSettings()
            self.save(settings)
            return settings

        settings = self._from_dict(data)
        normalized = asdict(settings)
        if data != normalized:
            # Persist normalized content only when it actually differs.
            self.save(settings)
        return settings

    def save(self, settings: AppSettings) -> None:
        atomic_write_text(
            self._path,
            json.dumps(asdict(settings), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    @staticmethod
    def _from_dict(raw: Any) -> AppSettings:
        if not isinstance(raw, dict):
            return AppSettings()

        defaults = asdict(AppSettings())
        normalized: dict[str, Any] = {}

        for key, default_value in defaults.items():
            candidate = raw.get(key, default_value)

            if isinstance(default_value, bool):
                normalized[key] = bool(candidate)
                continue

            if isinstance(default_value, int):
                try:
                    parsed = int(candidate)
                except (TypeError, ValueError):
                    parsed = default_value
                if key == "long_break_interval":
                    normalized[key] = max(2, parsed)
                elif key == "ui_scale_percent":
                    normalized[key] = min(130, max(85, parsed))
                elif key == "main_start_button_height":
                    normalized[key] = min(64, max(38, parsed))
                elif key == "main_timer_scale_percent":
                    normalized[key] = min(118, max(65, parsed))
                elif key == "main_card_opacity_percent":
                    normalized[key] = min(100, max(72, parsed))
                elif key == "planning_visual_max_symbols":
                    normalized[key] = min(16, max(3, parsed))
                elif key == "planning_row_height":
                    normalized[key] = min(84, max(40, parsed))
                elif key == "planning_table_font_size":
                    normalized[key] = min(22, max(12, parsed))
                elif key == "planning_today_highlight_percent":
                    normalized[key] = min(100, max(30, parsed))
                elif key == "planning_task_column_width":
                    normalized[key] = min(320, max(140, parsed))
                elif key == "planning_total_column_width":
                    normalized[key] = min(160, max(72, parsed))
                elif key == "planning_daily_limit":
                    normalized[key] = min(64, max(1, parsed))
                elif key == "planning_weekly_limit":
                    normalized[key] = min(448, max(1, parsed))
                elif key == "timer_sound_volume_percent":
                    normalized[key] = min(100, max(0, parsed))
                elif key == "floating_opacity_percent":
                    normalized[key] = min(100, max(35, parsed))
                elif key == "floating_pin_button_size":
                    normalized[key] = min(56, max(28, parsed))
                elif key == "floating_blink_threshold_seconds":
                    normalized[key] = min(20, max(3, parsed))
                elif key == "update_check_interval_hours":
                    normalized[key] = min(168, max(1, parsed))
                else:
                    normalized[key] = max(1, parsed)
                continue

            if isinstance(default_value, str):
                normalized[key] = str(candidate)
            else:
                normalized[key] = candidate

        allowed_themes = {"ocean", "rose", "forest", "sunset", "graphite"}
        if normalized.get("theme_name") not in allowed_themes:
            normalized["theme_name"] = "ocean"

        allowed_planning_progress = {"fraction", "visual"}
        if normalized.get("planning_progress_view") not in allowed_planning_progress:
            normalized["planning_progress_view"] = "fraction"

        allowed_planning_visual_styles = {"circle", "tomato", "square", "bar"}
        if normalized.get("planning_visual_style") not in allowed_planning_visual_styles:
            normalized["planning_visual_style"] = "circle"

        allowed_planning_cell_styles = {"soft", "contrast", "minimal"}
        if normalized.get("planning_cell_style") not in allowed_planning_cell_styles:
            normalized["planning_cell_style"] = "soft"

        allowed_timer_sound_ids = {
            "alarm_classic",
            "soft_chime",
            "digital",
            "bell",
            "ascending",
        }
        if normalized.get("timer_sound_id") not in allowed_timer_sound_ids:
            normalized["timer_sound_id"] = "alarm_classic"
        normalized["updates_manifest_url"] = (
            str(normalized.get("updates_manifest_url", "")).strip()
            or DEFAULT_UPDATE_MANIFEST_URL
        )
        normalized["last_update_check_attempt_at"] = str(
            normalized.get("last_update_check_attempt_at", "")
        ).strip()
        normalized["last_update_check_success_at"] = str(
            normalized.get("last_update_check_success_at", "")
        ).strip()
        normalized["dismissed_update_version"] = str(
            normalized.get("dismissed_update_version", "")
        ).strip()

        return AppSettings(**normalized)
