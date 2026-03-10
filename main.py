from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication

from app.core.pomodoro_controller import PomodoroController
from app.core.settings_manager import SettingsManager
from app.core.timer_state import TimerMode, TimerState
from app.ui.main_window import MainWindow
from app.ui.styles import build_app_stylesheet


def main() -> int:
    app = QApplication(sys.argv)
    settings_manager = SettingsManager()
    settings = settings_manager.load()
    app.setStyleSheet(
        build_app_stylesheet(
            theme_name=settings.theme_name,
            main_card_opacity_percent=settings.main_card_opacity_percent,
            main_start_button_height=settings.main_start_button_height,
            ui_scale_percent=settings.ui_scale_percent,
        )
    )

    mode_minutes = {
        TimerMode.POMODORO: settings.pomodoro_minutes,
        TimerMode.SHORT_BREAK: settings.short_break_minutes,
        TimerMode.LONG_BREAK: settings.long_break_minutes,
    }

    initial_mode = TimerMode.POMODORO
    initial_seconds = mode_minutes[initial_mode] * 60

    state = TimerState(initial_mode=initial_mode, initial_seconds=initial_seconds)
    controller = PomodoroController(
        state=state,
        mode_minutes=mode_minutes,
        long_break_interval=settings.long_break_interval,
    )

    window = MainWindow(
        controller=controller,
        settings=settings,
        settings_manager=settings_manager,
    )
    window.showMaximized()

    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
