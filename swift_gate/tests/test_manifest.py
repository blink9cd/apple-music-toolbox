"""Grouped suite: the manifest dump parsed into ``PackageFacts``, and SWG001 / SWG002.

Every fixture is the trimmed real dump-package JSON captured from ``fixtures/floorpkg``,
edited per case, so a drift in SwiftPM's key names fails here first.
"""

from __future__ import annotations

import io
import json
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory

from hypothesis import given
from hypothesis import strategies as st

from _fixtures import dump_package, write  # noqa: E402 - fixtures bootstrap sys.path

import swgate_config  # noqa: E402 - on sys.path via _fixtures
import swgate_manifest  # noqa: E402 - same
from swgate_model import ConfigError, ParseError  # noqa: E402 - same

FLOOR = "14"
SHOWN = "Package.swift"


def _facts(**changes: object) -> swgate_manifest.PackageFacts:
    """Parse the captured dump with top-level keys replaced."""
    return swgate_manifest.parse_dump_package(json.dumps(dump_package(**changes)))


def _codes(facts: swgate_manifest.PackageFacts, floor: str = FLOOR) -> list[str]:
    """The finding codes check_manifest gives *facts* at *floor*."""
    return [f.code for f in swgate_manifest.check_manifest(facts, floor, SHOWN)]


def _macos(version: str) -> list[dict[str, object]]:
    """A platforms list holding one macOS entry at *version*."""
    return [{"options": [], "platformName": "macos", "version": version}]


def _with_target_mode(mode: str) -> list[dict[str, object]]:
    """The captured targets with a swiftLanguageMode setting on the first one."""
    targets = dump_package()["targets"]
    assert isinstance(targets, list)
    targets[0]["settings"] = [
        {"kind": {"swiftLanguageMode": {"_0": mode}}, "tool": "swift"},
        {"kind": {"define": {"_0": "DEBUG_AID"}}, "tool": "swift"},
    ]
    return targets


class ParseTests(unittest.TestCase):
    """parse_dump_package reads the live key names."""

    def test_captured_dump_parses_to_its_facts(self) -> None:
        facts = _facts()
        self.assertEqual(facts.name, "Floor")
        self.assertEqual(facts.macos, "14.0")
        self.assertEqual(facts.tools_version, "6.0.0")
        self.assertEqual(facts.language_modes, ())
        self.assertEqual(facts.target_modes, {})

    def test_language_modes_and_target_modes_are_read(self) -> None:
        facts = _facts(swiftLanguageVersions=["6"], targets=_with_target_mode("5"))
        self.assertEqual(facts.language_modes, ("6",))
        self.assertEqual(facts.target_modes, {"Floor": "5"})

    def test_other_platforms_are_ignored(self) -> None:
        platforms = [{"options": [], "platformName": "ios", "version": "17.0"}]
        self.assertIsNone(_facts(platforms=platforms).macos)

    def test_malformed_json_is_a_parse_error(self) -> None:
        with self.assertRaises(ParseError):
            swgate_manifest.parse_dump_package("{not json")

    def test_wrong_shapes_are_a_parse_error(self) -> None:
        bads: list[object] = [
            [],
            {"name": "X"},
            dump_package(platforms="macos"),
            dump_package(toolsVersion={"version": "6.0"}),
            dump_package(targets=[{"name": "X", "settings": "none"}]),
            dump_package(swiftLanguageVersions="6"),
            dump_package(name=5),
        ]
        for bad in bads:
            with self.subTest(bad=bad), self.assertRaises(ParseError):
                swgate_manifest.parse_dump_package(json.dumps(bad))

    @given(st.text(max_size=200))
    def test_fuzz_parse_dump_package(self, text: str) -> None:
        """Never-crash: any text parses to facts or raises ParseError, nothing else."""
        try:
            swgate_manifest.parse_dump_package(text)
        except ParseError:
            pass


class FloorTests(unittest.TestCase):
    """SWG001: the macOS platform entry must equal the configured floor exactly."""

    def test_floor_equal_passes(self) -> None:
        self.assertEqual(_codes(_facts()), [])

    def test_floor_written_with_minor_passes(self) -> None:
        self.assertEqual(_codes(_facts(), "14.0"), [])

    def test_missing_macos_platform_is_swg001(self) -> None:
        self.assertEqual(_codes(_facts(platforms=[])), ["SWG001"])

    def test_lower_platform_is_swg001(self) -> None:
        self.assertEqual(_codes(_facts(platforms=_macos("13.0"))), ["SWG001"])

    def test_higher_platform_is_swg001(self) -> None:
        self.assertEqual(_codes(_facts(platforms=_macos("15.0"))), ["SWG001"])

    def test_non_numeric_floor_is_config_error(self) -> None:
        with self.assertRaises(ConfigError):
            _codes(_facts(), "fourteen")


