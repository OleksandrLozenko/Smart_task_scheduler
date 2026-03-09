from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QSpinBox,
    QVBoxLayout,
)

from app.core.settings_manager import AppSettings


class SettingsDialog(QDialog):
    def __init__(self, settings: AppSettings, parent=None) -> None:
        super().__init__(parent)
        self._source_settings = settings

        self.setWindowTitle("Настройки")
        self.setModal(True)
        self.resize(440, 320)

        layout = QVBoxLayout(self)
        form = QFormLayout()
        form.setHorizontalSpacing(18)
        form.setVerticalSpacing(12)

        self._pomodoro = QSpinBox(self)
        self._pomodoro.setRange(1, 180)
        self._pomodoro.setValue(settings.pomodoro_minutes)

        self._short_break = QSpinBox(self)
        self._short_break.setRange(1, 90)
        self._short_break.setValue(settings.short_break_minutes)

        self._long_break = QSpinBox(self)
        self._long_break.setRange(1, 180)
        self._long_break.setValue(settings.long_break_minutes)

        self._long_break_interval = QSpinBox(self)
        self._long_break_interval.setRange(2, 6)
        self._long_break_interval.setValue(settings.long_break_interval)

        self._always_on_top_default = QCheckBox("Плавающий таймер сразу поверх окон", self)
        self._always_on_top_default.setChecked(settings.always_on_top_default)

        form.addRow("Помодоро (мин)", self._pomodoro)
        form.addRow("Короткий перерыв (мин)", self._short_break)
        form.addRow("Длинный перерыв (мин)", self._long_break)
        form.addRow("Длинный перерыв после N помодоро", self._long_break_interval)
        form.addRow("", self._always_on_top_default)

        note = QLabel(
            "После завершения сессии происходит только переключение режима. Следующий таймер запускается вручную кнопкой СТАРТ.",
            self,
        )
        note.setWordWrap(True)
        note.setObjectName("settingsHint")

        buttons = QDialogButtonBox(
            QDialogButtonBox.Save | QDialogButtonBox.Cancel,
            parent=self,
        )
        save_button = buttons.button(QDialogButtonBox.Save)
        cancel_button = buttons.button(QDialogButtonBox.Cancel)
        if save_button is not None:
            save_button.setText("Сохранить")
        if cancel_button is not None:
            cancel_button.setText("Отмена")

        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout.addLayout(form)
        layout.addWidget(note)
        layout.addWidget(buttons)

    def to_settings(self) -> AppSettings:
        return AppSettings(
            pomodoro_minutes=self._pomodoro.value(),
            short_break_minutes=self._short_break.value(),
            long_break_minutes=self._long_break.value(),
            long_break_interval=self._long_break_interval.value(),
            always_on_top_default=self._always_on_top_default.isChecked(),
            auto_start_breaks=False,
            auto_start_pomodoros=False,
        )
