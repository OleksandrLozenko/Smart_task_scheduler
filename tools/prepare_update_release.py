from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import re
import zipfile
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
APP_VERSION_PATH = PROJECT_ROOT / "app" / "core" / "app_version.py"
DEFAULT_MANIFEST_PATH = PROJECT_ROOT / "update_manifest.json"
DEFAULT_DIST_FLOWGRID_DIR = PROJECT_ROOT / "dist" / "FlowGrid"
DEFAULT_DIST_DIR = PROJECT_ROOT / "dist"
DEFAULT_RELEASE_URL_TEMPLATE = (
    "https://github.com/OleksandrLozenko/Smart_task_scheduler/releases/download/"
    "v{version}/FlowGrid_portable_{version}.zip"
)
SEMVER_RE = re.compile(r"^\s*\d+\.\d+\.\d+\s*$")


class ReleasePrepError(Exception):
    pass


def _read_app_version() -> str:
    text = APP_VERSION_PATH.read_text(encoding="utf-8")
    match = re.search(r'APP_VERSION\s*=\s*"([^"]+)"', text)
    if not match:
        raise ReleasePrepError("Не удалось прочитать APP_VERSION из app/core/app_version.py")
    return match.group(1).strip()


def _validate_semver(version: str) -> str:
    clean = str(version or "").strip()
    if not SEMVER_RE.match(clean):
        raise ReleasePrepError(f"Некорректная версия: {version!r}. Ожидается формат X.Y.Z")
    return clean


def _read_release_notes(notes_text: str, notes_file: str) -> str:
    text = str(notes_text or "").strip()
    if notes_file:
        file_text = Path(notes_file).read_text(encoding="utf-8").strip()
        if file_text:
            text = file_text
    return text


def _zip_flowgrid(source_dir: Path, zip_path: Path) -> None:
    if not source_dir.exists() or not source_dir.is_dir():
        raise ReleasePrepError(f"Каталог сборки не найден: {source_dir}")

    zip_path.parent.mkdir(parents=True, exist_ok=True)
    if zip_path.exists():
        zip_path.unlink()

    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as archive:
        for file_path in source_dir.rglob("*"):
            if not file_path.is_file():
                continue
            archive.write(file_path, file_path.relative_to(source_dir))


def _sha256_file(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            hasher.update(chunk)
    return hasher.hexdigest().lower()


def _load_manifest(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ReleasePrepError(f"Манифест поврежден: {path}") from exc


def _save_manifest(path: Path, data: dict) -> None:
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _resolve_download_url(
    *,
    version: str,
    explicit_url: str,
    url_template: str,
    zip_name: str,
) -> str:
    if explicit_url:
        return explicit_url.strip()
    template = str(url_template or "").strip() or DEFAULT_RELEASE_URL_TEMPLATE
    if "{zip_name}" not in template:
        template = template.replace("{version}", version) if "{version}" in template else template
        return template
    return template.format(version=version, zip_name=zip_name)


def run() -> int:
    parser = argparse.ArgumentParser(
        description="Подготовка update-пакета и update_manifest.json для FlowGrid",
    )
    parser.add_argument("--version", default="", help="Версия релиза (по умолчанию APP_VERSION)")
    parser.add_argument(
        "--manifest",
        default=str(DEFAULT_MANIFEST_PATH),
        help="Путь к update_manifest.json",
    )
    parser.add_argument(
        "--flowgrid-dir",
        default=str(DEFAULT_DIST_FLOWGRID_DIR),
        help="Путь к собранной onedir-папке FlowGrid",
    )
    parser.add_argument(
        "--dist-dir",
        default=str(DEFAULT_DIST_DIR),
        help="Папка, куда положить zip",
    )
    parser.add_argument(
        "--zip-name",
        default="",
        help="Имя zip-файла (по умолчанию FlowGrid_portable_<version>.zip)",
    )
    parser.add_argument(
        "--download-url",
        default="",
        help="Полный URL пакета обновления (если не задан, используется шаблон)",
    )
    parser.add_argument(
        "--download-url-template",
        default=DEFAULT_RELEASE_URL_TEMPLATE,
        help=(
            "Шаблон URL. Поддерживает {version} и {zip_name}. "
            "По умолчанию GitHub Releases."
        ),
    )
    parser.add_argument(
        "--minimum-supported-version",
        default="",
        help="Минимально поддерживаемая версия (по умолчанию из манифеста или APP_VERSION)",
    )
    parser.add_argument("--release-notes", default="", help="Текст release notes")
    parser.add_argument(
        "--release-notes-file",
        default="",
        help="Файл с release notes (UTF-8). Имеет приоритет над --release-notes",
    )
    parser.add_argument(
        "--published-at",
        default="",
        help="Дата публикации в ISO-формате (по умолчанию текущее UTC время)",
    )
    args = parser.parse_args()

    app_version = _validate_semver(_read_app_version())
    version = _validate_semver(args.version or app_version)

    manifest_path = Path(args.manifest).resolve()
    flowgrid_dir = Path(args.flowgrid_dir).resolve()
    dist_dir = Path(args.dist_dir).resolve()
    zip_name = args.zip_name.strip() or f"FlowGrid_portable_{version}.zip"
    zip_path = dist_dir / zip_name

    _zip_flowgrid(flowgrid_dir, zip_path)
    sha256_hex = _sha256_file(zip_path)

    manifest = _load_manifest(manifest_path)
    min_supported_source = (
        args.minimum_supported_version.strip()
        or str(manifest.get("minimum_supported_version", "")).strip()
        or app_version
    )
    minimum_supported_version = _validate_semver(min_supported_source)
    release_notes = _read_release_notes(args.release_notes, args.release_notes_file)
    published_at = args.published_at.strip() or dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    download_url = _resolve_download_url(
        version=version,
        explicit_url=args.download_url,
        url_template=args.download_url_template,
        zip_name=zip_name,
    )

    manifest.update(
        {
            "latest_version": version,
            "minimum_supported_version": minimum_supported_version,
            "release_notes": release_notes,
            "download_url": download_url,
            "sha256": sha256_hex,
            "published_at": published_at,
        }
    )
    _save_manifest(manifest_path, manifest)

    print("Release package ready.")
    print(f"  APP_VERSION           : {app_version}")
    print(f"  RELEASE VERSION       : {version}")
    print(f"  ZIP                   : {zip_path}")
    print(f"  SHA256                : {sha256_hex}")
    print(f"  DOWNLOAD URL          : {download_url}")
    print(f"  MANIFEST UPDATED      : {manifest_path}")
    if version != app_version:
        print(
            "WARNING: release version differs from APP_VERSION. "
            "Обновите app/core/app_version.py перед сборкой релиза."
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
