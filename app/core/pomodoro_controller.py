from __future__ import annotations

from typing import Mapping

from PySide6.QtCore import QObject, QTimer, Signal

from app.core.timer_state import TimerMode, TimerState, TimerStatus


class PomodoroController(QObject):
    session_completed = Signal(str, str)

    def __init__(
        self,
        state: TimerState,
        mode_minutes: Mapping[TimerMode, int],
        *,
        long_break_interval: int = 3,
    ) -> None:
        super().__init__()
        self._state = state
        self._durations_seconds = {
            mode: max(1, int(minutes)) * 60 for mode, minutes in mode_minutes.items()
        }
        self._long_break_interval = max(2, int(long_break_interval))

        self._ticker = QTimer(self)
        self._ticker.setInterval(1000)
        self._ticker.timeout.connect(self._on_tick)

    @property
    def state(self) -> TimerState:
        return self._state

    def duration_for_mode(self, mode: TimerMode) -> int:
        return self._durations_seconds[mode]

    def update_configuration(
        self,
        mode_minutes: Mapping[TimerMode, int],
        *,
        long_break_interval: int | None = None,
    ) -> None:
        self._durations_seconds = {
            mode: max(1, int(minutes)) * 60 for mode, minutes in mode_minutes.items()
        }

        if long_break_interval is not None:
            self._long_break_interval = max(2, int(long_break_interval))

        if self._state.status in {TimerStatus.IDLE, TimerStatus.COMPLETED}:
            self._state.apply(
                remaining_seconds=self.duration_for_mode(self._state.mode),
                status=TimerStatus.IDLE,
            )

    def is_active(self) -> bool:
        return self._state.status in {TimerStatus.RUNNING, TimerStatus.PAUSED}

    def change_mode(self, mode: TimerMode) -> None:
        self._ticker.stop()
        self._state.apply(
            mode=mode,
            remaining_seconds=self.duration_for_mode(mode),
            status=TimerStatus.IDLE,
        )

    def start(self) -> None:
        if self._state.status is TimerStatus.RUNNING:
            return

        if self._state.remaining_seconds <= 0:
            self._state.apply(remaining_seconds=self.duration_for_mode(self._state.mode))

        self._state.apply(status=TimerStatus.RUNNING)
        self._ticker.start()

    def pause(self) -> None:
        if self._state.status is not TimerStatus.RUNNING:
            return
        self._ticker.stop()
        self._state.apply(status=TimerStatus.PAUSED)

    def resume(self) -> None:
        if self._state.status is not TimerStatus.PAUSED:
            return
        self._state.apply(status=TimerStatus.RUNNING)
        self._ticker.start()

    def reset(self) -> None:
        self._ticker.stop()
        self._state.apply(
            remaining_seconds=self.duration_for_mode(self._state.mode),
            status=TimerStatus.IDLE,
        )

    def toggle_primary(self) -> None:
        if self._state.status is TimerStatus.RUNNING:
            self.pause()
            return
        if self._state.status is TimerStatus.PAUSED:
            self.resume()
            return
        self.start()

    def _on_tick(self) -> None:
        next_seconds = self._state.remaining_seconds - 1
        if next_seconds > 0:
            self._state.apply(remaining_seconds=next_seconds)
            return

        self._ticker.stop()

        finished_mode = self._state.mode
        completed = self._state.completed_pomodoros
        if finished_mode is TimerMode.POMODORO:
            completed += 1

        next_mode = self._next_mode_after(finished_mode, completed)

        # Complete current session and prepare next mode without auto-start.
        self._state.apply(
            mode=next_mode,
            remaining_seconds=self.duration_for_mode(next_mode),
            status=TimerStatus.IDLE,
            completed_pomodoros=completed,
        )
        self.session_completed.emit(finished_mode.title, next_mode.title)

    def _next_mode_after(self, finished_mode: TimerMode, completed_pomodoros: int) -> TimerMode:
        if finished_mode is TimerMode.POMODORO:
            if completed_pomodoros % self._long_break_interval == 0:
                return TimerMode.LONG_BREAK
            return TimerMode.SHORT_BREAK

        return TimerMode.POMODORO
