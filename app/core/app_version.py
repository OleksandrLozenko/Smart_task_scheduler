from __future__ import annotations

import re


APP_VERSION = "0.6.1"
DEFAULT_UPDATE_MANIFEST_URL = (
    "https://raw.githubusercontent.com/OleksandrLozenko/Smart_task_scheduler/main/update_manifest.json"
)
_SEMVER_RE = re.compile(r"^\s*[vV]?(\d+)\.(\d+)\.(\d+)\s*$")


def parse_semver(version_text: str) -> tuple[int, int, int]:
    match = _SEMVER_RE.match(str(version_text or ""))
    if not match:
        raise ValueError(f"Invalid semantic version: {version_text!r}")
    major, minor, patch = match.groups()
    return int(major), int(minor), int(patch)


def compare_semver(left: str, right: str) -> int:
    left_v = parse_semver(left)
    right_v = parse_semver(right)
    if left_v < right_v:
        return -1
    if left_v > right_v:
        return 1
    return 0
