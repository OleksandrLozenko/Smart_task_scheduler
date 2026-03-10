from __future__ import annotations

import unittest

from app.core.app_version import compare_semver, parse_semver


class SemverTests(unittest.TestCase):
    def test_parse_semver_valid(self) -> None:
        self.assertEqual(parse_semver("1.2.3"), (1, 2, 3))
        self.assertEqual(parse_semver("v0.9.10"), (0, 9, 10))
        self.assertEqual(parse_semver("  12.0.5 "), (12, 0, 5))

    def test_parse_semver_invalid(self) -> None:
        with self.assertRaises(ValueError):
            parse_semver("1.2")
        with self.assertRaises(ValueError):
            parse_semver("alpha")
        with self.assertRaises(ValueError):
            parse_semver("1.2.3.4")

    def test_compare_semver(self) -> None:
        self.assertEqual(compare_semver("1.2.3", "1.2.3"), 0)
        self.assertEqual(compare_semver("1.2.4", "1.2.3"), 1)
        self.assertEqual(compare_semver("1.2.2", "1.2.3"), -1)


if __name__ == "__main__":
    unittest.main()
