from __future__ import annotations

from datetime import date

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QWidget


class WeekHeader(QWidget):
    previous_clicked = Signal()
    next_clicked = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        self._prev_button = QPushButton("<", self)
        self._next_button = QPushButton(">", self)
        self._title = QLabel("", self)

        self._prev_button.clicked.connect(self.previous_clicked.emit)
        self._next_button.clicked.connect(self.next_clicked.emit)

        self._prev_button.setObjectName("planningArrowButton")
        self._next_button.setObjectName("planningArrowButton")
        self._prev_button.setFocusPolicy(Qt.NoFocus)
        self._next_button.setFocusPolicy(Qt.NoFocus)

        self._title.setObjectName("planningWeekTitle")
        self._title.setAlignment(Qt.AlignCenter)

        layout.addWidget(self._prev_button)
        layout.addStretch(1)
        layout.addWidget(self._title)
        layout.addStretch(1)
        layout.addWidget(self._next_button)

    def set_week_range(self, start: date, end: date, *, is_current_week: bool) -> None:
        _ = is_current_week
        self._title.setText(f"{start.strftime('%d.%m.%Y')} - {end.strftime('%d.%m.%Y')}")
