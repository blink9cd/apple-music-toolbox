"""run_allowlist: the repository-relative allowlist, resolved, refused, read and checked.

The paths are invented (nothing under ``/opt/example`` exists), the checkout is the kit's
fake repository, and git is the kit's `FakeTools`.
"""

from __future__ import annotations

import dataclasses
import json
import subprocess
import sys
import unittest
from collections.abc import Sequence
from pathlib import Path
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parent))

import _run_fixtures as fx  # noqa: E402 - import follows the sys.path bootstrap above
import app_bundle  # noqa: E402 - on sys.path once _run_fixtures is imported
import run_allowlist  # noqa: E402 - on sys.path once _run_fixtures is imported

#: An invented checkout and interpreter; neither exists.
_ROOT = Path("/opt/example/checkout")
_PYTHON = "/opt/example/venv/bin/python"


class ResolveTest(unittest.TestCase):
    """`resolve` joins each script to the checkout root, and refuses what could escape it."""

    def assert_refused(
        self, document: object, *named: str, python: str = _PYTHON
    ) -> None:
        """Resolving `document` is Refused, with a message naming each of `named`."""
        with self.assertRaises(app_bundle.Refused) as caught:
            run_allowlist.resolve(document, root=_ROOT, python=python)
        for word in named:
            self.assertIn(word, str(caught.exception))

    def test_scripts_resolve_against_the_checkout_root(self) -> None:
        root = Path("/opt/example/checkout")
        got = run_allowlist.resolve(
            {"scripts": ["projects/a/tool.py"]},
            root=root,
            python="/opt/example/venv/bin/python",
        )
        self.assertEqual(
            got,
            {
                "python": "/opt/example/venv/bin/python",
                "scripts": ["/opt/example/checkout/projects/a/tool.py"],
            },
        )

    def test_an_escaping_path_is_refused(self) -> None:
        with self.assertRaises(app_bundle.Refused):
            run_allowlist.resolve(
                {"scripts": ["../x.py"]}, root=Path("/r"), python="/v/p"
            )

    def test_a_parent_part_anywhere_is_refused(self) -> None:
        self.assert_refused({"scripts": ["projects/../../x.py"]}, "projects/../../x.py")

    def test_an_absolute_entry_is_refused(self) -> None:
        self.assert_refused({"scripts": ["/opt/example/x.py"]}, "/opt/example/x.py")

    def test_a_home_shorthand_entry_is_refused(self) -> None:
        self.assert_refused({"scripts": ["~/x.py"]}, "~/x.py")

    def test_scripts_that_are_not_a_list_are_refused(self) -> None:
        self.assert_refused({"scripts": "projects/a/tool.py"}, "list")

    def test_an_entry_that_is_not_text_is_refused(self) -> None:
        self.assert_refused({"scripts": ["projects/a/tool.py", 7]}, "list")

    def test_an_empty_entry_is_refused(self) -> None:
        self.assert_refused({"scripts": [""]}, "empty")

    def test_a_document_that_is_not_an_object_is_refused(self) -> None:
        self.assert_refused(["projects/a/tool.py"], "scripts")

    def test_any_other_key_is_refused(self) -> None:
        self.assert_refused({"scripts": [], "python": _PYTHON}, "scripts")

    def test_a_relative_python_is_refused(self) -> None:
        self.assert_refused({"scripts": []}, "absolute", python="venv/bin/python")

    def test_an_unknown_python_is_refused(self) -> None:
        # What sys.executable is when Python cannot tell its own path.
        self.assert_refused({"scripts": []}, "absolute", python="")

    def test_a_missing_script_file_is_refused(self) -> None:
        seen: list[Path] = []

        def is_file(path: Path) -> bool:
            seen.append(path)
            return False

        with self.assertRaises(app_bundle.Refused) as caught:
            run_allowlist.resolve(
                {"scripts": ["projects/a/tool.py"]},
                root=_ROOT,
                python=_PYTHON,
                is_file=is_file,
            )
        self.assertEqual(seen, [_ROOT / "projects/a/tool.py"])
        self.assertIn("projects/a/tool.py", str(caught.exception))
        self.assertIn("is not a file", str(caught.exception))

    def test_the_interpreter_is_never_resolved(self) -> None:
        # A venv's python is a link to the base interpreter; the allowlist holds the
        # link's own path, the string a scheduled job passes.
        got = run_allowlist.resolve({"scripts": []}, root=_ROOT, python="/v/../v/p")
        self.assertEqual(got["python"], "/v/../v/p")


