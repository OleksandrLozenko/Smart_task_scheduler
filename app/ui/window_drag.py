from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QWidget


class DragHandleFrame(QFrame):
    def __init__(
        self,
        host: QWidget,
        *,
        allow_drag: Callable[[], bool] | None = None,
        on_double_click: Callable[[], None] | None = None,
    ) -> None:
        super().__init__(host)
        self._host = host
        self._allow_drag = allow_drag
        self._on_double_click = on_double_click
        self._drag_offset = None

    def _can_drag(self) -> bool:
        if self._allow_drag is None:
            return True
        return bool(self._allow_drag())

    def mousePressEvent(self, event) -> None:  # type: ignore[override]
        if event.button() == Qt.LeftButton and self._can_drag():
            self._drag_offset = event.globalPosition().toPoint() - self._host.frameGeometry().topLeft()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:  # type: ignore[override]
        if (
            self._drag_offset is not None
            and (event.buttons() & Qt.LeftButton)
            and self._can_drag()
            and not self._host.isMaximized()
        ):
            self._host.move(event.globalPosition().toPoint() - self._drag_offset)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # type: ignore[override]
        self._drag_offset = None
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event) -> None:  # type: ignore[override]
        if event.button() == Qt.LeftButton and self._on_double_click is not None and self._can_drag():
            self._on_double_click()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)
