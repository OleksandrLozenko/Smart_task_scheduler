from __future__ import annotations

import argparse
import ctypes
import json
import os
import shutil
import subprocess
import time
import zipfile
from pathlib import Path, PurePosixPath


class UpdaterError(Exception):
    pass


def _log(message: str) -> None:
    print(f"[FlowGridUpdater] {message}", flush=True)


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.resolve(strict=False).relative_to(root.resolve(strict=False))
        return True
    except Exception:
        return False


def _ensure_outside(path: Path, target_dir: Path, label: str) -> None:
    if path.resolve(strict=False) == target_dir.resolve(strict=False):
        raise UpdaterError(f"{label} не может совпадать с папкой приложения.")
    if _is_within(path, target_dir):
        raise UpdaterError(f"{label} должен находиться вне папки приложения.")


def _wait_for_pid_exit(pid: int, timeout_seconds: int) -> bool:
    if pid <= 0:
        return True

    timeout_ms = max(1000, int(timeout_seconds) * 1000)
    if os.name != "nt":
        deadline = time.monotonic() + max(1, int(timeout_seconds))
        while time.monotonic() < deadline:
            try:
                os.kill(pid, 0)
            except OSError:
                return True
            time.sleep(0.2)
        return False

    kernel32 = ctypes.windll.kernel32
    SYNCHRONIZE = 0x00100000
    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    WAIT_OBJECT_0 = 0x00000000
    WAIT_TIMEOUT = 0x00000102

    handle = kernel32.OpenProcess(SYNCHRONIZE | PROCESS_QUERY_LIMITED_INFORMATION, False, int(pid))
    if not handle:
        return True
    try:
        result = kernel32.WaitForSingleObject(handle, timeout_ms)
        if result == WAIT_OBJECT_0:
            return True
        if result == WAIT_TIMEOUT:
            return False
        return False
    finally:
        kernel32.CloseHandle(handle)


def _assert_target_writable(target_dir: Path) -> None:
    parent = target_dir.parent
    if not parent.exists():
        raise UpdaterError("Родительская папка установки не существует.")
    probe = parent / f".fg-updater-probe-{int(time.time() * 1000)}"
    try:
        probe.mkdir(parents=False, exist_ok=False)
    except OSError as exc:
        raise UpdaterError(
            "Папка установки недоступна для записи. V1 поддерживает только per-user install."
        ) from exc
    finally:
        try:
            if probe.exists():
                probe.rmdir()
        except OSError:
            pass


def _sanitize_zip_parts(name: str) -> list[str]:
    normalized = str(name or "").replace("\\", "/").strip()
    if not normalized or normalized.endswith("/"):
        return []
    if normalized.startswith("/") or normalized.startswith("\\"):
        raise UpdaterError("В zip обнаружен абсолютный путь.")

    pure = PurePosixPath(normalized)
    parts = [part for part in pure.parts if part not in ("", ".")]
    if not parts:
        return []
    if any(part == ".." for part in parts):
        raise UpdaterError("В zip обнаружен path traversal (..).")
    if ":" in parts[0]:
        raise UpdaterError("В zip обнаружен недопустимый путь с диском Windows.")
    return parts


def _extract_safe_zip(package_zip: Path, staging_dir: Path) -> None:
    if staging_dir.exists():
        shutil.rmtree(staging_dir, ignore_errors=True)
    staging_dir.mkdir(parents=True, exist_ok=True)

    with zipfile.ZipFile(package_zip, "r") as archive:
        entries: list[tuple[zipfile.ZipInfo, list[str]]] = []
        for info in archive.infolist():
            parts = _sanitize_zip_parts(info.filename)
            if not parts:
                continue
            entries.append((info, parts))

        if not entries:
            raise UpdaterError("Архив обновления пуст.")

        common_root: str | None = None
        roots = {parts[0] for _, parts in entries}
        if len(roots) == 1 and all(len(parts) >= 2 for _, parts in entries):
            common_root = next(iter(roots))

        extracted_files = 0
        staging_resolved = staging_dir.resolve(strict=False)
        for info, parts in entries:
            rel_parts = parts[1:] if common_root and parts[0] == common_root else parts
            if not rel_parts:
                continue
            relative = Path(*rel_parts)
            destination = (staging_dir / relative).resolve(strict=False)
            if not _is_within(destination, staging_resolved):
                raise UpdaterError("Обнаружен небезопасный путь файла в zip.")

            if info.is_dir():
                destination.mkdir(parents=True, exist_ok=True)
                continue

            destination.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(info, "r") as src, destination.open("wb") as dst:
                shutil.copyfileobj(src, dst, length=1024 * 1024)
            extracted_files += 1

    if extracted_files <= 0:
        raise UpdaterError("Архив обновления не содержит файлов для установки.")


def _validate_package_layout(staging_dir: Path, restart_cmd: list[str]) -> None:
    if not restart_cmd or not restart_cmd[0]:
        raise UpdaterError("Некорректная команда перезапуска.")

    restart_name = Path(restart_cmd[0]).name
    if not restart_name:
        raise UpdaterError("Некорректный restart executable в аргументах updater.")

    if Path(restart_name).suffix.lower() == ".exe":
        restart_candidate = staging_dir / restart_name
        if not restart_candidate.exists():
            raise UpdaterError("В пакете обновления не найден исполняемый файл приложения.")
        return

    # Dev/script mode fallback validation.
    if not (staging_dir / "main.py").exists():
        raise UpdaterError("В пакете обновления не найден main.py для script-режима.")


