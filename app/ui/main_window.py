from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSignalBlocker, QSize, Qt
from PySide6.QtGui import QColor, QIcon, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QFrame,
    QFormLayout,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from app.core.pomodoro_controller import PomodoroController
from app.core.settings_manager import AppSettings, SettingsManager
from app.core.timer_state import TimerMode, TimerSnapshot, TimerStatus
from app.ui.circular_timer import CircularTimerWidget
from app.ui.floating_timer import FloatingTimerWindow
from app.ui.styles import build_app_stylesheet
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


class MainWindow(QMainWindow):
    def __init__(
        self,
        controller: PomodoroController,
        settings: AppSettings,
        settings_manager: SettingsManager,
    ) -> None:
        super().__init__()
        self._controller = controller
        self._settings = settings
        self._settings_manager = settings_manager
        self._floating_window: FloatingTimerWindow | None = None

        self._sparkles_source = self._load_svg("sparkles.svg")
        self._display_total_seconds = self._controller.duration_for_mode(self._controller.state.mode)
        self._last_mode = self._controller.state.mode

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
        self._primary_button.clicked.connect(self._controller.toggle_primary)

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
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addStretch(1)

        box = QFrame(page)
        box.setObjectName("planningCard")
        box.setMaximumWidth(760)

        box_layout = QVBoxLayout(box)
        box_layout.setContentsMargins(30, 30, 30, 30)

        title = QLabel("Планирование", box)
        title.setObjectName("planningTitle")
        title.setAlignment(Qt.AlignCenter)

        text = QLabel("Раздел пока пустой. Здесь будет дневное планирование.", box)
        text.setObjectName("planningText")
        text.setAlignment(Qt.AlignCenter)

        box_layout.addWidget(title)
        box_layout.addSpacing(8)
        box_layout.addWidget(text)

        layout.addWidget(box, alignment=Qt.AlignHCenter)
        layout.addStretch(1)
        return page

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

        self._circular_timer.set_palette(
            track=QColor(222, 243, 255, 84),
            progress=QColor(108, 194, 234, 255),
            time_text=QColor(255, 255, 255, 250),
            mode_text=QColor(223, 241, 252, 228),
        )

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
        self._cycle_label.setText(snapshot.cycle_label)
        self._status_label.setText(snapshot.mode.hint)

    def _ring_mode_text(self, mode: TimerMode) -> str:
        if mode is TimerMode.POMODORO:
            return "ФОКУС"
        if mode is TimerMode.SHORT_BREAK:
            return "ПАУЗА"
        return "ДЛИННАЯ ПАУЗА"

    def _on_session_completed(self, finished_mode: str, next_mode: str) -> None:
        play_completion_alert()
        self.statusBar().showMessage(
            f"Режим «{finished_mode}» завершен. Далее: «{next_mode}». Нажмите СТАРТ.",
            5500,
        )

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
