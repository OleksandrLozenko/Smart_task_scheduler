from __future__ import annotations

import json
from dataclasses import dataclass
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from app.core.app_version import compare_semver, parse_semver


DEFAULT_MANIFEST_TIMEOUT_SECONDS = 6


class UpdateCheckError(Exception):
    pass


@dataclass(frozen=True, slots=True)
class UpdateManifest:
    latest_version: str
    minimum_supported_version: str
    release_notes: str
    download_url: str
    sha256: str
    published_at: str

    @classmethod
    def from_dict(cls, raw: object) -> "UpdateManifest":
        if not isinstance(raw, dict):
            raise UpdateCheckError("Invalid update manifest format.")

        latest_version = str(raw.get("latest_version", "")).strip()
        if not latest_version:
            raise UpdateCheckError("Manifest is missing latest_version.")
        try:
            parse_semver(latest_version)
        except ValueError as exc:
            raise UpdateCheckError("Manifest latest_version has invalid semver format.") from exc

        minimum_supported_version = (
            str(raw.get("minimum_supported_version", "0.0.0")).strip() or "0.0.0"
        )
        try:
            parse_semver(minimum_supported_version)
        except ValueError as exc:
            raise UpdateCheckError(
                "Manifest minimum_supported_version has invalid semver format."
            ) from exc

        download_url = str(raw.get("download_url", "")).strip()
        if download_url:
            parsed_download = urlparse(download_url)
            if parsed_download.scheme.lower() not in {"http", "https", "file"}:
                raise UpdateCheckError(
                    "Manifest download_url has invalid scheme (use http/https/file)."
                )

        return cls(
            latest_version=latest_version,
            minimum_supported_version=minimum_supported_version,
            release_notes=str(raw.get("release_notes", "")).strip(),
            download_url=download_url,
            sha256=str(raw.get("sha256", "")).strip(),
            published_at=str(raw.get("published_at", "")).strip(),
        )


@dataclass(frozen=True, slots=True)
class UpdateCheckResult:
    current_version: str
    latest_version: str
    minimum_supported_version: str
    is_update_available: bool
    is_current_version_supported: bool
    release_notes: str
    download_url: str
    sha256: str
    published_at: str


def _download_manifest_json(url: str, timeout_seconds: int) -> object:
    parsed = urlparse(url)
    scheme = parsed.scheme.lower()
    if scheme not in {"http", "https", "file"}:
        raise UpdateCheckError("Invalid manifest URL. Use http(s)://... or file:///...")
    if scheme == "file" and not parsed.path:
        raise UpdateCheckError("Invalid file:// manifest URL.")

    request: object
    if scheme in {"http", "https"}:
        request = Request(
            url,
            headers={
                "User-Agent": "FlowGrid-Desktop/UpdateCheck",
                "Accept": "application/json",
            },
        )
    else:
        request = url

    try:
        with urlopen(request, timeout=max(2, int(timeout_seconds))) as response:
            payload = response.read().decode("utf-8-sig")
    except ValueError as exc:
        raise UpdateCheckError("Malformed update manifest URL.") from exc
    except HTTPError as exc:
        raise UpdateCheckError(f"Update server returned HTTP {exc.code}.") from exc
    except URLError as exc:
        if scheme == "file":
            raise UpdateCheckError("Could not open local manifest file (file://).") from exc
        raise UpdateCheckError("Could not connect to update server.") from exc
    except TimeoutError as exc:
        raise UpdateCheckError("Timed out while waiting for update server response.") from exc
    except OSError as exc:
        raise UpdateCheckError("Network error while checking updates.") from exc

    try:
        return json.loads(payload)
    except json.JSONDecodeError as exc:
        raise UpdateCheckError("Update manifest contains invalid JSON.") from exc


def check_for_updates(
    *,
    current_version: str,
    manifest_url: str,
    timeout_seconds: int = DEFAULT_MANIFEST_TIMEOUT_SECONDS,
) -> UpdateCheckResult:
    manifest_url = str(manifest_url or "").strip()
    if not manifest_url:
        raise UpdateCheckError("Manifest URL is not set.")

    try:
        parse_semver(current_version)
    except ValueError as exc:
        raise UpdateCheckError("Current app version has invalid semver format.") from exc

    raw_manifest = _download_manifest_json(manifest_url, timeout_seconds=timeout_seconds)
    manifest = UpdateManifest.from_dict(raw_manifest)

    is_update_available = compare_semver(manifest.latest_version, current_version) > 0
    is_current_version_supported = (
        compare_semver(current_version, manifest.minimum_supported_version) >= 0
    )

    return UpdateCheckResult(
        current_version=current_version,
        latest_version=manifest.latest_version,
        minimum_supported_version=manifest.minimum_supported_version,
        is_update_available=is_update_available,
        is_current_version_supported=is_current_version_supported,
        release_notes=manifest.release_notes,
        download_url=manifest.download_url,
        sha256=manifest.sha256,
        published_at=manifest.published_at,
    )
