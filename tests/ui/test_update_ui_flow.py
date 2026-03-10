from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from app.core.app_paths import get_app_paths
from app.core.pomodoro_controller import PomodoroController
from app.core.settings_manager import SettingsManager
from app.core.timer_state import TimerMode, TimerState
from app.core.update_service import UpdateCheckResult
from app.ui.main_window import MainWindow


class UpdateUiFlowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        root = Path(self._tmp.name)
        self._appdata = root / "appdata"
        self._localappdata = root / "localappdata"
        self._appdata.mkdir(parents=True, exist_ok=True)
        self._localappdata.mkdir(parents=True, exist_ok=True)

        self._old_appdata = os.environ.get("APPDATA")
        self._old_localappdata = os.environ.get("LOCALAPPDATA")
        os.environ["APPDATA"] = str(self._appdata)
        os.environ["LOCALAPPDATA"] = str(self._localappdata)
        get_app_paths.cache_clear()

        settings_path = self._appdata / "FlowGrid" / "settings.json"
        settings_manager = SettingsManager(settings_path)
        settings = settings_manager.load()
        settings.auto_check_updates_on_start = False
        settings.updates_manifest_url = "file:///C:/tmp/update_manifest.json"
        settings_manager.save(settings)

        state = TimerState(
            initial_mode=TimerMode.POMODORO,
            initial_seconds=settings.pomodoro_minutes * 60,
        )
        controller = PomodoroController(
            state=state,
            mode_minutes={
                TimerMode.POMODORO: settings.pomodoro_minutes,
                TimerMode.SHORT_BREAK: settings.short_break_minutes,
                TimerMode.LONG_BREAK: settings.long_break_minutes,
            },
            long_break_interval=settings.long_break_interval,
        )
        self.window = MainWindow(
            controller=controller,
            settings=settings,
            settings_manager=settings_manager,
            app_version="0.6.0",
        )
        self.window.show()
        self._app.processEvents()

    def tearDown(self) -> None:
        self.window.close()
        self._app.processEvents()
        get_app_paths.cache_clear()
        if self._old_appdata is None:
            os.environ.pop("APPDATA", None)
        else:
            os.environ["APPDATA"] = self._old_appdata
        if self._old_localappdata is None:
            os.environ.pop("LOCALAPPDATA", None)
        else:
            os.environ["LOCALAPPDATA"] = self._old_localappdata
        self._tmp.cleanup()

    def _result(
        self,
        *,
        latest_version: str,
        update_available: bool,
        download_url: str = "file:///C:/updates/update.zip",
        sha256: str = "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
        release_notes: str = "Fixes",
    ) -> UpdateCheckResult:
        return UpdateCheckResult(
            current_version="0.6.0",
            latest_version=latest_version,
            minimum_supported_version="0.5.0",
            is_update_available=update_available,
            is_current_version_supported=True,
            release_notes=release_notes,
            download_url=download_url,
            sha256=sha256,
            published_at="2026-03-10T12:00:00Z",
        )

    def test_auto_check_start_is_non_blocking_and_triggers_manager(self) -> None:
        self.window._settings.auto_check_updates_on_start = True
        self.window._settings.last_update_check_attempt_at = ""
        start_mock = Mock(return_value=True)
        self.window._update_manager.start_check = start_mock  # type: ignore[method-assign]

        self.window._run_startup_update_check_if_due()
        self._app.processEvents()

        start_mock.assert_called_once()

    def test_updates_nav_hidden_from_sidebar(self) -> None:
        self.assertFalse(self.window._updates_nav.isVisible())

    def test_footer_appears_when_update_available(self) -> None:
        self.window._update_check_origin = "auto"
        self.window._update_check_show_popups = False
        self.window._on_update_check_finished(
            self._result(latest_version="0.7.0", update_available=True)
        )
        self._app.processEvents()
        self.assertTrue(self.window._update_footer.isVisible())

    def test_footer_hidden_when_up_to_date(self) -> None:
        self.window._update_check_origin = "auto"
        self.window._update_check_show_popups = False
        self.window._on_update_check_finished(
            self._result(
                latest_version="0.6.0",
                update_available=False,
                download_url="",
                sha256="",
            )
        )
        self._app.processEvents()
        self.assertFalse(self.window._update_footer.isVisible())

    def test_footer_dismiss_is_version_specific(self) -> None:
        self.window._update_check_origin = "auto"
        self.window._update_check_show_popups = False
        self.window._on_update_check_finished(
            self._result(latest_version="0.7.0", update_available=True)
        )
        self._app.processEvents()
        self.assertTrue(self.window._update_footer.isVisible())

        self.window._update_footer_hide_button.click()
        self._app.processEvents()
        self.assertEqual(self.window._settings.dismissed_update_version, "0.7.0")
        self.assertFalse(self.window._update_footer.isVisible())

        self.window._on_update_check_finished(
            self._result(latest_version="0.7.0", update_available=True)
        )
        self._app.processEvents()
        self.assertFalse(self.window._update_footer.isVisible())

        self.window._on_update_check_finished(
            self._result(latest_version="0.8.0", update_available=True)
        )
        self._app.processEvents()
        self.assertTrue(self.window._update_footer.isVisible())

    def test_manual_check_resets_dismiss_for_same_version(self) -> None:
        self.window._settings.dismissed_update_version = "0.7.0"
        self.window._update_check_origin = "manual"
        self.window._update_check_show_popups = False
        self.window._on_update_check_finished(
            self._result(latest_version="0.7.0", update_available=True)
        )
        self._app.processEvents()
        self.assertEqual(self.window._settings.dismissed_update_version, "")
        self.assertTrue(self.window._update_footer.isVisible())

    def test_footer_update_button_opens_updates_page(self) -> None:
        self.window._update_check_origin = "auto"
        self.window._update_check_show_popups = False
        self.window._switch_page(self.window.PAGE_POMODORO)
        self.window._on_update_check_finished(
            self._result(latest_version="0.7.0", update_available=True)
        )
        self._app.processEvents()

        self.window._update_footer_open_button.click()
        self._app.processEvents()
        self.assertEqual(self.window._stack.currentIndex(), self.window.PAGE_UPDATES)

    def test_release_notes_rendered_on_updates_page(self) -> None:
        notes = "Release section updated.\n- Added footer banner.\n- Improved status rendering."
        self.window._update_check_origin = "auto"
        self.window._update_check_show_popups = False
        self.window._on_update_check_finished(
            self._result(latest_version="0.7.0", update_available=True, release_notes=notes)
        )
        self.window._switch_page(self.window.PAGE_UPDATES)
        self._app.processEvents()
        self.assertIn("Release section updated.", self.window._updates_release_summary_value.text())
        details_text = self.window._updates_release_notes_value.text()
        self.assertIn("Added footer banner.", details_text)
        self.assertIn("Improved status rendering.", details_text)

    def test_install_button_enabled_only_for_installable_update(self) -> None:
        self.window._update_check_origin = "auto"
        self.window._update_check_show_popups = False
        self.window._on_update_check_finished(
            self._result(
                latest_version="0.7.0",
                update_available=True,
                sha256="",
            )
        )
        self._app.processEvents()
        self.assertFalse(self.window._updates_install_button.isEnabled())

        self.window._on_update_check_finished(
            self._result(latest_version="0.7.0", update_available=True)
        )
        self._app.processEvents()
        self.assertTrue(self.window._updates_install_button.isEnabled())


if __name__ == "__main__":
    unittest.main()