def _swap_with_backup(target_dir: Path, backup_dir: Path, staging_dir: Path) -> None:
    if backup_dir.exists():
        raise UpdaterError("Папка backup уже существует. Очистите ее перед новой установкой.")

    moved_to_backup = False
    try:
        if target_dir.exists():
            target_dir.parent.mkdir(parents=True, exist_ok=True)
            backup_dir.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(target_dir), str(backup_dir))
            moved_to_backup = True
        shutil.move(str(staging_dir), str(target_dir))
    except Exception as exc:
        if moved_to_backup and not target_dir.exists() and backup_dir.exists():
            try:
                shutil.move(str(backup_dir), str(target_dir))
            except Exception:
                raise UpdaterError(
                    "Ошибка установки и не удалось восстановить backup приложения."
                ) from exc
        raise UpdaterError("Ошибка при замене файлов приложения.") from exc


def _resolve_restart_command(restart_cmd: list[str], target_dir: Path) -> list[str]:
    if not restart_cmd:
        raise UpdaterError("Отсутствует команда перезапуска приложения.")

    first = Path(str(restart_cmd[0]))
    if first.suffix.lower() != ".exe":
        return list(restart_cmd)

    preferred = target_dir / first.name
    if preferred.exists():
        return [str(preferred), *restart_cmd[1:]]
    return list(restart_cmd)


def _start_restart_command(restart_cmd: list[str], cwd: Path) -> None:
    if not restart_cmd:
        raise UpdaterError("Отсутствует команда перезапуска приложения.")

    creationflags = 0
    if os.name == "nt":
        creationflags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) | getattr(
            subprocess, "DETACHED_PROCESS", 0
        )

    try:
        subprocess.Popen(
            restart_cmd,
            cwd=str(cwd),
            close_fds=True,
            creationflags=creationflags,
        )
        return
    except OSError:
        # Fallback launcher for Windows when direct spawn from updater is blocked.
        if os.name != "nt":
            raise

    try:
        cmd_line = subprocess.list2cmdline(restart_cmd)
        helper = cwd.parent / f".flowgrid-restart-{int(time.time() * 1000)}.cmd"
        helper_script = (
            "@echo off\r\n"
            f'cd /d "{cwd}"\r\n'
            f'start "" {cmd_line}\r\n'
        )
        helper.write_text(
            helper_script,
            encoding="utf-8",
        )
        subprocess.Popen(
            ["cmd", "/c", str(helper)],
            cwd=str(cwd),
            close_fds=True,
            creationflags=creationflags,
        )
    except OSError as exc:
        raise UpdaterError("Установка выполнена, но не удалось запустить новую версию.") from exc


def _cleanup_paths(*paths: Path) -> None:
    for path in paths:
        try:
            if path.is_file():
                path.unlink()
            elif path.is_dir():
                shutil.rmtree(path, ignore_errors=True)
        except OSError:
            pass


def run(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="FlowGrid updater")
    parser.add_argument("--target-dir", required=True)
    parser.add_argument("--package-zip", required=True)
    parser.add_argument("--backup-dir", required=True)
    parser.add_argument("--staging-dir", required=True)
    parser.add_argument("--restart-cmd-json", required=True)
    parser.add_argument("--wait-pid", required=True, type=int)
    parser.add_argument("--wait-timeout-seconds", type=int, default=45)
    args = parser.parse_args(argv)

    target_dir = Path(args.target_dir).resolve(strict=False)
    package_zip = Path(args.package_zip).resolve(strict=False)
    backup_dir = Path(args.backup_dir).resolve(strict=False)
    staging_dir = Path(args.staging_dir).resolve(strict=False)

    try:
        restart_cmd = json.loads(args.restart_cmd_json)
        if not isinstance(restart_cmd, list) or not restart_cmd:
            raise ValueError
        restart_cmd = [str(v) for v in restart_cmd if str(v)]
        if not restart_cmd:
            raise ValueError
    except ValueError as exc:
        raise UpdaterError("Некорректный restart-cmd-json.") from exc

    package_consumed = False
    try:
        _log("Waiting for app process to exit...")
        if not _wait_for_pid_exit(int(args.wait_pid), int(args.wait_timeout_seconds)):
            raise UpdaterError("Превышен таймаут ожидания завершения приложения.")

        _log("Checking write access...")
        _assert_target_writable(target_dir)
        _ensure_outside(backup_dir, target_dir, "Backup")
        _ensure_outside(staging_dir, target_dir, "Staging")

        if not package_zip.exists() or not package_zip.is_file():
            raise UpdaterError("Пакет обновления не найден.")

        _log("Extracting package...")
        _extract_safe_zip(package_zip, staging_dir)
        _validate_package_layout(staging_dir, restart_cmd)

        _log("Swapping app files...")
        _swap_with_backup(target_dir, backup_dir, staging_dir)
        package_consumed = True

        _log("Starting updated app...")
        resolved_restart_cmd = _resolve_restart_command(restart_cmd, target_dir)
        _start_restart_command(resolved_restart_cmd, target_dir)
        _log("Update finished.")
        return 0
    finally:
        _cleanup_paths(staging_dir)
        if package_consumed:
            _cleanup_paths(package_zip)


def main() -> int:
    try:
        return run()
    except UpdaterError as exc:
        _log(f"ERROR: {exc}")
        return 2
    except Exception as exc:
        _log(f"UNEXPECTED ERROR: {exc}")
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
