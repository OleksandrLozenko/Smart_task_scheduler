from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from pathlib import Path
import re
from uuid import uuid4

from PySide6.QtCore import QMimeData, QPoint, QRect, QSignalBlocker, QSize, Qt, QTimer, Signal, Slot
from PySide6.QtGui import QColor, QDrag, QIcon, QPaintEvent, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QComboBox,
    QFrame,
    QFormLayout,
    QGridLayout,
    QHeaderView,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QDialog,
    QDialogButtonBox,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QLineEdit,
    QVBoxLayout,
    QWidget,
)

from app.core.app_version import APP_VERSION, DEFAULT_UPDATE_MANIFEST_URL
from app.core.pomodoro_controller import PomodoroController
from app.core.planner_controller import PlannerController
from app.core.planning_state_manager import PlanningStateManager
from app.core.settings_manager import AppSettings, SettingsManager
from app.core.timer_state import TimerMode, TimerSnapshot, TimerStatus
from app.core.update_install_manager import UpdateInstallManager
from app.core.update_manager import UpdateManager
from app.core.update_service import UpdateCheckResult
from app.ui.circular_timer import CircularTimerWidget
from app.ui.floating_timer import FloatingTimerWindow
from app.ui.styles import build_app_stylesheet
from app.ui.week_header import WeekHeader
from app.ui.window_drag import DragHandleFrame
from app.utils.audio_alert import (
    available_timer_sounds,
    play_completion_alert,
    preview_completion_alert,
)
from app.utils.time_format import format_seconds


class NoWheelSpinBox(QSpinBox):
    """SpinBox that ignores wheel scrolling to prevent accidental value changes."""

    def wheelEvent(self, event) -> None:  # type: ignore[override]
        event.ignore()


class NoWheelComboBox(QComboBox):
    """ComboBox that changes value only by click/keyboard, not by wheel hover."""

    def wheelEvent(self, event) -> None:  # type: ignore[override]
        if self.view().isVisible():
            super().wheelEvent(event)
            return
        event.ignore()


