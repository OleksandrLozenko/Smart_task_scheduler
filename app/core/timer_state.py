from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from PySide6.QtCore import QObject, Signal


class TimerMode(str, Enum):
    POMODORO = "pomodoro"
    SHORT_BREAK = "short_break"
    LONG_BREAK = "long_break"

    @property
    def title(self) -> str:
        if self is TimerMode.POMODORO:
            return "Помодоро"
        if self is TimerMode.SHORT_BREAK:
            return "Короткий перерыв"
        return "Длинный перерыв"

    @property
    def hint(self) -> str:
        if self is TimerMode.POMODORO:
            return "Время сосредоточиться!"
        if self is TimerMode.SHORT_BREAK:
            return "Время для короткого перерыва!"
        return "Время для длинного перерыва!"


class TimerStatus(str, Enum):
    IDLE = "idle"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"


@dataclass(frozen=True, slots=True)
class TimerSnapshot:
    mode: TimerMode
    remaining_seconds: int
    status: TimerStatus
    completed_pomodoros: int

    @property
    def action_label(self) -> str:
        if self.status is TimerStatus.RUNNING:
            return "ПАУЗА"
        if self.status is TimerStatus.PAUSED:
            return "ПРОДОЛЖИТЬ"
        return "СТАРТ"

    @property
    def cycle_label(self) -> str:
        return f"#{self.completed_pomodoros + 1}"


class TimerState(QObject):
    changed = Signal(object)

    def __init__(self, initial_mode: TimerMode, initial_seconds: int) -> None:
        super().__init__()
        self._mode = initial_mode
        self._remaining_seconds = initial_seconds
        self._status = TimerStatus.IDLE
        self._completed_pomodoros = 0

    @property
    def mode(self) -> TimerMode:
        return self._mode

    @property
    def remaining_seconds(self) -> int:
        return self._remaining_seconds

    @property
    def status(self) -> TimerStatus:
        return self._status

    @property
    def completed_pomodoros(self) -> int:
        return self._completed_pomodoros

    def snapshot(self) -> TimerSnapshot:
        return TimerSnapshot(
            mode=self._mode,
            remaining_seconds=self._remaining_seconds,
            status=self._status,
            completed_pomodoros=self._completed_pomodoros,
        )

    def apply(
        self,
        *,
        mode: TimerMode | None = None,
        remaining_seconds: int | None = None,
        status: TimerStatus | None = None,
        completed_pomodoros: int | None = None,
    ) -> None:
        dirty = False

        if mode is not None and mode != self._mode:
            self._mode = mode
            dirty = True

        if remaining_seconds is not None:
            clamped = max(0, int(remaining_seconds))
            if clamped != self._remaining_seconds:
                self._remaining_seconds = clamped
                dirty = True

        if status is not None and status != self._status:
            self._status = status
            dirty = True

        if completed_pomodoros is not None and completed_pomodoros != self._completed_pomodoros:
            self._completed_pomodoros = max(0, int(completed_pomodoros))
            dirty = True

        if dirty:
            self.changed.emit(self.snapshot())

    def emit_current(self) -> None:
        self.changed.emit(self.snapshot())
