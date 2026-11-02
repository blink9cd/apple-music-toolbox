"""Grouped suite: this project's sys.path bootstrap never reaches above its own root.

Each tool puts this library, the other shared library and its sibling tool folders on
``sys.path`` from one fixed place: directly under the project root, derived from the
tool's own ``__file__``. Nothing here searches the ancestors, so no folder above a
checkout can be imported in place of the real one. ``stdio_utf8.md``, "How this
project's tools import it", says why.

Run through ``../test_stdio_utf8.py``'s ``load_tests`` hook, which is how this file runs.
"""

from __future__ import annotations

import ast
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

#: This project's root: two levels above this file, which sits in stdio_utf8/tests/.
_PROJECT_ROOT = Path(__file__).resolve().parents[2]

sys.path.insert(0, str(_PROJECT_ROOT / "bounded_run"))

import bounded_run  # noqa: E402 - import follows the sys.path bootstrap above

#: A generous ceiling for the black-box child: a hung CLI must fail this suite
#: rather than hang it.
_SUBPROCESS_TIMEOUT = 120

#: Every file carrying a sys.path bootstrap, relative to the root, with the arguments
#: that run it to a clean exit. recently_added has no CLI: run bare, it bootstraps,
#: imports its sibling and exits.
_BOOTSTRAPPED: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("album_stats/album_stats.py", ("--help",)),
    ("recently_added/recently_added.py", ()),
    ("tag_refresh/tag_refresh.py", ("--help",)),
    ("library_audit/library_audit.py", ("--help",)),
    ("phone_audit/phone_audit.py", ("--help",)),
)


def _ancestor_walk_lines(source: str) -> list[int]:
    """Lines in *source* where a comprehension iterates a ``.parents`` sequence.

    That is the shape of an unbounded upward search. A single ``parents[N]`` index is a
    subscript rather than an iteration, so the bounded form every bootstrap here uses
    reads as clean.
    """
    return [
        clause.iter.lineno
        for node in ast.walk(ast.parse(source))
        for clause in getattr(node, "generators", [])
        if isinstance(clause.iter, ast.Attribute) and clause.iter.attr == "parents"
    ]