class PlanningWeekTable(QTableWidget):
    """QTableWidget with full-height highlighted day column overlay."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._highlighted_column: int | None = None
        self._highlight_alpha = 82
        self._highlight_fill = QColor(242, 94, 126, 120)
        self._highlight_border = QColor(255, 182, 199, 180)

    def set_highlighted_column(self, column: int | None) -> None:
        normalized = int(column) if isinstance(column, int) and column >= 0 else None
        if normalized == self._highlighted_column:
            return
        self._highlighted_column = normalized
        self.viewport().update()

    def set_highlight_strength(self, percent: int) -> None:
        alpha = max(30, min(100, int(percent)))
        if alpha == self._highlight_alpha:
            return
        self._highlight_alpha = alpha
        self.viewport().update()

    def set_highlight_palette(self, *, fill: QColor, border: QColor) -> None:
        fill_color = QColor(fill)
        border_color = QColor(border)
        if fill_color == self._highlight_fill and border_color == self._highlight_border:
            return
        self._highlight_fill = fill_color
        self._highlight_border = border_color
        self.viewport().update()

    def paintEvent(self, event: QPaintEvent) -> None:  # type: ignore[override]
        super().paintEvent(event)
        if self._highlighted_column is None:
            return
        if self._highlighted_column >= self.columnCount():
            return

        header = self.horizontalHeader()
        x = header.sectionViewportPosition(self._highlighted_column)
        width = header.sectionSize(self._highlighted_column)
        if width <= 0:
            return

        viewport_rect = self.viewport().rect()
        if x > viewport_rect.right() or (x + width) < viewport_rect.left():
            return

        painter = QPainter(self.viewport())
        painter.setRenderHint(QPainter.Antialiasing, False)

        fill_alpha = int(22 + self._highlight_alpha * 1.25)
        border_alpha = min(225, int(58 + self._highlight_alpha * 1.35))
        fill_color = QColor(self._highlight_fill)
        fill_color.setAlpha(max(24, min(210, fill_alpha)))
        border_color = QColor(self._highlight_border)
        border_color.setAlpha(max(70, min(235, border_alpha)))
        painter.fillRect(
            x,
            viewport_rect.top(),
            width,
            viewport_rect.height(),
            fill_color,
        )
        border_pen = QPen(border_color)
        border_pen.setWidth(2)
        painter.setPen(border_pen)
        painter.drawLine(x, viewport_rect.top(), x, viewport_rect.bottom())
        painter.drawLine(x + width - 1, viewport_rect.top(), x + width - 1, viewport_rect.bottom())
        painter.end()


class TaskUnitsDayTable(QTableWidget):
    """Day-level table with drag-and-drop row reorder and order-changed signal."""

    order_changed = Signal(object)
    _ROW_MIME = "application/x-flowgrid-task-unit-id"

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._drag_unit_id: str | None = None
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDropIndicatorShown(True)
        self.setDragDropOverwriteMode(False)
        self.setDefaultDropAction(Qt.MoveAction)
        self.setDragDropMode(QAbstractItemView.DragDrop)
        self.setAutoScroll(True)

    def startDrag(self, supportedActions) -> None:  # type: ignore[override]
        row = self.currentRow()
        if row < 0:
            return

        dragged_unit_id = self._unit_id_for_row(row)
        if not dragged_unit_id:
            return
        self._drag_unit_id = dragged_unit_id

        indexes = self.selectedIndexes()
        mime: QMimeData | None = self.model().mimeData(indexes) if indexes else None
        if mime is None:
            mime = QMimeData()
        mime.setData(self._ROW_MIME, dragged_unit_id.encode("utf-8"))

        drag = QDrag(self)
        drag.setMimeData(mime)

        ghost = self._build_drag_ghost(row)
        if not ghost.isNull():
            drag.setPixmap(ghost)
            drag.setHotSpot(QPoint(min(18, max(0, ghost.width() - 1)), ghost.height() // 2))

        drag.exec(Qt.MoveAction)
        self._drag_unit_id = None

    def dragEnterEvent(self, event) -> None:  # type: ignore[override]
        if event.source() is self:
            event.setDropAction(Qt.MoveAction)
            event.accept()
            return
        event.ignore()

    def dragMoveEvent(self, event) -> None:  # type: ignore[override]
        if event.source() is self:
            super().dragMoveEvent(event)
            event.setDropAction(Qt.MoveAction)
            event.accept()
            return
        event.ignore()

    def dropEvent(self, event) -> None:  # type: ignore[override]
        if event.source() is not self:
            event.ignore()
            return

        current_ids = self._ordered_ids()
        if not current_ids:
            event.ignore()
            return

        moved_id = self._drag_unit_id or self._dragged_id_from_mime(event.mimeData())
        if not moved_id or moved_id not in current_ids:
            event.ignore()
            return

        source_row = current_ids.index(moved_id)
        drop_y = int(event.position().y())
        row_at = self.rowAt(drop_y)
        if row_at < 0:
            target_row = len(current_ids)
        else:
            rect = self.visualRect(self.model().index(row_at, 0))
            target_row = row_at + (1 if drop_y > rect.center().y() else 0)

        reordered = list(current_ids)
        reordered.pop(source_row)
        if target_row > source_row:
            target_row -= 1
        target_row = max(0, min(target_row, len(reordered)))
        reordered.insert(target_row, moved_id)

        if reordered != current_ids:
            self.order_changed.emit(reordered)

        self._drag_unit_id = None
        event.setDropAction(Qt.MoveAction)
        event.accept()

    def dragLeaveEvent(self, event) -> None:  # type: ignore[override]
        self._drag_unit_id = None
        super().dragLeaveEvent(event)

    def _ordered_ids(self) -> list[str]:
        result: list[str] = []
        for row in range(self.rowCount()):
            item = self.item(row, 2)
            if item is None:
                continue
            unit_id = str(item.data(Qt.UserRole) or "")
            if unit_id:
                result.append(unit_id)
        return result

    def _unit_id_for_row(self, row: int) -> str:
        if not 0 <= int(row) < self.rowCount():
            return ""
        item = self.item(int(row), 2)
        if item is None:
            return ""
        return str(item.data(Qt.UserRole) or "")

    def _dragged_id_from_mime(self, mime: QMimeData | None) -> str:
        if mime is None or not mime.hasFormat(self._ROW_MIME):
            return ""
        raw = mime.data(self._ROW_MIME)
        if raw.isEmpty():
            return ""
        try:
            return bytes(raw).decode("utf-8").strip()
        except UnicodeDecodeError:
            return ""

    def _build_drag_ghost(self, row: int) -> QPixmap:
        row_top = self.rowViewportPosition(row)
        row_height = self.rowHeight(row)
        viewport_width = self.viewport().width()
        if row_top < 0 or row_height <= 0 or viewport_width <= 0:
            return QPixmap()

        capture_rect = QRect(0, row_top, viewport_width, row_height)
        source = self.viewport().grab(capture_rect)
        if source.isNull():
            return QPixmap()

        ghost = QPixmap(source.size())
        ghost.fill(Qt.transparent)
        painter = QPainter(ghost)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setOpacity(0.74)
        painter.drawPixmap(0, 0, source)

        border_pen = QPen(QColor(170, 224, 255, 225))
        border_pen.setWidth(2)
        painter.setPen(border_pen)
        painter.setBrush(Qt.NoBrush)
        painter.drawRoundedRect(
            QRect(1, 1, max(1, ghost.width() - 2), max(1, ghost.height() - 2)),
            8,
            8,
        )
        painter.end()
        return ghost


class _UpdateCheckOrigin:
    AUTO = "auto"
    MANUAL = "manual"


class MainWindow(QMainWindow):
    PAGE_POMODORO = 0
    PAGE_PLANNING = 1
    PAGE_TASKS = 2
    PAGE_UPDATES = 3
    PAGE_SETTINGS = 4
    _PLANNING_DAILY_LIMIT_ROW_ID = "__daily_limit_row__"

    def __init__(
        self,
        controller: PomodoroController,
        settings: AppSettings,
        settings_manager: SettingsManager,
        *,
        app_version: str = APP_VERSION,
    ) -> None:
        super().__init__()
        self._controller = controller
        self._controller.set_start_guard(self._can_start_session)
        self._settings = settings
        self._settings_manager = settings_manager
        self._app_version = app_version
        if str(self._settings.updates_manifest_url or "").strip().lower().startswith("file://"):
            self._settings.updates_manifest_url = DEFAULT_UPDATE_MANIFEST_URL
            self._settings_manager.save(self._settings)
        self._floating_window: FloatingTimerWindow | None = None
        self._update_manager = UpdateManager(self)
        self._update_manager.check_started.connect(self._on_update_check_started)
        self._update_manager.check_finished.connect(self._on_update_check_finished)
        self._update_manager.check_failed.connect(self._on_update_check_failed)
        self._update_manager.checking_changed.connect(self._on_update_checking_changed)
        self._update_install_manager = UpdateInstallManager(self)
        self._update_install_manager.install_started.connect(self._on_update_install_started)
        self._update_install_manager.install_status.connect(self._on_update_install_status)
        self._update_install_manager.install_finished.connect(self._on_update_install_finished)
        self._update_install_manager.install_failed.connect(self._on_update_install_failed)
        self._update_install_manager.installing_changed.connect(self._on_update_installing_changed)
        self._last_update_result: UpdateCheckResult | None = None
        self._last_update_error: str = ""
        self._update_check_origin: str = _UpdateCheckOrigin.MANUAL
        self._update_check_show_popups = False

        self._sparkles_source = self._load_svg("sparkles.svg")
        self._display_total_seconds = self._controller.duration_for_mode(self._controller.state.mode)
        self._last_mode = self._controller.state.mode
        self._today = date.today()
        self._planning_week_start = self._today - timedelta(days=self._today.weekday())
        self._planning_store = PlanningStateManager()
        self._planner_controller = PlannerController()
        self._planning_tasks: list[dict[str, str]] = []
        self._planning_excluded_cells_by_week: dict[str, dict[str, set[int]]] = {}
        self._planning_planned_cells_by_week: dict[str, dict[str, list[int]]] = {}
        self._planning_done_cells_by_week: dict[str, dict[str, list[int]]] = {}
        self._planning_weekly_targets_by_week: dict[str, dict[str, int]] = {}
        self._planning_selected_unit_by_week: dict[str, str] = {}
        self._planning_selected_task_id: str | None = None
        self._planning_selected_day_index: int | None = None
        self._planning_pending_switch_key: tuple[str, int | None] | None = None
        self._planning_delete_mode = False
        self._planning_exclude_mode = False
        self._tasks_day_tables: dict[int, QTableWidget] = {}
        self._tasks_day_headers: dict[int, QPushButton] = {}
        self._tasks_day_empty_labels: dict[int, QLabel] = {}
        self._tasks_expanded_days_by_week: dict[str, set[int]] = {}
        self._is_populating_tasks_tables = False
        self._tasks_units_compact_mode = bool(self._settings.tasks_units_compact_mode)
        self._day_names_short = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]
        self._is_populating_settings_form = False
        self._settings_live_preview_bound = False
        self._planning_save_pending = False
        self._planning_save_timer = QTimer(self)
        self._planning_save_timer.setSingleShot(True)
        self._planning_save_timer.setInterval(420)
        self._planning_save_timer.timeout.connect(self._persist_planning_state)
        self._update_install_progress_value = 0
        self._update_install_progress_real = False
        self._update_install_progress_timer = QTimer(self)
        self._update_install_progress_timer.setInterval(140)
        self._update_install_progress_timer.timeout.connect(self._tick_update_install_progress)
        tomato_path = self._asset_path("tomato.svg")
        self._tomato_icon = QIcon(str(tomato_path)) if tomato_path.exists() else QIcon()
        self._load_planning_state()

        self.setWindowFlags(Qt.Window | Qt.FramelessWindowHint)
        self.setWindowTitle("Фокус-таймер Pomodoro")
        self.resize(1180, 760)
        self.setMinimumSize(920, 620)

        self._mode_buttons: dict[TimerMode, QPushButton] = {}
        self._nav_buttons: list[QPushButton] = []

        self._build_ui()
        self._apply_theme_and_visual_settings()
        self._ensure_follow_queue_selection(save_if_changed=True)

        self._controller.state.changed.connect(self._on_state_changed)
        self._controller.session_completed.connect(self._on_session_completed)
        self._on_state_changed(self._controller.state.snapshot())
        self._update_planning_week_labels()
        self._apply_responsive_fonts()
        self._refresh_update_ui()
        QTimer.singleShot(700, self._run_startup_update_check_if_due)

    def _load_svg(self, filename: str) -> QPixmap:
        icon_path = self._asset_path(filename)
        if not icon_path.exists():
            return QPixmap()
        return QPixmap(str(icon_path))

    def _asset_path(self, filename: str) -> Path:
        return Path(__file__).resolve().parents[1] / "assets" / filename

    def _build_ui(self) -> None:
        root = QWidget(self)
        root.setObjectName("root")
        self.setCentralWidget(root)

        root_layout = QVBoxLayout(root)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        self._title_bar = DragHandleFrame(self, on_double_click=self._toggle_maximize_restore)
        self._title_bar.setObjectName("windowTitleBar")
        self._title_bar.setFixedHeight(46)

        title_bar_layout = QHBoxLayout(self._title_bar)
        title_bar_layout.setContentsMargins(13, 7, 9, 7)
        title_bar_layout.setSpacing(8)

        title_label = QLabel("Фокус-таймер Pomodoro", self._title_bar)
        title_label.setObjectName("windowTitleLabel")
        title_label.setAttribute(Qt.WA_TransparentForMouseEvents, True)

        self._window_minimize_button = QPushButton("—", self._title_bar)
        self._window_minimize_button.setObjectName("windowCtrlButton")
        self._window_minimize_button.setFixedSize(34, 26)
        self._window_minimize_button.clicked.connect(self.showMinimized)

        self._window_maximize_button = QPushButton("□", self._title_bar)
        self._window_maximize_button.setObjectName("windowCtrlButton")
        self._window_maximize_button.setFixedSize(34, 26)
        self._window_maximize_button.clicked.connect(self._toggle_maximize_restore)

        self._window_close_button = QPushButton("✕", self._title_bar)
        self._window_close_button.setObjectName("windowCloseButton")
        self._window_close_button.setFixedSize(34, 26)
        self._window_close_button.clicked.connect(self.close)

        title_bar_layout.addWidget(title_label)
        title_bar_layout.addStretch(1)
        title_bar_layout.addWidget(self._window_minimize_button)
        title_bar_layout.addWidget(self._window_maximize_button)
        title_bar_layout.addWidget(self._window_close_button)

        body = QWidget(root)
        body_layout = QHBoxLayout(body)
        body_layout.setContentsMargins(20, 14, 20, 20)
        body_layout.setSpacing(16)

        sidebar = QFrame(body)
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(240)

        sidebar_layout = QVBoxLayout(sidebar)
        sidebar_layout.setContentsMargins(15, 15, 15, 15)
        sidebar_layout.setSpacing(11)

        title_row = QHBoxLayout()
        title_row.setContentsMargins(0, 0, 0, 0)
        title_row.setSpacing(6)

        title = QLabel("FlowGrid", sidebar)
        title.setObjectName("sidebarTitle")

        self._sidebar_sparkles = QLabel(sidebar)
        self._sidebar_sparkles.setObjectName("sidebarSparkles")
        self._sidebar_sparkles.setFixedSize(24, 24)

        title_row.addWidget(title)
        title_row.addWidget(self._sidebar_sparkles)
        title_row.addStretch(1)

        subtitle = QLabel("Личный планировщик", sidebar)
        subtitle.setObjectName("sidebarSubtitle")

        self._pomodoro_nav = QPushButton("Pomodoro Time", sidebar)
        self._pomodoro_nav.setObjectName("sidebarNavButton")
        self._pomodoro_nav.setCheckable(True)
        self._pomodoro_nav.setChecked(True)
        self._pomodoro_nav.clicked.connect(lambda: self._switch_page(self.PAGE_POMODORO))

        self._planning_nav = QPushButton("Планирование", sidebar)
        self._planning_nav.setObjectName("sidebarNavButton")
        self._planning_nav.setCheckable(True)
        self._planning_nav.clicked.connect(lambda: self._switch_page(self.PAGE_PLANNING))

        self._tasks_nav = QPushButton("Задачи", sidebar)
        self._tasks_nav.setObjectName("sidebarNavButton")
        self._tasks_nav.setCheckable(True)
        self._tasks_nav.clicked.connect(lambda: self._switch_page(self.PAGE_TASKS))

        self._updates_nav = QPushButton("Обновления", sidebar)
        self._updates_nav.setObjectName("sidebarNavButton")
        self._updates_nav.setCheckable(True)
        self._updates_nav.clicked.connect(lambda: self._switch_page(self.PAGE_UPDATES))
        self._updates_nav.setVisible(False)

        self._settings_nav = QPushButton("Настройки", sidebar)
        self._settings_nav.setObjectName("sidebarSettingsButton")
        self._settings_nav.setCheckable(True)
        self._settings_nav.clicked.connect(lambda: self._switch_page(self.PAGE_SETTINGS))

        self._nav_buttons = [
            self._pomodoro_nav,
            self._planning_nav,
            self._tasks_nav,
            self._updates_nav,
            self._settings_nav,
        ]

        sidebar_layout.addLayout(title_row)
        sidebar_layout.addWidget(subtitle)
        sidebar_layout.addSpacing(10)
        sidebar_layout.addWidget(self._pomodoro_nav)
        sidebar_layout.addWidget(self._planning_nav)
        sidebar_layout.addWidget(self._tasks_nav)
        sidebar_layout.addStretch(1)
        sidebar_layout.addWidget(self._settings_nav)

        self._stack = QStackedWidget(body)
        self._stack.addWidget(self._build_pomodoro_page())
        self._stack.addWidget(self._build_planning_page())
        self._stack.addWidget(self._build_tasks_page())
        self._stack.addWidget(self._build_updates_page())
        self._stack.addWidget(self._build_settings_page())

        body_layout.addWidget(sidebar)
        body_layout.addWidget(self._stack, stretch=1)

        root_layout.addWidget(self._title_bar)
        root_layout.addWidget(body, stretch=1)
        root_layout.addWidget(self._build_update_footer(root))

        self.statusBar().setSizeGripEnabled(False)
        self._update_window_buttons()

    def _build_pomodoro_page(self) -> QWidget:
        page = QWidget(self)
        layout = QVBoxLayout(page)
        layout.setContentsMargins(4, 4, 4, 4)

        card = QFrame(page)
        card.setObjectName("card")
        card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(28, 24, 28, 22)
        card_layout.setSpacing(14)

        modes_layout = QHBoxLayout()
        modes_layout.setSpacing(10)
        for mode in (TimerMode.POMODORO, TimerMode.SHORT_BREAK, TimerMode.LONG_BREAK):
            button = QPushButton(mode.title, card)
            button.setObjectName("modeButton")
            button.setCheckable(True)
            button.clicked.connect(
                lambda checked, selected_mode=mode: self._on_mode_clicked(selected_mode, checked)
            )
            self._mode_buttons[mode] = button
            modes_layout.addWidget(button)

        self._timer_shell = QFrame(card)
        self._timer_shell.setObjectName("timerShell")
        self._timer_shell.setMinimumHeight(340)
        self._timer_shell.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        timer_shell_layout = QGridLayout(self._timer_shell)
        timer_shell_layout.setContentsMargins(20, 20, 20, 20)
        timer_shell_layout.setHorizontalSpacing(16)
        timer_shell_layout.setVerticalSpacing(8)
        timer_shell_layout.setColumnStretch(0, 1)
        timer_shell_layout.setColumnStretch(1, 0)
        timer_shell_layout.setRowStretch(0, 1)
        timer_shell_layout.setRowStretch(1, 1)

        center = QWidget(self._timer_shell)
        center.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        center_layout = QVBoxLayout(center)
        center_layout.setContentsMargins(0, 0, 0, 0)
        center_layout.setSpacing(0)

        self._circular_timer = CircularTimerWidget(center)
        self._circular_timer.setObjectName("circularTimer")
        center_layout.addStretch(1)
        center_layout.addWidget(self._circular_timer, alignment=Qt.AlignCenter)
        center_layout.addStretch(1)

        self._time_up_button = QPushButton("▲", self._timer_shell)
        self._time_up_button.setObjectName("timeArrowButton")
        self._time_up_button.setToolTip("Увеличить время режима на 1 минуту")
        self._time_up_button.clicked.connect(lambda: self._adjust_current_mode_minutes(1))

        self._time_down_button = QPushButton("▼", self._timer_shell)
        self._time_down_button.setObjectName("timeArrowButton")
        self._time_down_button.setToolTip("Уменьшить время режима на 1 минуту")
        self._time_down_button.clicked.connect(lambda: self._adjust_current_mode_minutes(-1))

        timer_shell_layout.addWidget(center, 0, 0, 2, 1)
        timer_shell_layout.addWidget(self._time_up_button, 0, 1, alignment=Qt.AlignBottom)
        timer_shell_layout.addWidget(self._time_down_button, 1, 1, alignment=Qt.AlignTop)

        controls_layout = QHBoxLayout()
        controls_layout.setSpacing(10)

        self._primary_button = QPushButton("СТАРТ", card)
        self._primary_button.setObjectName("primaryButton")
        self._primary_button.clicked.connect(self._on_primary_clicked)

        self._reset_button = QPushButton("СБРОС", card)
        self._reset_button.setObjectName("secondaryButton")
        self._reset_button.clicked.connect(self._controller.reset)

        controls_layout.addWidget(self._primary_button, stretch=2)
        controls_layout.addWidget(self._reset_button, stretch=1)

        self._popout_button = QPushButton("Открыть плавающее окно", card)
        self._popout_button.setObjectName("linkButton")
        self._popout_button.clicked.connect(self._open_floating_timer)

        self._cycle_label = QLabel("#1", card)
        self._cycle_label.setObjectName("cycleLabel")
        self._cycle_label.setAlignment(Qt.AlignCenter)

        self._status_label = QLabel("Время сосредоточиться!", card)
        self._status_label.setObjectName("statusLabel")
        self._status_label.setAlignment(Qt.AlignCenter)
        self._status_label.setWordWrap(True)

        card_layout.addLayout(modes_layout)
        card_layout.addWidget(self._timer_shell, stretch=1)
        card_layout.addLayout(controls_layout)
        card_layout.addWidget(self._popout_button)
        card_layout.addSpacing(4)
        card_layout.addWidget(self._cycle_label)
        card_layout.addWidget(self._status_label)

        layout.addWidget(card, stretch=1)
        return page

    def _build_planning_page(self) -> QWidget:
        page = QWidget(self)
        layout = QVBoxLayout(page)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(10)

        card = QFrame(page)
        card.setObjectName("planningCard")
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(24, 20, 24, 20)
        card_layout.setSpacing(12)

        self._week_header = WeekHeader(card)
        self._week_header.previous_clicked.connect(lambda: self._shift_planning_week(-1))
        self._week_header.next_clicked.connect(lambda: self._shift_planning_week(1))

        self._planning_table = PlanningWeekTable(card)
        self._planning_table.setObjectName("planningWeekTable")
        self._planning_table.setColumnCount(9)
        self._planning_table.setHorizontalHeaderLabels(["Задача", "Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс", "Всего"])
        self._planning_table.setRowCount(6)
        self._planning_table.verticalHeader().setVisible(False)
        self._planning_table.setAlternatingRowColors(False)
        self._planning_table.setFocusPolicy(Qt.NoFocus)
        self._planning_table.setSelectionMode(QAbstractItemView.NoSelection)
        self._planning_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._planning_table.setIconSize(QSize(14, 14))
        self._planning_table.cellClicked.connect(self._on_planning_cell_clicked)
        self._planning_table.cellEntered.connect(self._on_planning_cell_entered)
        self._planning_table.cellDoubleClicked.connect(self._on_planning_cell_double_clicked)
        self._planning_table.setMouseTracking(True)
        header = self._planning_table.horizontalHeader()
        header.setStretchLastSection(False)
        header.setDefaultAlignment(Qt.AlignCenter)
        header.setHighlightSections(False)
        header.setSectionResizeMode(0, QHeaderView.Fixed)
        self._planning_table.setColumnWidth(
            0,
            max(150, min(240, self._settings.planning_task_column_width)),
        )
        for col in range(1, 8):
            header.setSectionResizeMode(col, QHeaderView.Stretch)
        header.setSectionResizeMode(8, QHeaderView.Fixed)
        self._planning_table.setColumnWidth(
            8,
            max(66, min(110, self._settings.planning_total_column_width)),
        )

        controls = QHBoxLayout()
        controls.setContentsMargins(0, 0, 0, 0)
        controls.setSpacing(8)

        self._planning_add_task_button = QPushButton(card)
        self._planning_add_task_button.setObjectName("planningIconButton")
        self._planning_add_task_button.setFocusPolicy(Qt.NoFocus)
        self._planning_add_task_button.setFixedSize(40, 40)
        self._planning_add_task_button.setToolTip("Добавить новую задачу")
        add_icon_path = self._asset_path("add.svg")
        if add_icon_path.exists():
            self._planning_add_task_button.setIcon(QIcon(str(add_icon_path)))
            self._planning_add_task_button.setIconSize(QSize(18, 18))
        self._planning_add_task_button.clicked.connect(self._on_add_planning_task)

        self._planning_exclude_day_button = QPushButton(card)
        self._planning_exclude_day_button.setObjectName("planningIconButton")
        self._planning_exclude_day_button.setCheckable(True)
        self._planning_exclude_day_button.setFocusPolicy(Qt.NoFocus)
        self._planning_exclude_day_button.setFixedSize(40, 40)
        self._planning_exclude_day_button.setToolTip("Режим исключения дня для выбранной задачи")
        exclude_icon_path = self._asset_path("exclude_day.svg")
        if exclude_icon_path.exists():
            self._planning_exclude_day_button.setIcon(QIcon(str(exclude_icon_path)))
            self._planning_exclude_day_button.setIconSize(QSize(18, 18))
        self._planning_exclude_day_button.toggled.connect(self._on_toggle_planning_exclude_mode)

        self._planning_delete_task_button = QPushButton(card)
        self._planning_delete_task_button.setObjectName("planningIconButton")
        self._planning_delete_task_button.setCheckable(True)
        self._planning_delete_task_button.setFocusPolicy(Qt.NoFocus)
        self._planning_delete_task_button.setFixedSize(40, 40)
        self._planning_delete_task_button.setToolTip("Режим удаления задачи")
        delete_icon_path = self._asset_path("delete.svg")
        if delete_icon_path.exists():
            self._planning_delete_task_button.setIcon(QIcon(str(delete_icon_path)))
            self._planning_delete_task_button.setIconSize(QSize(18, 18))
        self._planning_delete_task_button.toggled.connect(self._on_toggle_planning_delete_mode)

        controls.addWidget(self._planning_add_task_button)
        controls.addWidget(self._planning_exclude_day_button)
        controls.addWidget(self._planning_delete_task_button)
        controls.addSpacing(8)

        self._planning_clear_plan_button = QPushButton(card)
        self._planning_clear_plan_button.setObjectName("planningIconButton")
        self._planning_clear_plan_button.setFocusPolicy(Qt.NoFocus)
        self._planning_clear_plan_button.setFixedSize(40, 40)
        self._planning_clear_plan_button.setToolTip("Очистить план выбранной задачи")
        clear_icon_path = self._asset_path("clear.svg")
        if clear_icon_path.exists():
            self._planning_clear_plan_button.setIcon(QIcon(str(clear_icon_path)))
            self._planning_clear_plan_button.setIconSize(QSize(18, 18))
        self._planning_clear_plan_button.clicked.connect(self._clear_selected_task_plan)
        controls.addWidget(self._planning_clear_plan_button)

        self._planning_save_button = QPushButton(card)
        self._planning_save_button.setObjectName("planningIconButton")
        self._planning_save_button.setFocusPolicy(Qt.NoFocus)
        self._planning_save_button.setFixedSize(40, 40)
        self._planning_save_button.setToolTip("Сохранить изменения планирования")
        save_icon_path = self._asset_path("save.svg")
        if save_icon_path.exists():
            self._planning_save_button.setIcon(QIcon(str(save_icon_path)))
            self._planning_save_button.setIconSize(QSize(18, 18))
        self._planning_save_button.clicked.connect(self._save_planning_changes)
        controls.addWidget(self._planning_save_button)
        controls.addStretch(1)

        card_layout.addWidget(self._week_header)
        card_layout.addLayout(controls)
        card_layout.addWidget(self._planning_table, stretch=1)

        layout.addWidget(card, stretch=1)
        self._rebuild_planning_table()
        return page

    def _build_tasks_page(self) -> QWidget:
        page = QWidget(self)
        layout = QVBoxLayout(page)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(0)

        card = QFrame(page)
        card.setObjectName("tasksCard")
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(28, 24, 28, 24)
        card_layout.setSpacing(12)

        self._tasks_week_header = WeekHeader(card)
        self._tasks_week_header.previous_clicked.connect(lambda: self._shift_planning_week(-1))
        self._tasks_week_header.next_clicked.connect(lambda: self._shift_planning_week(1))

        self._tasks_scroll = QScrollArea(card)
        self._tasks_scroll.setObjectName("tasksScrollArea")
        self._tasks_scroll.setWidgetResizable(True)
        self._tasks_scroll.setFrameShape(QFrame.NoFrame)
        self._tasks_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        self._tasks_scroll_content = QWidget(self._tasks_scroll)
        self._tasks_days_layout = QVBoxLayout(self._tasks_scroll_content)
        self._tasks_days_layout.setContentsMargins(0, 0, 0, 0)
        self._tasks_days_layout.setSpacing(10)

        self._tasks_day_tables.clear()
        self._tasks_day_headers.clear()
        self._tasks_day_empty_labels.clear()
        for day_index in range(7):
            self._create_tasks_day_section(day_index)
        self._tasks_days_layout.addStretch(1)

        self._tasks_scroll.setWidget(self._tasks_scroll_content)

        card_layout.addWidget(self._tasks_week_header)
        card_layout.addWidget(self._tasks_scroll, stretch=1)
        layout.addWidget(card, stretch=1)
        self._refresh_tasks_page()
        return page

    def _build_update_footer(self, parent: QWidget) -> QWidget:
        footer = QFrame(parent)
        self._update_footer = footer
        footer.setObjectName("updateFooter")
        footer_layout = QHBoxLayout(footer)
        footer_layout.setContentsMargins(14, 8, 14, 8)
        footer_layout.setSpacing(10)

        self._update_footer_label = QLabel("Доступна новая версия.", footer)
        self._update_footer_label.setObjectName("updateFooterLabel")
        self._update_footer_label.setWordWrap(True)

        self._update_footer_open_button = QPushButton("Обновить", footer)
        self._update_footer_open_button.setObjectName("updateFooterPrimaryButton")
        self._update_footer_open_button.clicked.connect(self._open_updates_page_from_footer)

        self._update_footer_hide_button = QPushButton("Скрыть", footer)
        self._update_footer_hide_button.setObjectName("updateFooterSecondaryButton")
        self._update_footer_hide_button.clicked.connect(self._dismiss_update_footer)

        footer_layout.addWidget(self._update_footer_label, stretch=1)
        footer_layout.addWidget(self._update_footer_open_button)
        footer_layout.addWidget(self._update_footer_hide_button)
        footer.setVisible(False)
        return footer

    def _build_updates_page(self) -> QWidget:
        page = QWidget(self)
        layout = QVBoxLayout(page)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(0)

        card = QFrame(page)
        card.setObjectName("settingsPageCard")
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(28, 24, 28, 24)
        card_layout.setSpacing(14)

        title = QLabel("Обновления", card)
        title.setObjectName("settingsPageTitle")
        hint = QLabel(
            "Проверка при запуске выполняется автоматически (тихо). "
            "Здесь доступна ручная проверка и установка новой версии.",
            card,
        )
        hint.setObjectName("settingsPageHint")
        hint.setWordWrap(True)

        info_box = QFrame(card)
        info_box.setObjectName("settingsFormBox")
        info_layout = QFormLayout(info_box)
        info_layout.setContentsMargins(16, 14, 16, 14)
        info_layout.setHorizontalSpacing(24)
        info_layout.setVerticalSpacing(12)

        info_title = QLabel("Состояние", info_box)
        info_title.setObjectName("settingsSectionTitle")
        info_layout.addRow(info_title)

        self._updates_current_version_value = QLabel(self._app_version, info_box)
        self._updates_current_version_value.setObjectName("settingsPageHint")
        self._updates_latest_version_value = QLabel("—", info_box)
        self._updates_latest_version_value.setObjectName("settingsPageHint")
        self._updates_min_supported_value = QLabel("—", info_box)
        self._updates_min_supported_value.setObjectName("settingsPageHint")
        self._updates_published_at_value = QLabel("—", info_box)
        self._updates_published_at_value.setObjectName("settingsPageHint")
        self._updates_last_attempt_value = QLabel("—", info_box)
        self._updates_last_attempt_value.setObjectName("settingsPageHint")
        self._updates_last_success_value = QLabel("—", info_box)
        self._updates_last_success_value.setObjectName("settingsPageHint")
        self._updates_status_value = QLabel("Проверка обновлений не выполнялась.", info_box)
        self._updates_status_value.setObjectName("settingsPageHint")
        self._updates_status_value.setWordWrap(True)
        self._updates_error_value = QLabel("", info_box)
        self._updates_error_value.setObjectName("updatesErrorText")
        self._updates_error_value.setWordWrap(True)
        self._updates_error_value.setVisible(False)
        self._updates_support_warning = QLabel("", info_box)
        self._updates_support_warning.setObjectName("updatesWarningText")
        self._updates_support_warning.setWordWrap(True)
        self._updates_support_warning.setVisible(False)

        self._updates_release_summary_value = QLabel("—", info_box)
        self._updates_release_summary_value.setObjectName("settingsPageHint")
        self._updates_release_summary_value.setWordWrap(True)
        self._updates_release_summary_value.setTextInteractionFlags(
            Qt.TextSelectableByMouse | Qt.TextSelectableByKeyboard
        )

        self._updates_release_notes_value = QLabel("—", info_box)
        self._updates_release_notes_value.setObjectName("settingsPageHint")
        self._updates_release_notes_value.setWordWrap(True)
        self._updates_release_notes_value.setTextInteractionFlags(
            Qt.TextSelectableByMouse | Qt.TextSelectableByKeyboard
        )

        info_layout.addRow("Текущая версия", self._updates_current_version_value)
        info_layout.addRow("Последняя версия", self._updates_latest_version_value)
        info_layout.addRow("Мин. поддержка", self._updates_min_supported_value)
        info_layout.addRow("Дата публикации", self._updates_published_at_value)
        info_layout.addRow("Последняя попытка", self._updates_last_attempt_value)
        info_layout.addRow("Последний успех", self._updates_last_success_value)
        info_layout.addRow("Статус", self._updates_status_value)
        info_layout.addRow("", self._updates_error_value)
        info_layout.addRow("", self._updates_support_warning)
        info_layout.addRow("Общее", self._updates_release_summary_value)
        info_layout.addRow("Подробно", self._updates_release_notes_value)

        actions = QHBoxLayout()
        actions.setContentsMargins(0, 0, 0, 0)
        actions.setSpacing(10)

        self._updates_check_now_button = QPushButton("Проверить сейчас", card)
        self._updates_check_now_button.setObjectName("settingsPreviewButton")
        self._updates_check_now_button.clicked.connect(self._on_check_updates_clicked)

        self._updates_install_button = QPushButton("Установить", card)
        self._updates_install_button.setObjectName("settingsPreviewButton")
        self._updates_install_button.setEnabled(False)
        self._updates_install_button.clicked.connect(self._on_install_update_clicked)

        actions.addWidget(self._updates_check_now_button)
        actions.addWidget(self._updates_install_button)
        actions.addStretch(1)

        self._updates_install_progress_label = QLabel("Прогресс установки", card)
        self._updates_install_progress_label.setObjectName("settingsPageHint")
        self._updates_install_progress_bar = QProgressBar(card)
        self._updates_install_progress_bar.setObjectName("updatesInstallProgressBar")
        self._updates_install_progress_bar.setRange(0, 100)
        self._updates_install_progress_bar.setValue(0)
        self._updates_install_progress_bar.setTextVisible(True)
        self._updates_install_progress_bar.setFormat("%p%")
        self._updates_install_progress_bar.setVisible(False)

        card_layout.addWidget(title)
        card_layout.addWidget(hint)
        card_layout.addWidget(info_box)
        card_layout.addLayout(actions)
        card_layout.addWidget(self._updates_install_progress_label)
        card_layout.addWidget(self._updates_install_progress_bar)

        layout.addWidget(card, stretch=1)
        return page

    def _create_tasks_day_section(self, day_index: int) -> None:
        section = QFrame(self._tasks_scroll_content)
        section.setObjectName("tasksDayCard")
        section_layout = QVBoxLayout(section)
        section_layout.setContentsMargins(12, 10, 12, 10)
        section_layout.setSpacing(8)

        header_button = QPushButton(section)
        header_button.setObjectName("tasksDayHeaderButton")
        header_button.setCheckable(True)
        header_button.setChecked(False)
        header_button.setFocusPolicy(Qt.NoFocus)
        header_button.toggled.connect(
            lambda checked, d=day_index: self._toggle_tasks_day_expanded(d, checked)
        )

        empty_label = QLabel("На этот день пока нет Pomodoro-единиц.", section)
        empty_label.setObjectName("tasksDayEmptyLabel")
        empty_label.setWordWrap(True)
        empty_label.setVisible(False)

        table = TaskUnitsDayTable(section)
        table.setObjectName("tasksDayTable")
        table.setColumnCount(6)
        table.setHorizontalHeaderLabels(["#", "Задача", "Pomodoro-единица", "", "Статус", ""])
        table.verticalHeader().setVisible(False)
        table.verticalHeader().setDefaultSectionSize(42)
        table.setAlternatingRowColors(False)
        table.setSelectionMode(QAbstractItemView.SingleSelection)
        table.setSelectionBehavior(QAbstractItemView.SelectRows)
        table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        table.setFocusPolicy(Qt.NoFocus)
        table.setWordWrap(not self._tasks_units_compact_mode)
        table.setTextElideMode(Qt.ElideRight if self._tasks_units_compact_mode else Qt.ElideNone)
        table.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        table.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        table.setIconSize(QSize(14, 14))
        header = table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.Fixed)
        header.setSectionResizeMode(2, QHeaderView.Fixed)
        header.setSectionResizeMode(3, QHeaderView.Fixed)
        header.setSectionResizeMode(4, QHeaderView.Fixed)
        header.setSectionResizeMode(5, QHeaderView.Fixed)
        table.setColumnWidth(1, 170)
        table.setColumnWidth(2, 360)
        table.setColumnWidth(3, 52)
        table.setColumnWidth(4, 132)
        table.setColumnWidth(5, 92)
        table.order_changed.connect(
            lambda ordered_ids, d=day_index: self._on_tasks_day_order_changed(d, ordered_ids)
        )
        table.cellDoubleClicked.connect(
            lambda row, column, d=day_index: self._on_tasks_day_cell_double_clicked(d, row, column)
        )
        table.itemSelectionChanged.connect(
            lambda d=day_index: self._on_tasks_table_selection_changed(d)
        )
        table.setVisible(False)

        section_layout.addWidget(header_button)
        section_layout.addWidget(empty_label)
        section_layout.addWidget(table)
        self._tasks_days_layout.addWidget(section)

        self._tasks_day_headers[day_index] = header_button
        self._tasks_day_empty_labels[day_index] = empty_label
        self._tasks_day_tables[day_index] = table

    def _expanded_days_for_week(self, week_key: str) -> set[int]:
        if week_key not in self._tasks_expanded_days_by_week:
            expanded = {
                day_idx
                for day_idx in range(7)
                if self._planner_controller.units_for_day(
                    week_start_iso=week_key,
                    day_index=day_idx,
                )
            }
            if not expanded:
                current_week_start = self._today - timedelta(days=self._today.weekday())
                if self._planning_week_start == current_week_start:
                    expanded = {self._today.weekday()}
            self._tasks_expanded_days_by_week[week_key] = expanded
        return self._tasks_expanded_days_by_week[week_key]

    def _toggle_tasks_day_expanded(self, day_index: int, expanded: bool) -> None:
        if self._is_populating_tasks_tables:
            return
        week_key = self._planning_week_key()
        expanded_days = self._expanded_days_for_week(week_key)
        if expanded:
            expanded_days.add(day_index)
        else:
            expanded_days.discard(day_index)
        self._refresh_tasks_page()

    def _refresh_tasks_page(self, *, force: bool = False) -> None:
        if not hasattr(self, "_tasks_week_header"):
            return
        if not force and hasattr(self, "_stack") and self._stack.currentIndex() != self.PAGE_TASKS:
            return
        week_start = self._planning_week_start
        week_end = week_start + timedelta(days=6)
        current_week_start = self._today - timedelta(days=self._today.weekday())
        self._tasks_week_header.set_week_range(
            week_start,
            week_end,
            is_current_week=(week_start == current_week_start),
        )

        week_key = self._planning_week_key()
        expanded_days = self._expanded_days_for_week(week_key)
        task_name_map = {task["id"]: task["name"] for task in self._planning_tasks}
        selected_unit = self._selected_unit_for_current_week()

        self._is_populating_tasks_tables = True
        try:
            for day_index in range(7):
                table = self._tasks_day_tables[day_index]
                table.setWordWrap(not self._tasks_units_compact_mode)
                table.setTextElideMode(Qt.ElideRight if self._tasks_units_compact_mode else Qt.ElideNone)
                day_units = self._planner_controller.units_for_day(
                    week_start_iso=week_key,
                    day_index=day_index,
                )
                self._rebuild_tasks_day_table(
                    day_index,
                    day_units,
                    task_name_map,
                    selected_unit_id=str(getattr(selected_unit, "id", "")) if selected_unit is not None else None,
                )

                done_count = sum(1 for unit in day_units if unit.status == "done")
                total_count = len(day_units)
                day_date = self._planning_week_start + timedelta(days=day_index)
                is_expanded = day_index in expanded_days
                arrow = "▾" if is_expanded else "▸"
                progress_text, progress_icon = self._planning_progress_repr(done_count, total_count)
                if not progress_text:
                    progress_text = "0"
                elif self._settings.planning_progress_view == "fraction":
                    progress_text = f"🍅 {progress_text}"
                header_text = (
                    f"{arrow} {self._day_names_short[day_index]} ({day_date.strftime('%d.%m')})"
                    f"   {progress_text}"
                )
                header_button = self._tasks_day_headers[day_index]
                with QSignalBlocker(header_button):
                    header_button.setChecked(is_expanded)
                header_button.setText(header_text)
                header_button.setIcon(progress_icon)
                header_button.setIconSize(QSize(15, 15))

                empty_label = self._tasks_day_empty_labels[day_index]
                self._apply_tasks_day_open_state(
                    day_index=day_index,
                    is_expanded=is_expanded,
                    total_count=total_count,
                )
        finally:
            self._is_populating_tasks_tables = False

    def _rebuild_tasks_day_table(
        self,
        day_index: int,
        day_units: list,
        task_name_map: dict[str, str],
        *,
        selected_unit_id: str | None = None,
    ) -> None:
        table = self._tasks_day_tables[day_index]
        table.blockSignals(True)
        try:
            table.setRowCount(len(day_units))
            selected_row = -1
            edit_icon = QIcon()
            edit_icon_path = self._asset_path("edit.svg")
            if edit_icon_path.exists():
                edit_icon = QIcon(str(edit_icon_path))
            for row, unit in enumerate(day_units):
                task_id = str(unit.parent_task_id)
                task_name = task_name_map.get(task_id, "Задача")
                default_title = task_name
                title_value = str(unit.custom_title).strip() or default_title
                unit_id = str(unit.id)

                idx_item = QTableWidgetItem(str(row + 1))
                idx_item.setTextAlignment(Qt.AlignCenter)
                idx_item.setFlags(idx_item.flags() & ~Qt.ItemIsEditable)
                idx_item.setData(Qt.UserRole, unit_id)
                table.setItem(row, 0, idx_item)

                task_item = QTableWidgetItem(task_name)
                task_item.setTextAlignment(Qt.AlignVCenter | Qt.AlignLeft)
                task_item.setFlags(task_item.flags() & ~Qt.ItemIsEditable)
                task_item.setToolTip(
                    f"<span style='font-size:16px; font-weight:600'>{task_name}</span>"
                )
                table.setItem(row, 1, task_item)

                title_item = QTableWidgetItem(title_value)
                title_item.setTextAlignment(Qt.AlignVCenter | Qt.AlignLeft)
                title_item.setData(Qt.UserRole, unit_id)
                title_item.setData(Qt.UserRole + 1, default_title)
                title_item.setData(Qt.UserRole + 2, task_id)
                title_item.setToolTip(
                    f"<span style='font-size:17px; font-weight:700'>{title_value}</span>"
                )
                table.setItem(row, 2, title_item)

                edit_button = QPushButton(table)
                edit_button.setObjectName("tasksUnitEditButton")
                edit_button.setFixedSize(30, 24)
                edit_button.setFocusPolicy(Qt.NoFocus)
                if not edit_icon.isNull():
                    edit_button.setIcon(edit_icon)
                    edit_button.setIconSize(QSize(15, 15))
                else:
                    edit_button.setText("✎")
                edit_button.clicked.connect(
                    lambda _=False, d=day_index, uid=unit_id: self._edit_task_unit_title(d, uid)
                )
                table.setCellWidget(row, 3, edit_button)

                status_text = "Готово" if str(unit.status) == "done" else "В ожидании"
                status_item = QTableWidgetItem(status_text)
                status_item.setTextAlignment(Qt.AlignCenter)
                status_item.setFlags(status_item.flags() & ~Qt.ItemIsEditable)
                if str(unit.status) == "done":
                    status_item.setForeground(QColor(184, 255, 207, 240))
                else:
                    status_item.setForeground(QColor(255, 242, 242, 220))
                table.setItem(row, 4, status_item)

                actions = QWidget(table)
                actions_layout = QHBoxLayout(actions)
                actions_layout.setContentsMargins(0, 0, 0, 0)
                actions_layout.setSpacing(4)

                up_button = QPushButton("▲", actions)
                up_button.setObjectName("tasksUnitActionButton")
                up_button.setFixedSize(32, 24)
                up_button.setFocusPolicy(Qt.NoFocus)
                up_button.setEnabled(row > 0)
                up_button.clicked.connect(
                    lambda _=False, d=day_index, uid=str(unit.id): self._move_task_unit_in_day(d, uid, -1)
                )

                down_button = QPushButton("▼", actions)
                down_button.setObjectName("tasksUnitActionButton")
                down_button.setFixedSize(32, 24)
                down_button.setFocusPolicy(Qt.NoFocus)
                down_button.setEnabled(row < len(day_units) - 1)
                down_button.clicked.connect(
                    lambda _=False, d=day_index, uid=str(unit.id): self._move_task_unit_in_day(d, uid, 1)
                )

                actions_layout.addWidget(up_button)
                actions_layout.addWidget(down_button)
                table.setCellWidget(row, 5, actions)
                table.setRowHeight(
                    row,
                    self._tasks_title_row_height(
                        table=table,
                        text=title_value,
                    ),
                )

                if selected_unit_id and unit_id == selected_unit_id:
                    selected_row = row

            base_height = table.horizontalHeader().height() + table.frameWidth() * 2 + 4
            content_height = sum(table.rowHeight(r) for r in range(table.rowCount()))
            table.setFixedHeight(max(base_height + content_height, base_height + 2))
            if selected_row >= 0:
                table.setCurrentCell(selected_row, 2)
            else:
                table.clearSelection()
        finally:
            table.blockSignals(False)

    def _tasks_title_row_height(self, *, table: QTableWidget, text: str) -> int:
        if self._tasks_units_compact_mode:
            return 40
        content = str(text or "").strip()
        if not content:
            return 40
        title_width = max(160, table.columnWidth(2) - 14)
        metrics = table.fontMetrics()
        rect = metrics.boundingRect(
            QRect(0, 0, title_width, 240),
            Qt.TextWordWrap | Qt.AlignLeft | Qt.AlignVCenter,
            content,
        )
        return max(40, min(170, rect.height() + 20))

    def _apply_tasks_day_open_state(self, *, day_index: int, is_expanded: bool, total_count: int) -> None:
        table = self._tasks_day_tables[day_index]
        empty_label = self._tasks_day_empty_labels[day_index]
        table.setVisible(is_expanded and total_count > 0)
        empty_label.setVisible(is_expanded and total_count == 0)

    def _on_tasks_table_item_changed(self, day_index: int, item: QTableWidgetItem) -> None:
        if self._is_populating_tasks_tables:
            return
        if item.column() != 2:
            return
        unit_id = str(item.data(Qt.UserRole) or "")
        if not unit_id:
            return

        entered_title = str(item.text() or "").strip()
        default_title = str(item.data(Qt.UserRole + 1) or "").strip()
        if entered_title == default_title:
            entered_title = ""

        week_key = self._planning_week_key()
        if not self._planner_controller.set_unit_custom_title(
            week_start_iso=week_key,
            unit_id=unit_id,
            custom_title=entered_title,
        ):
            return

        self._save_planning_state()
        self.statusBar().showMessage("Название Pomodoro-единицы обновлено.", 2000)
        self._refresh_tasks_page()

    def _on_tasks_day_cell_double_clicked(self, day_index: int, row: int, column: int) -> None:
        if column != 2:
            return
        table = self._tasks_day_tables.get(day_index)
        if table is None:
            return
        item = table.item(row, 2)
        if item is None:
            return
        unit_id = str(item.data(Qt.UserRole) or "")
        if not unit_id:
            return
        self._edit_task_unit_title(day_index, unit_id)

    def _edit_task_unit_title(self, day_index: int, unit_id: str) -> None:
        week_key = self._planning_week_key()
        unit = self._planner_controller.get_unit(
            week_start_iso=week_key,
            unit_id=unit_id,
        )
        if unit is None:
            return

        task_name = self._task_display_name(str(unit.parent_task_id)) or "Задача"
        current_text = str(unit.custom_title).strip() or task_name

        dialog = QDialog(self)
        dialog.setObjectName("planningTaskDialog")
        dialog.setWindowTitle("Редактировать единицу")
        dialog.setMinimumWidth(440)

        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(10)

        caption = QLabel("Название Pomodoro-единицы", dialog)
        caption.setObjectName("planningTaskLabel")
        edit = QLineEdit(dialog)
        edit.setObjectName("planningTaskInput")
        edit.setText(current_text)
        edit.selectAll()
        edit.setFocus()

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel, dialog)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)

        layout.addWidget(caption)
        layout.addWidget(edit)
        layout.addWidget(buttons)

        if dialog.exec() != QDialog.Accepted:
            return

        entered = str(edit.text() or "").strip()
        custom_title = "" if entered == task_name else entered
        if not self._planner_controller.set_unit_custom_title(
            week_start_iso=week_key,
            unit_id=unit_id,
            custom_title=custom_title,
        ):
            return
        self._save_planning_state()
        self._refresh_tasks_page()
        self.statusBar().showMessage("Название Pomodoro-единицы обновлено.", 2200)

    def _on_tasks_day_order_changed(self, day_index: int, ordered_ids: object) -> None:
        if self._is_populating_tasks_tables:
            return
        if not isinstance(ordered_ids, list):
            return
        week_key = self._planning_week_key()
        moved = self._planner_controller.reorder_day_units(
            week_start_iso=week_key,
            day_index=day_index,
            ordered_unit_ids=[str(v) for v in ordered_ids],
        )
        if not moved:
            return
        self._save_planning_state()
        self._refresh_tasks_page()

    def _on_tasks_table_selection_changed(self, day_index: int) -> None:
        if self._is_populating_tasks_tables:
            return
        table = self._tasks_day_tables.get(day_index)
        if table is None:
            return
        row = table.currentRow()
        if row < 0:
            return

        title_item = table.item(row, 2)
        if title_item is None:
            return

        unit_id = str(title_item.data(Qt.UserRole) or "")
        task_id = str(title_item.data(Qt.UserRole + 2) or "")
        if not unit_id or not task_id:
            return

        week_key = self._planning_week_key()
        unit = self._planner_controller.get_unit(
            week_start_iso=week_key,
            unit_id=unit_id,
        )
        if unit is None:
            return

        self._planning_selected_task_id = task_id
        self._planning_selected_day_index = day_index
        self._planning_selected_unit_by_week[week_key] = unit_id
        self._save_planning_state()
        self._refresh_planning_column_visuals()
        self._on_state_changed(self._controller.state.snapshot())

        unit_title = self._task_unit_display_title(unit)
        self.statusBar().showMessage(
            f"Выбрана единица: {unit_title}.",
            2200,
        )

    def _move_task_unit_in_day(self, day_index: int, unit_id: str, delta: int) -> None:
        week_key = self._planning_week_key()
        moved = self._planner_controller.move_unit_within_day(
            week_start_iso=week_key,
            day_index=day_index,
            unit_id=unit_id,
            delta=delta,
        )
        if not moved:
            return
        self._save_planning_state()
        self._refresh_tasks_page()

    def _shift_planning_week(self, offset: int) -> None:
        self._planning_week_start = self._planning_week_start + timedelta(days=7 * int(offset))
        self._planning_pending_switch_key = None
        self._reconcile_planner_week(self._planning_week_key())
        self._update_planning_week_labels()

    def _go_to_current_planning_week(self) -> None:
        self._planning_week_start = self._today - timedelta(days=self._today.weekday())
        self._planning_pending_switch_key = None
        self._reconcile_planner_week(self._planning_week_key())
        self._update_planning_week_labels()

    def _planning_week_key(self) -> str:
        return self._planning_week_start.isoformat()

    def _planning_task_ids_set(self) -> set[str]:
        return {task["id"] for task in self._planning_tasks}

    def _reconcile_planner_week(self, week_key: str) -> None:
        task_ids = self._planning_task_ids_set()
        planned_week = self._planning_planned_cells_by_week.setdefault(week_key, {})
        excluded_week = self._planning_excluded_cells_by_week.setdefault(week_key, {})
        done_week = self._planner_controller.reconcile_week(
            week_start_iso=week_key,
            task_ids=task_ids,
            planned_cells_week=planned_week,
            excluded_cells_week=excluded_week,
        )
        self._planning_done_cells_by_week[week_key] = done_week
        selected_unit_id = self._planning_selected_unit_by_week.get(week_key)
        if selected_unit_id and not self._planner_controller.has_unit(
            week_start_iso=week_key,
            unit_id=selected_unit_id,
        ):
            self._planning_selected_unit_by_week.pop(week_key, None)

    def _reconcile_planner_all_weeks(self) -> None:
        week_keys = set(self._planning_planned_cells_by_week.keys())
        week_keys.update(self._planning_excluded_cells_by_week.keys())
        week_keys.update(self._planning_weekly_targets_by_week.keys())
        week_keys.update(self._planning_done_cells_by_week.keys())
        week_keys.update(self._planner_controller.week_keys())
        week_keys.add(self._planning_week_key())
        for week_key in sorted(week_keys):
            self._reconcile_planner_week(week_key)

    def _excluded_cells_for_current_week(self) -> dict[str, set[int]]:
        key = self._planning_week_key()
        if key not in self._planning_excluded_cells_by_week:
            self._planning_excluded_cells_by_week[key] = {}
        return self._planning_excluded_cells_by_week[key]

    def _planned_cells_for_current_week(self) -> dict[str, list[int]]:
        key = self._planning_week_key()
        if key not in self._planning_planned_cells_by_week:
            self._planning_planned_cells_by_week[key] = {}
        return self._planning_planned_cells_by_week[key]

    def _done_cells_for_current_week(self) -> dict[str, list[int]]:
        key = self._planning_week_key()
        if key not in self._planning_done_cells_by_week:
            self._planning_done_cells_by_week[key] = {}
        return self._planning_done_cells_by_week[key]

    def _weekly_targets_for_current_week(self) -> dict[str, int]:
        key = self._planning_week_key()
        if key not in self._planning_weekly_targets_by_week:
            self._planning_weekly_targets_by_week[key] = {}
        return self._planning_weekly_targets_by_week[key]

    def _task_weekly_target(self, task_id: str) -> int:
        return max(0, int(self._weekly_targets_for_current_week().get(task_id, 0)))

    def _planning_progress_repr(self, done: int, planned: int) -> tuple[str, QIcon]:
        planned = max(0, int(planned))
        done = max(0, min(int(done), planned))
        if planned <= 0:
            return "", QIcon()

        mode = self._settings.planning_progress_view
        if mode == "fraction":
            icon = self._tomato_icon if not self._tomato_icon.isNull() else QIcon()
            return f"{done}/{planned}", icon

        symbol_style = self._settings.planning_visual_style
        max_symbols = max(3, min(16, self._settings.planning_visual_max_symbols))
        if planned <= max_symbols:
            visible_done = done
            visible_total = planned
        else:
            visible_total = max_symbols
            visible_done = int(round((done / planned) * visible_total)) if planned > 0 else 0
            if done > 0 and visible_done == 0:
                visible_done = 1
            visible_done = min(visible_total, visible_done)

        icon = QIcon()
        if symbol_style == "tomato":
            filled_symbol = "◉"
            empty_symbol = "◌"
            if not self._tomato_icon.isNull():
                icon = self._tomato_icon
        elif symbol_style == "square":
            filled_symbol = "■"
            empty_symbol = "□"
        elif symbol_style == "bar":
            filled_symbol = "▰"
            empty_symbol = "▱"
        else:
            filled_symbol = "●"
            empty_symbol = "○"

        text = (filled_symbol * visible_done) + (empty_symbol * max(0, visible_total - visible_done))
        if planned > max_symbols:
            text = f"{text} {done}/{planned}"
        return text, icon

    def _week_task_values(self, storage: dict[str, list[int]], task_id: str) -> list[int]:
        values = storage.get(task_id)
        if not isinstance(values, list) or len(values) != 7:
            values = [0] * 7
            storage[task_id] = values
        sanitized = [max(0, int(v)) for v in values[:7]]
        if sanitized != values:
            storage[task_id] = sanitized
        return storage[task_id]

    def _repair_task_name(self, value: str) -> str:
        text = str(value or "").strip()
        if not text:
            return ""

        # Best-effort recovery for legacy mojibake from older planner JSON snapshots.
        if any(ch in text for ch in ("Р", "С", "Ð", "Ñ")):
            for src_encoding in ("cp1251", "latin1"):
                try:
                    repaired = text.encode(src_encoding, errors="strict").decode("utf-8", errors="strict").strip()
                except (UnicodeEncodeError, UnicodeDecodeError):
                    continue
                if repaired and repaired != text:
                    text = repaired
                    break

        text = text.replace("\ufffd", "").strip()
        text = re.sub(r"^\?{2,}\s*", "", text)
        if not text:
            return "Задача"
        return text

    def _task_display_name(self, task_id: str | None) -> str | None:
        if not task_id:
            return None
        for task in self._planning_tasks:
            if task["id"] == task_id:
                return str(task.get("name", "Задача"))
        return None

    def _task_description(self, task_id: str | None) -> str:
        if not task_id:
            return ""
        for task in self._planning_tasks:
            if task["id"] == task_id:
                return str(task.get("description", "")).strip()
        return ""

    def _selected_unit_for_current_week(self):
        week_key = self._planning_week_key()
        unit_id = self._planning_selected_unit_by_week.get(week_key)
        if not unit_id:
            return None
        unit = self._planner_controller.get_unit(
            week_start_iso=week_key,
            unit_id=unit_id,
        )
        if unit is None:
            self._planning_selected_unit_by_week.pop(week_key, None)
            return None
        return unit

    def _task_unit_display_title(self, unit) -> str:
        task_name = self._task_display_name(str(unit.parent_task_id)) or "Задача"
        custom = str(getattr(unit, "custom_title", "") or "").strip()
        if custom:
            return custom
        return task_name

    def _find_next_pending_unit_in_sequence(
        self,
        *,
        week_key: str,
        completed_day_index: int,
        completed_unit_id: str | None,
    ):
        def pending_for_day(day_index: int, *, prioritize_after_completed: bool) -> object | None:
            units = self._planner_controller.units_for_day(
                week_start_iso=week_key,
                day_index=day_index,
            )
            if not units:
                return None

            if prioritize_after_completed and completed_unit_id:
                current_index = next(
                    (idx for idx, unit in enumerate(units) if str(unit.id) == str(completed_unit_id)),
                    -1,
                )
                if current_index >= 0:
                    for unit in units[current_index + 1 :]:
                        if str(unit.status) == "pending":
                            return unit
                    for unit in units[: current_index + 1]:
                        if str(unit.status) == "pending":
                            return unit

            for unit in units:
                if str(unit.status) == "pending":
                    return unit
            return None

        same_day_unit = pending_for_day(completed_day_index, prioritize_after_completed=True)
        if same_day_unit is not None:
            return same_day_unit

        for day_index in range(completed_day_index + 1, 7):
            next_unit = pending_for_day(day_index, prioritize_after_completed=False)
            if next_unit is not None:
                return next_unit

        for day_index in range(0, completed_day_index):
            next_unit = pending_for_day(day_index, prioritize_after_completed=False)
            if next_unit is not None:
                return next_unit
        return None

    def _first_pending_unit_for_day(self, *, week_key: str, day_index: int):
        units = self._planner_controller.units_for_day(
            week_start_iso=week_key,
            day_index=day_index,
        )
        for unit in units:
            if str(unit.status) == "pending":
                return unit
        return None

    def _sync_today_reference(self) -> bool:
        now = date.today()
        if now == self._today:
            return False
        prev_current_week = self._today - timedelta(days=self._today.weekday())
        new_current_week = now - timedelta(days=now.weekday())
        was_on_current_week = self._planning_week_start == prev_current_week
        self._today = now
        if was_on_current_week:
            self._planning_week_start = new_current_week
        return True

    def _apply_selected_unit(self, *, week_key: str, unit) -> bool:
        unit_task_id = str(unit.parent_task_id)
        unit_day_index = int(unit.day_index)
        unit_id = str(unit.id)
        changed = (
            self._planning_selected_task_id != unit_task_id
            or self._planning_selected_day_index != unit_day_index
            or self._planning_selected_unit_by_week.get(week_key) != unit_id
        )
        self._planning_selected_task_id = unit_task_id
        self._planning_selected_day_index = unit_day_index
        self._planning_selected_unit_by_week[week_key] = unit_id
        if changed:
            self._planning_pending_switch_key = None
        return changed

    def _ensure_follow_queue_selection(self, *, save_if_changed: bool = False) -> bool:
        changed = self._sync_today_reference()
        week_key = self._planning_week_key()
        self._reconcile_planner_week(week_key)

        selected_unit = self._selected_unit_for_current_week()
        if selected_unit is not None and str(selected_unit.status) != "pending":
            self._planning_selected_unit_by_week.pop(week_key, None)
            selected_unit = None
            changed = True

        if not self._settings.planning_follow_tasks_queue:
            if save_if_changed and changed:
                self._save_planning_state()
            return changed

        current_week_start = self._today - timedelta(days=self._today.weekday())
        today_index = self._today.weekday() if self._planning_week_start == current_week_start else None

        # Keep previous progress point, but on a new day prefer today's queue if it has pending units.
        if selected_unit is not None:
            if (
                today_index is not None
                and int(selected_unit.day_index) != today_index
            ):
                today_pending = self._first_pending_unit_for_day(
                    week_key=week_key,
                    day_index=today_index,
                )
                if today_pending is not None:
                    changed = self._apply_selected_unit(week_key=week_key, unit=today_pending) or changed
            else:
                changed = self._apply_selected_unit(week_key=week_key, unit=selected_unit) or changed

            if save_if_changed and changed:
                self._save_planning_state()
            return changed

        day_order = list(range(7))
        if today_index is not None:
            day_order = list(range(today_index, 7)) + list(range(0, today_index))

        next_pending = None
        for day_index in day_order:
            candidate = self._first_pending_unit_for_day(week_key=week_key, day_index=day_index)
            if candidate is not None:
                next_pending = candidate
                break

        if next_pending is not None:
            changed = self._apply_selected_unit(week_key=week_key, unit=next_pending) or changed
        else:
            if self._planning_selected_task_id is not None or self._planning_selected_day_index is not None:
                self._planning_selected_task_id = None
                self._planning_selected_day_index = None
                changed = True
            if week_key in self._planning_selected_unit_by_week:
                self._planning_selected_unit_by_week.pop(week_key, None)
                changed = True

        if save_if_changed and changed:
            self._save_planning_state()
        return changed

    def _on_planning_cell_entered(self, row: int, column: int) -> None:
        if not (0 <= row < len(self._planning_tasks)):
            return
        task = self._planning_tasks[row]
        name = str(task.get("name", "Задача"))
        description = str(task.get("description", "")).strip()
        if column == 0 and description:
            self.statusBar().showMessage(f"{name}: {description}", 2800)

    def _on_planning_cell_double_clicked(self, row: int, column: int) -> None:
        if self._planning_delete_mode or self._planning_exclude_mode:
            return
        if column != 0:
            return
        if not (0 <= row < len(self._planning_tasks)):
            return
        task_id = str(self._planning_tasks[row].get("id", ""))
        if not task_id:
            return
        self._edit_planning_task(task_id)

    def _save_planning_changes(self) -> None:
        self._save_planning_state()
        self.statusBar().showMessage("Изменения в планировании сохранены.", 2400)

    def _edit_selected_planning_task(self) -> None:
        task_id = self._planning_selected_task_id
        if not task_id:
            self.statusBar().showMessage("Сначала выберите задачу для редактирования.", 2200)
            return
        self._edit_planning_task(task_id)

    def _clear_selected_task_plan(self) -> None:
        task_id = self._planning_selected_task_id
        if not task_id:
            self.statusBar().showMessage("Сначала выберите задачу в таблице.", 2200)
            return
        self._distribute_weekly_total_for_task(task_id, 0)
        self._planning_pending_switch_key = None
        self._save_planning_state()
        self._update_planning_week_labels()
        self._on_state_changed(self._controller.state.snapshot())
        self.statusBar().showMessage("План выбранной задачи очищен.", 2400)

    def _on_planning_daily_limit_changed(self, value: int) -> None:
        limit = max(1, int(value))
        self._settings.planning_daily_limit = limit
        self._settings_manager.save(self._settings)
        self._enforce_day_limits_for_current_week()
        self._save_planning_state()
        self._refresh_planning_column_visuals()
        self.statusBar().showMessage(f"Лимит на день обновлен: {limit} 🍅.", 2200)

    def _on_planning_weekly_limit_changed(self, value: int) -> None:
        limit = max(1, int(value))
        self._settings.planning_weekly_limit = limit
        self._settings_manager.save(self._settings)
        current_total = self._week_planned_total()
        self._save_planning_state()
        self._refresh_planning_column_visuals()
        if current_total > limit:
            self.statusBar().showMessage(
                f"Текущий недельный план {current_total} превышает лимит {limit}.",
                3200,
            )
            return
        self.statusBar().showMessage(f"Лимит на неделю обновлен: {limit} 🍅.", 2200)

    def _maybe_switch_to_timer_on_selection(self, task_id: str, day_index: int | None) -> None:
        if not self._settings.planning_auto_switch_to_timer_on_select:
            self._planning_pending_switch_key = None
            return
        key = (task_id, day_index)
        if self._settings.planning_confirm_before_timer_switch:
            if self._planning_pending_switch_key != key:
                self._planning_pending_switch_key = key
                self.statusBar().showMessage(
                    "Выбрано. Нажмите еще раз по этой же задаче/дню для перехода в Pomodoro.",
                    3000,
                )
                return
        self._planning_pending_switch_key = None
        self._switch_page(self.PAGE_POMODORO)

    def _on_toggle_planning_delete_mode(self, enabled: bool) -> None:
        self._planning_delete_mode = bool(enabled)
        self._planning_pending_switch_key = None
        if self._planning_delete_mode and hasattr(self, "_planning_exclude_day_button"):
            with QSignalBlocker(self._planning_exclude_day_button):
                self._planning_exclude_day_button.setChecked(False)
            self._planning_exclude_mode = False
        message = (
            "Режим удаления: клик по названию задачи удаляет строку."
            if self._planning_delete_mode
            else "Режим выбора задачи активен."
        )
        self.statusBar().showMessage(message, 2600)
        self._refresh_planning_column_visuals()

    def _on_toggle_planning_exclude_mode(self, enabled: bool) -> None:
        self._planning_exclude_mode = bool(enabled)
        self._planning_pending_switch_key = None
        if self._planning_exclude_mode and hasattr(self, "_planning_delete_task_button"):
            with QSignalBlocker(self._planning_delete_task_button):
                self._planning_delete_task_button.setChecked(False)
            self._planning_delete_mode = False
        message = (
            "Режим исключения: клик по ячейке дня включает/снимает исключение для задачи."
            if self._planning_exclude_mode
            else "Режим выбора задачи активен."
        )
        self.statusBar().showMessage(message, 2600)
        self._refresh_planning_column_visuals()

    def _toggle_task_day_exclusion(self, task_id: str, day_index: int) -> None:
        week_excluded = self._excluded_cells_for_current_week()
        task_excluded = week_excluded.setdefault(task_id, set())

        if day_index in task_excluded:
            task_excluded.remove(day_index)
            if not task_excluded:
                week_excluded.pop(task_id, None)
            self.statusBar().showMessage("Исключение снято для выбранной ячейки.", 2200)
        else:
            task_excluded.add(day_index)
            self.statusBar().showMessage("День исключен для выбранной задачи.", 2200)
            if self._planning_selected_task_id == task_id and self._planning_selected_day_index == day_index:
                self._planning_selected_day_index = None
                self._planning_pending_switch_key = None
                self._planning_selected_unit_by_week.pop(self._planning_week_key(), None)
        self._reconcile_planner_week(self._planning_week_key())

    def _prompt_day_plan(self, task_name: str, day_index: int, current_value: int) -> int | None:
        dialog = QDialog(self)
        dialog.setObjectName("planningTaskDialog")
        dialog.setWindowTitle("План на день")
        dialog.setMinimumWidth(420)

        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(10)

        day_name = self._day_names_short[day_index]
        caption = QLabel(
            f"Сколько помидоров запланировать на {day_name} для задачи «{task_name}»?",
            dialog,
        )
        caption.setObjectName("planningTaskLabel")
        caption.setWordWrap(True)

        spin = NoWheelSpinBox(dialog)
        spin.setObjectName("planningTaskInput")
        spin.setRange(0, 30)
        spin.setValue(max(0, int(current_value)))
        spin.setSuffix(" 🍅")
        spin.selectAll()
        spin.setFocus()

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel, dialog)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)

        layout.addWidget(caption)
        layout.addWidget(spin)
        layout.addWidget(buttons)

        if dialog.exec() != QDialog.Accepted:
            return None
        return int(spin.value())

    def _task_done_value_for_day(self, task_id: str, day_index: int) -> int:
        week_key = self._planning_week_key()
        done_map = self._planner_controller.done_by_day_for_week(
            week_start_iso=week_key,
            task_ids={task_id},
        )
        values = done_map.get(task_id, [0] * 7)
        if not 0 <= int(day_index) <= 6:
            return 0
        return max(0, int(values[int(day_index)]))

    def _day_planned_total(self, day_index: int, *, exclude_task_id: str | None = None) -> int:
        day = int(day_index)
        if not 0 <= day <= 6:
            return 0
        total = 0
        storage = self._planned_cells_for_current_week()
        for task in self._planning_tasks:
            task_id = str(task.get("id", ""))
            if not task_id or task_id == exclude_task_id:
                continue
            values = self._week_task_values(storage, task_id)
            total += max(0, int(values[day]))
        return total

    def _week_planned_total(self) -> int:
        total = 0
        storage = self._planned_cells_for_current_week()
        for task in self._planning_tasks:
            task_id = str(task.get("id", ""))
            if not task_id:
                continue
            values = self._week_task_values(storage, task_id)
            for day in range(7):
                total += max(0, int(values[day]))
        return total

    def _max_allowed_for_task_day(self, task_id: str, day_index: int) -> int:
        day = int(day_index)
        limit = max(1, int(self._settings.planning_daily_limit))
        other_total = self._day_planned_total(day, exclude_task_id=task_id)
        hard_cap = max(0, limit - other_total)
        done_floor = self._task_done_value_for_day(task_id, day)
        weekly_limit = max(1, int(self._settings.planning_weekly_limit))
        current_values = self._week_task_values(self._planned_cells_for_current_week(), task_id)
        current_cell = max(0, int(current_values[day]))
        week_total_without_cell = max(0, self._week_planned_total() - current_cell)
        weekly_cap = max(0, weekly_limit - week_total_without_cell)
        return max(done_floor, min(hard_cap, weekly_cap))

    def _enforce_day_limits_for_current_week(self) -> None:
        week_key = self._planning_week_key()
        planned_storage = self._planned_cells_for_current_week()
        limit = max(1, int(self._settings.planning_daily_limit))
        done_map = self._planner_controller.done_by_day_for_week(
            week_start_iso=week_key,
            task_ids=self._planning_task_ids_set(),
        )

        for day_index in range(7):
            total = 0
            for task in self._planning_tasks:
                task_id = str(task.get("id", ""))
                if not task_id:
                    continue
                values = self._week_task_values(planned_storage, task_id)
                total += max(0, int(values[day_index]))

            if total <= limit:
                continue

            while total > limit:
                reduced = False
                task_order = sorted(
                    (
                        str(task.get("id", ""))
                        for task in self._planning_tasks
                        if str(task.get("id", ""))
                    ),
                    key=lambda tid: self._week_task_values(planned_storage, tid)[day_index],
                    reverse=True,
                )
                for task_id in task_order:
                    values = self._week_task_values(planned_storage, task_id)
                    current_value = max(0, int(values[day_index]))
                    done_floor = max(0, int(done_map.get(task_id, [0] * 7)[day_index]))
                    if current_value <= done_floor:
                        continue
                    values[day_index] = current_value - 1
                    total -= 1
                    reduced = True
                    if total <= limit:
                        break
                if not reduced:
                    break

        for task in self._planning_tasks:
            task_id = str(task.get("id", ""))
            if not task_id:
                continue
            values = self._week_task_values(planned_storage, task_id)
            self._weekly_targets_for_current_week()[task_id] = sum(values)

        self._reconcile_planner_week(week_key)

    def _set_task_day_plan(self, task_id: str, day_index: int, value: int) -> None:
        week_excluded = self._excluded_cells_for_current_week()
        if day_index in week_excluded.get(task_id, set()):
            self.statusBar().showMessage("Сначала снимите исключение с этого дня.", 2200)
            return

        planned_values = self._week_task_values(self._planned_cells_for_current_week(), task_id)
        requested = max(0, int(value))
        max_allowed = self._max_allowed_for_task_day(task_id, day_index)
        applied = min(requested, max_allowed)
        planned_values[day_index] = applied
        if applied < requested:
            self.statusBar().showMessage(
                f"Лимит дня достигнут. Применено {applied} из {requested}.",
                3200,
            )
        self._weekly_targets_for_current_week()[task_id] = sum(planned_values)
        self._reconcile_planner_week(self._planning_week_key())

    def _prompt_weekly_total(self, task_name: str, current_total: int) -> int | None:
        dialog = QDialog(self)
        dialog.setObjectName("planningTaskDialog")
        dialog.setWindowTitle("План на неделю")
        dialog.setMinimumWidth(420)

        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(10)

        caption = QLabel(f"Сколько помидоров запланировать для задачи «{task_name}»?", dialog)
        caption.setObjectName("planningTaskLabel")
        caption.setWordWrap(True)

        spin = NoWheelSpinBox(dialog)
        spin.setObjectName("planningTaskInput")
        spin.setRange(0, 200)
        spin.setValue(max(0, int(current_total)))
        spin.setSuffix(" 🍅")
        spin.selectAll()
        spin.setFocus()

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel, dialog)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)

        layout.addWidget(caption)
        layout.addWidget(spin)
        layout.addWidget(buttons)

        if dialog.exec() != QDialog.Accepted:
            return None
        return int(spin.value())

    def _distribute_weekly_total_for_task(
        self,
        task_id: str,
        total: int,
        *,
        pinned_day: int | None = None,
        pinned_value: int | None = None,
    ) -> None:
        total = max(0, int(total))
        week_excluded = self._excluded_cells_for_current_week()
        excluded_days = week_excluded.get(task_id, set())
        planned_storage = self._planned_cells_for_current_week()
        active_days = [idx for idx in range(7) if idx not in excluded_days]
        ordered_active_days = self._distribution_order_for_week(active_days)
        week_key = self._planning_week_key()
        done_map = self._planner_controller.done_by_day_for_week(
            week_start_iso=week_key,
            task_ids={task_id},
        )
        done_values = done_map.get(task_id, [0] * 7)
        locked_excluded: dict[int, int] = {
            day_idx: done_values[day_idx]
            for day_idx in excluded_days
            if done_values[day_idx] > 0
        }
        locked_excluded_sum = sum(locked_excluded.values())

        # Predictable rule: weekly_target includes locked done units on excluded days.
        done_active_sum = sum(done_values[day] for day in active_days)
        effective_total = max(total, locked_excluded_sum + done_active_sum)
        weekly_limit = max(1, int(self._settings.planning_weekly_limit))
        other_week_total = 0
        for task in self._planning_tasks:
            other_task_id = str(task.get("id", ""))
            if not other_task_id or other_task_id == task_id:
                continue
            values = self._week_task_values(planned_storage, other_task_id)
            other_week_total += sum(max(0, int(v)) for v in values)
        max_allowed_for_task = max(0, weekly_limit - other_week_total)
        effective_total_capped = max(locked_excluded_sum + done_active_sum, min(effective_total, max_allowed_for_task))
        if effective_total_capped < effective_total:
            self.statusBar().showMessage(
                "Недельный лимит ограничил раскладку для выбранной задачи.",
                3400,
            )
        effective_total = effective_total_capped
        self._weekly_targets_for_current_week()[task_id] = effective_total

        if not active_days:
            planned = [0] * 7
            for day_idx, done_count in locked_excluded.items():
                planned[day_idx] = done_count
            planned_storage[task_id] = planned
            self._reconcile_planner_week(week_key)
            self.statusBar().showMessage("Нет активных дней для раскладки. Снимите исключение хотя бы с одного дня.", 3200)
            return

        new_plan = [0] * 7
        for day_idx, done_count in locked_excluded.items():
            new_plan[day_idx] = done_count
        candidate_days = list(ordered_active_days)
        available_for_active = max(0, effective_total - locked_excluded_sum)

        capacities: dict[int, int] = {}
        daily_limit = max(1, int(self._settings.planning_daily_limit))
        day_values: dict[int, int] = {}
        for day_idx in ordered_active_days:
            other_day_total = self._day_planned_total(day_idx, exclude_task_id=task_id)
            daily_cap = max(0, daily_limit - other_day_total)
            capacities[day_idx] = max(done_values[day_idx], daily_cap)
            day_values[day_idx] = max(0, int(done_values[day_idx]))

        remainder_pool = available_for_active - sum(day_values.values())
        remainder_pool = max(0, remainder_pool)
        if (
            pinned_day is not None
            and pinned_value is not None
            and 0 <= int(pinned_day) <= 6
            and int(pinned_day) in active_days
        ):
            pinned_day = int(pinned_day)
            min_value = day_values.get(pinned_day, 0)
            pinned_cap = capacities.get(pinned_day, min_value)
            pinned_value = max(min_value, min(int(pinned_value), pinned_cap))
            day_values[pinned_day] = pinned_value
            remainder_pool = available_for_active - sum(day_values.values())
            remainder_pool = max(0, remainder_pool)
            candidate_days = [idx for idx in ordered_active_days if idx != pinned_day]

        if remainder_pool > 0 and candidate_days:
            while remainder_pool > 0:
                changed = False
                for day_index in candidate_days:
                    if remainder_pool <= 0:
                        break
                    if day_values.get(day_index, 0) >= capacities.get(day_index, 0):
                        continue
                    day_values[day_index] = day_values.get(day_index, 0) + 1
                    remainder_pool -= 1
                    changed = True
                if not changed:
                    break

        for day_idx in ordered_active_days:
            new_plan[day_idx] = max(0, int(day_values.get(day_idx, 0)))
        planned_storage[task_id] = new_plan
        self._reconcile_planner_week(week_key)

        if remainder_pool > 0:
            self.statusBar().showMessage(
                "Не удалось распределить весь недельный план из-за дневного лимита.",
                3600,
            )

        if self._planning_selected_task_id == task_id:
            if self._planning_selected_day_index is None:
                self._planning_selected_day_index = ordered_active_days[0]
            elif self._planning_selected_day_index in excluded_days:
                self._planning_selected_day_index = ordered_active_days[0]

    def _distribution_order_for_week(self, day_indexes: list[int]) -> list[int]:
        ordered = sorted({int(day) for day in day_indexes if 0 <= int(day) <= 6})
        if not ordered:
            return []
        current_week_start = self._today - timedelta(days=self._today.weekday())
        if self._planning_week_start != current_week_start:
            return ordered

        today_idx = self._today.weekday()
        future_or_today = [day for day in ordered if day >= today_idx]
        past = [day for day in ordered if day < today_idx]
        return future_or_today + past

    def _auto_pick_day_for_task(self, task_id: str) -> int | None:
        excluded = self._excluded_cells_for_current_week().get(task_id, set())
        active_days = [idx for idx in range(7) if idx not in excluded]
        if not active_days:
            return None

        ordered = self._distribution_order_for_week(active_days)
        planned_values = self._week_task_values(self._planned_cells_for_current_week(), task_id)
        done_values = self._week_task_values(self._done_cells_for_current_week(), task_id)

        for day_index in ordered:
            if planned_values[day_index] > done_values[day_index]:
                return day_index
        return ordered[0]

    def _delete_planning_task_by_id(self, task_id: str) -> None:
        idx = next((i for i, task in enumerate(self._planning_tasks) if task["id"] == task_id), -1)
        if idx < 0:
            return
        removed_name = str(self._planning_tasks[idx].get("name", "Задача"))
        self._planning_tasks.pop(idx)

        for week_map in self._planning_excluded_cells_by_week.values():
            week_map.pop(task_id, None)
        for week_map in self._planning_planned_cells_by_week.values():
            week_map.pop(task_id, None)
        for week_map in self._planning_done_cells_by_week.values():
            week_map.pop(task_id, None)
        for week_map in self._planning_weekly_targets_by_week.values():
            week_map.pop(task_id, None)
        self._planner_controller.remove_task(task_id)
        self._planning_selected_unit_by_week.clear()

        if self._planning_selected_task_id == task_id:
            self._planning_selected_task_id = None
            self._planning_selected_day_index = None
            self._planning_pending_switch_key = None

        self._save_planning_state()
        self.statusBar().showMessage(f"Задача «{removed_name}» удалена.", 2200)
        self._rebuild_planning_table()
        self._on_state_changed(self._controller.state.snapshot())

    def _on_planning_cell_clicked(self, row: int, column: int) -> None:
        tasks_count = len(self._planning_tasks)
        if row == tasks_count:
            self.statusBar().showMessage("Лимиты на день/неделю находятся в разделе «Настройки -> Планирование».", 2800)
            return

        if not (0 <= row < tasks_count):
            return
        task = self._planning_tasks[row]
        task_id = str(task.get("id", ""))
        if not task_id:
            return
        previous_task_id = self._planning_selected_task_id
        if previous_task_id != task_id:
            self._planning_selected_day_index = None
            self._planning_selected_unit_by_week.pop(self._planning_week_key(), None)
            self._planning_pending_switch_key = None
        self._planning_selected_task_id = task_id

        if (
            self._planning_selected_day_index is None
            or self._planning_selected_day_index in self._excluded_cells_for_current_week().get(task_id, set())
        ):
            auto_day = self._auto_pick_day_for_task(task_id)
            self._planning_selected_day_index = auto_day

        if self._planning_delete_mode:
            if column == 0:
                self._delete_planning_task_by_id(task_id)
                return
            self.statusBar().showMessage("В режиме удаления кликните по названию задачи в первом столбце.", 2400)
            self._refresh_planning_column_visuals()
            return

        if self._planning_exclude_mode:
            if 1 <= column <= 7:
                self._toggle_task_day_exclusion(task_id, column - 1)
                self._save_planning_state()
                self._update_planning_week_labels()
                self._on_state_changed(self._controller.state.snapshot())
                return
            self.statusBar().showMessage("В режиме исключения кликните по дню (Пн-Вс).", 2200)
            self._refresh_planning_column_visuals()
            return

        if column == 8:
            planned_values = self._week_task_values(self._planned_cells_for_current_week(), task_id)
            current_total = sum(planned_values)
            total = self._prompt_weekly_total(str(task.get("name", "Задача")), current_total)
            if total is None:
                return
            self._distribute_weekly_total_for_task(task_id, total)
            self._planning_pending_switch_key = None
            self.statusBar().showMessage("План на неделю распределен по активным дням.", 2600)
        elif 1 <= column <= 7:
            day_index = column - 1
            excluded = self._excluded_cells_for_current_week().get(task_id, set())
            if day_index in excluded:
                self.statusBar().showMessage("Этот день исключен для выбранной задачи.", 2200)
                self._planning_pending_switch_key = None
            else:
                is_same_day = (
                    self._planning_selected_task_id == task_id
                    and self._planning_selected_day_index == day_index
                )
                if is_same_day:
                    current_value = self._week_task_values(self._planned_cells_for_current_week(), task_id)[day_index]
                    custom_value = self._prompt_day_plan(
                        str(task.get("name", "Задача")),
                        day_index,
                        current_value,
                    )
                    if custom_value is not None:
                        self._set_task_day_plan(task_id, day_index, custom_value)
                        self.statusBar().showMessage("План для дня обновлен.", 2200)
                    self._planning_pending_switch_key = None
                else:
                    self._planning_selected_day_index = day_index
                    self._planning_selected_unit_by_week.pop(self._planning_week_key(), None)
                    self.statusBar().showMessage("День выбран. Повторный клик по этой же ячейке — изменить план.", 2300)
                    self._planning_pending_switch_key = None
        else:
            description = str(task.get("description", "")).strip()
            if description:
                self.statusBar().showMessage(f"Выбрано: {task.get('name', 'Задача')}. {description}", 2600)
            else:
                self.statusBar().showMessage("Задача выбрана для Pomodoro.", 2000)
            self._maybe_switch_to_timer_on_selection(task_id, self._planning_selected_day_index)

        self._save_planning_state()
        self._update_planning_week_labels()
        self._on_state_changed(self._controller.state.snapshot())

    def _on_add_planning_task(self) -> None:
        task_data = self._prompt_planning_task_data()
        if task_data is None:
            return
        title, description = task_data
        title = self._repair_task_name(title)
        if not title:
            return
        task_id = uuid4().hex
        self._planning_tasks.append({"id": task_id, "name": title, "description": description})
        self._planning_selected_task_id = task_id
        self._planning_selected_day_index = self._today.weekday()
        self._planning_pending_switch_key = None
        self._planning_selected_unit_by_week.pop(self._planning_week_key(), None)
        self._reconcile_planner_week(self._planning_week_key())
        self._save_planning_state()
        self._rebuild_planning_table()
        self._on_state_changed(self._controller.state.snapshot())

    def _prompt_planning_task_data(
        self,
        *,
        initial_name: str = "",
        initial_description: str = "",
        is_edit: bool = False,
    ) -> tuple[str, str] | None:
        dialog = QDialog(self)
        dialog.setObjectName("planningTaskDialog")
        dialog.setWindowTitle("Редактировать задачу" if is_edit else "Добавить задачу")
        dialog.setMinimumWidth(460)

        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(10)

        caption = QLabel("Название задачи", dialog)
        caption.setObjectName("planningTaskLabel")
        name_edit = QLineEdit(dialog)
        name_edit.setObjectName("planningTaskInput")
        name_edit.setPlaceholderText("Например: Английский")
        name_edit.setText(initial_name)

        description_caption = QLabel("Короткое описание (опционально)", dialog)
        description_caption.setObjectName("planningTaskLabel")
        description_edit = QLineEdit(dialog)
        description_edit.setObjectName("planningTaskInput")
        description_edit.setPlaceholderText("Например: Грамматика + разговорная практика")
        description_edit.setText(initial_description)
        description_edit.setMaxLength(180)

        if initial_name:
            name_edit.selectAll()
        name_edit.setFocus()

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel, dialog)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)

        layout.addWidget(caption)
        layout.addWidget(name_edit)
        layout.addWidget(description_caption)
        layout.addWidget(description_edit)
        layout.addWidget(buttons)

        if dialog.exec() != QDialog.Accepted:
            return None

        title = self._repair_task_name(name_edit.text().strip())
        if not title:
            return None
        description = str(description_edit.text() or "").strip()
        return title, description

    def _edit_planning_task(self, task_id: str) -> None:
        index = next((i for i, task in enumerate(self._planning_tasks) if task["id"] == task_id), -1)
        if index < 0:
            return

        task = self._planning_tasks[index]
        task_data = self._prompt_planning_task_data(
            initial_name=str(task.get("name", "")),
            initial_description=str(task.get("description", "")),
            is_edit=True,
        )
        if task_data is None:
            return

        title, description = task_data
        self._planning_tasks[index]["name"] = self._repair_task_name(title)
        self._planning_tasks[index]["description"] = description
        self._save_planning_state()
        self._rebuild_planning_table()
        self.statusBar().showMessage("Задача обновлена.", 2200)

    def _rebuild_planning_table(self) -> None:
        if not hasattr(self, "_planning_table"):
            return
        self._planning_table.blockSignals(True)
        try:
            tasks_rows = len(self._planning_tasks)
            rows = tasks_rows + 1
            self._planning_table.setRowCount(rows)
            for row, task in enumerate(self._planning_tasks):
                self._planning_table.setRowHeight(row, max(40, min(84, self._settings.planning_row_height)))
                self._planning_table.setCellWidget(row, 0, None)
                task_name = str(task.get("name", "Задача"))
                task_description = str(task.get("description", "")).strip()
                task_item = QTableWidgetItem(task_name)
                task_item.setTextAlignment(Qt.AlignVCenter | Qt.AlignLeft)
                task_item.setData(Qt.UserRole, task["id"])
                task_item.setData(Qt.UserRole + 5, task_description)
                task_item.setToolTip(
                    f"{task_name}\n{task_description}" if task_description else task_name
                )
                self._planning_table.setItem(row, 0, task_item)
                for col in range(1, 9):
                    item = QTableWidgetItem("")
                    item.setTextAlignment(Qt.AlignCenter)
                    self._planning_table.setItem(row, col, item)

            limit_row = tasks_rows
            self._planning_table.setRowHeight(limit_row, max(36, min(72, self._settings.planning_row_height - 6)))
            limit_item = QTableWidgetItem("Лимит дня")
            limit_item.setTextAlignment(Qt.AlignVCenter | Qt.AlignLeft)
            limit_item.setData(Qt.UserRole, self._PLANNING_DAILY_LIMIT_ROW_ID)
            limit_item.setToolTip("Сервисная строка: суммарная дневная нагрузка по всем задачам.")
            self._planning_table.setItem(limit_row, 0, limit_item)
            for col in range(1, 9):
                item = QTableWidgetItem("")
                item.setTextAlignment(Qt.AlignCenter)
                self._planning_table.setItem(limit_row, col, item)
        finally:
            self._planning_table.blockSignals(False)

        self._refresh_planning_column_visuals()
        self._refresh_tasks_page()

    def _delete_selected_planning_task(self) -> None:
        task_id = self._planning_selected_task_id
        if not task_id:
            self.statusBar().showMessage("Сначала выберите задачу (ячейку в столбце «Задача»).", 2500)
            return
        self._delete_planning_task_by_id(task_id)

    @staticmethod
    def _color_with_alpha(color: QColor, alpha: int) -> QColor:
        mixed = QColor(color)
        mixed.setAlpha(max(0, min(255, int(alpha))))
        return mixed

    @staticmethod
    def _blend_colors(first: QColor, second: QColor, ratio: float) -> QColor:
        ratio = max(0.0, min(1.0, float(ratio)))
        inv = 1.0 - ratio
        return QColor(
            int(first.red() * inv + second.red() * ratio),
            int(first.green() * inv + second.green() * ratio),
            int(first.blue() * inv + second.blue() * ratio),
            255,
        )

    def _planning_theme_colors(self) -> tuple[QColor, QColor, QColor, QColor]:
        theme = self._settings.theme_name
        if theme == "forest":
            accent = QColor(142, 216, 168)
            accent_soft = QColor(205, 241, 218)
            danger = QColor(227, 121, 128)
            text = QColor(236, 249, 241)
            return accent, accent_soft, danger, text
        if theme == "rose":
            accent = QColor(255, 111, 117)
            accent_soft = QColor(255, 212, 215)
            danger = QColor(255, 96, 104)
            text = QColor(255, 242, 242)
            return accent, accent_soft, danger, text
        if theme == "sunset":
            accent = QColor(255, 194, 129)
            accent_soft = QColor(255, 230, 198)
            danger = QColor(233, 127, 138)
            text = QColor(255, 244, 236)
            return accent, accent_soft, danger, text
        if theme == "graphite":
            accent = QColor(136, 190, 234)
            accent_soft = QColor(205, 227, 247)
            danger = QColor(224, 122, 131)
            text = QColor(236, 243, 250)
            return accent, accent_soft, danger, text
        accent = QColor(108, 194, 234)
        accent_soft = QColor(202, 233, 250)
        danger = QColor(228, 116, 126)
        text = QColor(234, 245, 255)
        return accent, accent_soft, danger, text

    def _refresh_planning_column_visuals(self) -> None:
        if not hasattr(self, "_planning_table"):
            return
        week_excluded = self._excluded_cells_for_current_week()
        week_planned = self._planned_cells_for_current_week()
        week_done = self._done_cells_for_current_week()
        current_week_start = self._today - timedelta(days=self._today.weekday())
        today_day_index = self._today.weekday() if self._planning_week_start == current_week_start else None
        base_font_size = max(11, min(19, self._settings.planning_table_font_size))
        normal_size = max(10, base_font_size - 2)
        selected_size = max(10, base_font_size - 1)
        cross_size = min(22, base_font_size + 3)
        cell_style = self._settings.planning_cell_style
        today_boost = max(30, min(100, self._settings.planning_today_highlight_percent))
        accent, accent_soft, danger, text_main = self._planning_theme_colors()
        bright = self._blend_colors(accent, accent_soft, 0.42)

        if cell_style == "contrast":
            task_selected_bg = self._color_with_alpha(self._blend_colors(accent, danger, 0.18), 204)
            task_default_bg = QColor(0, 0, 0, 34)
            excluded_bg = self._color_with_alpha(danger, 186)
            excluded_today_bg = self._color_with_alpha(self._blend_colors(danger, accent, 0.2), 205)
            selected_day_bg = self._color_with_alpha(bright, 198)
            today_bg = self._color_with_alpha(accent, min(200, 96 + int(today_boost * 0.9)))
            today_selected_bg = self._color_with_alpha(bright, min(220, 108 + int(today_boost * 0.95)))
            regular_selected_bg = self._color_with_alpha(self._blend_colors(accent, danger, 0.2), 132)
            regular_bg = QColor(0, 0, 0, 28)
            total_selected_bg = self._color_with_alpha(accent, 146)
            total_bg = QColor(0, 0, 0, 30)
        elif cell_style == "minimal":
            task_selected_bg = self._color_with_alpha(accent, 146)
            task_default_bg = QColor(0, 0, 0, 18)
            excluded_bg = self._color_with_alpha(danger, 146)
            excluded_today_bg = self._color_with_alpha(self._blend_colors(danger, accent, 0.18), 160)
            selected_day_bg = self._color_with_alpha(bright, 154)
            today_bg = self._color_with_alpha(accent, min(178, 72 + int(today_boost * 0.8)))
            today_selected_bg = self._color_with_alpha(bright, min(196, 84 + int(today_boost * 0.85)))
            regular_selected_bg = self._color_with_alpha(accent, 96)
            regular_bg = QColor(0, 0, 0, 16)
            total_selected_bg = self._color_with_alpha(accent, 108)
            total_bg = QColor(0, 0, 0, 20)
        else:
            task_selected_bg = self._color_with_alpha(accent, 172)
            task_default_bg = QColor(0, 0, 0, 24)
            excluded_bg = self._color_with_alpha(danger, 168)
            excluded_today_bg = self._color_with_alpha(self._blend_colors(danger, accent, 0.2), 184)
            selected_day_bg = self._color_with_alpha(bright, 176)
            today_bg = self._color_with_alpha(accent, min(190, 82 + int(today_boost * 0.85)))
            today_selected_bg = self._color_with_alpha(bright, min(208, 94 + int(today_boost * 0.9)))
            regular_selected_bg = self._color_with_alpha(accent, 118)
            regular_bg = QColor(0, 0, 0, 22)
            total_selected_bg = self._color_with_alpha(accent, 126)
            total_bg = QColor(0, 0, 0, 26)

        for row in range(self._planning_table.rowCount()):
            task_item = self._planning_table.item(row, 0)
            task_id = ""
            is_selected = False
            if task_item is not None:
                task_id = str(task_item.data(Qt.UserRole) or "")
                is_selected = task_id == self._planning_selected_task_id
                task_item.setForeground(self._color_with_alpha(text_main, 246))
                task_item.setBackground(task_selected_bg if is_selected else task_default_bg)
                task_font = task_item.font()
                task_font.setPointSize(selected_size if is_selected else normal_size)
                task_font.setBold(is_selected)
                task_item.setFont(task_font)

            if task_id == self._PLANNING_DAILY_LIMIT_ROW_ID:
                limit_value = max(1, int(self._settings.planning_daily_limit))
                weekly_limit_value = max(1, int(self._settings.planning_weekly_limit))
                if task_item is not None:
                    task_item.setBackground(self._color_with_alpha(accent, 126))
                    task_item.setForeground(self._color_with_alpha(text_main, 252))
                    limit_font = task_item.font()
                    limit_font.setBold(True)
                    limit_font.setPointSize(normal_size)
                    task_item.setFont(limit_font)

                day_totals: list[int] = []
                for day_idx in range(7):
                    day_used = self._day_planned_total(day_idx)
                    day_totals.append(day_used)
                    cell = self._planning_table.item(row, day_idx + 1)
                    if cell is None:
                        continue

                    over_limit = day_used > limit_value
                    if self._settings.planning_progress_view == "visual":
                        symbol_text, icon = self._planning_progress_repr(min(day_used, limit_value), limit_value)
                        text = f"{symbol_text} {day_used}/{limit_value}".strip()
                    else:
                        icon = self._tomato_icon if not self._tomato_icon.isNull() else QIcon()
                        text = f"{day_used}/{limit_value}"

                    if over_limit:
                        cell.setBackground(self._color_with_alpha(danger, 142))
                        cell.setForeground(self._color_with_alpha(text_main, 252))
                    else:
                        cell.setBackground(self._color_with_alpha(accent, 92))
                        cell.setForeground(self._color_with_alpha(text_main, 236))
                    cell.setIcon(icon)
                    cell.setText(text)
                    cell_font = cell.font()
                    cell_font.setBold(over_limit)
                    cell_font.setPointSize(normal_size)
                    cell.setFont(cell_font)

                total_item = self._planning_table.item(row, 8)
                if total_item is not None:
                    week_used = sum(day_totals)
                    week_limit = weekly_limit_value
                    if self._settings.planning_progress_view == "visual":
                        symbol_text, icon = self._planning_progress_repr(min(week_used, week_limit), week_limit)
                        text = f"{symbol_text} {week_used}/{week_limit}".strip()
                    else:
                        icon = self._tomato_icon if not self._tomato_icon.isNull() else QIcon()
                        text = f"{week_used}/{week_limit}"
                    total_item.setText(text)
                    total_item.setIcon(icon)
                    total_item.setBackground(self._color_with_alpha(accent, 108))
                    total_item.setForeground(self._color_with_alpha(text_main, 242))
                    total_font = total_item.font()
                    total_font.setBold(week_used > week_limit)
                    total_font.setPointSize(normal_size)
                    total_item.setFont(total_font)
                continue

            planned_values = self._week_task_values(week_planned, task_id) if task_id else [0] * 7
            done_values = self._week_task_values(week_done, task_id) if task_id else [0] * 7
            for day_idx in range(7):
                col = day_idx + 1
                item = self._planning_table.item(row, col)
                if item is None:
                    continue
                is_today_column = today_day_index is not None and day_idx == today_day_index
                is_selected_day = (
                    is_selected
                    and self._planning_selected_day_index is not None
                    and self._planning_selected_day_index == day_idx
                    and not self._planning_delete_mode
                )
                task_excluded_days = week_excluded.get(task_id, set())
                if day_idx in task_excluded_days:
                    item.setBackground(excluded_today_bg if is_today_column else excluded_bg)
                    item.setForeground(self._color_with_alpha(text_main, 244))
                    cross_font = item.font()
                    cross_font.setBold(True)
                    cross_font.setPointSize(cross_size)
                    item.setFont(cross_font)
                    item.setText("✕")
                    item.setIcon(QIcon())
                elif is_selected_day:
                    item.setBackground(selected_day_bg)
                    item.setForeground(self._color_with_alpha(text_main, 252))
                    strong_font = item.font()
                    strong_font.setBold(True)
                    strong_font.setPointSize(selected_size)
                    item.setFont(strong_font)
                    planned = planned_values[day_idx]
                    done = min(done_values[day_idx], planned)
                    text, icon = self._planning_progress_repr(done, planned)
                    item.setIcon(icon)
                    item.setText(text)
                elif is_today_column:
                    item.setBackground(today_selected_bg if is_selected else today_bg)
                    item.setForeground(self._color_with_alpha(text_main, 252))
                    normal_font = item.font()
                    normal_font.setBold(is_selected and self._planning_selected_day_index == day_idx)
                    normal_font.setPointSize(selected_size if is_selected else normal_size)
                    item.setFont(normal_font)
                    planned = planned_values[day_idx]
                    done = min(done_values[day_idx], planned)
                    text, icon = self._planning_progress_repr(done, planned)
                    item.setIcon(icon)
                    item.setText(text)
                else:
                    item.setBackground(regular_selected_bg if is_selected else regular_bg)
                    item.setForeground(self._color_with_alpha(text_main, 232))
                    normal_font = item.font()
                    normal_font.setBold(False)
                    normal_font.setPointSize(selected_size if is_selected else normal_size)
                    item.setFont(normal_font)
                    planned = planned_values[day_idx]
                    done = min(done_values[day_idx], planned)
                    text, icon = self._planning_progress_repr(done, planned)
                    item.setIcon(icon)
                    item.setText(text)

            total_item = self._planning_table.item(row, 8)
            if total_item is not None:
                total_planned = sum(planned_values)
                total_done = sum(min(done_values[idx], planned_values[idx]) for idx in range(7))
                total_target = max(total_planned, total_done)
                total_text, total_icon = self._planning_progress_repr(total_done, total_target)
                total_item.setText(total_text if total_text else "0")
                total_item.setIcon(total_icon)
                total_item.setForeground(self._color_with_alpha(text_main, 244))
                total_item.setBackground(total_selected_bg if is_selected else total_bg)
                total_font = total_item.font()
                total_font.setBold(is_selected)
                total_font.setPointSize(normal_size)
                total_item.setFont(total_font)

    def _update_planning_week_labels(self) -> None:
        if not hasattr(self, "_week_header"):
            return
        week_end = self._planning_week_start + timedelta(days=6)
        is_current_week = self._planning_week_start == (self._today - timedelta(days=self._today.weekday()))
        self._week_header.set_week_range(self._planning_week_start, week_end, is_current_week=is_current_week)
        headers = ["Задача"]
        day_short = self._day_names_short
        current_week_start = self._today - timedelta(days=self._today.weekday())
        today_index = self._today.weekday() if self._planning_week_start == current_week_start else None
        header_size = max(11, min(16, self._settings.planning_table_font_size - 1))
        today_strength = max(30, min(100, self._settings.planning_today_highlight_percent))
        accent, accent_soft, danger, text_main = self._planning_theme_colors()
        today_header_alpha = min(225, 84 + int(today_strength * 1.05))
        task_header_bg = self._color_with_alpha(self._blend_colors(accent, danger, 0.24), 172)
        day_header_bg = self._color_with_alpha(accent, 146)
        total_header_bg = self._color_with_alpha(self._blend_colors(accent, danger, 0.2), 164)
        today_header_bg = self._color_with_alpha(self._blend_colors(accent, accent_soft, 0.55), today_header_alpha)
        for idx, day_name in enumerate(day_short):
            d = self._planning_week_start + timedelta(days=idx)
            headers.append(f"{day_name} ({d.strftime('%d.%m')})")
        headers.append("Всего")

        for col, label in enumerate(headers):
            header_item = self._planning_table.horizontalHeaderItem(col)
            if header_item is None:
                header_item = QTableWidgetItem()
                self._planning_table.setHorizontalHeaderItem(col, header_item)
            header_item.setText(label)
            header_item.setTextAlignment(Qt.AlignCenter)

            font = header_item.font()
            if col == 0:
                header_item.setBackground(task_header_bg)
                header_item.setForeground(self._color_with_alpha(text_main, 248))
                font.setBold(True)
                font.setPointSize(header_size)
            elif col == 8:
                header_item.setBackground(total_header_bg)
                header_item.setForeground(self._color_with_alpha(text_main, 248))
                font.setBold(True)
                font.setPointSize(header_size)
            elif today_index is not None and col == today_index + 1:
                header_item.setBackground(today_header_bg)
                header_item.setForeground(self._color_with_alpha(text_main, 252))
                font.setBold(True)
                font.setPointSize(header_size)
            else:
                header_item.setBackground(day_header_bg)
                header_item.setForeground(self._color_with_alpha(text_main, 238))
                font.setBold(False)
                font.setPointSize(header_size)
            header_item.setFont(font)

        self._planning_table.set_highlighted_column(today_index + 1 if today_index is not None else None)
        self._refresh_planning_column_visuals()
        self._refresh_tasks_page()

    def _load_planning_state(self) -> None:
        raw = self._planning_store.load()
        tasks_raw = raw.get("tasks", [])
        excluded_raw = raw.get("excluded_cells", {})
        planned_raw = raw.get("planned_cells", {})
        done_raw = raw.get("done_cells", {})
        weekly_targets_raw = raw.get("weekly_targets", {})
        task_units_raw = raw.get("task_units_by_week", {})
        selected_unit_by_week_raw = raw.get("selected_unit_by_week", {})
        selected_task_id = raw.get("selected_task_id")
        selected_day_index = raw.get("selected_day_index")

        loaded_tasks: list[dict[str, str]] = []
        if isinstance(tasks_raw, list):
            for item in tasks_raw:
                if isinstance(item, dict):
                    task_id = str(item.get("id") or uuid4().hex)
                    task_name = self._repair_task_name(str(item.get("name") or "").strip())
                    task_description = str(item.get("description") or "").strip()
                    if task_name:
                        loaded_tasks.append(
                            {"id": task_id, "name": task_name, "description": task_description}
                        )
                elif isinstance(item, str):
                    name = self._repair_task_name(item.strip())
                    if name:
                        loaded_tasks.append({"id": uuid4().hex, "name": name, "description": ""})
        self._planning_tasks = loaded_tasks

        normalized_excluded: dict[str, dict[str, set[int]]] = {}
        if isinstance(excluded_raw, dict):
            for week_key, week_map in excluded_raw.items():
                if not isinstance(week_map, dict):
                    continue
                week_out: dict[str, set[int]] = {}
                for task_id, day_list in week_map.items():
                    if not isinstance(day_list, list):
                        continue
                    day_set = {int(v) for v in day_list if isinstance(v, int) and 0 <= int(v) <= 6}
                    if day_set:
                        week_out[str(task_id)] = day_set
                if week_out:
                    normalized_excluded[str(week_key)] = week_out
        self._planning_excluded_cells_by_week = normalized_excluded

        def _normalize_week_values(raw_map: object) -> dict[str, dict[str, list[int]]]:
            out: dict[str, dict[str, list[int]]] = {}
            if not isinstance(raw_map, dict):
                return out
            for week_key, week_values in raw_map.items():
                if not isinstance(week_values, dict):
                    continue
                task_out: dict[str, list[int]] = {}
                for task_id, day_values in week_values.items():
                    if not isinstance(day_values, list):
                        continue
                    normalized_days = [0] * 7
                    for idx, value in enumerate(day_values[:7]):
                        try:
                            normalized_days[idx] = max(0, int(value))
                        except (TypeError, ValueError):
                            normalized_days[idx] = 0
                    task_out[str(task_id)] = normalized_days
                if task_out:
                    out[str(week_key)] = task_out
            return out

        self._planning_planned_cells_by_week = _normalize_week_values(planned_raw)
        legacy_done_cells_by_week = _normalize_week_values(done_raw)
        # done_cells is derived from task_units. Keep legacy done only for one-time bootstrap.
        self._planning_done_cells_by_week = {}
        normalized_weekly_targets: dict[str, dict[str, int]] = {}
        if isinstance(weekly_targets_raw, dict):
            for week_key, week_values in weekly_targets_raw.items():
                if not isinstance(week_values, dict):
                    continue
                task_targets: dict[str, int] = {}
                for task_id, value in week_values.items():
                    try:
                        parsed = max(0, int(value))
                    except (TypeError, ValueError):
                        parsed = 0
                    if parsed > 0:
                        task_targets[str(task_id)] = parsed
                if task_targets:
                    normalized_weekly_targets[str(week_key)] = task_targets
        self._planning_weekly_targets_by_week = normalized_weekly_targets

        self._planner_controller.load_task_units_by_week(task_units_raw)

        normalized_selected_units: dict[str, str] = {}
        if isinstance(selected_unit_by_week_raw, dict):
            for week_key, unit_id in selected_unit_by_week_raw.items():
                week = str(week_key).strip()
                uid = str(unit_id).strip() if isinstance(unit_id, str) else ""
                if week and uid:
                    normalized_selected_units[week] = uid
        self._planning_selected_unit_by_week = normalized_selected_units

        task_ids = {task["id"] for task in self._planning_tasks}
        self._planner_controller.bootstrap_from_legacy(
            task_ids=task_ids,
            planned_by_week=self._planning_planned_cells_by_week,
            done_by_week=legacy_done_cells_by_week,
        )
        self._reconcile_planner_all_weeks()

        self._planning_selected_task_id = (
            selected_task_id if isinstance(selected_task_id, str) and selected_task_id in task_ids else None
        )
        self._planning_selected_day_index = (
            int(selected_day_index)
            if isinstance(selected_day_index, int) and 0 <= int(selected_day_index) <= 6
            else None
        )

        for week_key in list(self._planning_selected_unit_by_week.keys()):
            unit_id = self._planning_selected_unit_by_week.get(week_key, "")
            if (
                week_key not in self._planner_controller.week_keys()
                or not self._planner_controller.has_unit(week_start_iso=week_key, unit_id=unit_id)
            ):
                self._planning_selected_unit_by_week.pop(week_key, None)
        # Persist normalized names/data with debounce to avoid extra startup blocking.
        self._save_planning_state()

    def _save_planning_state(self, *, immediate: bool = False) -> None:
        if immediate:
            self._planning_save_timer.stop()
            self._persist_planning_state()
            return

        self._planning_save_pending = True
        self._planning_save_timer.start()

    def _persist_planning_state(self) -> None:
        self._planning_save_pending = False
        self._reconcile_planner_all_weeks()

        excluded_serialized: dict[str, dict[str, list[int]]] = {}
        for week_key, week_map in self._planning_excluded_cells_by_week.items():
            if not week_map:
                continue
            excluded_serialized[week_key] = {
                task_id: sorted(list(days))
                for task_id, days in week_map.items()
                if days
            }

        def _serialize_week_values(source: dict[str, dict[str, list[int]]]) -> dict[str, dict[str, list[int]]]:
            out: dict[str, dict[str, list[int]]] = {}
            for week_key, week_map in source.items():
                week_out: dict[str, list[int]] = {}
                for task_id, day_values in week_map.items():
                    if not isinstance(day_values, list):
                        continue
                    normalized_days = [max(0, int(v)) for v in day_values[:7]]
                    if len(normalized_days) < 7:
                        normalized_days.extend([0] * (7 - len(normalized_days)))
                    if any(v > 0 for v in normalized_days):
                        week_out[task_id] = normalized_days
                if week_out:
                    out[week_key] = week_out
            return out

        weekly_targets_serialized: dict[str, dict[str, int]] = {}
        for week_key, week_values in self._planning_weekly_targets_by_week.items():
            if not isinstance(week_values, dict):
                continue
            task_targets: dict[str, int] = {}
            for task_id, value in week_values.items():
                try:
                    parsed = max(0, int(value))
                except (TypeError, ValueError):
                    parsed = 0
                if parsed > 0:
                    task_targets[task_id] = parsed
            if task_targets:
                weekly_targets_serialized[week_key] = task_targets

        self._planning_store.save(
            {
                "tasks": self._planning_tasks,
                "excluded_cells": excluded_serialized,
                "planned_cells": _serialize_week_values(self._planning_planned_cells_by_week),
                "done_cells": _serialize_week_values(self._planning_done_cells_by_week),
                "weekly_targets": weekly_targets_serialized,
                "task_units_by_week": self._planner_controller.dump_task_units_by_week(),
                "selected_unit_by_week": {
                    week_key: unit_id
                    for week_key, unit_id in self._planning_selected_unit_by_week.items()
                    if (
                        isinstance(week_key, str)
                        and isinstance(unit_id, str)
                        and week_key
                        and unit_id
                        and self._planner_controller.has_unit(week_start_iso=week_key, unit_id=unit_id)
                    )
                },
                "selected_task_id": self._planning_selected_task_id,
                "selected_day_index": self._planning_selected_day_index,
            }
        )

    def _build_settings_page(self) -> QWidget:
        page = QWidget(self)
        layout = QVBoxLayout(page)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(0)

        scroll = QScrollArea(page)
        scroll.setObjectName("settingsScrollArea")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)

        scroll_content = QWidget(scroll)
        scroll_content_layout = QVBoxLayout(scroll_content)
        scroll_content_layout.setContentsMargins(0, 0, 0, 0)
        scroll_content_layout.setSpacing(0)

        card = QFrame(scroll_content)
        card.setObjectName("settingsPageCard")
        card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(28, 24, 28, 24)
        card_layout.setSpacing(18)

        title_row = QHBoxLayout()
        title_row.setContentsMargins(0, 0, 0, 0)
        title_row.setSpacing(8)

        icon_label = QLabel(card)
        icon_label.setObjectName("settingsPageIcon")
        icon_label.setFixedSize(24, 24)
        icon_pixmap = self._load_svg("settings_badge.svg")
        if not icon_pixmap.isNull():
            icon_label.setPixmap(icon_pixmap.scaled(22, 22, Qt.KeepAspectRatio, Qt.SmoothTransformation))

        title = QLabel("Настройки", card)
        title.setObjectName("settingsPageTitle")

        title_row.addWidget(icon_label)
        title_row.addWidget(title)
        title_row.addStretch(1)

        hint = QLabel(
            "Изменения применяются сразу для предпросмотра. "
            "Кнопка «Сохранить настройки» фиксирует их в файле settings.json.",
            card,
        )
        hint.setObjectName("settingsPageHint")
        hint.setWordWrap(True)

        general_box = QFrame(card)
        general_box.setObjectName("settingsFormBox")
        general_layout = QFormLayout(general_box)
        general_layout.setContentsMargins(16, 14, 16, 14)
        general_layout.setHorizontalSpacing(24)
        general_layout.setVerticalSpacing(14)

        general_title = QLabel("Общие", general_box)
        general_title.setObjectName("settingsSectionTitle")
        general_layout.addRow(general_title)

        self._settings_theme_name = NoWheelComboBox(general_box)
        self._settings_theme_name.addItem("Глубокий океан", "ocean")
        self._settings_theme_name.addItem("Мягкая роза", "rose")
        self._settings_theme_name.addItem("Лесной баланс", "forest")
        self._settings_theme_name.addItem("Теплый закат", "sunset")
        self._settings_theme_name.addItem("Графит", "graphite")

        self._settings_ui_scale_percent = NoWheelSpinBox(general_box)
        self._settings_ui_scale_percent.setRange(85, 130)
        self._settings_ui_scale_percent.setSuffix(" %")

        self._settings_launch_maximized = QCheckBox("Открывать приложение развернутым", general_box)
        self._settings_show_sidebar_icons = QCheckBox("Показывать SVG-иконки в боковом меню", general_box)

        general_layout.addRow("Тема интерфейса", self._settings_theme_name)
        general_layout.addRow("Масштаб интерфейса", self._settings_ui_scale_percent)
        general_layout.addRow("", self._settings_launch_maximized)
        general_layout.addRow("", self._settings_show_sidebar_icons)

        updates_box = QFrame(card)
        updates_box.setObjectName("settingsFormBox")
        updates_layout = QFormLayout(updates_box)
        updates_layout.setContentsMargins(16, 14, 16, 14)
        updates_layout.setHorizontalSpacing(24)
        updates_layout.setVerticalSpacing(14)

        updates_title = QLabel("Обновления", updates_box)
        updates_title.setObjectName("settingsSectionTitle")
        updates_layout.addRow(updates_title)

        self._settings_app_version_value = QLabel(self._app_version, updates_box)
        self._settings_app_version_value.setObjectName("settingsPageHint")

        self._settings_updates_manifest_url = QLineEdit(updates_box)
        self._settings_updates_manifest_url.setObjectName("planningTaskInput")
        self._settings_updates_manifest_url.setPlaceholderText(
            "https://.../update_manifest.json"
        )
        self._settings_updates_manifest_url.setClearButtonEnabled(True)

        self._settings_auto_check_updates_on_start = QCheckBox(
            "Проверять обновления при запуске (тихо)",
            updates_box,
        )
        self._settings_update_check_interval_hours = NoWheelSpinBox(updates_box)
        self._settings_update_check_interval_hours.setRange(1, 168)
        self._settings_update_check_interval_hours.setSuffix(" ч")

        self._settings_check_updates_button = QPushButton("Проверить обновления", updates_box)
        self._settings_check_updates_button.setObjectName("settingsPreviewButton")
        self._settings_check_updates_button.clicked.connect(self._on_check_updates_clicked)

        self._settings_install_update_button = QPushButton("Скачать и установить", updates_box)
        self._settings_install_update_button.setObjectName("settingsPreviewButton")
        self._settings_install_update_button.setEnabled(False)
        self._settings_install_update_button.clicked.connect(self._on_install_update_clicked)

        self._settings_open_updates_page_button = QPushButton(
            "Открыть страницу «Обновления»",
            updates_box,
        )
        self._settings_open_updates_page_button.setObjectName("settingsPreviewButton")
        self._settings_open_updates_page_button.clicked.connect(
            lambda: self._switch_page(self.PAGE_UPDATES)
        )

        self._settings_update_status = QLabel("Проверка обновлений не выполнялась.", updates_box)
        self._settings_update_status.setObjectName("settingsPageHint")
        self._settings_update_status.setWordWrap(True)

        updates_layout.addRow("Текущая версия", self._settings_app_version_value)
        updates_layout.addRow("URL манифеста", self._settings_updates_manifest_url)
        updates_layout.addRow("", self._settings_auto_check_updates_on_start)
        updates_layout.addRow("Интервал автопроверки", self._settings_update_check_interval_hours)
        updates_layout.addRow("", self._settings_check_updates_button)
        updates_layout.addRow("", self._settings_install_update_button)
        updates_layout.addRow("", self._settings_open_updates_page_button)
        updates_layout.addRow("", self._settings_update_status)

        main_box = QFrame(card)
        main_box.setObjectName("settingsFormBox")
        main_layout = QFormLayout(main_box)
        main_layout.setContentsMargins(16, 14, 16, 14)
        main_layout.setHorizontalSpacing(24)
        main_layout.setVerticalSpacing(14)

        main_title = QLabel("Главная страница", main_box)
        main_title.setObjectName("settingsSectionTitle")
        main_layout.addRow(main_title)

        self._settings_pomodoro = NoWheelSpinBox(main_box)
        self._settings_pomodoro.setRange(1, 180)
        self._settings_pomodoro.setSuffix(" мин")

        self._settings_short_break = NoWheelSpinBox(main_box)
        self._settings_short_break.setRange(1, 90)
        self._settings_short_break.setSuffix(" мин")

        self._settings_long_break = NoWheelSpinBox(main_box)
        self._settings_long_break.setRange(1, 180)
        self._settings_long_break.setSuffix(" мин")

        self._settings_long_break_interval = NoWheelSpinBox(main_box)
        self._settings_long_break_interval.setRange(2, 6)
        self._settings_long_break_interval.setSuffix(" цикла")

        self._settings_main_start_button_height = NoWheelSpinBox(main_box)
        self._settings_main_start_button_height.setRange(38, 64)
        self._settings_main_start_button_height.setSuffix(" px")

        self._settings_main_timer_scale_percent = NoWheelSpinBox(main_box)
        self._settings_main_timer_scale_percent.setRange(65, 118)
        self._settings_main_timer_scale_percent.setSuffix(" %")

        self._settings_main_card_opacity_percent = NoWheelSpinBox(main_box)
        self._settings_main_card_opacity_percent.setRange(72, 100)
        self._settings_main_card_opacity_percent.setSuffix(" %")
        self._settings_main_start_button_height.hide()
        self._settings_main_timer_scale_percent.hide()
        self._settings_main_card_opacity_percent.hide()

        main_layout.addRow("Помодоро", self._settings_pomodoro)
        main_layout.addRow("Короткий перерыв", self._settings_short_break)
        main_layout.addRow("Длинный перерыв", self._settings_long_break)
        main_layout.addRow("Длинный перерыв после", self._settings_long_break_interval)

        planning_box = QFrame(card)
        planning_box.setObjectName("settingsFormBox")
        planning_layout = QFormLayout(planning_box)
        planning_layout.setContentsMargins(16, 14, 16, 14)
        planning_layout.setHorizontalSpacing(24)
        planning_layout.setVerticalSpacing(14)

        planning_title = QLabel("Планирование", planning_box)
        planning_title.setObjectName("settingsSectionTitle")
        planning_layout.addRow(planning_title)

        self._settings_planning_progress_view = NoWheelComboBox(planning_box)
        self._settings_planning_progress_view.addItem("0/3 (дробь)", "fraction")
        self._settings_planning_progress_view.addItem("Визуально (иконки)", "visual")

        self._settings_planning_visual_style = NoWheelComboBox(planning_box)
        self._settings_planning_visual_style.addItem("Кружки", "circle")
        self._settings_planning_visual_style.addItem("Помидоры", "tomato")
        self._settings_planning_visual_style.addItem("Квадраты", "square")
        self._settings_planning_visual_style.addItem("Полоски", "bar")

        self._settings_planning_cell_style = NoWheelComboBox(planning_box)
        self._settings_planning_cell_style.addItem("Мягкий", "soft")
        self._settings_planning_cell_style.addItem("Контрастный", "contrast")
        self._settings_planning_cell_style.addItem("Минималистичный", "minimal")

        self._settings_planning_visual_max_symbols = NoWheelSpinBox(planning_box)
        self._settings_planning_visual_max_symbols.setRange(3, 16)
        self._settings_planning_visual_max_symbols.setSuffix(" шт")

        self._settings_planning_row_height = NoWheelSpinBox(planning_box)
        self._settings_planning_row_height.setRange(40, 84)
        self._settings_planning_row_height.setSuffix(" px")

        self._settings_planning_table_font_size = NoWheelSpinBox(planning_box)
        self._settings_planning_table_font_size.setRange(12, 22)
        self._settings_planning_table_font_size.setSuffix(" px")

        self._settings_planning_today_highlight_percent = NoWheelSpinBox(planning_box)
        self._settings_planning_today_highlight_percent.setRange(30, 100)
        self._settings_planning_today_highlight_percent.setSuffix(" %")

        self._settings_planning_task_column_width = NoWheelSpinBox(planning_box)
        self._settings_planning_task_column_width.setRange(140, 320)
        self._settings_planning_task_column_width.setSuffix(" px")

        self._settings_planning_total_column_width = NoWheelSpinBox(planning_box)
        self._settings_planning_total_column_width.setRange(72, 160)
        self._settings_planning_total_column_width.setSuffix(" px")

        self._settings_planning_daily_limit = NoWheelSpinBox(planning_box)
        self._settings_planning_daily_limit.setRange(1, 64)
        self._settings_planning_daily_limit.setSuffix(" 🍅")

        self._settings_planning_weekly_limit = NoWheelSpinBox(planning_box)
        self._settings_planning_weekly_limit.setRange(1, 448)
        self._settings_planning_weekly_limit.setSuffix(" 🍅")

        self._settings_planning_auto_switch_to_timer = QCheckBox(
            "Автопереход в Pomodoro при выборе задачи",
            planning_box,
        )
        self._settings_planning_confirm_before_switch = QCheckBox(
            "Требовать повторный клик перед переходом в Pomodoro",
            planning_box,
        )
        self._settings_planning_follow_queue = QCheckBox(
            "Следовать очереди из «Задач» (автовыбор)",
            planning_box,
        )
        self._settings_tasks_units_compact_mode = QCheckBox(
            "Раздел «Задачи»: компактный вид Pomodoro-единиц",
            planning_box,
        )
        self._settings_planning_cell_style.hide()
        self._settings_planning_visual_max_symbols.hide()
        self._settings_planning_row_height.hide()
        self._settings_planning_table_font_size.hide()
        self._settings_planning_today_highlight_percent.hide()
        self._settings_planning_task_column_width.hide()
        self._settings_planning_total_column_width.hide()

        self._settings_planning_progress_view.currentIndexChanged.connect(
            self._on_planning_settings_view_mode_changed
        )

        planning_layout.addRow("Формат прогресса", self._settings_planning_progress_view)
        planning_layout.addRow("Тип визуализации", self._settings_planning_visual_style)
        planning_layout.addRow("Лимит помидоров в день", self._settings_planning_daily_limit)
        planning_layout.addRow("Лимит помидоров в неделю", self._settings_planning_weekly_limit)
        planning_layout.addRow("", self._settings_planning_auto_switch_to_timer)
        planning_layout.addRow("", self._settings_planning_confirm_before_switch)
        planning_layout.addRow("", self._settings_planning_follow_queue)
        planning_layout.addRow("", self._settings_tasks_units_compact_mode)

        sound_box = QFrame(card)
        sound_box.setObjectName("settingsFormBox")
        sound_layout = QFormLayout(sound_box)
        sound_layout.setContentsMargins(16, 14, 16, 14)
        sound_layout.setHorizontalSpacing(24)
        sound_layout.setVerticalSpacing(14)

        sound_title = QLabel("Звук таймера", sound_box)
        sound_title.setObjectName("settingsSectionTitle")
        sound_layout.addRow(sound_title)

        self._settings_timer_sound_id = NoWheelComboBox(sound_box)
        for sound_id, label in available_timer_sounds():
            self._settings_timer_sound_id.addItem(label, sound_id)

        self._settings_timer_sound_volume_percent = NoWheelSpinBox(sound_box)
        self._settings_timer_sound_volume_percent.setRange(0, 100)
        self._settings_timer_sound_volume_percent.setSuffix(" %")

        self._settings_sound_preview_button = QPushButton("Прослушать", sound_box)
        self._settings_sound_preview_button.setObjectName("settingsPreviewButton")
        self._settings_sound_preview_button.clicked.connect(self._preview_selected_timer_sound)

        sound_layout.addRow("Сигнал завершения", self._settings_timer_sound_id)
        sound_layout.addRow("Громкость сигнала", self._settings_timer_sound_volume_percent)
        sound_layout.addRow("", self._settings_sound_preview_button)

        floating_box = QFrame(card)
        floating_box.setObjectName("settingsFormBox")
        floating_layout = QFormLayout(floating_box)
        floating_layout.setContentsMargins(16, 14, 16, 14)
        floating_layout.setHorizontalSpacing(24)
        floating_layout.setVerticalSpacing(14)

        floating_title = QLabel("Плавающее окно", floating_box)
        floating_title.setObjectName("settingsSectionTitle")
        floating_layout.addRow(floating_title)

        self._settings_always_on_top_default = QCheckBox(
            "Поверх всех окон по умолчанию",
            floating_box,
        )

        self._settings_floating_opacity_percent = NoWheelSpinBox(floating_box)
        self._settings_floating_opacity_percent.setRange(35, 100)
        self._settings_floating_opacity_percent.setSuffix(" %")

        self._settings_floating_pin_button_size = NoWheelSpinBox(floating_box)
        self._settings_floating_pin_button_size.setRange(28, 56)
        self._settings_floating_pin_button_size.setSuffix(" px")

        self._settings_floating_blink_enabled = QCheckBox(
            "Мигать таймером перед окончанием",
            floating_box,
        )

        self._settings_floating_blink_threshold_seconds = NoWheelSpinBox(floating_box)
        self._settings_floating_blink_threshold_seconds.setRange(3, 20)
        self._settings_floating_blink_threshold_seconds.setSuffix(" сек")
        self._settings_floating_blink_enabled.toggled.connect(
            self._settings_floating_blink_threshold_seconds.setEnabled
        )

        floating_layout.addRow("", self._settings_always_on_top_default)
        floating_layout.addRow("Прозрачность окна", self._settings_floating_opacity_percent)
        floating_layout.addRow("Размер кнопки закрепления", self._settings_floating_pin_button_size)
        floating_layout.addRow("", self._settings_floating_blink_enabled)
        floating_layout.addRow("Мигать за", self._settings_floating_blink_threshold_seconds)
        blink_hint = QLabel("Рекомендуемо: 5-10 секунд для мягкого предупреждения.", floating_box)
        blink_hint.setObjectName("settingsPageHint")
        blink_hint.setWordWrap(True)
        floating_layout.addRow("", blink_hint)

        buttons = QHBoxLayout()
        buttons.setContentsMargins(0, 0, 0, 0)
        buttons.setSpacing(10)

        save_button = QPushButton("Сохранить настройки", card)
        save_button.setObjectName("settingsSaveButton")
        save_button.clicked.connect(self._save_settings_page)

        reset_button = QPushButton("Сброс по умолчанию", card)
        reset_button.setObjectName("settingsResetButton")
        reset_button.clicked.connect(self._reset_settings_form_to_defaults)

        buttons.addWidget(save_button, stretch=2)
        buttons.addWidget(reset_button, stretch=1)

        card_layout.addLayout(title_row)
        card_layout.addWidget(hint)
        card_layout.addWidget(general_box)
        card_layout.addWidget(updates_box)
        card_layout.addWidget(main_box)
        card_layout.addWidget(planning_box)
        card_layout.addWidget(sound_box)
        card_layout.addWidget(floating_box)
        card_layout.addLayout(buttons)

        scroll_content_layout.addWidget(card)
        scroll.setWidget(scroll_content)
        layout.addWidget(scroll, stretch=1)
        self._populate_settings_form()
        self._refresh_update_ui()
        self._connect_settings_live_preview()
        return page

    def _populate_settings_form(self, source: AppSettings | None = None) -> None:
        source_settings = self._settings if source is None else source
        self._is_populating_settings_form = True
        widgets = [
            self._settings_theme_name,
            self._settings_ui_scale_percent,
            self._settings_launch_maximized,
            self._settings_show_sidebar_icons,
            self._settings_updates_manifest_url,
            self._settings_auto_check_updates_on_start,
            self._settings_update_check_interval_hours,
            self._settings_pomodoro,
            self._settings_short_break,
            self._settings_long_break,
            self._settings_long_break_interval,
            self._settings_main_start_button_height,
            self._settings_main_timer_scale_percent,
            self._settings_main_card_opacity_percent,
            self._settings_planning_progress_view,
            self._settings_planning_visual_style,
            self._settings_planning_cell_style,
            self._settings_planning_visual_max_symbols,
            self._settings_planning_row_height,
            self._settings_planning_table_font_size,
            self._settings_planning_today_highlight_percent,
            self._settings_planning_task_column_width,
            self._settings_planning_total_column_width,
            self._settings_planning_daily_limit,
            self._settings_planning_weekly_limit,
            self._settings_planning_auto_switch_to_timer,
            self._settings_planning_confirm_before_switch,
            self._settings_planning_follow_queue,
            self._settings_tasks_units_compact_mode,
            self._settings_timer_sound_id,
            self._settings_timer_sound_volume_percent,
            self._settings_always_on_top_default,
            self._settings_floating_opacity_percent,
            self._settings_floating_pin_button_size,
            self._settings_floating_blink_enabled,
            self._settings_floating_blink_threshold_seconds,
        ]
        try:
            for widget in widgets:
                with QSignalBlocker(widget):
                    if widget is self._settings_theme_name:
                        index = self._settings_theme_name.findData(source_settings.theme_name)
                        self._settings_theme_name.setCurrentIndex(0 if index < 0 else index)
                    elif widget is self._settings_ui_scale_percent:
                        widget.setValue(source_settings.ui_scale_percent)
                    elif widget is self._settings_launch_maximized:
                        widget.setChecked(source_settings.launch_maximized)
                    elif widget is self._settings_show_sidebar_icons:
                        widget.setChecked(source_settings.show_sidebar_icons)
                    elif widget is self._settings_updates_manifest_url:
                        widget.setText(source_settings.updates_manifest_url)
                    elif widget is self._settings_auto_check_updates_on_start:
                        widget.setChecked(source_settings.auto_check_updates_on_start)
                    elif widget is self._settings_update_check_interval_hours:
                        widget.setValue(source_settings.update_check_interval_hours)
                    elif widget is self._settings_pomodoro:
                        widget.setValue(source_settings.pomodoro_minutes)
                    elif widget is self._settings_short_break:
                        widget.setValue(source_settings.short_break_minutes)
                    elif widget is self._settings_long_break:
                        widget.setValue(source_settings.long_break_minutes)
                    elif widget is self._settings_long_break_interval:
                        widget.setValue(source_settings.long_break_interval)
                    elif widget is self._settings_main_start_button_height:
                        widget.setValue(source_settings.main_start_button_height)
                    elif widget is self._settings_main_timer_scale_percent:
                        widget.setValue(source_settings.main_timer_scale_percent)
                    elif widget is self._settings_main_card_opacity_percent:
                        widget.setValue(source_settings.main_card_opacity_percent)
                    elif widget is self._settings_planning_progress_view:
                        index = self._settings_planning_progress_view.findData(source_settings.planning_progress_view)
                        self._settings_planning_progress_view.setCurrentIndex(0 if index < 0 else index)
                    elif widget is self._settings_planning_visual_style:
                        index = self._settings_planning_visual_style.findData(source_settings.planning_visual_style)
                        self._settings_planning_visual_style.setCurrentIndex(0 if index < 0 else index)
                    elif widget is self._settings_planning_cell_style:
                        index = self._settings_planning_cell_style.findData(source_settings.planning_cell_style)
                        self._settings_planning_cell_style.setCurrentIndex(0 if index < 0 else index)
                    elif widget is self._settings_planning_visual_max_symbols:
                        widget.setValue(source_settings.planning_visual_max_symbols)
                    elif widget is self._settings_planning_row_height:
                        widget.setValue(source_settings.planning_row_height)
                    elif widget is self._settings_planning_table_font_size:
                        widget.setValue(source_settings.planning_table_font_size)
                    elif widget is self._settings_planning_today_highlight_percent:
                        widget.setValue(source_settings.planning_today_highlight_percent)
                    elif widget is self._settings_planning_task_column_width:
                        widget.setValue(source_settings.planning_task_column_width)
                    elif widget is self._settings_planning_total_column_width:
                        widget.setValue(source_settings.planning_total_column_width)
                    elif widget is self._settings_planning_daily_limit:
                        widget.setValue(source_settings.planning_daily_limit)
                    elif widget is self._settings_planning_weekly_limit:
                        widget.setValue(source_settings.planning_weekly_limit)
                    elif widget is self._settings_planning_auto_switch_to_timer:
                        widget.setChecked(source_settings.planning_auto_switch_to_timer_on_select)
                    elif widget is self._settings_planning_confirm_before_switch:
                        widget.setChecked(source_settings.planning_confirm_before_timer_switch)
                    elif widget is self._settings_planning_follow_queue:
                        widget.setChecked(source_settings.planning_follow_tasks_queue)
                    elif widget is self._settings_tasks_units_compact_mode:
                        widget.setChecked(source_settings.tasks_units_compact_mode)
                    elif widget is self._settings_timer_sound_id:
                        index = self._settings_timer_sound_id.findData(source_settings.timer_sound_id)
                        self._settings_timer_sound_id.setCurrentIndex(0 if index < 0 else index)
                    elif widget is self._settings_timer_sound_volume_percent:
                        widget.setValue(source_settings.timer_sound_volume_percent)
                    elif widget is self._settings_always_on_top_default:
                        self._settings_always_on_top_default.setChecked(
                            source_settings.always_on_top_default
                        )
                    elif widget is self._settings_floating_opacity_percent:
                        widget.setValue(source_settings.floating_opacity_percent)
                    elif widget is self._settings_floating_pin_button_size:
                        widget.setValue(source_settings.floating_pin_button_size)
                    elif widget is self._settings_floating_blink_enabled:
                        widget.setChecked(source_settings.floating_blink_enabled)
                    else:
                        widget.setValue(source_settings.floating_blink_threshold_seconds)

            self._settings_floating_blink_threshold_seconds.setEnabled(
                self._settings_floating_blink_enabled.isChecked()
            )
            self._on_planning_settings_view_mode_changed()
        finally:
            self._is_populating_settings_form = False

    def _on_planning_settings_view_mode_changed(self, _index: int | None = None) -> None:
        is_visual = str(self._settings_planning_progress_view.currentData()) == "visual"
        self._settings_planning_visual_style.setEnabled(is_visual)
        self._settings_planning_visual_max_symbols.setEnabled(is_visual)

    def _connect_settings_live_preview(self) -> None:
        if self._settings_live_preview_bound:
            return

        spin_boxes = [
            self._settings_ui_scale_percent,
            self._settings_pomodoro,
            self._settings_short_break,
            self._settings_long_break,
            self._settings_long_break_interval,
            self._settings_main_start_button_height,
            self._settings_main_timer_scale_percent,
            self._settings_main_card_opacity_percent,
            self._settings_planning_visual_max_symbols,
            self._settings_planning_row_height,
            self._settings_planning_table_font_size,
            self._settings_planning_today_highlight_percent,
            self._settings_planning_task_column_width,
            self._settings_planning_total_column_width,
            self._settings_planning_daily_limit,
            self._settings_planning_weekly_limit,
            self._settings_update_check_interval_hours,
            self._settings_timer_sound_volume_percent,
            self._settings_floating_opacity_percent,
            self._settings_floating_pin_button_size,
            self._settings_floating_blink_threshold_seconds,
        ]
        combo_boxes = [
            self._settings_theme_name,
            self._settings_planning_progress_view,
            self._settings_planning_visual_style,
            self._settings_planning_cell_style,
            self._settings_timer_sound_id,
        ]
        check_boxes = [
            self._settings_launch_maximized,
            self._settings_show_sidebar_icons,
            self._settings_auto_check_updates_on_start,
            self._settings_planning_auto_switch_to_timer,
            self._settings_planning_confirm_before_switch,
            self._settings_planning_follow_queue,
            self._settings_tasks_units_compact_mode,
            self._settings_always_on_top_default,
            self._settings_floating_blink_enabled,
        ]
        line_edits = [
            self._settings_updates_manifest_url,
        ]

        for spin in spin_boxes:
            spin.valueChanged.connect(self._on_settings_form_changed)
        for combo in combo_boxes:
            combo.currentIndexChanged.connect(self._on_settings_form_changed)
        for check in check_boxes:
            check.toggled.connect(self._on_settings_form_changed)
        for line_edit in line_edits:
            line_edit.editingFinished.connect(self._on_settings_form_changed)

        self._settings_live_preview_bound = True

    def _collect_settings_from_form(self) -> AppSettings:
        return AppSettings(
            pomodoro_minutes=self._settings_pomodoro.value(),
            short_break_minutes=self._settings_short_break.value(),
            long_break_minutes=self._settings_long_break.value(),
            long_break_interval=self._settings_long_break_interval.value(),
            theme_name=str(self._settings_theme_name.currentData()),
            launch_maximized=self._settings_launch_maximized.isChecked(),
            show_sidebar_icons=self._settings_show_sidebar_icons.isChecked(),
            ui_scale_percent=self._settings_ui_scale_percent.value(),
            main_start_button_height=self._settings_main_start_button_height.value(),
            main_timer_scale_percent=self._settings_main_timer_scale_percent.value(),
            main_card_opacity_percent=self._settings_main_card_opacity_percent.value(),
            planning_progress_view=str(self._settings_planning_progress_view.currentData()),
            planning_visual_style=str(self._settings_planning_visual_style.currentData()),
            planning_cell_style=str(self._settings_planning_cell_style.currentData()),
            planning_visual_max_symbols=self._settings_planning_visual_max_symbols.value(),
            planning_row_height=self._settings_planning_row_height.value(),
            planning_table_font_size=self._settings_planning_table_font_size.value(),
            planning_today_highlight_percent=self._settings_planning_today_highlight_percent.value(),
            planning_task_column_width=self._settings_planning_task_column_width.value(),
            planning_total_column_width=self._settings_planning_total_column_width.value(),
            planning_daily_limit=self._settings_planning_daily_limit.value(),
            planning_weekly_limit=self._settings_planning_weekly_limit.value(),
            planning_auto_switch_to_timer_on_select=self._settings_planning_auto_switch_to_timer.isChecked(),
            planning_confirm_before_timer_switch=self._settings_planning_confirm_before_switch.isChecked(),
            planning_follow_tasks_queue=self._settings_planning_follow_queue.isChecked(),
            tasks_units_compact_mode=self._settings_tasks_units_compact_mode.isChecked(),
            updates_manifest_url=str(self._settings_updates_manifest_url.text() or "").strip(),
            auto_check_updates_on_start=self._settings_auto_check_updates_on_start.isChecked(),
            update_check_interval_hours=self._settings_update_check_interval_hours.value(),
            last_update_check_attempt_at=self._settings.last_update_check_attempt_at,
            last_update_check_success_at=self._settings.last_update_check_success_at,
            dismissed_update_version=self._settings.dismissed_update_version,
            timer_sound_id=str(self._settings_timer_sound_id.currentData()),
            timer_sound_volume_percent=self._settings_timer_sound_volume_percent.value(),
            always_on_top_default=self._settings_always_on_top_default.isChecked(),
            floating_opacity_percent=self._settings_floating_opacity_percent.value(),
            floating_pin_button_size=self._settings_floating_pin_button_size.value(),
            floating_blink_enabled=self._settings_floating_blink_enabled.isChecked(),
            floating_blink_threshold_seconds=self._settings_floating_blink_threshold_seconds.value(),
            auto_start_breaks=False,
            auto_start_pomodoros=False,
        )

    def _on_settings_form_changed(self, *_args) -> None:
        if self._is_populating_settings_form:
            return
        preview_settings = self._collect_settings_from_form()
        self._apply_settings(
            preview_settings,
            show_message=False,
            persist=False,
            sync_form=False,
        )
        self.statusBar().showMessage(
            "Изменения применены в предпросмотре. Нажмите «Сохранить настройки» для подтверждения.",
            3200,
        )

    def _reset_settings_form_to_defaults(self) -> None:
        defaults = AppSettings()
        self._populate_settings_form(defaults)
        self._apply_settings(
            defaults,
            show_message=False,
            persist=False,
            sync_form=False,
        )
        self.statusBar().showMessage(
            "Значения по умолчанию применены в предпросмотре. Нажмите «Сохранить настройки» для подтверждения.",
            4500,
        )

    def _preview_selected_timer_sound(self) -> None:
        sound_id = str(self._settings_timer_sound_id.currentData())
        volume = self._settings_timer_sound_volume_percent.value()
        preview_completion_alert(sound_id=sound_id, volume_percent=volume)
        self.statusBar().showMessage("Проигрываю выбранный сигнал.", 1800)

    @staticmethod
    def _now_utc() -> datetime:
        return datetime.now(timezone.utc)

    @staticmethod
    def _to_iso_utc(dt: datetime) -> str:
        return dt.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")

    @staticmethod
    def _parse_iso_utc(value: str) -> datetime | None:
        text = str(value or "").strip()
        if not text:
            return None
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError:
            return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)

    def _format_time_for_ui(self, iso_value: str) -> str:
        dt = self._parse_iso_utc(iso_value)
        if dt is None:
            return "—"
        return dt.astimezone().strftime("%d.%m.%Y %H:%M")

    def _persist_update_metadata(self) -> None:
        persisted = self._settings_manager.load()
        persisted.last_update_check_attempt_at = self._settings.last_update_check_attempt_at
        persisted.last_update_check_success_at = self._settings.last_update_check_success_at
        persisted.dismissed_update_version = self._settings.dismissed_update_version
        self._settings_manager.save(persisted)

    def _record_update_attempt(self) -> None:
        self._settings.last_update_check_attempt_at = self._to_iso_utc(self._now_utc())
        self._persist_update_metadata()

    def _record_update_success(self) -> None:
        self._settings.last_update_check_success_at = self._to_iso_utc(self._now_utc())
        self._persist_update_metadata()

    def _effective_manifest_url(self) -> str:
        if hasattr(self, "_settings_updates_manifest_url"):
            manifest_url = str(self._settings_updates_manifest_url.text() or "").strip()
        else:
            manifest_url = str(self._settings.updates_manifest_url or "").strip()
        if manifest_url.lower().startswith("file://"):
            manifest_url = DEFAULT_UPDATE_MANIFEST_URL
            if hasattr(self, "_settings_updates_manifest_url"):
                with QSignalBlocker(self._settings_updates_manifest_url):
                    self._settings_updates_manifest_url.setText(manifest_url)
        self._settings.updates_manifest_url = manifest_url
        return manifest_url

    def _is_auto_update_check_due(self) -> bool:
        interval_hours = max(1, int(self._settings.update_check_interval_hours))
        last_attempt = self._parse_iso_utc(self._settings.last_update_check_attempt_at)
        if last_attempt is None:
            return True
        return self._now_utc() >= (last_attempt + timedelta(hours=interval_hours))

    def _run_startup_update_check_if_due(self) -> None:
        if not bool(self._settings.auto_check_updates_on_start):
            return
        if self._update_manager.is_checking() or self._update_install_manager.is_installing():
            return
        if not self._effective_manifest_url():
            return
        if not self._is_auto_update_check_due():
            return
        self._start_update_check(origin=_UpdateCheckOrigin.AUTO, show_popups=False)

    def _start_update_check(self, *, origin: str, show_popups: bool) -> bool:
        if self._update_manager.is_checking():
            if show_popups:
                self.statusBar().showMessage("Проверка обновлений уже выполняется.", 2200)
            return False
        if self._update_install_manager.is_installing():
            if show_popups:
                self.statusBar().showMessage("Установка обновления уже выполняется.", 2200)
            return False

        manifest_url = self._effective_manifest_url()
        if not manifest_url:
            text = "Укажите URL манифеста обновлений в настройках."
            self._last_update_error = text
            self._refresh_update_ui()
            if show_popups:
                QMessageBox.information(self, "Проверка обновлений", text)
            return False

        self._update_check_origin = origin
        self._update_check_show_popups = show_popups
        self._last_update_error = ""
        self._record_update_attempt()

        started = self._update_manager.start_check(
            current_version=self._app_version,
            manifest_url=manifest_url,
            timeout_seconds=6,
        )
        if not started and show_popups:
            self.statusBar().showMessage("Проверка обновлений уже выполняется.", 2200)
        self._refresh_update_ui()
        return started

    def _on_check_updates_clicked(self) -> None:
        self._start_update_check(origin=_UpdateCheckOrigin.MANUAL, show_popups=False)

    @Slot()
    def _on_update_check_started(self) -> None:
        self._refresh_update_ui()
        self.statusBar().showMessage("Проверяю обновления...", 2800)

    @Slot(object)
    def _on_update_check_finished(self, result: UpdateCheckResult) -> None:
        was_manual = self._update_check_origin == _UpdateCheckOrigin.MANUAL
        self._last_update_result = result
        self._last_update_error = ""
        self._record_update_success()

        if was_manual and result.is_update_available:
            # Manual check is a significant check: allow showing banner again.
            if str(self._settings.dismissed_update_version or "").strip() == str(result.latest_version):
                self._settings.dismissed_update_version = ""
                self._persist_update_metadata()
        if not result.is_update_available and self._settings.dismissed_update_version:
            self._settings.dismissed_update_version = ""
            self._persist_update_metadata()

        self._refresh_update_ui()
        if result.is_update_available:
            self.statusBar().showMessage(
                f"Найдена новая версия {result.latest_version}.",
                4500,
            )
            return

        self.statusBar().showMessage("Установлена актуальная версия приложения.", 3200)

    @Slot(str)
    def _on_update_check_failed(self, message: str) -> None:
        text = message or "Ошибка проверки обновлений."
        self._last_update_error = text
        self._refresh_update_ui()
        self.statusBar().showMessage(
            text,
            4200,
        )

    @Slot(bool)
    def _on_update_checking_changed(self, is_checking: bool) -> None:
        if hasattr(self, "_settings_check_updates_button"):
            self._settings_check_updates_button.setText("Проверяю..." if is_checking else "Проверить обновления")
        self._refresh_update_ui()

    def _on_install_update_clicked(self) -> None:
        update_result = self._last_update_result
        if update_result is None or not update_result.is_update_available or not self._has_installable_update_result():
            QMessageBox.information(
                self,
                "Установка обновления",
                "Сначала выполните проверку и найдите доступное обновление.",
            )
            return
        if self._update_manager.is_checking():
            self.statusBar().showMessage("Дождитесь завершения проверки обновлений.", 2400)
            return
        if self._update_install_manager.is_installing():
            self.statusBar().showMessage("Установка обновления уже выполняется.", 2400)
            return
        started = self._update_install_manager.start_install(update_result=update_result)
        if not started:
            self.statusBar().showMessage("Не удалось запустить установку обновления.", 2600)
        self._refresh_update_ui()

    @Slot()
    def _on_update_install_started(self) -> None:
        self.statusBar().showMessage("Подготовка установки обновления...", 2400)
        self._start_update_install_progress_simulation()
        self._set_update_install_progress(6)
        self._refresh_update_ui()

    @Slot(str)
    def _on_update_install_status(self, message: str) -> None:
        text = str(message or "").strip() or "Установка обновления..."
        if hasattr(self, "_settings_update_status"):
            self._settings_update_status.setText(text)
        if hasattr(self, "_updates_status_value"):
            self._updates_status_value.setText(text)
        self._update_install_progress_from_status(text)
        self.statusBar().showMessage(text, 2200)

    @Slot(str)
    def _on_update_install_finished(self, version: str) -> None:
        self._set_update_install_progress(100)
        self._stop_update_install_progress_simulation()
        self._last_update_error = ""
        self._settings.dismissed_update_version = ""
        self._persist_update_metadata()
        self._refresh_update_ui()
        if hasattr(self, "_settings_update_status"):
            self._settings_update_status.setText(
                f"Updater запущен. Приложение закроется для установки версии {version}."
            )
        QMessageBox.information(
            self,
            "Установка обновления",
            "Updater запущен. Приложение будет закрыто для установки обновления.",
        )
        self.statusBar().showMessage(
            f"Updater запущен для версии {version}. Закрываю приложение...",
            3800,
        )
        QTimer.singleShot(420, self.close)

    @Slot(str)
    def _on_update_install_failed(self, message: str) -> None:
        self._stop_update_install_progress_simulation()
        text = message or "Не удалось подготовить установку обновления."
        if hasattr(self, "_settings_update_status"):
            self._settings_update_status.setText(text)
        QMessageBox.warning(
            self,
            "Ошибка установки обновления",
            text,
        )
        self.statusBar().showMessage(text, 4200)
        self._refresh_update_ui()

    @Slot(bool)
    def _on_update_installing_changed(self, _is_installing: bool) -> None:
        if not self._update_install_manager.is_installing():
            self._stop_update_install_progress_simulation()
        self._refresh_update_ui()

    def _set_update_install_progress(self, value: int) -> None:
        bounded = max(0, min(100, int(value)))
        if bounded <= self._update_install_progress_value:
            return
        self._update_install_progress_value = bounded
        if hasattr(self, "_updates_install_progress_bar"):
            self._updates_install_progress_bar.setValue(bounded)

    def _start_update_install_progress_simulation(self) -> None:
        self._update_install_progress_real = False
        self._update_install_progress_value = 0
        self._set_update_install_progress(3)
        if hasattr(self, "_updates_install_progress_bar"):
            self._updates_install_progress_bar.setVisible(True)
        if not self._update_install_progress_timer.isActive():
            self._update_install_progress_timer.start()

    def _stop_update_install_progress_simulation(self) -> None:
        if self._update_install_progress_timer.isActive():
            self._update_install_progress_timer.stop()

    @Slot()
    def _tick_update_install_progress(self) -> None:
        if not self._update_install_manager.is_installing():
            self._stop_update_install_progress_simulation()
            return
        cap = 92 if self._update_install_progress_real else 88
        if self._update_install_progress_value >= cap:
            return
        self._set_update_install_progress(self._update_install_progress_value + 1)

    def _update_install_progress_from_status(self, text: str) -> None:
        lowered = str(text or "").lower()
        percent_match = re.search(r"(\d{1,3})\s*%", lowered)

        if "preparing update" in lowered or "подготов" in lowered:
            self._set_update_install_progress(7)
            return

        if "downloading update" in lowered or "скачив" in lowered:
            self._set_update_install_progress(12)
            if percent_match:
                try:
                    percent = max(0, min(100, int(percent_match.group(1))))
                except (TypeError, ValueError):
                    percent = 0
                mapped = 12 + int(percent * 0.60)
                self._update_install_progress_real = True
                self._set_update_install_progress(mapped)
            return

        if "verifying checksum" in lowered or "провер" in lowered:
            self._set_update_install_progress(80)
            return

        if "launching updater" in lowered or "запуск" in lowered:
            self._set_update_install_progress(93)

    def _has_installable_update_result(self) -> bool:
        result = self._last_update_result
        if result is None or not result.is_update_available:
            return False
        return bool(str(result.download_url or "").strip()) and bool(str(result.sha256 or "").strip())

    def _refresh_update_controls(self) -> None:
        if not hasattr(self, "_settings_check_updates_button"):
            return
        is_checking = self._update_manager.is_checking()
        is_installing = self._update_install_manager.is_installing()
        can_install = self._has_installable_update_result()
        self._settings_check_updates_button.setEnabled(not is_checking and not is_installing)
        if hasattr(self, "_settings_install_update_button"):
            self._settings_install_update_button.setEnabled(
                (not is_checking) and (not is_installing) and can_install
            )
            if is_installing:
                self._settings_install_update_button.setText("Устанавливаю...")
            else:
                self._settings_install_update_button.setText("Скачать и установить")
        if hasattr(self, "_updates_check_now_button"):
            self._updates_check_now_button.setEnabled(not is_checking and not is_installing)
            self._updates_check_now_button.setText("Проверяю..." if is_checking else "Проверить сейчас")
        if hasattr(self, "_updates_install_button"):
            self._updates_install_button.setEnabled(
                (not is_checking) and (not is_installing) and can_install
            )
            self._updates_install_button.setText("Устанавливаю..." if is_installing else "Установить")
        if hasattr(self, "_updates_install_progress_bar"):
            if is_installing:
                self._updates_install_progress_bar.setVisible(True)
            elif self._update_install_progress_value >= 100:
                self._updates_install_progress_bar.setVisible(True)
            else:
                self._updates_install_progress_bar.setVisible(False)

    def _update_status_message(self) -> str:
        if self._update_install_manager.is_installing():
            return "Установка обновления..."
        if self._update_manager.is_checking():
            return "Проверяю обновления..."
        if self._last_update_error:
            return "Последняя проверка завершилась с ошибкой."
        result = self._last_update_result
        if result is None:
            return "Проверка обновлений не выполнялась."
        if result.is_update_available:
            if self._has_installable_update_result():
                return f"Доступна версия {result.latest_version}. Можно установить."
            return f"Доступна версия {result.latest_version}. В манифесте не хватает данных для установки."
        return "Установлена актуальная версия приложения."

    def _refresh_update_footer_visibility(self) -> None:
        if not hasattr(self, "_update_footer"):
            return
        result = self._last_update_result
        is_updates_page_open = hasattr(self, "_stack") and self._stack.currentIndex() == self.PAGE_UPDATES
        should_show = (
            result is not None
            and result.is_update_available
            and str(self._settings.dismissed_update_version or "").strip() != str(result.latest_version)
            and not is_updates_page_open
        )
        if should_show:
            self._update_footer_label.setText(f"Доступна новая версия {result.latest_version}")
        self._update_footer.setVisible(bool(should_show))

    def _open_updates_page_from_footer(self) -> None:
        self._switch_page(self.PAGE_UPDATES)

    def _dismiss_update_footer(self) -> None:
        result = self._last_update_result
        if result is not None and result.is_update_available:
            self._settings.dismissed_update_version = str(result.latest_version)
            self._persist_update_metadata()
        self._refresh_update_footer_visibility()

    def _refresh_update_ui(self) -> None:
        status_text = self._update_status_message()
        if hasattr(self, "_settings_update_status"):
            self._settings_update_status.setText(status_text)
        if hasattr(self, "_updates_status_value"):
            self._updates_status_value.setText(status_text)

        result = self._last_update_result
        if hasattr(self, "_updates_current_version_value"):
            self._updates_current_version_value.setText(self._app_version)
        if hasattr(self, "_updates_latest_version_value"):
            self._updates_latest_version_value.setText(result.latest_version if result is not None else "—")
        if hasattr(self, "_updates_min_supported_value"):
            self._updates_min_supported_value.setText(
                result.minimum_supported_version if result is not None else "—"
            )
        if hasattr(self, "_updates_published_at_value"):
            published = str(result.published_at).strip() if result is not None else ""
            self._updates_published_at_value.setText(published or "—")
        summary, details_text = self._format_release_notes_for_ui(result)
        if hasattr(self, "_updates_release_summary_value"):
            self._updates_release_summary_value.setText(summary or "—")
        if hasattr(self, "_updates_release_notes_value"):
            self._updates_release_notes_value.setText(details_text or "—")
        if hasattr(self, "_updates_last_attempt_value"):
            self._updates_last_attempt_value.setText(
                self._format_time_for_ui(self._settings.last_update_check_attempt_at)
            )
        if hasattr(self, "_updates_last_success_value"):
            self._updates_last_success_value.setText(
                self._format_time_for_ui(self._settings.last_update_check_success_at)
            )
        if hasattr(self, "_updates_error_value"):
            has_error = bool(self._last_update_error)
            self._updates_error_value.setVisible(has_error)
            if has_error:
                self._updates_error_value.setText(f"Ошибка: {self._last_update_error}")
        if hasattr(self, "_updates_support_warning"):
            show_warning = result is not None and not result.is_current_version_supported
            self._updates_support_warning.setVisible(show_warning)
            if show_warning:
                self._updates_support_warning.setText(
                    "Ваша версия ниже минимально поддерживаемой. Рекомендуется установить обновление."
                )
        if hasattr(self, "_updates_install_progress_label"):
            if self._update_install_manager.is_installing():
                self._updates_install_progress_label.setText("Прогресс установки (скачивание и подготовка)")
            elif self._update_install_progress_value >= 100:
                self._updates_install_progress_label.setText("Установка запущена, приложение перезапускается")
            else:
                self._updates_install_progress_label.setText("Прогресс установки")

        self._refresh_update_controls()
        self._refresh_update_footer_visibility()

    @staticmethod
    def _format_release_notes_for_ui(result: UpdateCheckResult | None) -> tuple[str, str]:
        notes = str(result.release_notes).strip() if result is not None else ""
        if not notes:
            return "", ""

        lines = [line.strip() for line in notes.replace("\r\n", "\n").split("\n") if line.strip()]
        if not lines:
            return "", ""

        summary = lines[0]
        detail_candidates = lines[1:]
        details: list[str] = []
        for line in detail_candidates:
            normalized = line.lstrip("-•* ").strip()
            if normalized:
                details.append(normalized)

        # Fallback for single-line notes separated by ';'
        if not details and ";" in summary:
            parts = [part.strip() for part in summary.split(";") if part.strip()]
            if parts:
                summary = parts[0]
                details = parts[1:]

        details_text = "\n".join(f"• {item}" for item in details)
        return summary, details_text

    def _save_settings_page(self) -> None:
        self._apply_settings(self._collect_settings_from_form(), persist=True)

    def _apply_theme_and_visual_settings(self) -> None:
        app = QApplication.instance()
        if app is not None:
            app.setStyleSheet(
                build_app_stylesheet(
                    theme_name=self._settings.theme_name,
                    main_card_opacity_percent=self._settings.main_card_opacity_percent,
                    main_start_button_height=self._settings.main_start_button_height,
                    ui_scale_percent=self._settings.ui_scale_percent,
                )
            )
        self._apply_sidebar_icons(self._settings.show_sidebar_icons)
        self._apply_ring_palette(self._settings.theme_name)
        self._apply_planning_visual_settings()
        self._tasks_units_compact_mode = bool(self._settings.tasks_units_compact_mode)
        if hasattr(self, "_tasks_day_tables"):
            self._refresh_tasks_page()

    def _apply_sidebar_icons(self, enabled: bool) -> None:
        icon_paths = [
            (self._pomodoro_nav, "nav_timer.svg"),
            (self._planning_nav, "nav_plan.svg"),
            (self._tasks_nav, "nav_tasks.svg"),
            (self._updates_nav, "nav_settings.svg"),
            (self._settings_nav, "nav_settings.svg"),
        ]
        for button, filename in icon_paths:
            if enabled:
                path = self._asset_path(filename)
                if path.exists():
                    button.setIcon(QIcon(str(path)))
                    button.setIconSize(QSize(20, 20))
                else:
                    button.setIcon(QIcon())
            else:
                button.setIcon(QIcon())

    def _apply_ring_palette(self, theme_name: str) -> None:
        if theme_name == "forest":
            self._circular_timer.set_palette(
                track=QColor(226, 249, 237, 75),
                progress=QColor(142, 216, 168, 255),
                time_text=QColor(255, 255, 255, 248),
                mode_text=QColor(226, 249, 237, 222),
            )
            return
        if theme_name == "rose":
            self._circular_timer.set_palette(
                track=QColor(251, 239, 239, 92),
                progress=QColor(255, 96, 104, 255),
                time_text=QColor(255, 255, 255, 250),
                mode_text=QColor(251, 239, 239, 230),
            )
            return
        if theme_name == "sunset":
            self._circular_timer.set_palette(
                track=QColor(255, 230, 212, 84),
                progress=QColor(255, 194, 129, 255),
                time_text=QColor(255, 250, 245, 250),
                mode_text=QColor(255, 235, 220, 228),
            )
            return
        if theme_name == "graphite":
            self._circular_timer.set_palette(
                track=QColor(219, 233, 246, 78),
                progress=QColor(136, 190, 234, 255),
                time_text=QColor(243, 249, 255, 250),
                mode_text=QColor(219, 233, 246, 224),
            )
            return

        self._circular_timer.set_palette(
            track=QColor(222, 243, 255, 84),
            progress=QColor(108, 194, 234, 255),
            time_text=QColor(255, 255, 255, 250),
            mode_text=QColor(223, 241, 252, 228),
        )

    def _apply_planning_visual_settings(self) -> None:
        if not hasattr(self, "_planning_table"):
            return
        row_height = max(40, min(84, self._settings.planning_row_height))
        for row in range(self._planning_table.rowCount()):
            self._planning_table.setRowHeight(row, row_height)

        table_font = self._planning_table.font()
        table_font.setPointSize(max(12, min(22, self._settings.planning_table_font_size)))
        self._planning_table.setFont(table_font)

        icon_size = max(12, min(22, self._settings.planning_table_font_size))
        self._planning_table.setIconSize(QSize(icon_size, icon_size))
        self._planning_table.setColumnWidth(
            0,
            max(150, min(240, self._settings.planning_task_column_width)),
        )
        self._planning_table.setColumnWidth(
            8,
            max(66, min(110, self._settings.planning_total_column_width)),
        )
        self._apply_planning_day_columns_width()
        accent, accent_soft, danger, _ = self._planning_theme_colors()
        highlight_fill = self._blend_colors(accent, accent_soft, 0.44)
        highlight_border = self._blend_colors(accent_soft, danger, 0.1)
        self._planning_table.set_highlight_palette(fill=highlight_fill, border=highlight_border)
        self._planning_table.set_highlight_strength(self._settings.planning_today_highlight_percent)
        if hasattr(self, "_week_header"):
            self._update_planning_week_labels()
        else:
            self._refresh_planning_column_visuals()

    def _apply_planning_day_columns_width(self) -> None:
        if not hasattr(self, "_planning_table"):
            return
        header = self._planning_table.horizontalHeader()
        task_width = max(150, min(240, self._settings.planning_task_column_width))
        total_width = max(66, min(110, self._settings.planning_total_column_width))
        self._planning_table.setColumnWidth(0, task_width)
        self._planning_table.setColumnWidth(8, total_width)
        header.setStretchLastSection(False)
        for col in range(1, 8):
            header.setSectionResizeMode(col, QHeaderView.Stretch)
        header.setSectionResizeMode(8, QHeaderView.Fixed)

    def _apply_floating_visual_settings(self) -> None:
        if self._floating_window is None:
            return
        self._floating_window.set_pinned(self._settings.always_on_top_default)
        self._floating_window.apply_visual_settings(
            opacity_percent=self._settings.floating_opacity_percent,
            pin_button_size=self._settings.floating_pin_button_size,
            blink_enabled=self._settings.floating_blink_enabled,
            blink_threshold_seconds=self._settings.floating_blink_threshold_seconds,
            theme_name=self._settings.theme_name,
        )

    def _switch_page(self, index: int) -> None:
        self._stack.setCurrentIndex(index)
        if index == self.PAGE_POMODORO:
            if self._ensure_follow_queue_selection(save_if_changed=True):
                self._update_planning_week_labels()
            self._on_state_changed(self._controller.state.snapshot())
        elif index == self.PAGE_UPDATES:
            self._refresh_update_ui()
        elif index == self.PAGE_SETTINGS:
            self._populate_settings_form()
        elif index == self.PAGE_TASKS:
            self._reconcile_planner_week(self._planning_week_key())
            self._refresh_tasks_page(force=True)
        for i, button in enumerate(self._nav_buttons):
            with QSignalBlocker(button):
                button.setChecked(i == index)
        self._refresh_update_footer_visibility()

    def _adjust_current_mode_minutes(self, delta: int) -> None:
        mode = self._controller.state.mode

        if mode is TimerMode.POMODORO:
            self._settings.pomodoro_minutes = max(1, self._settings.pomodoro_minutes + delta)
            minutes = self._settings.pomodoro_minutes
        elif mode is TimerMode.SHORT_BREAK:
            self._settings.short_break_minutes = max(1, self._settings.short_break_minutes + delta)
            minutes = self._settings.short_break_minutes
        else:
            self._settings.long_break_minutes = max(1, self._settings.long_break_minutes + delta)
            minutes = self._settings.long_break_minutes

        self._apply_settings(self._settings, show_message=False)

        suffix = ""
        if self._controller.is_active():
            suffix = " Изменение применится после сброса/следующей сессии."
        self.statusBar().showMessage(f"{mode.title}: {minutes} мин.{suffix}", 3500)

    def _on_primary_clicked(self) -> None:
        self._controller.toggle_primary()

    def _can_start_session(self) -> bool:
        snapshot = self._controller.state.snapshot()
        if snapshot.status in {TimerStatus.RUNNING, TimerStatus.PAUSED}:
            return True

        if snapshot.mode is not TimerMode.POMODORO or not self._planning_tasks:
            return True

        if self._ensure_follow_queue_selection(save_if_changed=True):
            self._update_planning_week_labels()
            self._on_state_changed(snapshot)
        task_name = self._task_display_name(self._planning_selected_task_id)
        if not task_name:
            self.statusBar().showMessage("Выберите задачу в разделе «Планирование».", 3000)
            return False
        if self._planning_selected_day_index is None:
            self.statusBar().showMessage("Выберите день недели для выбранной задачи.", 3000)
            return False

        day_index = self._planning_selected_day_index
        task_id = self._planning_selected_task_id or ""
        excluded = self._excluded_cells_for_current_week().get(task_id, set())
        if day_index in excluded:
            self.statusBar().showMessage("Выбранный день исключен. Снимите исключение или выберите другой день.", 3200)
            return False

        planned = self._week_task_values(self._planned_cells_for_current_week(), task_id)[day_index]
        done = self._week_task_values(self._done_cells_for_current_week(), task_id)[day_index]
        if planned <= 0:
            self.statusBar().showMessage("Для этого дня нет плана. Укажите «Всего» в конце строки задачи.", 3200)
            return False
        if done >= planned:
            self.statusBar().showMessage("План по выбранному дню уже выполнен.", 2600)
            return False

        selected_unit = self._selected_unit_for_current_week()
        if selected_unit is not None:
            if (
                str(selected_unit.parent_task_id) != task_id
                or int(selected_unit.day_index) != day_index
            ):
                self._planning_selected_unit_by_week.pop(self._planning_week_key(), None)
            elif str(selected_unit.status) != "pending":
                self.statusBar().showMessage(
                    "Выбранная Pomodoro-единица уже выполнена. Выберите pending-единицу в разделе «Задачи».",
                    3400,
                )
                return False
        return True

    def _on_mode_clicked(self, mode: TimerMode, checked: bool) -> None:
        if not checked:
            return

        snapshot = self._controller.state.snapshot()
        if mode is snapshot.mode:
            return

        if self._controller.is_active():
            dialog = QMessageBox(self)
            dialog.setIcon(QMessageBox.Warning)
            dialog.setWindowTitle("Сменить режим?")
            dialog.setText("Текущий прогресс таймера будет сброшен. Продолжить?")
            yes_button = dialog.addButton("Да", QMessageBox.YesRole)
            no_button = dialog.addButton("Нет", QMessageBox.NoRole)
            dialog.setDefaultButton(no_button)
            dialog.exec()

            if dialog.clickedButton() is not yes_button:
                self._sync_mode_buttons(snapshot.mode)
                return

        self._controller.change_mode(mode)

    def _sync_mode_buttons(self, active_mode: TimerMode) -> None:
        for mode, button in self._mode_buttons.items():
            with QSignalBlocker(button):
                button.setChecked(mode is active_mode)

    def _open_floating_timer(self) -> None:
        if self._floating_window is None:
            self._floating_window = FloatingTimerWindow(
                self._controller,
                always_on_top_default=self._settings.always_on_top_default,
                parent=None,
            )
            self._floating_window.setAttribute(Qt.WA_DeleteOnClose, True)
            self._floating_window.destroyed.connect(self._on_floating_closed)
            self._floating_window.return_requested.connect(self._on_floating_return_requested)
            self._apply_floating_visual_settings()

        self._floating_window.show()
        self._floating_window.raise_()
        self._floating_window.activateWindow()

    def _on_floating_closed(self, _obj=None) -> None:
        self._floating_window = None

    def _on_floating_return_requested(self) -> None:
        if self.isMinimized():
            self.showNormal()
        else:
            self.show()
        self.raise_()
        self.activateWindow()
        if self._floating_window is not None:
            self._floating_window.close()

    def _mode_minutes(self) -> dict[TimerMode, int]:
        return {
            TimerMode.POMODORO: self._settings.pomodoro_minutes,
            TimerMode.SHORT_BREAK: self._settings.short_break_minutes,
            TimerMode.LONG_BREAK: self._settings.long_break_minutes,
        }

    def _apply_settings(
        self,
        settings: AppSettings,
        *,
        show_message: bool = True,
        persist: bool = True,
        sync_form: bool = True,
    ) -> None:
        self._settings = settings
        if persist:
            self._settings_manager.save(settings)

        self._apply_theme_and_visual_settings()
        self._controller.update_configuration(
            self._mode_minutes(),
            long_break_interval=settings.long_break_interval,
        )
        self._apply_floating_visual_settings()
        selection_changed = self._ensure_follow_queue_selection(save_if_changed=False)

        if sync_form and hasattr(self, "_settings_theme_name"):
            self._populate_settings_form()
        self._apply_responsive_fonts()
        self._refresh_update_ui()
        if selection_changed:
            self._update_planning_week_labels()
            self._on_state_changed(self._controller.state.snapshot())

        if show_message:
            if persist:
                self.statusBar().showMessage(
                    f"Настройки сохранены: {self._settings_manager.path}",
                    4200,
                )
            else:
                self.statusBar().showMessage("Изменения применены в предпросмотре.", 2600)

    def _on_state_changed(self, snapshot: TimerSnapshot) -> None:
        mode_duration = self._controller.duration_for_mode(snapshot.mode)
        if snapshot.mode is not self._last_mode:
            self._last_mode = snapshot.mode
            self._display_total_seconds = mode_duration
        elif snapshot.status in {TimerStatus.IDLE, TimerStatus.COMPLETED} and snapshot.remaining_seconds == mode_duration:
            self._display_total_seconds = mode_duration

        total_seconds = max(1, self._display_total_seconds)
        progress = max(0.0, min(1.0, snapshot.remaining_seconds / total_seconds))

        self._sync_mode_buttons(snapshot.mode)
        self._circular_timer.set_time_text(format_seconds(snapshot.remaining_seconds))
        self._circular_timer.set_mode_text(self._ring_mode_text(snapshot.mode))
        self._circular_timer.set_progress(progress)
        self._primary_button.setText(snapshot.action_label)
        cycle_text, status_text = self._planner_context_labels(snapshot)
        self._cycle_label.setText(cycle_text)
        self._status_label.setText(status_text)

    def _ring_mode_text(self, mode: TimerMode) -> str:
        if mode is TimerMode.POMODORO:
            return "ФОКУС"
        if mode is TimerMode.SHORT_BREAK:
            return "ПАУЗА"
        return "ДЛИННАЯ ПАУЗА"

    def _planner_context_labels(self, snapshot: TimerSnapshot) -> tuple[str, str]:
        task_name = self._task_display_name(self._planning_selected_task_id)
        if not task_name:
            return snapshot.cycle_label, snapshot.mode.hint

        cycle_text = task_name
        if self._planning_selected_day_index is None:
            return cycle_text, "Выберите день в разделе «Планирование»."

        day_index = self._planning_selected_day_index
        day_name = self._day_names_short[day_index]
        excluded = self._excluded_cells_for_current_week().get(self._planning_selected_task_id or "", set())
        if day_index in excluded:
            return cycle_text, f"{day_name}: день исключен."

        planned_values = self._week_task_values(self._planned_cells_for_current_week(), self._planning_selected_task_id or "")
        done_values = self._week_task_values(self._done_cells_for_current_week(), self._planning_selected_task_id or "")
        planned = planned_values[day_index]
        done = min(done_values[day_index], planned)
        selected_unit = self._selected_unit_for_current_week()
        selected_unit_text = ""
        if (
            selected_unit is not None
            and str(selected_unit.parent_task_id) == str(self._planning_selected_task_id or "")
            and int(selected_unit.day_index) == day_index
        ):
            unit_title = self._task_unit_display_title(selected_unit)
            if unit_title and unit_title != task_name:
                if str(selected_unit.status) == "done":
                    selected_unit_text = f"{unit_title} (готово). "
                else:
                    selected_unit_text = f"{unit_title}. "

        if planned <= 0:
            progress_text = f"{selected_unit_text}{day_name}: задайте количество через «Всего»."
        elif done >= planned:
            progress_text = f"{selected_unit_text}{day_name}: план выполнен ({done}/{planned})."
        else:
            progress_text = f"{selected_unit_text}{day_name}: {done}/{planned} помидоров."

        if snapshot.mode is TimerMode.POMODORO:
            return cycle_text, progress_text
        return cycle_text, f"{snapshot.mode.hint} {progress_text}"

    def _on_session_completed(self, finished_mode: str, next_mode: str) -> None:
        sequence_note = ""
        if (
            finished_mode == TimerMode.POMODORO.title
            and self._planning_selected_task_id
            and self._planning_selected_day_index is not None
        ):
            task_id = self._planning_selected_task_id
            day_index = self._planning_selected_day_index
            excluded = self._excluded_cells_for_current_week().get(task_id, set())
            if day_index not in excluded:
                planned = self._week_task_values(self._planned_cells_for_current_week(), task_id)[day_index]
                if planned > 0:
                    week_key = self._planning_week_key()
                    selected_unit_id = self._planning_selected_unit_by_week.get(week_key)
                    completed_unit = self._planner_controller.complete_next_pending(
                        week_start_iso=week_key,
                        task_id=task_id,
                        day_index=day_index,
                        selected_unit_id=selected_unit_id,
                    )
                    marked = completed_unit is not None
                    if selected_unit_id and not marked:
                        self.statusBar().showMessage(
                            "Выбранная Pomodoro-единица не была засчитана. Выберите pending-единицу в «Задачах».",
                            3600,
                        )
                    if marked:
                        self._reconcile_planner_week(week_key)
                        if self._settings.planning_follow_tasks_queue:
                            next_unit = self._find_next_pending_unit_in_sequence(
                                week_key=week_key,
                                completed_day_index=int(completed_unit.day_index),
                                completed_unit_id=str(completed_unit.id),
                            )
                            if next_unit is not None:
                                self._planning_selected_task_id = str(next_unit.parent_task_id)
                                self._planning_selected_day_index = int(next_unit.day_index)
                                self._planning_selected_unit_by_week[week_key] = str(next_unit.id)
                                next_title = self._task_unit_display_title(next_unit)
                                next_day_name = self._day_names_short[int(next_unit.day_index)]
                                sequence_note = f" Далее: {next_day_name} — {next_title}."
                            else:
                                self._planning_selected_unit_by_week.pop(week_key, None)
                                sequence_note = " Все Pomodoro-единицы на неделе выполнены."
                        elif selected_unit_id and str(getattr(completed_unit, "id", "")) == str(selected_unit_id):
                            # Queue-following disabled: keep current task/day, but clear explicit unit
                            # because it is now done and should not block the next run.
                            self._planning_selected_unit_by_week.pop(week_key, None)
                    self._save_planning_state()
                    self._refresh_planning_column_visuals()
                else:
                    self._save_planning_state()

        play_completion_alert(
            sound_id=self._settings.timer_sound_id,
            volume_percent=self._settings.timer_sound_volume_percent,
        )
        self.statusBar().showMessage(
            f"Режим «{finished_mode}» завершен. Далее: «{next_mode}». Нажмите СТАРТ.{sequence_note}",
            5500,
        )
        self._on_state_changed(self._controller.state.snapshot())
        self._refresh_tasks_page()

    def _toggle_maximize_restore(self) -> None:
        if self.isMaximized():
            self.showNormal()
        else:
            self.showMaximized()
        self._update_window_buttons()

    def _update_window_buttons(self) -> None:
        if not hasattr(self, "_window_maximize_button"):
            return
        if self.isMaximized():
            self._window_maximize_button.setText("❐")
        else:
            self._window_maximize_button.setText("□")

    def _apply_responsive_fonts(self) -> None:
        shell_width = self._timer_shell.width()
        shell_height = self._timer_shell.height()
        side_padding = 42
        available = max(210, min(shell_width - side_padding, shell_height - 10))
        scale = max(65, min(118, self._settings.main_timer_scale_percent)) / 100.0
        ring_size = int(available * scale)
        if shell_width > 1250:
            ring_size += int((shell_width - 1250) * 0.10)
        ring_size = min(ring_size, max(220, min(shell_width - 22, shell_height - 6)))
        self._circular_timer.setFixedSize(ring_size, ring_size)

        if not self._sparkles_source.isNull():
            spark = self._sparkles_source.scaled(22, 22, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            self._sidebar_sparkles.setPixmap(spark)

    def resizeEvent(self, event) -> None:  # type: ignore[override]
        super().resizeEvent(event)
        self._update_window_buttons()
        self._apply_responsive_fonts()
        if hasattr(self, "_planning_table"):
            self._apply_planning_day_columns_width()

    def closeEvent(self, event) -> None:  # type: ignore[override]
        if hasattr(self, "_update_manager") and self._update_manager is not None:
            self._update_manager.shutdown(timeout_ms=1000)
        if hasattr(self, "_update_install_manager") and self._update_install_manager is not None:
            self._update_install_manager.shutdown(timeout_ms=1000)
        if self._planning_save_pending or self._planning_save_timer.isActive():
            self._save_planning_state(immediate=True)
        if self._floating_window is not None:
            self._floating_window.close()
        super().closeEvent(event)

