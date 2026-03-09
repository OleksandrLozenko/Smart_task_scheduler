from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


@dataclass(slots=True)
class AppSettings:
    pomodoro_minutes: int = 25
    short_break_minutes: int = 5
    long_break_minutes: int = 15
    long_break_interval: int = 3
    theme_name: str = "ocean"
    launch_maximized: bool = False
    show_sidebar_icons: bool = True
    main_start_button_height: int = 48
    main_timer_scale_percent: int = 92
    main_card_opacity_percent: int = 94
    planning_progress_view: str = "fraction"
    planning_visual_style: str = "circle"
    planning_visual_max_symbols: int = 6
    planning_row_height: int = 52
    planning_table_font_size: int = 16
    planning_auto_switch_to_timer_on_select: bool = True
    always_on_top_default: bool = False
    floating_opacity_percent: int = 96
    floating_pin_button_size: int = 34
    floating_blink_enabled: bool = True
    floating_blink_threshold_seconds: int = 8
    auto_start_breaks: bool = False
    auto_start_pomodoros: bool = False


class SettingsManager:
    def __init__(self, path: str | Path = "settings.json") -> None:
        self._path = Path(path)

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

        # Re-save normalized content to keep config stable and editable.
        self.save(settings)
        return settings

    def save(self, settings: AppSettings) -> None:
        self._path.write_text(
            json.dumps(asdict(settings), indent=2),
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
                elif key == "main_start_button_height":
                    normalized[key] = min(64, max(38, parsed))
                elif key == "main_timer_scale_percent":
                    normalized[key] = min(98, max(65, parsed))
                elif key == "main_card_opacity_percent":
                    normalized[key] = min(100, max(72, parsed))
                elif key == "planning_visual_max_symbols":
                    normalized[key] = min(16, max(3, parsed))
                elif key == "planning_row_height":
                    normalized[key] = min(84, max(40, parsed))
                elif key == "planning_table_font_size":
                    normalized[key] = min(22, max(12, parsed))
                elif key == "floating_opacity_percent":
                    normalized[key] = min(100, max(35, parsed))
                elif key == "floating_pin_button_size":
                    normalized[key] = min(56, max(28, parsed))
                elif key == "floating_blink_threshold_seconds":
                    normalized[key] = min(20, max(3, parsed))
                else:
                    normalized[key] = max(1, parsed)
                continue

            normalized[key] = candidate

        allowed_themes = {"ocean", "rose", "forest", "sunset", "graphite"}
        if normalized.get("theme_name") not in allowed_themes:
            normalized["theme_name"] = "ocean"

        allowed_planning_progress = {"fraction", "visual"}
        if normalized.get("planning_progress_view") not in allowed_planning_progress:
            normalized["planning_progress_view"] = "fraction"

        allowed_planning_visual_styles = {"circle", "tomato"}
        if normalized.get("planning_visual_style") not in allowed_planning_visual_styles:
            normalized["planning_visual_style"] = "circle"

        return AppSettings(**normalized)