class TestBootstrapStaysInsideTheProject(unittest.TestCase):
    """No tool's sys.path bootstrap may reach above this project's root.

    Each tool puts the shared libraries and its sibling tool folders on sys.path from
    the project root, one fixed candidate per name. A search that walked every ancestor
    instead would put any directory above the checkout that holds a same-named folder
    onto sys.path ahead of the standard library. These copy the project under a parent
    holding exactly such a folder and run each tool in a real subprocess; the planted
    module records that it ran.
    """

    def _plant_decoys(self, parent: Path) -> Path:
        """Plant a folder the old search would have taken, holding a shadowing module.

        ``bounded_run/bounded_run.py`` is what makes an ancestor search take the folder,
        and it is deliberately empty: the real library sits nearer, so it still wins its
        own name. The decoy is ``ctypes.py``, which the real ``bounded_run`` imports at
        its top level, after the bootstrap has put this folder on sys.path and before
        anything else has imported ctypes. That is the actual hazard, and it is why
        "the tool imported the module it asked for" proves nothing: a stranger's folder
        left on the path captures the next import, ahead of the standard library.
        Returns the path the decoy creates when it runs.
        """
        marker = parent / "decoy-ran"
        folder = parent / "bounded_run"
        folder.mkdir()
        (folder / "bounded_run.py").write_text("", encoding="utf-8", newline="\n")
        (folder / "ctypes.py").write_text(
            f"from pathlib import Path\nPath({str(marker)!r}).touch()\n",
            encoding="utf-8",
            newline="\n",
        )
        return marker

    def _run(self, script: Path, *args: str) -> subprocess.CompletedProcess[str]:
        """Run *script* to exit with no inherited PYTHON* setting, bounded.

        Through ``run_bounded`` rather than a captured ``subprocess.run``: on expiry
        CPython kills only the direct child and then re-reads pipes a surviving
        grandchild still holds open, so that bound does not hold. Output is captured so
        a failure here can name its own cause.
        """
        env = {k: v for k, v in os.environ.items() if not k.startswith("PYTHON")}
        return bounded_run.run_bounded(
            [sys.executable, str(script), *args],
            timeout=_SUBPROCESS_TIMEOUT,
            env=env,
        )

    def _staged_copy(self, parent: Path) -> Path:
        """This project's tool folders copied to ``<parent>/project``, without caches.

        A tool folder is one holding a module named after it (the layout every
        bootstrap relies on), so nothing else at the root is copied on every run.
        """
        project = parent / "project"
        for folder in _PROJECT_ROOT.iterdir():
            if (folder / f"{folder.name}.py").is_file():
                shutil.copytree(
                    folder,
                    project / folder.name,
                    ignore=shutil.ignore_patterns(".*", "__pycache__"),
                )
        return project

    def test_no_tool_imports_a_module_planted_above_the_root(self) -> None:
        for script, args in _BOOTSTRAPPED:
            with self.subTest(script=script), tempfile.TemporaryDirectory() as td:
                parent = Path(td)
                marker = self._plant_decoys(parent)
                done = self._run(self._staged_copy(parent) / script, *args)
                self.assertFalse(marker.exists(), f"{script} ran a planted module")
                # Also proves the tool really ran: a broken bootstrap exits non-zero.
                self.assertEqual(done.returncode, 0, done.stderr)

    def test_the_decoy_fires_for_an_unbounded_search(self) -> None:
        """The control: the walk these bootstraps replaced does run the decoy.

        Without it a clean result above could mean a dead decoy rather than a bounded
        search.
        """
        probe = (
            "import sys\n"
            "from pathlib import Path\n"
            "sys.path[:0] = [\n"
            "    str(folder)\n"
            "    for ancestor in Path(__file__).resolve().parents\n"
            '    for folder in (ancestor / "bounded_run",)\n'
            '    if (folder / "bounded_run.py").is_file()\n'
            "]\n"
            "import bounded_run  # noqa: E402, F401\n"
        )
        with tempfile.TemporaryDirectory() as td:
            parent = Path(td)
            marker = self._plant_decoys(parent)
            script = self._staged_copy(parent) / "probe" / "probe.py"
            script.parent.mkdir()
            script.write_text(probe, encoding="utf-8", newline="\n")
            self._run(script)
            self.assertTrue(marker.exists(), "the decoy never ran; the test is blind")

    def test_no_shipped_module_searches_every_ancestor(self) -> None:
        """Structural, so a walk added later fails here and not in a stranger's tree.

        The subprocess tests above cover the bootstraps that exist today; this one reads
        every shipped module.
        """
        offenders = [
            f"{path.relative_to(_PROJECT_ROOT)}:{line}"
            for path in sorted(_PROJECT_ROOT.rglob("*.py"))
            for line in _ancestor_walk_lines(path.read_text(encoding="utf-8"))
        ]
        self.assertEqual(offenders, [], "an unbounded ancestor search reached a module")

    def test_the_walk_detector_names_an_unbounded_search(self) -> None:
        """The detector's own control: it must fire on the shape it exists to refuse."""
        source = (
            "import sys\n"
            "from pathlib import Path\n"
            "sys.path[:0] = [\n"
            "    str(a / 'x') for a in Path(__file__).resolve().parents\n"
            "]\n"
        )
        self.assertEqual(_ancestor_walk_lines(source), [4])

    def test_the_walk_detector_passes_a_bounded_index(self) -> None:
        """``parents[N]`` is the bounded form, and must not read as a walk."""
        source = (
            "from pathlib import Path\nroot = Path(__file__).resolve().parents[1]\n"
        )
        self.assertEqual(_ancestor_walk_lines(source), [])
