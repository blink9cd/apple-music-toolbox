"""The published configuration carries every `refresh_tags` pin, exactly, in two places.

tag_refresh's optional mutagen is pinned to one release in the `refresh_tags`
extra. A standalone checkout of this project proves itself by installing only its `test`
extra, so that extra lists the same pin beside its own test packages. It cannot name
`apple-music-toolbox[refresh_tags]` instead: the release's proof installs the extra's
requirement strings on their own, before it installs the project, so a self-reference
would name a package not yet installed and be looked up on the package index.
Lists holding the same pins can drift, so these tests fail the moment the published
`refresh_tags` or `test` extra stops holding every pin this project's own `refresh_tags`
extra holds. It sits under tag_refresh, the tool the extra serves; it judges the whole
project's configuration.

The same drift threatens tag_refresh's zero-byte sample library: the PII scan's allowance
for those placeholders is configuration a standalone checkout needs as much as this one,
so a further test fails the moment the published configuration stops carrying it.
"""

from __future__ import annotations

import tomllib
import unittest
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
#: The configuration the tools are gated with, whose `refresh_tags` extra is the reference.
_WORKING_CONFIG = _PROJECT_ROOT / "pyproject.toml"
#: The configuration a standalone checkout ships with: in this checkout, the same file.
_PUBLIC_CONFIG = _PROJECT_ROOT / "pyproject.toml"


def _pii_scan_allow(config: Path) -> dict[str, list[str]]:
    """Return the `[tool.pii_scan.allow]` table of *config*, empty when it has none."""
    with config.open("rb") as handle:
        scan = tomllib.load(handle).get("tool", {}).get("pii_scan", {})
    allow: dict[str, list[str]] = scan.get("allow", {})
    return allow


def _extra(config: Path, name: str) -> list[str]:
    """Return the requirement strings of one optional-dependency group in *config*."""
    with config.open("rb") as handle:
        extras = tomllib.load(handle)["project"]["optional-dependencies"]
    group: list[str] = extras[name]
    return group


class PublicPinsTest(unittest.TestCase):
    def setUp(self) -> None:
        self.pins = _extra(_WORKING_CONFIG, "refresh_tags")
        # Non-vacuous: an emptied reference would make both checks below pass.
        self.assertTrue(self.pins, "the `refresh_tags` extra names no pin")

    def test_the_published_test_extra_holds_every_refresh_tags_pin(self) -> None:
        published = _extra(_PUBLIC_CONFIG, "test")
        for pin in self.pins:
            with self.subTest(pin=pin):
                self.assertIn(
                    pin,
                    published,
                    "the published `test` extra must list every `refresh_tags` pin "
                    "exactly, or a standalone checkout's suites fail on the import",
                )

    def test_the_published_refresh_tags_extra_matches_this_one(self) -> None:
        self.assertEqual(
            sorted(_extra(_PUBLIC_CONFIG, "refresh_tags")), sorted(self.pins)
        )


class PublicScanAllowanceTest(unittest.TestCase):
    def test_the_published_config_carries_the_sample_library_allowance(self) -> None:
        working = _pii_scan_allow(_WORKING_CONFIG)
        # Non-vacuous: with no allowance here, an empty published table would match.
        self.assertTrue(working, "this project's config allows no pii_scan finding")
        self.assertEqual(
            _pii_scan_allow(_PUBLIC_CONFIG),
            working,
            "a standalone checkout scans the same zero-byte sample library, so the "
            "published config must carry the same pii_scan allowances",
        )
