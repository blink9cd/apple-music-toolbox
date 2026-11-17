"""run_layout: the runner's one layout file, read and refused.

Every path is derived under a temporary home, never the real one, and every refusal is
read from an invented layout file written to a temporary directory.
"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parent / "src"))

import run_layout  # noqa: E402 - import follows the sys.path bootstrap above

#: Every key the layout file holds, restated here so a dropped key fails a test.
_KEYS = frozenset(
    {
        "version",
        "bundle_id",
        "launchd_label",
        "grant_label",
        "display_name",
        "app_name",
        "executable",
        "data_dir",
        "signing_config",
    }
)
#: The keys whose values are home-relative paths.
_PATH_KEYS = ("data_dir", "signing_config")
#: The keys whose values each name one file or folder inside a derived folder.
_NAME_KEYS = ("app_name", "launchd_label", "grant_label", "executable")


def _real_document() -> dict[str, str]:
    """The committed layout file's own JSON object."""
    text = run_layout.LAYOUT_FILE.read_text(encoding="utf-8")
    document: dict[str, str] = json.loads(text)
    return document


class LayoutCase(unittest.TestCase):
    """A fresh temporary directory per test, for invented layout files and homes."""

    def setUp(self) -> None:
        scratch = TemporaryDirectory()
        self.addCleanup(scratch.cleanup)
        self.scratch = Path(scratch.name)

    def write_layout(self, document: object) -> Path:
        """Write *document* as an invented layout file and return its path."""
        path = self.scratch / "layout.json"
        path.write_text(json.dumps(document), encoding="utf-8", newline="\n")
        return path

    def assert_refused(self, path: Path, *named: str) -> None:
        """Loading *path* raises LayoutError whose message names each of *named*."""
        with self.assertRaises(run_layout.LayoutError) as caught:
            run_layout.load_layout(path)
        for word in named:
            self.assertIn(word, str(caught.exception))


class LoadLayoutTest(LayoutCase):
    """The committed file loads with every key, and no value is absolute."""

    def test_the_file_is_the_one_beside_the_src_folder(self) -> None:
        self.assertEqual(run_layout.LAYOUT_FILE, _HERE.parent / "layout.json")

    def test_every_key_loads_with_its_value(self) -> None:
        layout = run_layout.load_layout()
        document = _real_document()
        self.assertEqual(set(document), _KEYS)
        for key in sorted(_KEYS):
            with self.subTest(key=key):
                self.assertEqual(getattr(layout, key), document[key])

    def test_the_loader_s_keys_are_the_file_s(self) -> None:
        self.assertEqual(run_layout.layout_keys(), _KEYS)

    def test_no_value_is_absolute(self) -> None:
        for key, value in _real_document().items():
            with self.subTest(key=key):
                self.assertFalse(Path(value).is_absolute())
                self.assertFalse(value.startswith("~"))

    def test_the_names_are_the_ones_macos_shows(self) -> None:
        layout = run_layout.load_layout()
        self.assertEqual(layout.display_name, "Apple Music Toolbox Runner")
        self.assertEqual(layout.app_name, "Apple Music Toolbox Runner.app")
        self.assertEqual(layout.bundle_id, "local.apple-music-toolbox.runner")
        self.assertEqual(layout.grant_label, f"{layout.launchd_label}.grant")


