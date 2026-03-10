from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from app.core.update_service import UpdateCheckError, check_for_updates


class UpdateServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self._root = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _write_manifest(self, data: object, *, filename: str = "manifest.json") -> str:
        path = self._root / filename
        if isinstance(data, str):
            path.write_text(data, encoding="utf-8")
        else:
            path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        return path.as_uri()

    def test_file_manifest_update_available(self) -> None:
        url = self._write_manifest(
            {
                "latest_version": "0.7.0",
                "minimum_supported_version": "0.5.0",
                "release_notes": "UI fixes",
                "download_url": "file:///C:/updates/update.zip",
                "sha256": "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
                "published_at": "2026-03-10T12:00:00Z",
            }
        )
        result = check_for_updates(current_version="0.6.0", manifest_url=url, timeout_seconds=2)
        self.assertTrue(result.is_update_available)
        self.assertEqual(result.latest_version, "0.7.0")
        self.assertTrue(result.is_current_version_supported)

    def test_file_manifest_up_to_date(self) -> None:
        url = self._write_manifest(
            {
                "latest_version": "0.6.0",
                "minimum_supported_version": "0.5.0",
                "release_notes": "",
                "download_url": "",
                "sha256": "",
                "published_at": "2026-03-10T12:00:00Z",
            }
        )
        result = check_for_updates(current_version="0.6.0", manifest_url=url, timeout_seconds=2)
        self.assertFalse(result.is_update_available)

    def test_invalid_manifest_url_scheme(self) -> None:
        with self.assertRaises(UpdateCheckError):
            check_for_updates(
                current_version="0.6.0",
                manifest_url="ftp://example.com/update_manifest.json",
                timeout_seconds=2,
            )

    def test_invalid_semver_in_manifest(self) -> None:
        url = self._write_manifest(
            {
                "latest_version": "0.7",
                "minimum_supported_version": "0.5.0",
                "release_notes": "",
                "download_url": "",
                "sha256": "",
                "published_at": "",
            }
        )
        with self.assertRaises(UpdateCheckError):
            check_for_updates(current_version="0.6.0", manifest_url=url, timeout_seconds=2)

    def test_broken_json_manifest(self) -> None:
        url = self._write_manifest("{ invalid json", filename="broken.json")
        with self.assertRaises(UpdateCheckError):
            check_for_updates(current_version="0.6.0", manifest_url=url, timeout_seconds=2)

    def test_invalid_current_semver(self) -> None:
        url = self._write_manifest(
            {
                "latest_version": "0.7.0",
                "minimum_supported_version": "0.5.0",
                "release_notes": "",
                "download_url": "",
                "sha256": "",
                "published_at": "",
            }
        )
        with self.assertRaises(UpdateCheckError):
            check_for_updates(current_version="bad-version", manifest_url=url, timeout_seconds=2)


if __name__ == "__main__":
    unittest.main()
