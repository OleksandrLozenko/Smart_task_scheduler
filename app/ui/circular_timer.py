from __future__ import annotations

from PySide6.QtCore import Qt, QRectF
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPen
from PySide6.QtWidgets import QSizePolicy, QWidget


class CircularTimerWidget(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._progress = 1.0
        self._time_text = "25:00"
        self._mode_text = "FOCUS"

        self._track_color = QColor(251, 239, 239, 92)
        self._progress_color = QColor(255, 82, 92, 255)
        self._time_color = QColor(255, 255, 255, 250)
        self._mode_color = QColor(251, 239, 239, 230)

        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setMinimumSize(120, 120)

    def set_palette(
        self,
        *,
        track: QColor,
        progress: QColor,
        time_text: QColor,
        mode_text: QColor,
    ) -> None:
        self._track_color = track
        self._progress_color = progress
        self._time_color = time_text
        self._mode_color = mode_text
        self.update()

    def set_progress(self, value: float) -> None:
        clamped = max(0.0, min(1.0, float(value)))
        if clamped != self._progress:
            self._progress = clamped
            self.update()

    def set_time_text(self, text: str) -> None:
        if text != self._time_text:
            self._time_text = text
            self.update()

    def set_mode_text(self, text: str) -> None:
        if text != self._mode_text:
            self._mode_text = text
            self.update()

    def paintEvent(self, event) -> None:  # type: ignore[override]
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)

        side = min(self.width(), self.height())
        margin = max(10.0, side * 0.08)
        pen_width = max(7.0, side * 0.042)
        diameter = side - margin * 2
        rect = QRectF(
            (self.width() - diameter) / 2.0,
            (self.height() - diameter) / 2.0,
            diameter,
            diameter,
        )

        track_pen = QPen(self._track_color, pen_width, Qt.SolidLine, Qt.RoundCap)
        painter.setPen(track_pen)
        painter.setBrush(Qt.NoBrush)
        painter.drawEllipse(rect)

        progress_pen = QPen(self._progress_color, pen_width, Qt.SolidLine, Qt.RoundCap)
        painter.setPen(progress_pen)
        start_angle = 90 * 16
        span_angle = int(-360 * 16 * self._progress)
        painter.drawArc(rect, start_angle, span_angle)

        inner = rect.adjusted(pen_width * 1.35, pen_width * 1.35, -pen_width * 1.35, -pen_width * 1.35)
        time_rect = QRectF(
            inner.left(),
            inner.top() + inner.height() * 0.18,
            inner.width(),
            inner.height() * 0.42,
        )
        mode_rect = QRectF(
            inner.left(),
            inner.top() + inner.height() * 0.62,
            inner.width(),
            inner.height() * 0.18,
        )

        time_font = self._fit_font(
            text=self._time_text,
            max_width=int(time_rect.width() * 0.92),
            max_height=int(time_rect.height() * 0.92),
            start_px=max(16, int(side * 0.18)),
            min_px=10,
            weight=QFont.Medium,
        )
        painter.setFont(time_font)
        painter.setPen(self._time_color)
        painter.drawText(time_rect, Qt.AlignCenter, self._time_text)

        mode_font = self._fit_font(
            text=self._mode_text,
            max_width=int(mode_rect.width() * 0.82),
            max_height=int(mode_rect.height() * 0.9),
            start_px=max(9, int(side * 0.048)),
            min_px=7,
            weight=QFont.DemiBold,
        )
        painter.setFont(mode_font)
        painter.setPen(self._mode_color)
        metrics = QFontMetrics(mode_font)
        mode_text = metrics.elidedText(self._mode_text, Qt.ElideRight, int(mode_rect.width() * 0.82))
        painter.drawText(mode_rect, Qt.AlignHCenter | Qt.AlignTop, mode_text)

    def _fit_font(
        self,
        *,
        text: str,
        max_width: int,
        max_height: int,
        start_px: int,
        min_px: int,
        weight: QFont.Weight,
    ) -> QFont:
        font = QFont(self.font())
        font.setWeight(weight)

        pixel_size = max(min_px, start_px)
        while pixel_size > min_px:
            font.setPixelSize(pixel_size)
            metrics = QFontMetrics(font)
            if metrics.horizontalAdvance(text) <= max_width and metrics.height() <= max_height:
                break
            pixel_size -= 1

        font.setPixelSize(max(min_px, pixel_size))
        return font