class RefusalTest(LayoutCase):
    """A layout file the loader cannot trust is a LayoutError, never a partial layout."""

    def test_a_missing_key_is_named(self) -> None:
        document = _real_document()
        del document["grant_label"]
        self.assert_refused(self.write_layout(document), "grant_label", "missing")

    def test_an_unknown_key_is_named(self) -> None:
        document = {**_real_document(), "spare_key": "x"}
        self.assert_refused(self.write_layout(document), "spare_key", "unknown")

    def test_a_value_that_is_not_a_string_is_named(self) -> None:
        document: dict[str, object] = {**_real_document(), "version": 1}
        self.assert_refused(self.write_layout(document), "version", "string")

    def test_an_absolute_path_value_is_named(self) -> None:
        for key in _PATH_KEYS:
            with self.subTest(key=key):
                document = {**_real_document(), key: "/elsewhere/file"}
                self.assert_refused(self.write_layout(document), key, "relative")

    def test_a_home_shorthand_path_value_is_named(self) -> None:
        document = {**_real_document(), "data_dir": "~/data"}
        self.assert_refused(self.write_layout(document), "data_dir", "relative")

    def test_a_name_holding_a_slash_is_named(self) -> None:
        for key in _NAME_KEYS:
            with self.subTest(key=key):
                document = {**_real_document(), key: "elsewhere/name"}
                self.assert_refused(self.write_layout(document), key, "one path part")

    def test_a_name_that_is_a_dot_is_named(self) -> None:
        for key in _NAME_KEYS:
            with self.subTest(key=key):
                document = {**_real_document(), key: "."}
                self.assert_refused(self.write_layout(document), key, "one path part")

    def test_a_name_that_is_two_dots_is_named(self) -> None:
        for key in _NAME_KEYS:
            with self.subTest(key=key):
                document = {**_real_document(), key: ".."}
                self.assert_refused(self.write_layout(document), key, "one path part")

    def test_a_path_value_with_a_parent_part_is_named(self) -> None:
        for key in _PATH_KEYS:
            with self.subTest(key=key):
                document = {**_real_document(), key: "Library/../../elsewhere"}
                self.assert_refused(self.write_layout(document), key, "..")

    def test_an_empty_value_is_named(self) -> None:
        document = {**_real_document(), "executable": ""}
        self.assert_refused(self.write_layout(document), "executable", "empty")

    def test_a_document_that_is_not_an_object_is_refused(self) -> None:
        self.assert_refused(self.write_layout(["version"]), "object")

    def test_text_that_is_not_json_is_refused(self) -> None:
        path = self.scratch / "layout.json"
        path.write_text("{not json", encoding="utf-8", newline="\n")
        self.assert_refused(path, "JSON")

    def test_an_absent_file_is_refused(self) -> None:
        self.assert_refused(self.scratch / "absent.json", "cannot read")

    def test_bytes_that_are_not_utf8_are_refused(self) -> None:
        path = self.scratch / "layout.json"
        path.write_bytes(b"\xff\xfe{}")
        self.assert_refused(path, "cannot read")


class PathsTest(LayoutCase):
    """Every derived path sits under the home it was given."""

    def test_each_path_is_under_the_given_home(self) -> None:
        home = self.scratch / "home"
        paths = run_layout.load_layout().paths(home)
        for name, path in vars(paths).items():
            with self.subTest(path=name):
                self.assertTrue(path.is_relative_to(home), path)

    def test_the_data_folder_holds_the_app_the_logs_and_the_grant_result(self) -> None:
        home = self.scratch / "home"
        layout = run_layout.load_layout()
        paths = layout.paths(home)
        data = home / layout.data_dir
        self.assertEqual(paths.data_dir, data)
        self.assertEqual(paths.app_bundle, data / layout.app_name)
        self.assertEqual(paths.logs_dir, data / "logs")
        self.assertEqual(paths.grant_err_log, data / "logs" / "grant.err.log")
        self.assertEqual(paths.grant_dir, data / "grant")
        self.assertEqual(paths.grant_result, data / "grant" / "result.json")

    def test_the_signing_and_agent_paths(self) -> None:
        home = self.scratch / "home"
        layout = run_layout.load_layout()
        paths = layout.paths(home)
        self.assertEqual(paths.signing_config, home / layout.signing_config)
        self.assertEqual(
            paths.grant_plist, paths.grant_dir / f"{layout.grant_label}.plist"
        )

    def test_the_grant_plist_stays_out_of_the_launch_agents_folder(self) -> None:
        # launchd loads every plist in ~/Library/LaunchAgents at login, and an uninstall
        # launchd cannot confirm keeps its plist; in the runner's own folder it is inert.
        home = self.scratch / "home"
        layout = run_layout.load_layout()
        grant_plist = layout.paths(home).grant_plist
        self.assertTrue(grant_plist.is_relative_to(home / layout.data_dir / "grant"))
        self.assertFalse(grant_plist.is_relative_to(home / "Library" / "LaunchAgents"))
        self.assertNotIn("launch_agents_dir", run_layout.layout_keys())


if __name__ == "__main__":
    unittest.main()
