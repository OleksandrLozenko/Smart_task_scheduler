from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path
import re
from uuid import uuid4

from PySide6.QtCore import QSignalBlocker, QSize, Qt
from PySide6.QtGui import QColor, QIcon, QPaintEvent, QPainter, QPen, QPixmap
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

from app.core.pomodoro_controller import PomodoroController
from app.core.planning_state_manager import PlanningStateManager
from app.core.settings_manager import AppSettings, SettingsManager
from app.core.timer_state import TimerMode, TimerSnapshot, TimerStatus
from app.ui.circular_timer import CircularTimerWidget
from app.ui.floating_timer import FloatingTimerWindow
from app.ui.styles import build_app_stylesheet
from app.ui.week_header import WeekHeader
from app.ui.window_drag import DragHandleFrame
from app.utils.audio_alert import play_completion_alert
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

    def set_highlighted_column(self, column: int | None) -> None:
        normalized = int(column) if isinstance(column, int) and column >= 0 else None
        if normalized == self._highlighted_column:
            return
        self._highlighted_column = normalized
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

        painter.fillRect(x, viewport_rect.top(), width, viewport_rect.height(), QColor(242, 94, 126, 82))
        border_pen = QPen(QColor(255, 182, 199, 210))
        border_pen.setWidth(2)
        painter.setPen(border_pen)
        painter.drawLine(x, viewport_rect.top(), x, viewport_rect.bottom())
        painter.drawLine(x + width - 1, viewport_rect.top(), x + width - 1, viewport_rect.bottom())
        painter.end()