class LanguageModeTests(unittest.TestCase):
    """SWG002: tools 6.0 or later, and language mode 6 everywhere."""

    def test_tools_version_5_10_is_swg002(self) -> None:
        facts = _facts(toolsVersion={"_version": "5.10.0"})
        self.assertEqual(_codes(facts), ["SWG002"])

    def test_package_language_mode_5_is_swg002(self) -> None:
        self.assertEqual(_codes(_facts(swiftLanguageVersions=["6", "5"])), ["SWG002"])

    def test_target_language_mode_5_is_swg002(self) -> None:
        facts = _facts(targets=_with_target_mode("5"))
        findings = swgate_manifest.check_manifest(facts, FLOOR, SHOWN)
        self.assertEqual([f.code for f in findings], ["SWG002"])
        self.assertIn("Floor", findings[0].message)

    def test_target_language_mode_6_passes(self) -> None:
        self.assertEqual(_codes(_facts(targets=_with_target_mode("6"))), [])

    def test_unreadable_tools_version_is_parse_error(self) -> None:
        facts = _facts(toolsVersion={"_version": "six"})
        with self.assertRaises(ParseError):
            _codes(facts)


class FloorConfigTests(unittest.TestCase):
    """The floor is read from [tool.swift_gate]; a missing key is never a default."""

    def _config(self, body: str) -> swgate_config.Config:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            write(root / "pyproject.toml", body)
            return swgate_config.read_config(root)

    def test_no_pyproject_anywhere_is_an_empty_config(self) -> None:
        config = swgate_config.read_config(Path("pkg"), is_file=lambda _path: False)
        self.assertEqual(config, swgate_config.Config())

    def test_a_pyproject_without_the_table_is_an_empty_config(self) -> None:
        self.assertEqual(self._config("[tool.other]\nx = 1\n"), swgate_config.Config())

    def test_the_nearest_pyproject_answers_even_without_the_table(self) -> None:
        # Nearest-pyproject semantics (the family policy): a pyproject lacking the
        # table is NOT walked past, so nothing above it can supply the floor.
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            write(root / "pyproject.toml", '[tool.swift_gate]\nmacos_floor = "14"\n')
            write(root / "pkg" / "pyproject.toml", "[tool.other]\nx = 1\n")
            config = swgate_config.read_config(root / "pkg")
        self.assertIsNone(config.macos_floor)

    def test_excludes_resolve_against_the_pyproject_dir(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            write(root / "pyproject.toml", '[tool.swift_gate]\nexclude = ["samples"]\n')
            config = swgate_config.read_config(root / "pkg")
        self.assertEqual(config.excludes, (root / "samples",))

    def test_a_malformed_config_message_carries_no_absolute_path(self) -> None:
        bodies = ("[tool.swift_gate\n", '[tool.swift_gate]\nexclude = "x"\n')
        for body in bodies:
            with self.subTest(body=body), TemporaryDirectory() as tmp:
                root = Path(tmp).resolve()
                write(root / "pyproject.toml", body)
                (root / "pkg").mkdir()
                with self.assertRaises(ConfigError) as ctx:
                    swgate_config.read_config(root / "pkg")
                message = str(ctx.exception)
                self.assertNotIn(str(root), message)
                self.assertIn("../pyproject.toml", message)

    def test_an_unreadable_config_message_carries_no_absolute_path(self) -> None:
        absolute = Path("/nonexistent/pyproject.toml").resolve()

        def unreadable(path: Path) -> str:
            raise PermissionError(13, "Permission denied", str(path))

        with self.assertRaises(ConfigError) as ctx:
            swgate_config.read_config(
                absolute.parent,
                is_file=lambda path: path == absolute,
                read_text=unreadable,
            )
        self.assertNotIn(str(absolute), str(ctx.exception))
        self.assertIn("Permission denied", str(ctx.exception))

    def test_a_non_string_floor_is_config_error(self) -> None:
        with self.assertRaises(ConfigError) as ctx:
            self._config("[tool.swift_gate]\nmacos_floor = 14\n")
        self.assertIn("macos_floor", str(ctx.exception))

    def test_floor_is_read(self) -> None:
        config = self._config('[tool.swift_gate]\nmacos_floor = "14"\n')
        self.assertEqual(swgate_config.require_floor(config), "14")

    def test_missing_floor_key_raises(self) -> None:
        config = self._config("[tool.swift_gate]\nexclude = []\n")
        with self.assertRaises(ConfigError) as ctx:
            swgate_config.require_floor(config)
        self.assertIn("macos_floor", str(ctx.exception))

    def test_missing_floor_exits_two(self) -> None:
        import swift_gate  # noqa: PLC0415 - imported late: the CLI is this test's subject

        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            write(root / "pyproject.toml", "[tool.swift_gate]\nexclude = []\n")
            write(root / "pkg" / "Package.swift", "// swift-tools-version: 6.0\n")
            err = io.StringIO()
            with redirect_stdout(io.StringIO()), redirect_stderr(err):
                code = swift_gate.main(["--path", str(root)])
        self.assertEqual(code, 2)
        self.assertIn("macos_floor", err.getvalue())


if __name__ == "__main__":
    unittest.main()
