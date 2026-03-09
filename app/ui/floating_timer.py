from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSignalBlocker, QSize, Qt, QTimer
from PySide6.QtGui import QFont, QFontMetrics, QIcon
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizeGrip,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from app.core.pomodoro_controller import PomodoroController
from app.core.timer_state import TimerSnapshot, TimerStatus
from app.ui.window_drag import DragHandleFrame
from app.utils.time_format import format_seconds


class FloatingTimerWindow(QWidget):
    def __init__(
        self,
        controller: PomodoroController,
        *,
        always_on_top_default: bool = False,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._controller = controller
        self._position_locked = False
        self._locked_pos = None
        self._forcing_position = False
        self._blink_enabled = True
        self._blink_threshold_seconds = 8
        self._blink_active = False
        self._theme_name = "ocean"
        self._opacity_percent = 96

        self._blink_timer = QTimer(self)
        self._blink_timer.setInterval(260)
        self._blink_timer.timeout.connect(self._toggle_blink)

        self.setWindowTitle("Плавающий таймер")
        self.resize(380, 270)
        self.setMinimumSize(280, 210)
        self.setObjectName("floatingRoot")
        self.setWindowFlags(Qt.Window | Qt.FramelessWindowHint)

        self._build_ui()
        self._controller.state.changed.connect(self._on_state_changed)

        self._on_state_changed(self._controller.state.snapshot())
        self.set_pinned(always_on_top_default)
        self._apply_responsive_fonts()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(8)

        self._title_bar = DragHandleFrame(self, allow_drag=lambda: not self._position_locked)
        self._title_bar.setObjectName("floatingTitleBar")
        self._title_bar.setFixedHeight(42)

        self._header = QHBoxLayout(self._title_bar)
        self._header.setContentsMargins(6, 2, 4, 2)
        self._header.setSpacing(8)

        self._action_button = QPushButton("СТАРТ", self._title_bar)
        self._action_button.setObjectName("floatingHeaderAction")
        self._action_button.setMinimumHeight(34)
        self._action_button.setMinimumWidth(104)
        self._action_button.clicked.connect(self._on_action_clicked)

        self._pin_button = QPushButton(self._title_bar)
        self._pin_button.setObjectName("floatingPinButton")
        self._pin_button.setCheckable(True)
        self._pin_button.setToolTip("Закрепить поверх окон и зафиксировать позицию")
        self._pin_button.setFixedSize(36, 36)
        self._pin_button.toggled.connect(self.set_pinned)

        pin_path = Path(__file__).resolve().parents[1] / "assets" / "pin.svg"
        if pin_path.exists():
            self._pin_button.setIcon(QIcon(str(pin_path)))
            self._pin_button.setIconSize(QSize(18, 18))

        self._close_button = QPushButton("✕", self._title_bar)
        self._close_button.setObjectName("floatingCtrlButton")
        self._close_button.setFixedSize(30, 30)
        self._close_button.clicked.connect(self.close)

        self._header.addWidget(self._action_button, stretch=0, alignment=Qt.AlignVCenter)
        self._header.addStretch(1)
        self._header.addWidget(self._pin_button, stretch=0, alignment=Qt.AlignVCenter)
        self._header.addWidget(self._close_button, stretch=0, alignment=Qt.AlignVCenter)

        self._time_frame = QWidget(self)
        self._time_frame.setObjectName("floatingTimeFrame")
        self._time_frame.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        time_layout = QVBoxLayout(self._time_frame)
        time_layout.setContentsMargins(12, 10, 12, 10)
        time_layout.setSpacing(0)

        self._time_label = QLabel(self)
        self._time_label.setObjectName("floatingTimerLabel")
        self._time_label.setAlignment(Qt.AlignCenter)
        self._time_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        time_layout.addWidget(self._time_label, stretch=1, alignment=Qt.AlignCenter)

        grip_row = QHBoxLayout()
        grip_row.setContentsMargins(0, 0, 0, 0)
        grip_row.addStretch(1)
        self._size_grip = QSizeGrip(self)
        self._size_grip.setObjectName("floatingSizeGrip")
        self._size_grip.setToolTip("Потяните угол для изменения размера")
        self._size_grip.setFixedSize(22, 22)
        grip_row.addWidget(self._size_grip)

        layout.addWidget(self._title_bar)
        layout.addWidget(self._time_frame, stretch=1)
        layout.addLayout(grip_row)

    def _on_action_clicked(self) -> None:
        self._controller.toggle_primary()

    def _on_state_changed(self, snapshot: TimerSnapshot) -> None:
        self._time_label.setText(format_seconds(snapshot.remaining_seconds))

        if snapshot.status is TimerStatus.RUNNING:
            self._action_button.setText("СТОП")
        else:
            self._action_button.setText("СТАРТ")

        self._update_blink_state(snapshot)
        self._apply_responsive_fonts()

    def apply_visual_settings(
        self,
        *,
        opacity_percent: int,
        pin_button_size: int,
        blink_enabled: bool,
        blink_threshold_seconds: int,
        theme_name: str,
    ) -> None:
        size = max(28, min(56, int(pin_button_size)))
        icon_size = max(14, size - 14)
        self._pin_button.setFixedSize(size, size)
        self._pin_button.setIconSize(QSize(icon_size, icon_size))
        self._close_button.setFixedSize(max(28, size - 4), max(28, size - 4))
        self._title_bar.setFixedHeight(max(40, size + 8))

        self._blink_enabled = bool(blink_enabled)
        self._blink_threshold_seconds = max(3, min(20, int(blink_threshold_seconds)))
        self._theme_name = theme_name
        self._opacity_percent = max(35, min(100, int(opacity_percent)))

        self._apply_transparency_style()
        self.setWindowOpacity(self._opacity_percent / 100.0)
        self._update_blink_state(self._controller.state.snapshot())

    def set_pinned(self, enabled: bool) -> None:
        geometry = self.geometry()
        was_visible = self.isVisible()

        self.setWindowFlag(Qt.WindowStaysOnTopHint, enabled)

        if was_visible:
            self.show()
            self.setGeometry(geometry)
            if enabled:
                self.raise_()
                self.activateWindow()

        self._position_locked = enabled
        self._locked_pos = self.pos() if enabled else None

        with QSignalBlocker(self._pin_button):
            self._pin_button.setChecked(enabled)

    def _update_blink_state(self, snapshot: TimerSnapshot) -> None:
        should_blink = (
            self._blink_enabled
            and snapshot.status is TimerStatus.RUNNING
            and 0 < snapshot.remaining_seconds <= self._blink_threshold_seconds
        )

        if should_blink:
            if not self._blink_timer.isActive():
                self._blink_active = False
                self._blink_timer.start()
                self._toggle_blink()
            return

        self._blink_timer.stop()
        self._blink_active = False
        self._time_label.setStyleSheet("")

    def _toggle_blink(self) -> None:
        self._blink_active = not self._blink_active
        if self._blink_active:
            self._time_label.setStyleSheet("color: rgba(255, 255, 255, 56);")
        else:
            self._time_label.setStyleSheet("")

    def _theme_rgb(self) -> tuple[int, int, int]:
        theme_map = {
            "ocean": (58, 102, 133),
            "rose": (203, 107, 112),
            "forest": (84, 132, 108),
        }
        return theme_map.get(self._theme_name, theme_map["ocean"])

    def _apply_transparency_style(self) -> None:
        # Keep text crisp: transparency is applied to background layers, not to whole window.
        background_alpha = int(self._opacity_percent * 255 / 100)
        focus_alpha = min(210, max(110, 110 + (100 - self._opacity_percent) * 2))
        frame_border_alpha = min(210, max(95, 95 + (100 - self._opacity_percent)))
        root_border_alpha = min(190, max(105, 105 + self._opacity_percent // 2))
        red, green, blue = self._theme_rgb()

        self.setStyleSheet(
            (
                "QWidget#floatingRoot {"
                f"background: rgba({red}, {green}, {blue}, {background_alpha});"
                f"border: 1px solid rgba(255, 255, 255, {root_border_alpha});"
                "border-radius: 12px;"
                "}"
                "QWidget#floatingTimeFrame {"
                f"background: rgba(9, 14, 20, {focus_alpha});"
                f"border: 1px solid rgba(255, 255, 255, {frame_border_alpha});"
                "border-radius: 12px;"
                "}"
            )
        )

    def _apply_responsive_fonts(self) -> None:
        available_w = max(110, self._time_frame.width() - 30)
        available_h = max(56, self._time_frame.height() - 24)
        sample_text = self._time_label.text() or "00:00"

        timer_font = QFont(self._time_label.font())
        timer_font.setWeight(QFont.Bold)

        pixel_size = min(96, max(16, int(min(available_h * 0.78, available_w / 2.8))))
        while pixel_size > 14:
            timer_font.setPixelSize(pixel_size)
            metrics = QFontMetrics(timer_font)
            if metrics.horizontalAdvance(sample_text) <= available_w and metrics.height() <= available_h:
                break
            pixel_size -= 1

        timer_font.setPixelSize(max(14, pixel_size))
        self._time_label.setFont(timer_font)

    def moveEvent(self, event) -> None:  # type: ignore[override]
        if self._position_locked and self._locked_pos is not None and not self._forcing_position:
            if self.pos() != self._locked_pos:
                self._forcing_position = True
                self.move(self._locked_pos)
                self._forcing_position = False
                return
        super().moveEvent(event)

    def resizeEvent(self, event) -> None:  # type: ignore[override]
        super().resizeEvent(event)
        self._apply_responsive_fonts()
