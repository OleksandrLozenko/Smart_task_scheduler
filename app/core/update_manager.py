from __future__ import annotations

from PySide6.QtCore import QCoreApplication, QObject, QThread, Signal, Slot

from app.core.update_service import UpdateCheckError, UpdateCheckResult, check_for_updates


class _UpdateCheckWorker(QObject):
    finished = Signal(object)
    failed = Signal(str)

    def __init__(self, *, current_version: str, manifest_url: str, timeout_seconds: int) -> None:
        super().__init__()
        self._current_version = current_version
        self._manifest_url = manifest_url
        self._timeout_seconds = timeout_seconds

    @Slot()
    def run(self) -> None:
        try:
            result = check_for_updates(
                current_version=self._current_version,
                manifest_url=self._manifest_url,
                timeout_seconds=self._timeout_seconds,
            )
        except UpdateCheckError as exc:
            self.failed.emit(str(exc))
            return
        except Exception:
            self.failed.emit("Unexpected error while checking updates.")
            return
        self.finished.emit(result)


class UpdateManager(QObject):
    check_started = Signal()
    check_finished = Signal(object)
    check_failed = Signal(str)
    checking_changed = Signal(bool)
    _detached_threads: set[QThread] = set()

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._thread: QThread | None = None
        self._worker: _UpdateCheckWorker | None = None
        app = QCoreApplication.instance()
        if app is not None:
            app.aboutToQuit.connect(self._on_about_to_quit)

    def is_checking(self) -> bool:
        return self._thread is not None and self._thread.isRunning()

    def start_check(
        self,
        *,
        current_version: str,
        manifest_url: str,
        timeout_seconds: int = 6,
    ) -> bool:
        if self.is_checking():
            return False

        thread = QThread(self)
        worker = _UpdateCheckWorker(
            current_version=current_version,
            manifest_url=manifest_url,
            timeout_seconds=timeout_seconds,
        )
        worker.moveToThread(thread)
        thread.started.connect(worker.run)

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
        self.check_started.emit()
        self.checking_changed.emit(True)
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
                # Do not force-kill: keep thread alive until it exits naturally.
                thread.setParent(None)
                self._detached_threads.add(thread)
                thread.finished.connect(lambda: UpdateManager._on_detached_thread_finished(thread))
                self._thread = None
                self._worker = None
                self.checking_changed.emit(False)
                return
        else:
            thread.wait(wait_ms)

        if self._thread is thread:
            self._thread = None
            self._worker = None
            self.checking_changed.emit(False)

    @classmethod
    def _on_detached_thread_finished(cls, thread: QThread) -> None:
        cls._detached_threads.discard(thread)

    @Slot(object)
    def _on_worker_finished(self, result: UpdateCheckResult) -> None:
        self.check_finished.emit(result)

    @Slot(str)
    def _on_worker_failed(self, message: str) -> None:
        self.check_failed.emit(message)

    @Slot()
    def _on_thread_finished(self) -> None:
        self._thread = None
        self._worker = None
        self.checking_changed.emit(False)

    @Slot()
    def _on_about_to_quit(self) -> None:
        self.shutdown(timeout_ms=350)
