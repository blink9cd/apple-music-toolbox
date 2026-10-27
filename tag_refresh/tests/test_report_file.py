"""report_file: a report is refused inside a git working tree and replaced atomically.

Every tree here is made under a fresh temporary directory, and the "working tree" is
nothing but a folder holding a ``.git`` entry, which is all the refusal looks for: no
git command is run and no real repository is touched.
"""

from __future__ import annotations

import os
import stat
import sys
import unittest
from pathlib import Path
from unittest import mock

_HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(_HERE), str(_HERE.parent / "src")]

import refresh_fixtures as rf  # noqa: E402 - import follows the sys.path bootstrap above
import report_file  # noqa: E402 - import follows the sys.path bootstrap above


class RefusalTest(rf.TreeCase):
    """Where a report may not go, and why."""

    def test_a_folder_outside_any_working_tree_is_accepted(self) -> None:
        self.assertIsNone(report_file.refusal(self.root / "report.txt"))

    def test_a_folder_holding_a_git_folder_is_refused(self) -> None:
        (self.root / "repo" / ".git").mkdir(parents=True)
        (self.root / "repo" / "deep" / "er").mkdir(parents=True)
        for target in (
            self.root / "repo" / "report.txt",
            self.root / "repo" / "deep" / "er" / "report.txt",
        ):
            with self.subTest(target=target):
                reason = report_file.refusal(target)
                self.assertIsNotNone(reason)
                self.assertIn("git working tree", str(reason))
                self.assertIn(str(self.root / "repo"), str(reason))

    def test_a_linked_worktree_whose_git_entry_is_a_file_is_refused(self) -> None:
        self.touch("worktree/.git", b"gitdir: elsewhere\n")
        self.assertIsNotNone(report_file.refusal(self.root / "worktree" / "r.txt"))

    def test_a_symlinked_folder_into_a_working_tree_is_refused(self) -> None:
        (self.root / "repo" / ".git").mkdir(parents=True)
        (self.root / "repo" / "out").mkdir()
        (self.root / "link").symlink_to(self.root / "repo" / "out")
        self.assertIsNotNone(report_file.refusal(self.root / "link" / "report.txt"))

    def test_a_relative_target_is_judged_from_the_working_directory(self) -> None:
        (self.root / "repo" / ".git").mkdir(parents=True)
        self.addCleanup(os.chdir, os.getcwd())
        os.chdir(self.root / "repo")
        self.assertIsNotNone(report_file.refusal(Path("report.txt")))

    def test_a_missing_folder_is_refused(self) -> None:
        reason = report_file.refusal(self.root / "absent" / "report.txt")
        self.assertIn("not a folder", str(reason))

    def test_a_target_that_is_a_folder_is_refused(self) -> None:
        (self.root / "taken").mkdir()
        reason = report_file.refusal(self.root / "taken")
        self.assertIn("is a folder", str(reason))


class WriteAtomicallyTest(rf.TreeCase):
    """The new bytes land whole, through a temporary file in the same folder."""

    def test_a_new_file_is_written(self) -> None:
        target = self.root / "report.txt"
        report_file.write_atomically(target, b"one\ntwo\n")
        self.assertEqual(target.read_bytes(), b"one\ntwo\n")
        self.assertEqual(sorted(p.name for p in self.root.iterdir()), ["report.txt"])

    def test_an_existing_file_is_replaced_whole(self) -> None:
        target = self.touch("report.txt", b"old and longer\n")
        report_file.write_atomically(target, b"new\n")
        self.assertEqual(target.read_bytes(), b"new\n")

    def test_the_file_is_readable_and_writable_by_its_owner_only(self) -> None:
        # It lists a private library: 0600 whatever the umask, and whatever mode the
        # file it replaces had.
        old_umask = os.umask(0)
        self.addCleanup(os.umask, old_umask)
        fresh = self.root / "fresh.txt"
        report_file.write_atomically(fresh, b"x\n")
        replaced = self.touch("replaced.txt", b"old\n")
        replaced.chmod(0o644)
        report_file.write_atomically(replaced, b"new\n")
        for target in (fresh, replaced):
            with self.subTest(target=target.name):
                self.assertEqual(stat.S_IMODE(target.stat().st_mode), 0o600)

    def test_the_temporary_file_sits_beside_the_target(self) -> None:
        target = self.root / "report.txt"
        seen: list[str] = []
        real_replace = os.replace

        def _replace(source: str, destination: Path) -> None:
            seen.append(source)
            real_replace(source, destination)

        with mock.patch.object(report_file.os, "replace", side_effect=_replace):
            report_file.write_atomically(target, b"x\n")
        self.assertEqual(Path(seen[0]).parent, self.root)

    def test_a_failed_replace_leaves_the_old_file_and_no_temporary(self) -> None:
        target = self.touch("report.txt", b"old\n")
        with (
            mock.patch.object(
                report_file.os, "replace", side_effect=OSError("invented failure")
            ),
            self.assertRaises(OSError),
        ):
            report_file.write_atomically(target, b"new\n")
        self.assertEqual(target.read_bytes(), b"old\n")
        self.assertEqual(sorted(p.name for p in self.root.iterdir()), ["report.txt"])


if __name__ == "__main__":
    unittest.main()
