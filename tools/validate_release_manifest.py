from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, url2pathname, urlopen


SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+$")
SHA256_RE = re.compile(r"^[0-9a-fA-F]{64}$")
EXPECTED_ASSET_TEMPLATE = "FlowGrid_portable_{version}.zip"


class ValidationError(Exception):
    pass


def _read_manifest(path: Path) -> dict:
    if not path.exists() or not path.is_file():
        raise ValidationError(f"Manifest not found: {path}")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValidationError(f"Manifest contains invalid JSON: {path}") from exc


def _validate_manifest_schema(data: dict) -> tuple[str, str, str]:
    if not isinstance(data, dict):
        raise ValidationError("Manifest root must be a JSON object.")

    latest_version = str(data.get("latest_version", "")).strip()
    if not latest_version:
        raise ValidationError("Manifest is missing latest_version.")
    if not SEMVER_RE.fullmatch(latest_version):
        raise ValidationError(f"latest_version has invalid semver format: {latest_version!r}")

    download_url = str(data.get("download_url", "")).strip()
    if not download_url:
        raise ValidationError("Manifest is missing download_url.")
    parsed = urlparse(download_url)
    if parsed.scheme.lower() not in {"https", "http", "file"}:
        raise ValidationError("download_url must use http://, https:// or file://")

    sha256_hex = str(data.get("sha256", "")).strip()
    if not SHA256_RE.fullmatch(sha256_hex):
        raise ValidationError("sha256 must be a 64-char hex string.")

    return latest_version, download_url, sha256_hex.lower()


def _validate_asset_name(*, latest_version: str, download_url: str) -> None:
    parsed = urlparse(download_url)
    asset_name = Path(parsed.path).name
    expected_asset = EXPECTED_ASSET_TEMPLATE.format(version=latest_version)
    if asset_name != expected_asset:
        raise ValidationError(
            "download_url asset name mismatch: "
            f"expected '{expected_asset}', got '{asset_name or '<empty>'}'."
        )


def _hash_local_file(path: Path) -> tuple[str, int]:
    if not path.exists() or not path.is_file():
        raise ValidationError(f"Local update package not found: {path}")
    hasher = hashlib.sha256()
    size = 0
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            hasher.update(chunk)
            size += len(chunk)
    return hasher.hexdigest().lower(), size


def _hash_remote_url(url: str, timeout_seconds: int) -> tuple[str, int]:
    request = Request(
        url,
        headers={
            "User-Agent": "FlowGrid-ReleaseValidation/1.0",
            "Accept": "application/octet-stream,*/*",
        },
    )
    try:
        with urlopen(request, timeout=max(3, int(timeout_seconds))) as response:
            hasher = hashlib.sha256()
            size = 0
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                hasher.update(chunk)
                size += len(chunk)
            return hasher.hexdigest().lower(), size
    except HTTPError as exc:
        if int(exc.code) == 404:
            raise ValidationError(
                "download_url returned HTTP 404: manifest is reachable, but update package is missing."
            ) from exc
        raise ValidationError(f"download_url returned HTTP {exc.code}.") from exc
    except URLError as exc:
        raise ValidationError("Could not access download_url.") from exc
    except OSError as exc:
        raise ValidationError("Network/filesystem error while downloading update package.") from exc


def _hash_download_target(download_url: str, timeout_seconds: int) -> tuple[str, int]:
    parsed = urlparse(download_url)
    if parsed.scheme.lower() == "file":
        raw_path = f"//{parsed.netloc}{parsed.path}" if parsed.netloc else parsed.path
        local_path = Path(url2pathname(raw_path))
        return _hash_local_file(local_path)
    return _hash_remote_url(download_url, timeout_seconds)


def run() -> int:
    parser = argparse.ArgumentParser(
        description="Validate FlowGrid update_manifest.json against release package.",
    )
    parser.add_argument(
        "--manifest",
        default="update_manifest.json",
        help="Path to update_manifest.json (default: update_manifest.json).",
    )
    parser.add_argument(
        "--timeout-seconds",
        type=int,
        default=25,
        help="Timeout for download_url checks.",
    )
    args = parser.parse_args()

    manifest_path = Path(args.manifest).resolve()
    print(f"[validate] manifest: {manifest_path}")

    data = _read_manifest(manifest_path)
    latest_version, download_url, manifest_sha = _validate_manifest_schema(data)
    print(f"[validate] latest_version: {latest_version}")
    print(f"[validate] download_url: {download_url}")

    _validate_asset_name(latest_version=latest_version, download_url=download_url)
    print("[validate] asset name matches version")

    downloaded_sha, size = _hash_download_target(download_url, args.timeout_seconds)
    print(f"[validate] package size: {size} bytes")
    print(f"[validate] package sha256: {downloaded_sha}")

    if downloaded_sha != manifest_sha:
        raise ValidationError(
            "sha256 mismatch: manifest.sha256 does not match downloaded package hash."
        )

    print("[validate] sha256 matches manifest")
    print("[validate] OK")
    return 0


def main() -> int:
    try:
        return run()
    except ValidationError as exc:
        print(f"[validate] ERROR: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:
        print(f"[validate] UNEXPECTED ERROR: {exc}", file=sys.stderr)
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
