from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from app.core.app_paths import AppPaths


class UpdateInstallError(Exception):
    pass


@dataclass(frozen=True, slots=True)
class UpdateInstallContext:
    target_dir: Path
    package_zip_path: Path
    backup_dir: Path
    staging_dir: Path
    session_dir: Path
    restart_command: list[str]
    updater_command: list[str]


def _project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def _current_target_dir() -> Path:
    if _is_frozen():
        return Path(sys.executable).resolve().parent
    return _project_root()


def _build_restart_command(target_dir: Path) -> list[str]:
    if _is_frozen():
        exe_name = Path(sys.executable).name
        restart_exe = target_dir / exe_name
        return [str(restart_exe)]

    python_exe = Path(sys.executable).resolve()
    main_py = target_dir / "main.py"
    if not main_py.exists():
        raise UpdateInstallError("?? ?????? main.py ??? ??????????? ??????????.")
    return [str(python_exe), str(main_py)]


def _copy_updater_to_session(*, target_dir: Path, session_dir: Path) -> list[str]:
    if _is_frozen():
        updater_source = target_dir / "FlowGridUpdater.exe"
        if not updater_source.exists():
            raise UpdateInstallError(
                "FlowGridUpdater.exe ?? ?????? ????? ? ???????????. "
                "???????????? ?????????? ? updater ? ?????????."
            )
        updater_run = session_dir / "FlowGridUpdater.exe"
        try:
            shutil.copy2(updater_source, updater_run)
        except OSError as exc:
            raise UpdateInstallError("?? ??????? ??????????? updater ??? ???????.") from exc
        return [str(updater_run)]

    updater_source = _project_root() / "tools" / "updater.py"
    if not updater_source.exists():
        raise UpdateInstallError("?? ?????? tools/updater.py ??? ??????? ?????????.")
    updater_run = session_dir / "updater.py"
    try:
        shutil.copy2(updater_source, updater_run)
    except OSError as exc:
        raise UpdateInstallError("?? ??????? ??????????? updater script.") from exc
    return [str(Path(sys.executable).resolve()), str(updater_run)]


def prepare_install_context(
    *,
    app_paths: AppPaths,
    target_version: str,
) -> UpdateInstallContext:
    target_dir = _current_target_dir()

    stamp = time.strftime("%Y%m%d-%H%M%S")
    pid = os.getpid()
    session_id = f"{target_version}-{stamp}-{pid}"

    updates_root = app_paths.updates_dir
    downloads_dir = updates_root / "downloads"
    sessions_root = updates_root / "sessions"
    backups_root = updates_root / "backups"
    staging_root = updates_root / "staging"

    for directory in (downloads_dir, sessions_root, backups_root, staging_root):
        directory.mkdir(parents=True, exist_ok=True)

    session_dir = sessions_root / session_id
    backup_dir = backups_root / f"backup-{session_id}"
    staging_dir = staging_root / f"staging-{session_id}"
    package_zip_path = downloads_dir / f"FlowGrid-{target_version}.zip"

    session_dir.mkdir(parents=True, exist_ok=True)
    updater_command = _copy_updater_to_session(target_dir=target_dir, session_dir=session_dir)
    restart_command = _build_restart_command(target_dir)

    return UpdateInstallContext(
        target_dir=target_dir,
        package_zip_path=package_zip_path,
        backup_dir=backup_dir,
        staging_dir=staging_dir,
        session_dir=session_dir,
        restart_command=restart_command,
        updater_command=updater_command,
    )


def launch_updater(
    *,
    context: UpdateInstallContext,
    wait_pid: int,
    wait_timeout_seconds: int = 45,
) -> None:
    updater_args = [
        "--target-dir",
        str(context.target_dir),
        "--package-zip",
        str(context.package_zip_path),
        "--backup-dir",
        str(context.backup_dir),
        "--staging-dir",
        str(context.staging_dir),
        "--restart-cmd-json",
        json.dumps(context.restart_command, ensure_ascii=False),
        "--wait-pid",
        str(int(wait_pid)),
        "--wait-timeout-seconds",
        str(max(5, int(wait_timeout_seconds))),
    ]

    command = [*context.updater_command, *updater_args]

    creationflags = 0
    if os.name == "nt":
        creationflags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) | getattr(
            subprocess, "DETACHED_PROCESS", 0
        )

    try:
        subprocess.Popen(
            command,
            cwd=str(context.session_dir),
            close_fds=True,
            creationflags=creationflags,
        )
    except OSError as exc:
        raise UpdateInstallError("?? ??????? ????????? updater ???????.") from exc