class LoadTest(unittest.TestCase):
    """`load` reads the allowlist file, refusing one it cannot read as a JSON document."""

    def setUp(self) -> None:
        scratch = TemporaryDirectory()
        self.addCleanup(scratch.cleanup)
        self.path = Path(scratch.name) / "allowlist.json"

    def test_the_file_is_the_one_beside_the_src_folder(self) -> None:
        self.assertEqual(run_allowlist.ALLOWLIST_FILE, fx.TOOL_ROOT / "allowlist.json")

    def test_the_committed_file_names_the_grant_probe_where_it_is(self) -> None:
        self.assertEqual(run_allowlist.load(), {"scripts": fx.repo_scripts()})
        (probe,) = [
            entry for entry in fx.repo_scripts() if Path(entry).name == fx.PROBE_NAME
        ]
        real = fx.PROBE_FILE
        self.assertTrue(real.is_file())
        self.assertEqual(real.parts[-len(Path(probe).parts) :], Path(probe).parts)

    def test_an_absent_file_is_refused(self) -> None:
        with self.assertRaises(app_bundle.Refused) as caught:
            run_allowlist.load(self.path)
        self.assertIn("cannot read the allowlist file", str(caught.exception))

    def test_text_that_is_not_json_is_refused(self) -> None:
        self.path.write_text("{not json", encoding="utf-8", newline="\n")
        with self.assertRaises(app_bundle.Refused) as caught:
            run_allowlist.load(self.path)
        self.assertIn("not JSON", str(caught.exception))

    def test_any_json_document_is_returned_for_resolve_to_judge(self) -> None:
        self.path.write_text(json.dumps([1]), encoding="utf-8", newline="\n")
        self.assertEqual(run_allowlist.load(self.path), [1])


class ForHostTest(unittest.TestCase):
    """`for_host` resolves the committed allowlist against the entry script's checkout."""

    def setUp(self) -> None:
        self.kit = fx.make_kit(self)

    def test_the_root_is_the_checkout_git_names(self) -> None:
        self.assertEqual(run_allowlist.for_host(self.kit.host), self.kit.allowlist())
        asked = self.kit.tools.calls[-1]
        folder = str(self.kit.host.script.parent)
        self.assertEqual(asked, ["git", "-C", folder, "rev-parse", "--show-toplevel"])

    def test_the_interpreter_is_this_one_unresolved(self) -> None:
        self.assertEqual(
            run_allowlist.for_host(self.kit.host)["python"], sys.executable
        )

    def test_a_script_missing_from_the_checkout_is_refused(self) -> None:
        self.kit.probe.unlink()
        with self.assertRaises(app_bundle.Refused) as caught:
            run_allowlist.for_host(self.kit.host)
        self.assertIn(fx.PROBE_NAME, str(caught.exception))

    def test_a_folder_outside_every_repository_is_refused(self) -> None:
        self.kit.tools.repos.clear()
        with self.assertRaises(app_bundle.Refused) as caught:
            run_allowlist.for_host(self.kit.host)
        self.assertIn("could not find the checkout", str(caught.exception))
        self.assertIn("exit 128", str(caught.exception))

    def test_a_git_that_cannot_run_is_refused(self) -> None:
        self.kit.tools.missing.add("git")
        with self.assertRaises(app_bundle.Refused) as caught:
            run_allowlist.for_host(self.kit.host)
        self.assertIn("FileNotFoundError", str(caught.exception))

    def test_a_git_that_names_no_folder_is_refused(self) -> None:
        def silent(
            argv: Sequence[str], *, cwd: Path, timeout: float
        ) -> subprocess.CompletedProcess[str]:
            return fx.done(argv, 0, "\n")

        host = dataclasses.replace(self.kit.host, run=silent)
        with self.assertRaises(app_bundle.Refused) as caught:
            run_allowlist.for_host(host)
        self.assertIn("could not find the checkout", str(caught.exception))


class InfoValueTest(unittest.TestCase):
    """`from_info_value` decodes the Info.plist value as the Swift runner does."""

    def test_a_well_formed_value_is_decoded(self) -> None:
        value = {"python": _PYTHON, "scripts": ["/opt/example/a.py"]}
        self.assertEqual(run_allowlist.from_info_value(value), value)

    def test_any_other_shape_is_none(self) -> None:
        shapes: tuple[object, ...] = (
            None,
            [_PYTHON],
            {"scripts": []},
            {"python": _PYTHON},
            {"python": 7, "scripts": []},
            {"python": _PYTHON, "scripts": "/opt/example/a.py"},
            {"python": _PYTHON, "scripts": ["/opt/example/a.py", 7]},
        )
        for shape in shapes:
            with self.subTest(shape=shape):
                self.assertIsNone(run_allowlist.from_info_value(shape))


class CheckTest(unittest.TestCase):
    """`check` passes an exact match only, in the Swift runner's own words."""

    ALLOWED: run_allowlist.Allowlist = {
        "python": _PYTHON,
        "scripts": ["/opt/example/a.py", "/opt/example/b.py"],
    }

    def test_an_exact_match_passes(self) -> None:
        run_allowlist.check(self.ALLOWED, python=_PYTHON, script="/opt/example/b.py")

    def test_another_interpreter_is_refused(self) -> None:
        with self.assertRaises(app_bundle.Refused) as caught:
            run_allowlist.check(
                self.ALLOWED, python="/usr/bin/python3", script="/opt/example/a.py"
            )
        self.assertEqual(
            str(caught.exception), "not in the runner's allowlist: /usr/bin/python3"
        )

    def test_another_script_is_refused(self) -> None:
        with self.assertRaises(app_bundle.Refused) as caught:
            run_allowlist.check(
                self.ALLOWED, python=_PYTHON, script="/opt/example/c.py"
            )
        self.assertEqual(
            str(caught.exception), "not in the runner's allowlist: /opt/example/c.py"
        )

    def test_no_path_is_normalized(self) -> None:
        with self.assertRaises(app_bundle.Refused):
            run_allowlist.check(
                self.ALLOWED, python=_PYTHON, script="/opt/example/./a.py"
            )


if __name__ == "__main__":
    unittest.main()
