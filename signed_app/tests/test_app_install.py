"""app_install: private folders and the linked-worktree refusal.

Every tool is a fake from `_app_fixtures` and every path is under a temporary root. The
bundle swap and the stale-folder sweep are `test_app_swap`'s.
"""

from __future__ import annotations

import os
import stat
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))

import _app_fixtures as fx  # noqa: E402 - import follows the sys.path bootstrap above
import app_bundle  # noqa: E402 - on sys.path once _app_fixtures is imported
import app_install  # noqa: E402 - on sys.path once _app_fixtures is imported

if sys.platform == "win32":
    # POSIX only, as a signed app is; also lets the win32 type-check skip os.getuid.
    raise unittest.SkipTest("a signed app runs on macOS only")  # pragma: only-on win32

#: The invented entry script, below the invented checkout.
_SCRIPT = "invented_tool/invented_tool.py"


class MakePrivateTest(unittest.TestCase):
    """`make_private`: the folder it checks is the folder it changes."""

    def setUp(self) -> None:
        kit = fx.make_host_kit(self, script=_SCRIPT, product="invented")
        self.root = kit.home.parent
        self.folder = self.root / "data" / "logs"
        self.elsewhere = self.root / "elsewhere"
        self.elsewhere.mkdir()
        self.elsewhere.chmod(0o755)

    def assert_refused_untouched(self, *words: str) -> None:
        """make_private refuses the folder naming each word, and `elsewhere` keeps 0755."""
        with self.assertRaises(app_bundle.Refused) as caught:
            app_install.make_private(self.folder)
        for word in words:
            self.assertIn(word, str(caught.exception))
        self.assertEqual(stat.S_IMODE(self.elsewhere.stat().st_mode), 0o755)

    def test_the_private_mode_is_the_user_s_alone(self) -> None:
        self.assertEqual(app_install.PRIVATE_MODE, 0o700)

    def test_a_new_folder_and_its_parents_are_made_and_the_folder_is_0700(
        self,
    ) -> None:
        app_install.make_private(self.folder)
        self.assertTrue(self.folder.is_dir())
        self.assertEqual(stat.S_IMODE(self.folder.stat().st_mode), 0o700)

    def test_every_level_it_makes_is_0700(self) -> None:
        deep = self.root / "data" / "one" / "two"
        app_install.make_private(deep)
        for level in (self.root / "data", self.root / "data" / "one", deep):
            with self.subTest(level=level.name):
                self.assertEqual(stat.S_IMODE(level.stat().st_mode), 0o700)

    def test_a_level_that_already_exists_above_the_new_ones_is_left_as_it_is(
        self,
    ) -> None:
        (self.root / "data").mkdir()
        (self.root / "data").chmod(0o755)
        app_install.make_private(self.folder)
        self.assertEqual(stat.S_IMODE((self.root / "data").stat().st_mode), 0o755)

    def test_an_existing_level_that_is_a_symlink_is_followed_as_found(self) -> None:
        # The levels that exist already are the user's own (Application Support moved to
        # another disk, say), so a link among them is used as found, never refused.
        (self.root / "data").symlink_to(self.elsewhere)
        app_install.make_private(self.folder)
        self.assertTrue((self.elsewhere / self.folder.name).is_dir())
        self.assertEqual(stat.S_IMODE(self.elsewhere.stat().st_mode), 0o755)

    def test_a_symlink_swapped_in_at_a_parent_it_makes_is_refused(self) -> None:
        real_mkdir = os.mkdir
        parent = self.folder.parent

        def make_then_swap(
            path: str, mode: int = 0o777, *, dir_fd: int | None = None
        ) -> None:
            real_mkdir(path, mode, dir_fd=dir_fd)
            if Path(path).name == parent.name:
                os.rmdir(parent)
                parent.symlink_to(self.elsewhere)

        with mock.patch.object(app_install.os, "mkdir", side_effect=make_then_swap):
            self.assert_refused_untouched("symbolic link", str(parent))
        self.assertEqual(list(self.elsewhere.iterdir()), [])

    def test_an_existing_open_folder_is_closed_to_0700(self) -> None:
        self.folder.mkdir(parents=True)
        self.folder.chmod(0o755)
        app_install.make_private(self.folder)
        self.assertEqual(stat.S_IMODE(self.folder.stat().st_mode), 0o700)

    def test_a_symlink_planted_before_the_call_is_refused(self) -> None:
        self.folder.parent.mkdir()
        self.folder.symlink_to(self.elsewhere)
        self.assert_refused_untouched("symbolic link")

    def test_a_symlink_to_nothing_is_refused(self) -> None:
        self.folder.parent.mkdir()
        self.folder.symlink_to(self.root / "missing")
        self.assert_refused_untouched("symbolic link")
        self.assertFalse((self.root / "missing").exists())

    def test_a_symlink_swapped_in_after_the_folder_is_made_is_refused(self) -> None:
        real_mkdir = os.mkdir

        def make_then_swap(
            path: str, mode: int = 0o777, *, dir_fd: int | None = None
        ) -> None:
            real_mkdir(path, mode, dir_fd=dir_fd)
            if Path(path).name == self.folder.name:
                os.rmdir(self.folder)
                self.folder.symlink_to(self.elsewhere)

        with mock.patch.object(app_install.os, "mkdir", side_effect=make_then_swap):
            self.assert_refused_untouched("symbolic link")

    def test_a_folder_of_another_user_is_refused_unchanged(self) -> None:
        self.folder.mkdir(parents=True)
        self.folder.chmod(0o755)
        real_fstat = os.fstat

        def foreign(descriptor: int) -> os.stat_result:
            fields = list(real_fstat(descriptor))
            fields[stat.ST_UID] = os.getuid() + 1
            return os.stat_result(fields)

        with mock.patch.object(app_install.os, "fstat", side_effect=foreign):
            self.assert_refused_untouched("another user")
        self.assertEqual(stat.S_IMODE(self.folder.stat().st_mode), 0o755)

    @unittest.skipIf(os.geteuid() == 0, "root reads a folder whatever its mode")
    def test_an_unreadable_folder_of_ours_is_refused_naming_it(self) -> None:
        for mode in (0o000, 0o300):
            with self.subTest(mode=oct(mode)):
                self.folder.mkdir(parents=True, exist_ok=True)
                self.folder.chmod(mode)
                # Restored before the temporary root is removed, which needs to list it.
                self.addCleanup(self.folder.chmod, 0o700)
                self.assert_refused_untouched(str(self.folder), "cannot be read")
                self.assertEqual(stat.S_IMODE(self.folder.stat().st_mode), mode)

    def test_a_file_at_the_path_is_an_os_error(self) -> None:
        self.folder.parent.mkdir()
        self.folder.write_bytes(b"")
        with self.assertRaises(OSError):
            app_install.make_private(self.folder)


