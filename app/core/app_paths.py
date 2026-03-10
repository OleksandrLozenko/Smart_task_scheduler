from __future__ import annotations

import os
import shutil
import sys
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path


APP_NAME = "FlowGrid"


@dataclass(frozen=True, slots=True)
class AppPaths:
    app_name: str
    config_dir: Path
    cache_dir: Path
    logs_dir: Path
    updates_dir: Path
    settings_path: Path
    planner_state_path: Path


def _roaming_root() -> Path:
    value = os.environ.get("APPDATA")
    if value:
        return Path(value)
    return Path.home() / "AppData" / "Roaming"


def _local_root() -> Path:
    value = os.environ.get("LOCALAPPDATA")
    if value:
        return Path(value)
    return Path.home() / "AppData" / "Local"


def _legacy_roots() -> list[Path]:
    roots: list[Path] = []
    try:
        roots.append(Path.cwd())
    except OSError:
        pass

    if getattr(sys, "frozen", False):
        roots.append(Path(sys.executable).resolve().parent)
    else:
        roots.append(Path(__file__).resolve().parents[2])

    normalized: list[Path] = []
    seen: set[str] = set()
    for root in roots:
        try:
            key = str(root.resolve()).lower()
        except OSError:
            key = str(root).lower()
        if key in seen:
            continue
        seen.add(key)
        normalized.append(root)
    return normalized


def _copy_if_missing(source: Path, destination: Path) -> None:
    if destination.exists() or not source.exists() or not source.is_file():
        return
    try:
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
    except OSError:
        # Legacy migration is best-effort and must never break app startup.
        return


def _migrate_legacy_files(paths: AppPaths) -> None:
    legacy_names = (
        ("settings.json", paths.settings_path),
        ("planner_state.json", paths.planner_state_path),
    )
    for root in _legacy_roots():
        for filename, destination in legacy_names:
            source = root / filename
            try:
                if source.resolve() == destination.resolve():
                    continue
            except OSError:
                pass
            _copy_if_missing(source, destination)


@lru_cache(maxsize=1)
def get_app_paths(app_name: str = APP_NAME) -> AppPaths:
    config_dir = _roaming_root() / app_name
    local_root = _local_root() / app_name
    cache_dir = local_root / "cache"
    logs_dir = local_root / "logs"
    updates_dir = local_root / "updates"

    config_dir.mkdir(parents=True, exist_ok=True)
    cache_dir.mkdir(parents=True, exist_ok=True)
    logs_dir.mkdir(parents=True, exist_ok=True)
    updates_dir.mkdir(parents=True, exist_ok=True)

    paths = AppPaths(
        app_name=app_name,
        config_dir=config_dir,
        cache_dir=cache_dir,
        logs_dir=logs_dir,
        updates_dir=updates_dir,
        settings_path=config_dir / "settings.json",
        planner_state_path=config_dir / "planner_state.json",
    )
    _migrate_legacy_files(paths)
    return paths
