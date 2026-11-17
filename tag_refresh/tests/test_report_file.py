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
from contextlib import AbstractContextManager
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


class ListingCase(rf.TreeCase):
    """A tree case that can list its folder."""

    def listing(self) -> list[str]:
        """The names in the folder, so a staging file left behind shows."""
        return sorted(p.name for p in self.root.iterdir())


class WriteNewTest(ListingCase):
    """The bytes land whole as a new file, and an existing one is never replaced."""

    def test_a_new_file_is_written_whole_at_mode_0600(self) -> None:
        old_umask = os.umask(0)
        self.addCleanup(os.umask, old_umask)
        target = self.root / "report.txt"
        report_file.write_new(target, b"one\ntwo\n")
        self.assertEqual(target.read_bytes(), b"one\ntwo\n")
        self.assertEqual(stat.S_IMODE(target.stat().st_mode), 0o600)
        self.assertEqual(self.listing(), ["report.txt"])

    def test_an_existing_file_is_refused_and_left_as_it_was(self) -> None:
        target = self.touch("report.txt", b"old\n")
        with self.assertRaises(FileExistsError):
            report_file.write_new(target, b"new\n")
        self.assertEqual(target.read_bytes(), b"old\n")
        self.assertEqual(self.listing(), ["report.txt"])

    def test_a_dangling_link_is_refused_and_not_followed(self) -> None:
        target = self.root / "report.txt"
        target.symlink_to(self.root / "absent.txt")
        with self.assertRaises(FileExistsError):
            report_file.write_new(target, b"new\n")
        self.assertTrue(target.is_symlink())
        self.assertEqual(self.listing(), ["report.txt"])

    def test_a_file_made_after_the_staging_write_is_not_replaced(self) -> None:
        # The race this pins: another writer makes the target once the staging
        # file is ready, just before it is published.
        target = self.root / "report.txt"
        real_link = os.link
        published: list[str] = []

        def plant_then_link(source: str, destination: Path) -> None:
            published.append(source)
            destination.write_bytes(b"planted\n")
            real_link(source, destination)

        with (
            mock.patch.object(report_file.os, "link", side_effect=plant_then_link),
            self.assertRaises(FileExistsError),
        ):
            report_file.write_new(target, b"new\n")
        self.assertEqual(Path(published[0]).parent, self.root)
        self.assertEqual(target.read_bytes(), b"planted\n")
        self.assertEqual(self.listing(), ["report.txt"])

    def test_a_failed_link_leaves_no_target_and_no_staging_file(self) -> None:
        target = self.root / "report.txt"
        with (
            mock.patch.object(
                report_file.os, "link", side_effect=OSError(45, "invented failure")
            ),
            self.assertRaises(OSError),
        ):
            report_file.write_new(target, b"new\n")
        self.assertEqual(self.listing(), [])

    def test_a_failed_staging_write_leaves_nothing(self) -> None:
        target = self.root / "report.txt"
        with (
            mock.patch.object(
                report_file.os, "fsync", side_effect=OSError(28, "No space left")
            ),
            self.assertRaises(OSError),
        ):
            report_file.write_new(target, b"new\n")
        self.assertEqual(self.listing(), [])

    def test_a_clean_publish_reports_no_leftover(self) -> None:
        self.assertIsNone(report_file.write_new(self.root / "report.txt", b"x\n"))


class WriteNewCleanupTest(ListingCase):
    """The link's outcome is the write's outcome: a failed cleanup never replaces it."""

    def unlink_failing(self, error: BaseException) -> AbstractContextManager[object]:
        """A patch making every unlink raise *error*, as a staging name that sticks."""
        return mock.patch.object(report_file.os, "unlink", side_effect=error)

    def test_a_failed_cleanup_after_the_link_still_publishes(self) -> None:
        target = self.root / "report.txt"
        with self.unlink_failing(PermissionError(1, "Operation not permitted")):
            leftover = report_file.write_new(target, b"whole\n")
        self.assertEqual(target.read_bytes(), b"whole\n")
        assert leftover is not None
        self.assertEqual(Path(leftover).parent, self.root)
        self.assertEqual(self.listing(), sorted([Path(leftover).name, "report.txt"]))

    def test_a_failed_cleanup_after_a_refused_link_keeps_the_refusal(self) -> None:
        target = self.touch("report.txt", b"old\n")
        with (
            self.unlink_failing(PermissionError(1, "Operation not permitted")),
            self.assertRaises(FileExistsError),
        ):
            report_file.write_new(target, b"new\n")
        self.assertEqual(target.read_bytes(), b"old\n")

    def test_a_failed_cleanup_after_a_failed_link_keeps_the_links_error(self) -> None:
        with (
            mock.patch.object(
                report_file.os, "link", side_effect=OSError(45, "invented failure")
            ),
            self.unlink_failing(PermissionError(1, "Operation not permitted")),
            self.assertRaises(OSError) as raised,
        ):
            report_file.write_new(self.root / "report.txt", b"new\n")
        self.assertEqual(raised.exception.errno, 45)


