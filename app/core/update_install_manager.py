from __future__ import annotations

import os
import re
import shutil

from PySide6.QtCore import QCoreApplication, QObject, QThread, Signal, Slot

from app.core.app_paths import get_app_paths
from app.core.update_downloader import UpdateDownloadError, download_update_package
from app.core.update_installer import (
    UpdateInstallError,
    launch_updater,
    prepare_install_context,
)
from app.core.update_service import UpdateCheckResult


class _UpdateInstallWorker(QObject):
    finished = Signal(str)
    failed = Signal(str)
    status_changed = Signal(str)

    def __init__(self, *, update_result: UpdateCheckResult) -> None:
        super().__init__()
        self._update_result = update_result

    @Slot()
    def run(self) -> None:
        context = None
        try:
            update = self._update_result
            download_url = str(update.download_url or "").strip()
            expected_sha = str(update.sha256 or "").strip().lower()
            if not download_url:
                raise UpdateInstallError("Manifest does not contain update package URL.")
            if not expected_sha:
                raise UpdateInstallError("Manifest does not contain package sha256.")
            if not re.fullmatch(r"[0-9a-f]{64}", expected_sha):
                raise UpdateInstallError("Manifest sha256 has invalid format.")

            self.status_changed.emit("Preparing update...")
            context = prepare_install_context(
                app_paths=get_app_paths(),
                target_version=update.latest_version,
            )

            self.status_changed.emit("Downloading update...")
            last_percent = -1

            def _on_progress(downloaded: int, total: int | None) -> None:
                nonlocal last_percent
                if not total or total <= 0:
                    return
                percent = int((downloaded / total) * 100)
                if percent >= last_percent + 5 or percent == 100:
                    last_percent = percent
                    self.status_changed.emit(f"Downloading update... {percent}%")

            downloaded = download_update_package(
                download_url=download_url,
                destination_path=context.package_zip_path,
                timeout_seconds=30,
                progress_callback=_on_progress,
            )

            self.status_changed.emit("Verifying checksum...")
            if downloaded.sha256_hex.lower() != expected_sha:
                try:
                    downloaded.file_path.unlink(missing_ok=True)
                except OSError:
                    pass
                raise UpdateInstallError("Checksum mismatch. Update installation aborted.")

            self.status_changed.emit("Launching updater...")
            launch_updater(
                context=context,
                wait_pid=os.getpid(),
                wait_timeout_seconds=45,
            )
            self.finished.emit(update.latest_version)
        except (UpdateInstallError, UpdateDownloadError) as exc:
            if context is not None:
                shutil.rmtree(context.staging_dir, ignore_errors=True)
                shutil.rmtree(context.session_dir, ignore_errors=True)
            self.failed.emit(str(exc))
        except Exception:
            if context is not None:
                shutil.rmtree(context.staging_dir, ignore_errors=True)
                shutil.rmtree(context.session_dir, ignore_errors=True)
            self.failed.emit("Failed to prepare update installation.")


class UpdateInstallManager(QObject):
    install_started = Signal()
    install_status = Signal(str)
    install_finished = Signal(str)
    install_failed = Signal(str)
    installing_changed = Signal(bool)
    _detached_threads: set[QThread] = set()

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._thread: QThread | None = None
        self._worker: _UpdateInstallWorker | None = None
        app = QCoreApplication.instance()
        if app is not None:
            app.aboutToQuit.connect(self._on_about_to_quit)

    def is_installing(self) -> bool:
        return self._thread is not None and self._thread.isRunning()

    def start_install(self, *, update_result: UpdateCheckResult) -> bool:
        if self.is_installing():
            return False

        thread = QThread(self)
        worker = _UpdateInstallWorker(update_result=update_result)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)

        worker.status_changed.connect(self.install_status.emit)
        worker.finished.connect(self._on_worker_finished)
        worker.failed.connect(self._on_worker_failed)
        worker.finished.connect(thread.quit)
        worker.failed.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        worker.failed.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(self._on_thread_finished)

        self._thread = thread
        self._worker = worker
        self.install_started.emit()
        self.installing_changed.emit(True)
        thread.start()
        return True

    def shutdown(self, timeout_ms: int = 350) -> None:
        thread = self._thread
        if thread is None:
            return

        wait_ms = max(1, int(timeout_ms))
        if thread.isRunning():
            thread.quit()
            if not thread.wait(wait_ms):
                thread.setParent(None)
                self._detached_threads.add(thread)
                thread.finished.connect(
                    lambda: UpdateInstallManager._on_detached_thread_finished(thread)
                )
                self._thread = None
                self._worker = None
                self.installing_changed.emit(False)
                return
        else:
            thread.wait(wait_ms)

        if self._thread is thread:
            self._thread = None
            self._worker = None
            self.installing_changed.emit(False)

    @classmethod
    def _on_detached_thread_finished(cls, thread: QThread) -> None:
        cls._detached_threads.discard(thread)

    @Slot(str)
    def _on_worker_finished(self, version: str) -> None:
        self.install_finished.emit(version)

    @Slot(str)
    def _on_worker_failed(self, message: str) -> None:
        self.install_failed.emit(message)

    @Slot()
    def _on_thread_finished(self) -> None:
        self._thread = None
        self._worker = None
        self.installing_changed.emit(False)

    @Slot()
    def _on_about_to_quit(self) -> None:
        self.shutdown(timeout_ms=1000)