class MainWindow(QMainWindow):
    def __init__(
        self,
        controller: PomodoroController,
        settings: AppSettings,
        settings_manager: SettingsManager,
    ) -> None:
        super().__init__()
        self._controller = controller
        self._controller.set_start_guard(self._can_start_session)
        self._settings = settings
        self._settings_manager = settings_manager
        self._floating_window: FloatingTimerWindow | None = None

        self._sparkles_source = self._load_svg("sparkles.svg")
        self._display_total_seconds = self._controller.duration_for_mode(self._controller.state.mode)
        self._last_mode = self._controller.state.mode
        self._today = date.today()
        self._planning_week_start = self._today - timedelta(days=self._today.weekday())
        self._planning_store = PlanningStateManager()
        self._planning_tasks: list[dict[str, str]] = []
        self._planning_excluded_cells_by_week: dict[str, dict[str, set[int]]] = {}
        self._planning_planned_cells_by_week: dict[str, dict[str, list[int]]] = {}
        self._planning_done_cells_by_week: dict[str, dict[str, list[int]]] = {}
        self._planning_weekly_targets_by_week: dict[str, dict[str, int]] = {}
        self._planning_selected_task_id: str | None = None
        self._planning_selected_day_index: int | None = None
        self._planning_delete_mode = False
        self._planning_exclude_mode = False
        self._day_names_short = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]
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

        self._controller.state.changed.connect(self._on_state_changed)
        self._controller.session_completed.connect(self._on_session_completed)
        self._on_state_changed(self._controller.state.snapshot())
        self._update_planning_week_labels()
        self._apply_responsive_fonts()

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
        self._pomodoro_nav.clicked.connect(lambda: self._switch_page(0))

        self._planning_nav = QPushButton("Планирование", sidebar)
        self._planning_nav.setObjectName("sidebarNavButton")
        self._planning_nav.setCheckable(True)
        self._planning_nav.clicked.connect(lambda: self._switch_page(1))

        self._settings_nav = QPushButton("Настройки", sidebar)
        self._settings_nav.setObjectName("sidebarSettingsButton")
        self._settings_nav.setCheckable(True)
        self._settings_nav.clicked.connect(lambda: self._switch_page(2))

        self._nav_buttons = [self._pomodoro_nav, self._planning_nav, self._settings_nav]

        sidebar_layout.addLayout(title_row)
        sidebar_layout.addWidget(subtitle)
        sidebar_layout.addSpacing(10)
        sidebar_layout.addWidget(self._pomodoro_nav)
        sidebar_layout.addWidget(self._planning_nav)
        sidebar_layout.addStretch(1)
        sidebar_layout.addWidget(self._settings_nav)

        self._stack = QStackedWidget(body)
        self._stack.addWidget(self._build_pomodoro_page())
        self._stack.addWidget(self._build_planning_page())
        self._stack.addWidget(self._build_settings_page())

        body_layout.addWidget(sidebar)
        body_layout.addWidget(self._stack, stretch=1)

        root_layout.addWidget(self._title_bar)
        root_layout.addWidget(body, stretch=1)

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
        self._timer_shell.setMinimumHeight(280)
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
        header = self._planning_table.horizontalHeader()
        header.setStretchLastSection(False)
        header.setDefaultAlignment(Qt.AlignCenter)
        header.setHighlightSections(False)
        header.setSectionResizeMode(0, QHeaderView.Fixed)
        self._planning_table.setColumnWidth(0, 190)
        for col in range(1, 8):
            header.setSectionResizeMode(col, QHeaderView.Stretch)
        header.setSectionResizeMode(8, QHeaderView.Fixed)
        self._planning_table.setColumnWidth(8, 94)

        controls = QHBoxLayout()
        controls.setContentsMargins(0, 0, 0, 0)
        controls.setSpacing(8)

        self._planning_add_task_button = QPushButton(card)
        self._planning_add_task_button.setObjectName("planningIconButton")
        self._planning_add_task_button.setFocusPolicy(Qt.NoFocus)
        self._planning_add_task_button.setFixedSize(34, 34)
        add_icon_path = self._asset_path("add.svg")
        if add_icon_path.exists():
            self._planning_add_task_button.setIcon(QIcon(str(add_icon_path)))
            self._planning_add_task_button.setIconSize(QSize(16, 16))
        self._planning_add_task_button.clicked.connect(self._on_add_planning_task)

        self._planning_exclude_day_button = QPushButton(card)
        self._planning_exclude_day_button.setObjectName("planningIconButton")
        self._planning_exclude_day_button.setCheckable(True)
        self._planning_exclude_day_button.setFocusPolicy(Qt.NoFocus)
        self._planning_exclude_day_button.setFixedSize(34, 34)
        exclude_icon_path = self._asset_path("exclude_day.svg")
        if exclude_icon_path.exists():
            self._planning_exclude_day_button.setIcon(QIcon(str(exclude_icon_path)))
            self._planning_exclude_day_button.setIconSize(QSize(16, 16))
        self._planning_exclude_day_button.toggled.connect(self._on_toggle_planning_exclude_mode)

        self._planning_delete_task_button = QPushButton(card)
        self._planning_delete_task_button.setObjectName("planningIconButton")
        self._planning_delete_task_button.setCheckable(True)
        self._planning_delete_task_button.setFocusPolicy(Qt.NoFocus)
        self._planning_delete_task_button.setFixedSize(34, 34)
        delete_icon_path = self._asset_path("delete.svg")
        if delete_icon_path.exists():
            self._planning_delete_task_button.setIcon(QIcon(str(delete_icon_path)))
            self._planning_delete_task_button.setIconSize(QSize(16, 16))
        self._planning_delete_task_button.toggled.connect(self._on_toggle_planning_delete_mode)

        controls.addWidget(self._planning_add_task_button)
        controls.addWidget(self._planning_exclude_day_button)
        controls.addWidget(self._planning_delete_task_button)
        controls.addStretch(1)

        card_layout.addWidget(self._week_header)
        card_layout.addLayout(controls)
        card_layout.addWidget(self._planning_table, stretch=1)

        layout.addWidget(card, stretch=1)
        self._rebuild_planning_table()
        return page

    def _shift_planning_week(self, offset: int) -> None:
        self._planning_week_start = self._planning_week_start + timedelta(days=7 * int(offset))
        self._update_planning_week_labels()

    def _go_to_current_planning_week(self) -> None:
        self._planning_week_start = self._today - timedelta(days=self._today.weekday())
        self._update_planning_week_labels()

    def _planning_week_key(self) -> str:
        return self._planning_week_start.isoformat()

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
                return task["name"]
        return None

    def _on_toggle_planning_delete_mode(self, enabled: bool) -> None:
        self._planning_delete_mode = bool(enabled)
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
        planned_storage = self._planned_cells_for_current_week()
        done_storage = self._done_cells_for_current_week()
        planned_values = self._week_task_values(planned_storage, task_id)
        done_values = self._week_task_values(done_storage, task_id)
        weekly_target = self._task_weekly_target(task_id)

        if day_index in task_excluded:
            task_excluded.remove(day_index)
            if not task_excluded:
                week_excluded.pop(task_id, None)
            self.statusBar().showMessage("Исключение снято для выбранной ячейки.", 2200)
        else:
            task_excluded.add(day_index)
            planned_values[day_index] = 0
            done_values[day_index] = 0
            self.statusBar().showMessage("День исключен для выбранной задачи.", 2200)
            if self._planning_selected_task_id == task_id and self._planning_selected_day_index == day_index:
                self._planning_selected_day_index = None

        if weekly_target > 0:
            self._distribute_weekly_total_for_task(task_id, weekly_target)

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

    def _set_task_day_plan(self, task_id: str, day_index: int, value: int) -> None:
        week_excluded = self._excluded_cells_for_current_week()
        if day_index in week_excluded.get(task_id, set()):
            self.statusBar().showMessage("Сначала снимите исключение с этого дня.", 2200)
            return

        planned_values = self._week_task_values(self._planned_cells_for_current_week(), task_id)
        done_values = self._week_task_values(self._done_cells_for_current_week(), task_id)
        weekly_target = self._task_weekly_target(task_id)
        current_sum = sum(planned_values)
        requested = max(0, int(value))

        if weekly_target <= 0:
            weekly_target = max(current_sum, requested)
            self._weekly_targets_for_current_week()[task_id] = weekly_target

        pinned_value = min(requested, weekly_target)
        self._distribute_weekly_total_for_task(
            task_id,
            weekly_target,
            pinned_day=day_index,
            pinned_value=pinned_value,
        )
        if requested > pinned_value:
            self.statusBar().showMessage(
                f"Лимит недели {weekly_target} 🍅. Увеличьте «Всего», чтобы поставить больше.",
                3200,
            )
        else:
            done_values[day_index] = min(done_values[day_index], pinned_value)

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
        done_storage = self._done_cells_for_current_week()
        planned_values = self._week_task_values(planned_storage, task_id)
        done_values = self._week_task_values(done_storage, task_id)
        active_days = [idx for idx in range(7) if idx not in excluded_days]

        self._weekly_targets_for_current_week()[task_id] = total

        if not active_days:
            planned_storage[task_id] = [0] * 7
            done_storage[task_id] = [0] * 7
            self.statusBar().showMessage("Нет активных дней для раскладки. Снимите исключение хотя бы с одного дня.", 3200)
            return

        new_plan = [0] * 7
        candidate_days = active_days
        remainder_pool = total
        if (
            pinned_day is not None
            and pinned_value is not None
            and 0 <= int(pinned_day) <= 6
            and int(pinned_day) in active_days
        ):
            pinned_day = int(pinned_day)
            pinned_value = max(0, min(int(pinned_value), total))
            new_plan[pinned_day] = pinned_value
            remainder_pool = total - pinned_value
            candidate_days = [idx for idx in active_days if idx != pinned_day]

        if remainder_pool > 0 and candidate_days:
            base = remainder_pool // len(candidate_days)
            remainder = remainder_pool % len(candidate_days)
            for pos, day_index in enumerate(candidate_days):
                new_plan[day_index] = base + (1 if pos < remainder else 0)
        planned_storage[task_id] = new_plan
        done_storage[task_id] = [min(done_values[idx], new_plan[idx]) for idx in range(7)]

        if self._planning_selected_task_id == task_id:
            if self._planning_selected_day_index is None:
                self._planning_selected_day_index = active_days[0]
            elif self._planning_selected_day_index in excluded_days:
                self._planning_selected_day_index = active_days[0]

    def _delete_planning_task_by_id(self, task_id: str) -> None:
        idx = next((i for i, task in enumerate(self._planning_tasks) if task["id"] == task_id), -1)
        if idx < 0:
            return
        removed_name = self._planning_tasks[idx]["name"]
        self._planning_tasks.pop(idx)

        for week_map in self._planning_excluded_cells_by_week.values():
            week_map.pop(task_id, None)
        for week_map in self._planning_planned_cells_by_week.values():
            week_map.pop(task_id, None)
        for week_map in self._planning_done_cells_by_week.values():
            week_map.pop(task_id, None)
        for week_map in self._planning_weekly_targets_by_week.values():
            week_map.pop(task_id, None)

        if self._planning_selected_task_id == task_id:
            self._planning_selected_task_id = None
            self._planning_selected_day_index = None

        self._save_planning_state()
        self.statusBar().showMessage(f"Задача «{removed_name}» удалена.", 2200)
        self._rebuild_planning_table()
        self._on_state_changed(self._controller.state.snapshot())

    def _on_planning_cell_clicked(self, row: int, column: int) -> None:
        if not (0 <= row < len(self._planning_tasks)):
            return
        task = self._planning_tasks[row]
        self._planning_selected_task_id = task["id"]
        task_id = task["id"]

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
            current_total = self._task_weekly_target(task_id) or sum(planned_values)
            total = self._prompt_weekly_total(task["name"], current_total)
            if total is None:
                return
            self._distribute_weekly_total_for_task(task_id, total)
            self.statusBar().showMessage("План на неделю распределен по активным дням.", 2600)
        elif 1 <= column <= 7:
            day_index = column - 1
            excluded = self._excluded_cells_for_current_week().get(task_id, set())
            if day_index in excluded:
                self.statusBar().showMessage("Этот день исключен для выбранной задачи.", 2200)
            else:
                is_same_day = (
                    self._planning_selected_task_id == task_id
                    and self._planning_selected_day_index == day_index
                )
                if is_same_day:
                    current_value = self._week_task_values(self._planned_cells_for_current_week(), task_id)[day_index]
                    custom_value = self._prompt_day_plan(task["name"], day_index, current_value)
                    if custom_value is not None:
                        self._set_task_day_plan(task_id, day_index, custom_value)
                        self.statusBar().showMessage("План для дня обновлен.", 2000)
                else:
                    self._planning_selected_day_index = day_index
                    self.statusBar().showMessage("День выбран для Pomodoro. Повторный клик — изменить количество.", 2200)
        else:
            self.statusBar().showMessage("Задача выбрана для Pomodoro.", 1800)
            if self._settings.planning_auto_switch_to_timer_on_select:
                self._switch_page(0)

        self._save_planning_state()
        self._update_planning_week_labels()
        self._on_state_changed(self._controller.state.snapshot())

    def _on_add_planning_task(self) -> None:
        title = self._prompt_planning_task_name()
        if title is None:
            return
        title = self._repair_task_name(title)
        if not title:
            return
        task_id = uuid4().hex
        self._planning_tasks.append({"id": task_id, "name": title})
        self._planning_selected_task_id = task_id
        self._planning_selected_day_index = self._today.weekday()
        self._save_planning_state()
        self._rebuild_planning_table()
        self._on_state_changed(self._controller.state.snapshot())

    def _prompt_planning_task_name(self) -> str | None:
        dialog = QDialog(self)
        dialog.setObjectName("planningTaskDialog")
        dialog.setWindowTitle("Добавить задачу")
        dialog.setMinimumWidth(420)

        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(10)

        caption = QLabel("Название задачи", dialog)
        caption.setObjectName("planningTaskLabel")
        edit = QLineEdit(dialog)
        edit.setObjectName("planningTaskInput")
        edit.setPlaceholderText("Например: Английский")
        edit.setFocus()

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel, dialog)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)

        layout.addWidget(caption)
        layout.addWidget(edit)
        layout.addWidget(buttons)

        if dialog.exec() != QDialog.Accepted:
            return None
        title = self._repair_task_name(edit.text().strip())
        if not title:
            return None
        return title

    def _rebuild_planning_table(self) -> None:
        if not hasattr(self, "_planning_table"):
            return
        self._planning_table.blockSignals(True)
        try:
            rows = len(self._planning_tasks)
            self._planning_table.setRowCount(rows)
            for row, task in enumerate(self._planning_tasks):
                self._planning_table.setRowHeight(row, max(40, min(84, self._settings.planning_row_height)))
                self._planning_table.setCellWidget(row, 0, None)
                task_item = QTableWidgetItem(task["name"])
                task_item.setTextAlignment(Qt.AlignVCenter | Qt.AlignLeft)
                task_item.setData(Qt.UserRole, task["id"])
                self._planning_table.setItem(row, 0, task_item)
                for col in range(1, 9):
                    item = QTableWidgetItem("")
                    item.setTextAlignment(Qt.AlignCenter)
                    self._planning_table.setItem(row, col, item)
        finally:
            self._planning_table.blockSignals(False)

        self._refresh_planning_column_visuals()

    def _delete_selected_planning_task(self) -> None:
        task_id = self._planning_selected_task_id
        if not task_id:
            self.statusBar().showMessage("Сначала выберите задачу (ячейку в столбце «Задача»).", 2500)
            return
        self._delete_planning_task_by_id(task_id)

    def _refresh_planning_column_visuals(self) -> None:
        if not hasattr(self, "_planning_table"):
            return
        week_excluded = self._excluded_cells_for_current_week()
        week_planned = self._planned_cells_for_current_week()
        week_done = self._done_cells_for_current_week()
        current_week_start = self._today - timedelta(days=self._today.weekday())
        today_day_index = self._today.weekday() if self._planning_week_start == current_week_start else None
        base_font_size = max(12, min(22, self._settings.planning_table_font_size))
        normal_size = max(10, base_font_size - 2)
        selected_size = max(11, base_font_size - 1)
        cross_size = min(28, base_font_size + 6)

        for row in range(self._planning_table.rowCount()):
            task_item = self._planning_table.item(row, 0)
            task_id = ""
            is_selected = False
            if task_item is not None:
                task_id = str(task_item.data(Qt.UserRole) or "")
                is_selected = task_id == self._planning_selected_task_id
                task_item.setForeground(QColor(255, 250, 250, 248))
                task_item.setBackground(QColor(142, 26, 52, 242) if is_selected else QColor(0, 0, 0, 28))
                task_font = task_item.font()
                task_font.setPointSize(selected_size if is_selected else normal_size)
                task_font.setBold(is_selected)
                task_item.setFont(task_font)
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
                    item.setBackground(QColor(140, 28, 54, 245) if is_today_column else QColor(112, 16, 34, 236))
                    item.setForeground(QColor(255, 240, 240, 245))
                    cross_font = item.font()
                    cross_font.setBold(True)
                    cross_font.setPointSize(cross_size)
                    item.setFont(cross_font)
                    item.setText("✕")
                    item.setIcon(QIcon())
                elif is_selected_day:
                    item.setBackground(QColor(248, 120, 146, 252))
                    item.setForeground(QColor(255, 250, 250, 255))
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
                    item.setBackground(QColor(230, 90, 122, 248) if is_selected else QColor(220, 82, 112, 230))
                    item.setForeground(QColor(255, 248, 248, 255))
                    normal_font = item.font()
                    normal_font.setBold(is_selected)
                    normal_font.setPointSize(selected_size if is_selected else normal_size)
                    item.setFont(normal_font)
                    planned = planned_values[day_idx]
                    done = min(done_values[day_idx], planned)
                    text, icon = self._planning_progress_repr(done, planned)
                    item.setIcon(icon)
                    item.setText(text)
                else:
                    item.setBackground(QColor(136, 28, 50, 196) if is_selected else QColor(0, 0, 0, 24))
                    item.setForeground(QColor(255, 246, 246, 230))
                    normal_font = item.font()
                    normal_font.setBold(is_selected)
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
                total_target = self._task_weekly_target(task_id) if task_id else 0
                if total_target <= 0:
                    total_target = total_planned
                total_text, total_icon = self._planning_progress_repr(total_done, total_target)
                total_item.setText(total_text if total_text else "0")
                total_item.setIcon(total_icon)
                total_item.setForeground(QColor(255, 247, 247, 246))
                total_item.setBackground(QColor(123, 34, 56, 214) if is_selected else QColor(0, 0, 0, 28))
                total_font = total_item.font()
                total_font.setBold(is_selected or total_target > 0)
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
        header_size = max(11, min(18, self._settings.planning_table_font_size - 1))
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
                header_item.setBackground(QColor(126, 35, 58, 235))
                header_item.setForeground(QColor(255, 245, 245, 250))
                font.setBold(True)
                font.setPointSize(header_size + 1)
            elif col == 8:
                header_item.setBackground(QColor(162, 61, 87, 232))
                header_item.setForeground(QColor(255, 246, 246, 252))
                font.setBold(True)
                font.setPointSize(header_size)
            elif today_index is not None and col == today_index + 1:
                header_item.setBackground(QColor(220, 84, 114, 245))
                header_item.setForeground(QColor(255, 250, 250, 255))
                font.setBold(True)
                font.setPointSize(header_size + 1)
            else:
                header_item.setBackground(QColor(154, 52, 79, 220))
                header_item.setForeground(QColor(255, 244, 244, 240))
                font.setBold(True)
                font.setPointSize(header_size)
            header_item.setFont(font)

        self._planning_table.set_highlighted_column(today_index + 1 if today_index is not None else None)
        self._refresh_planning_column_visuals()

    def _load_planning_state(self) -> None:
        raw = self._planning_store.load()
        tasks_raw = raw.get("tasks", [])
        excluded_raw = raw.get("excluded_cells", {})
        planned_raw = raw.get("planned_cells", {})
        done_raw = raw.get("done_cells", {})
        weekly_targets_raw = raw.get("weekly_targets", {})
        selected_task_id = raw.get("selected_task_id")
        selected_day_index = raw.get("selected_day_index")

        loaded_tasks: list[dict[str, str]] = []
        if isinstance(tasks_raw, list):
            for item in tasks_raw:
                if isinstance(item, dict):
                    task_id = str(item.get("id") or uuid4().hex)
                    task_name = self._repair_task_name(str(item.get("name") or "").strip())
                    if task_name:
                        loaded_tasks.append({"id": task_id, "name": task_name})
                elif isinstance(item, str):
                    name = self._repair_task_name(item.strip())
                    if name:
                        loaded_tasks.append({"id": uuid4().hex, "name": name})
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
        self._planning_done_cells_by_week = _normalize_week_values(done_raw)
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

        task_ids = {task["id"] for task in self._planning_tasks}
        self._planning_selected_task_id = (
            selected_task_id if isinstance(selected_task_id, str) and selected_task_id in task_ids else None
        )
        self._planning_selected_day_index = (
            int(selected_day_index)
            if isinstance(selected_day_index, int) and 0 <= int(selected_day_index) <= 6
            else None
        )
        # Persist normalized names/data immediately so legacy mojibake does not return.
        self._save_planning_state()

    def _save_planning_state(self) -> None:
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
            "Задайте длительности сессий и поведение плавающего таймера. Изменения применяются сразу после сохранения.",
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

        self._settings_launch_maximized = QCheckBox("Открывать приложение развернутым", general_box)
        self._settings_show_sidebar_icons = QCheckBox("Показывать SVG-иконки в боковом меню", general_box)

        general_layout.addRow("Тема интерфейса", self._settings_theme_name)
        general_layout.addRow("", self._settings_launch_maximized)
        general_layout.addRow("", self._settings_show_sidebar_icons)

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
        self._settings_main_timer_scale_percent.setRange(65, 98)
        self._settings_main_timer_scale_percent.setSuffix(" %")

        self._settings_main_card_opacity_percent = NoWheelSpinBox(main_box)
        self._settings_main_card_opacity_percent.setRange(72, 100)
        self._settings_main_card_opacity_percent.setSuffix(" %")

        main_layout.addRow("Помодоро", self._settings_pomodoro)
        main_layout.addRow("Короткий перерыв", self._settings_short_break)
        main_layout.addRow("Длинный перерыв", self._settings_long_break)
        main_layout.addRow("Длинный перерыв после", self._settings_long_break_interval)
        main_layout.addRow("Высота кнопки СТАРТ", self._settings_main_start_button_height)
        main_layout.addRow("Масштаб круга таймера", self._settings_main_timer_scale_percent)
        main_layout.addRow("Прозрачность карточек", self._settings_main_card_opacity_percent)

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

        self._settings_planning_visual_max_symbols = NoWheelSpinBox(planning_box)
        self._settings_planning_visual_max_symbols.setRange(3, 16)
        self._settings_planning_visual_max_symbols.setSuffix(" шт")

        self._settings_planning_row_height = NoWheelSpinBox(planning_box)
        self._settings_planning_row_height.setRange(40, 84)
        self._settings_planning_row_height.setSuffix(" px")

        self._settings_planning_table_font_size = NoWheelSpinBox(planning_box)
        self._settings_planning_table_font_size.setRange(12, 22)
        self._settings_planning_table_font_size.setSuffix(" px")

        self._settings_planning_auto_switch_to_timer = QCheckBox(
            "Автопереход в Pomodoro при выборе задачи",
            planning_box,
        )

        self._settings_planning_progress_view.currentIndexChanged.connect(
            self._on_planning_settings_view_mode_changed
        )

        planning_layout.addRow("Формат прогресса", self._settings_planning_progress_view)
        planning_layout.addRow("Тип визуализации", self._settings_planning_visual_style)
        planning_layout.addRow("Макс. иконок в ячейке", self._settings_planning_visual_max_symbols)
        planning_layout.addRow("Высота строки таблицы", self._settings_planning_row_height)
        planning_layout.addRow("Размер шрифта таблицы", self._settings_planning_table_font_size)
        planning_layout.addRow("", self._settings_planning_auto_switch_to_timer)

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
        card_layout.addWidget(main_box)
        card_layout.addWidget(planning_box)
        card_layout.addWidget(floating_box)
        card_layout.addLayout(buttons)

        scroll_content_layout.addWidget(card)
        scroll.setWidget(scroll_content)
        layout.addWidget(scroll, stretch=1)
        self._populate_settings_form()
        return page

    def _populate_settings_form(self, source: AppSettings | None = None) -> None:
        source_settings = self._settings if source is None else source
        widgets = [
            self._settings_theme_name,
            self._settings_launch_maximized,
            self._settings_show_sidebar_icons,
            self._settings_pomodoro,
            self._settings_short_break,
            self._settings_long_break,
            self._settings_long_break_interval,
            self._settings_main_start_button_height,
            self._settings_main_timer_scale_percent,
            self._settings_main_card_opacity_percent,
            self._settings_planning_progress_view,
            self._settings_planning_visual_style,
            self._settings_planning_visual_max_symbols,
            self._settings_planning_row_height,
            self._settings_planning_table_font_size,
            self._settings_planning_auto_switch_to_timer,
            self._settings_always_on_top_default,
            self._settings_floating_opacity_percent,
            self._settings_floating_pin_button_size,
            self._settings_floating_blink_enabled,
            self._settings_floating_blink_threshold_seconds,
        ]
        for widget in widgets:
            with QSignalBlocker(widget):
                if widget is self._settings_theme_name:
                    index = self._settings_theme_name.findData(source_settings.theme_name)
                    self._settings_theme_name.setCurrentIndex(0 if index < 0 else index)
                elif widget is self._settings_launch_maximized:
                    widget.setChecked(source_settings.launch_maximized)
                elif widget is self._settings_show_sidebar_icons:
                    widget.setChecked(source_settings.show_sidebar_icons)
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
                elif widget is self._settings_planning_visual_max_symbols:
                    widget.setValue(source_settings.planning_visual_max_symbols)
                elif widget is self._settings_planning_row_height:
                    widget.setValue(source_settings.planning_row_height)
                elif widget is self._settings_planning_table_font_size:
                    widget.setValue(source_settings.planning_table_font_size)
                elif widget is self._settings_planning_auto_switch_to_timer:
                    widget.setChecked(source_settings.planning_auto_switch_to_timer_on_select)
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

    def _on_planning_settings_view_mode_changed(self, _index: int | None = None) -> None:
        is_visual = str(self._settings_planning_progress_view.currentData()) == "visual"
        self._settings_planning_visual_style.setEnabled(is_visual)
        self._settings_planning_visual_max_symbols.setEnabled(is_visual)

    def _reset_settings_form_to_defaults(self) -> None:
        self._populate_settings_form(AppSettings())
        self.statusBar().showMessage(
            "Выставлены значения по умолчанию. Нажмите «Сохранить настройки», чтобы применить.",
            4500,
        )

    def _save_settings_page(self) -> None:
        new_settings = AppSettings(
            pomodoro_minutes=self._settings_pomodoro.value(),
            short_break_minutes=self._settings_short_break.value(),
            long_break_minutes=self._settings_long_break.value(),
            long_break_interval=self._settings_long_break_interval.value(),
            theme_name=str(self._settings_theme_name.currentData()),
            launch_maximized=self._settings_launch_maximized.isChecked(),
            show_sidebar_icons=self._settings_show_sidebar_icons.isChecked(),
            main_start_button_height=self._settings_main_start_button_height.value(),
            main_timer_scale_percent=self._settings_main_timer_scale_percent.value(),
            main_card_opacity_percent=self._settings_main_card_opacity_percent.value(),
            planning_progress_view=str(self._settings_planning_progress_view.currentData()),
            planning_visual_style=str(self._settings_planning_visual_style.currentData()),
            planning_visual_max_symbols=self._settings_planning_visual_max_symbols.value(),
            planning_row_height=self._settings_planning_row_height.value(),
            planning_table_font_size=self._settings_planning_table_font_size.value(),
            planning_auto_switch_to_timer_on_select=self._settings_planning_auto_switch_to_timer.isChecked(),
            always_on_top_default=self._settings_always_on_top_default.isChecked(),
            floating_opacity_percent=self._settings_floating_opacity_percent.value(),
            floating_pin_button_size=self._settings_floating_pin_button_size.value(),
            floating_blink_enabled=self._settings_floating_blink_enabled.isChecked(),
            floating_blink_threshold_seconds=self._settings_floating_blink_threshold_seconds.value(),
            auto_start_breaks=False,
            auto_start_pomodoros=False,
        )
        self._apply_settings(new_settings)

    def _apply_theme_and_visual_settings(self) -> None:
        app = QApplication.instance()
        if app is not None:
            app.setStyleSheet(
                build_app_stylesheet(
                    theme_name=self._settings.theme_name,
                    main_card_opacity_percent=self._settings.main_card_opacity_percent,
                    main_start_button_height=self._settings.main_start_button_height,
                )
            )
        self._apply_sidebar_icons(self._settings.show_sidebar_icons)
        self._apply_ring_palette(self._settings.theme_name)
        self._apply_planning_visual_settings()

    def _apply_sidebar_icons(self, enabled: bool) -> None:
        icon_paths = [
            (self._pomodoro_nav, "nav_timer.svg"),
            (self._planning_nav, "nav_plan.svg"),
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
        self._refresh_planning_column_visuals()

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
        if index == 2:
            self._populate_settings_form()
        for i, button in enumerate(self._nav_buttons):
            with QSignalBlocker(button):
                button.setChecked(i == index)

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
            self._apply_floating_visual_settings()

        self._floating_window.show()
        self._floating_window.raise_()
        self._floating_window.activateWindow()

    def _on_floating_closed(self, _obj=None) -> None:
        self._floating_window = None

    def _mode_minutes(self) -> dict[TimerMode, int]:
        return {
            TimerMode.POMODORO: self._settings.pomodoro_minutes,
            TimerMode.SHORT_BREAK: self._settings.short_break_minutes,
            TimerMode.LONG_BREAK: self._settings.long_break_minutes,
        }

    def _apply_settings(self, settings: AppSettings, *, show_message: bool = True) -> None:
        self._settings = settings
        self._settings_manager.save(settings)

        self._apply_theme_and_visual_settings()
        self._controller.update_configuration(
            self._mode_minutes(),
            long_break_interval=settings.long_break_interval,
        )
        self._apply_floating_visual_settings()

        self._populate_settings_form()
        self._apply_responsive_fonts()

        if show_message:
            self.statusBar().showMessage("Настройки сохранены.", 3500)

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

        if planned <= 0:
            progress_text = f"{day_name}: задайте количество через «Всего»."
        elif done >= planned:
            progress_text = f"{day_name}: план выполнен ({done}/{planned})."
        else:
            progress_text = f"{day_name}: {done}/{planned} помидоров."

        if snapshot.mode is TimerMode.POMODORO:
            return cycle_text, progress_text
        return cycle_text, f"{snapshot.mode.hint} {progress_text}"

    def _on_session_completed(self, finished_mode: str, next_mode: str) -> None:
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
                done_values = self._week_task_values(self._done_cells_for_current_week(), task_id)
                if planned > 0 and done_values[day_index] < planned:
                    done_values[day_index] += 1
                    self._save_planning_state()
                    self._refresh_planning_column_visuals()

        play_completion_alert()
        self.statusBar().showMessage(
            f"Режим «{finished_mode}» завершен. Далее: «{next_mode}». Нажмите СТАРТ.",
            5500,
        )
        self._on_state_changed(self._controller.state.snapshot())

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
        side_padding = 70
        available = max(140, min(shell_width - side_padding, shell_height - 26))
        scale = max(65, min(98, self._settings.main_timer_scale_percent)) / 100.0
        ring_size = int(available * scale)
        self._circular_timer.setFixedSize(ring_size, ring_size)

        if not self._sparkles_source.isNull():
            spark = self._sparkles_source.scaled(22, 22, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            self._sidebar_sparkles.setPixmap(spark)

    def resizeEvent(self, event) -> None:  # type: ignore[override]
        super().resizeEvent(event)
        self._update_window_buttons()
        self._apply_responsive_fonts()

    def closeEvent(self, event) -> None:  # type: ignore[override]
        if self._floating_window is not None:
            self._floating_window.close()
        super().closeEvent(event)