class LinkedWorktreeTest(unittest.TestCase):
    """`refuse_linked_worktree`: a linked worktree is refused, and so is a git in doubt."""

    def setUp(self) -> None:
        self.kit = fx.make_host_kit(self, script=_SCRIPT, product="invented")
        self.folder = self.kit.host.script.parent

    def refuse(self) -> str:
        """The refusal's message."""
        with self.assertRaises(app_bundle.Refused) as caught:
            app_install.refuse_linked_worktree(self.kit.host)
        return str(caught.exception)

    def test_a_main_checkout_may_install(self) -> None:
        app_install.refuse_linked_worktree(self.kit.host)
        self.assertEqual(
            self.kit.tools.calls,
            [
                [
                    "git",
                    "-C",
                    str(self.folder),
                    "rev-parse",
                    "--git-dir",
                    "--git-common-dir",
                ]
            ],
        )

    def test_a_linked_worktree_is_refused(self) -> None:
        self.kit.tools.git_dir = ".git/worktrees/lane"
        self.assertEqual(
            self.refuse(),
            f"{self.folder} is in a linked git worktree, which is often removed once "
            "its work is done; install from the repository's main checkout",
        )

    def test_a_folder_outside_every_repository_may_install(self) -> None:
        self.kit.tools.repos.clear()
        app_install.refuse_linked_worktree(self.kit.host)

    def test_a_git_that_cannot_run_is_refused(self) -> None:
        self.kit.tools.missing.add("git")
        self.assertEqual(
            self.refuse(),
            f"could not ask git whether {self.folder} is a linked worktree "
            "(FileNotFoundError)",
        )

    def test_a_git_that_fails_otherwise_is_refused(self) -> None:
        def failing(args: list[str], cwd: Path) -> fx.subprocess.CompletedProcess[str]:
            return fx.done(args, 128, err="fatal: invented unsafe repository\n")

        self.kit.tools._git = failing  # type: ignore[method-assign]
        self.assertEqual(
            self.refuse(),
            f"git could not say whether {self.folder} is a linked worktree (exit 128)",
        )

    def test_an_answer_short_of_two_lines_is_refused(self) -> None:
        def short(args: list[str], cwd: Path) -> fx.subprocess.CompletedProcess[str]:
            return fx.done(args, 0, ".git\n")

        self.kit.tools._git = short  # type: ignore[method-assign]
        self.assertIn("could not say", self.refuse())


if __name__ == "__main__":
    unittest.main()