class WriteNewInterruptTest(ListingCase):
    """Ctrl-C once the link is made says so; before it, a plain interrupt."""

    def test_an_interrupt_as_the_link_returns_is_published(self) -> None:
        target = self.root / "report.txt"
        real_link = os.link

        def link_then_interrupt(source: str, destination: Path) -> None:
            real_link(source, destination)
            raise KeyboardInterrupt

        with (
            mock.patch.object(report_file.os, "link", side_effect=link_then_interrupt),
            self.assertRaises(report_file.InterruptedAfterPublish),
        ):
            report_file.write_new(target, b"whole\n")
        self.assertEqual(target.read_bytes(), b"whole\n")
        self.assertEqual(self.listing(), ["report.txt"])

    def test_an_interrupt_during_the_cleanup_is_published(self) -> None:
        target = self.root / "report.txt"
        with (
            mock.patch.object(report_file.os, "unlink", side_effect=KeyboardInterrupt),
            self.assertRaises(report_file.InterruptedAfterPublish),
        ):
            report_file.write_new(target, b"whole\n")
        self.assertEqual(target.read_bytes(), b"whole\n")

    def test_an_interrupt_before_the_link_is_a_plain_interrupt(self) -> None:
        target = self.root / "report.txt"
        with (
            mock.patch.object(report_file.os, "link", side_effect=KeyboardInterrupt),
            self.assertRaises(KeyboardInterrupt) as raised,
        ):
            report_file.write_new(target, b"whole\n")
        self.assertNotIsInstance(raised.exception, report_file.InterruptedAfterPublish)
        self.assertEqual(self.listing(), [])

    def test_an_interrupt_before_the_link_beside_a_planted_file_is_plain(self) -> None:
        # The target exists but is not the staged file, so nothing was published.
        target = self.touch("report.txt", b"planted\n")
        with (
            mock.patch.object(report_file.os, "link", side_effect=KeyboardInterrupt),
            self.assertRaises(KeyboardInterrupt) as raised,
        ):
            report_file.write_new(target, b"whole\n")
        self.assertNotIsInstance(raised.exception, report_file.InterruptedAfterPublish)
        self.assertEqual(target.read_bytes(), b"planted\n")


class CleanupKeepsTheErrorTest(ListingCase):
    """A failed cleanup never replaces the error that made it, in either write."""

    def unlink_failing(self) -> AbstractContextManager[object]:
        """A patch making every unlink fail, as a temporary file that sticks."""
        return mock.patch.object(
            report_file.os,
            "unlink",
            side_effect=PermissionError(1, "Operation not permitted"),
        )

    def test_a_failed_cleanup_after_a_failed_replace_keeps_the_replaces_error(
        self,
    ) -> None:
        target = self.touch("report.txt", b"old\n")
        with (
            mock.patch.object(
                report_file.os, "replace", side_effect=OSError(18, "invented failure")
            ),
            self.unlink_failing(),
            self.assertRaises(OSError) as raised,
        ):
            report_file.write_atomically(target, b"new\n")
        self.assertEqual(raised.exception.errno, 18)
        self.assertEqual(target.read_bytes(), b"old\n")

    def test_a_failed_cleanup_after_a_failed_staging_write_keeps_its_error(
        self,
    ) -> None:
        for write in (report_file.write_atomically, report_file.write_new):
            with self.subTest(write=write.__name__):
                with (
                    mock.patch.object(
                        report_file.os, "fsync", side_effect=OSError(28, "No space")
                    ),
                    self.unlink_failing(),
                    self.assertRaises(OSError) as raised,
                ):
                    write(self.root / f"{write.__name__}.txt", b"new\n")
                self.assertEqual(raised.exception.errno, 28)

    def test_an_interrupt_then_a_failed_cleanup_stays_an_interrupt(self) -> None:
        cases = (
            (report_file.write_atomically, "replace"),
            (report_file.write_atomically, "fsync"),
            (report_file.write_new, "fsync"),
        )
        for write, call in cases:
            with self.subTest(write=write.__name__, call=call):
                with (
                    mock.patch.object(
                        report_file.os, call, side_effect=KeyboardInterrupt
                    ),
                    self.unlink_failing(),
                    self.assertRaises(KeyboardInterrupt) as raised,
                ):
                    write(self.root / f"{write.__name__}.txt", b"new\n")
                self.assertNotIsInstance(
                    raised.exception, report_file.InterruptedAfterPublish
                )


if __name__ == "__main__":
    unittest.main()
