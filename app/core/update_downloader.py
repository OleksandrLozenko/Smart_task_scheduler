from __future__ import annotations

import hashlib
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, url2pathname, urlopen


class UpdateDownloadError(Exception):
    pass


@dataclass(frozen=True, slots=True)
class DownloadedPackage:
    file_path: Path
    sha256_hex: str
    size_bytes: int


def _read_local_source(parsed) -> tuple[object, int | None]:
    raw_path = f"//{parsed.netloc}{parsed.path}" if parsed.netloc else parsed.path
    local_path = Path(url2pathname(raw_path))
    if not local_path.exists() or not local_path.is_file():
        raise UpdateDownloadError("Локальный пакет обновления не найден.")
    try:
        size = local_path.stat().st_size
    except OSError:
        size = None
    try:
        stream = local_path.open("rb")
    except OSError as exc:
        raise UpdateDownloadError("Не удалось открыть локальный пакет обновления.") from exc
    return stream, size


def _read_remote_source(url: str, timeout_seconds: int) -> tuple[object, int | None]:
    request = Request(
        url,
        headers={
            "User-Agent": "FlowGrid-Desktop/UpdateDownload",
            "Accept": "application/octet-stream",
        },
    )
    try:
        response = urlopen(request, timeout=max(4, int(timeout_seconds)))
    except HTTPError as exc:
        raise UpdateDownloadError(f"Сервер вернул HTTP {exc.code}.") from exc
    except URLError as exc:
        raise UpdateDownloadError("Не удалось подключиться к серверу обновлений.") from exc
    except TimeoutError as exc:
        raise UpdateDownloadError("Превышено время ожидания загрузки обновления.") from exc
    except OSError as exc:
        raise UpdateDownloadError("Сетевая ошибка при загрузке обновления.") from exc

    header = response.headers.get("Content-Length", "").strip()
    total: int | None = None
    if header:
        try:
            parsed = int(header)
            if parsed >= 0:
                total = parsed
        except (TypeError, ValueError):
            total = None
    return response, total


def download_update_package(
    *,
    download_url: str,
    destination_path: Path,
    timeout_seconds: int = 20,
    progress_callback=None,
) -> DownloadedPackage:
    url = str(download_url or "").strip()
    if not url:
        raise UpdateDownloadError("URL пакета обновления не задан.")

    parsed = urlparse(url)
    scheme = parsed.scheme.lower()
    if scheme not in {"http", "https", "file"}:
        raise UpdateDownloadError("Некорректный URL пакета. Используйте http(s):// или file://.")

    destination = Path(destination_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_path = tempfile.mkstemp(
        prefix=f".{destination.name}.",
        suffix=".part",
        dir=str(destination.parent),
    )
    temp_file = Path(temp_path)
    os.close(fd)

    stream = None
    hasher = hashlib.sha256()
    downloaded = 0
    try:
        if scheme == "file":
            stream, total = _read_local_source(parsed)
        else:
            stream, total = _read_remote_source(url, timeout_seconds)

        with stream, temp_file.open("wb") as out:
            while True:
                chunk = stream.read(1024 * 512)
                if not chunk:
                    break
                out.write(chunk)
                hasher.update(chunk)
                downloaded += len(chunk)
                if progress_callback is not None:
                    progress_callback(downloaded, total)
            out.flush()
            os.fsync(out.fileno())

        os.replace(temp_file, destination)
        return DownloadedPackage(
            file_path=destination,
            sha256_hex=hasher.hexdigest().lower(),
            size_bytes=downloaded,
        )
    except UpdateDownloadError:
        raise
    except OSError as exc:
        raise UpdateDownloadError("Ошибка записи пакета обновления на диск.") from exc
    except Exception as exc:  # defensive guard for worker thread
        raise UpdateDownloadError("Не удалось скачать пакет обновления.") from exc
    finally:
        try:
            if temp_file.exists():
                temp_file.unlink()
        except OSError:
            pass
