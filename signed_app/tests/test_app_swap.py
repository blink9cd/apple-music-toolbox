"""app_install: the one-step bundle swap, and the sweep of a dead install's work folders.

Every path is under a temporary root. The real exchange runs only on macOS, the one
system with `renamex_np`; the wrapper's own logic is also driven through a fake C library
so it is measured on any POSIX host.
"""

from __future__ import annotations

import ctypes
import errno
import io
import os
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))

import _app_fixtures as fx  # noqa: E402 - import follows the sys.path bootstrap above
import app_install  # noqa: E402 - on sys.path once _app_fixtures is imported

if sys.platform == "win32":
    # POSIX only, as a signed app is.
    raise unittest.SkipTest("a signed app runs on macOS only")  # pragma: only-on win32

#: The invented entry script, below the invented checkout.
_SCRIPT = "invented_tool/invented_tool.py"
#: A pid no process holds.
_DEAD_PID = fx.DEAD_PID
#: Why the real exchange is skipped elsewhere.
_NOT_MACOS = "renamex_np is macOS's own call"


def _temporary_root(test: unittest.TestCase) -> Path:
    """A fresh temporary folder for `test`, removed when it ends."""
    return fx.make_host_kit(test, script=_SCRIPT, product="invented").home


def _folder_with(path: Path, name: str) -> Path:
    """`path` made as a folder holding one file `name` whose bytes are its name."""
    path.mkdir(parents=True)
    (path / name).write_bytes(name.encode())
    return path


class SwapInTest(unittest.TestCase):
    """`swap_in`: a first install renames in; an upgrade exchanges the two in one step."""

    def setUp(self) -> None:
        self.root = _temporary_root(self)
        self.final = self.root / "final.app"
        self.staged = _folder_with(self.root / "staging" / "staged.app", "new")

    def test_a_first_install_renames_the_staged_bundle_in(self) -> None:
        exchange = mock.Mock()
        app_install.swap_in(self.staged, self.final, exchange=exchange)
        self.assertTrue((self.final / "new").is_file())
        self.assertFalse(self.staged.exists())
        exchange.assert_not_called()

    def test_a_failed_first_install_leaves_nothing_in_place(self) -> None:
        absent = self.root / "absent.app"
        with self.assertRaises(OSError):
            app_install.swap_in(absent, self.final)
        self.assertFalse(self.final.exists())

    def test_an_upgrade_exchanges_and_never_renames_the_old_bundle_away(
        self,
    ) -> None:
        # The regression: the old swap renamed `final` aside first, so for a moment, and
        # for good after a kill there, no bundle was at the path.
        _folder_with(self.final, "old")
        seen: list[tuple[Path, Path]] = []

        def exchange(first: Path, second: Path) -> None:
            # Called with the old bundle still at `final`, untouched by anything before.
            self.assertEqual(sorted(p.name for p in self.final.iterdir()), ["old"])
            seen.append((first, second))

        with mock.patch.object(Path, "rename", side_effect=AssertionError("renamed")):
            app_install.swap_in(self.staged, self.final, exchange=exchange)
        self.assertEqual(seen, [(self.staged, self.final)])

    def test_a_failed_exchange_propagates_and_moves_nothing(self) -> None:
        _folder_with(self.final, "old")
        refused = OSError(errno.EPERM, "Operation not permitted", str(self.staged))
        with self.assertRaises(OSError) as caught:
            app_install.swap_in(
                self.staged, self.final, exchange=mock.Mock(side_effect=refused)
            )
        self.assertIs(caught.exception, refused)
        self.assertTrue((self.final / "old").is_file())
        self.assertTrue((self.staged / "new").is_file())

    def test_an_entry_spelled_otherwise_takes_the_exact_name_after_an_exchange(
        self,
    ) -> None:
        # Runs on any volume: the identity seam says the folder spelled otherwise is
        # the one at `final`, as a case-insensitive volume would after an exchange.
        _folder_with(self.final, "placeholder").joinpath("placeholder").unlink()
        spelled = _folder_with(self.root / "FINAL.other", "new")

        def same(first: Path, second: Path) -> bool:
            return first == spelled and second == self.final

        app_install.swap_in(
            self.staged, self.final, exchange=mock.Mock(), same_entry=same
        )
        names = sorted(p.name for p in self.root.iterdir())
        self.assertEqual(names, ["final.app", "staging"])
        self.assertTrue((self.final / "new").is_file())

    def test_an_exact_name_is_left_alone(self) -> None:
        _folder_with(self.final, "old")
        neighbor = _folder_with(self.root / "neighbor.app", "kept")
        app_install.swap_in(self.staged, self.final, exchange=mock.Mock())
        self.assertTrue((neighbor / "kept").is_file())
        self.assertTrue((self.final / "old").is_file())

    def test_the_identity_of_an_absent_entry_is_never_the_same(self) -> None:
        self.assertFalse(app_install.same_entry(self.root / "absent", self.root))
        self.assertTrue(app_install.same_entry(self.root, self.root))

    def test_a_link_to_the_entry_is_not_the_entry(self) -> None:
        _folder_with(self.final, "old")
        link = self.root / "link.app"
        link.symlink_to(self.final)
        self.assertFalse(app_install.same_entry(link, self.final))

    @unittest.skipUnless(sys.platform == "darwin", _NOT_MACOS)
    @unittest.skipUnless(fx.CASE_INSENSITIVE_TMP, fx.CASE_SENSITIVE_REASON)
    def test_a_real_case_only_upgrade_ends_with_the_exact_name(self) -> None:
        old = _folder_with(self.root / self.final.name.swapcase(), "old")
        app_install.swap_in(self.staged, self.final)
        names = sorted(p.name for p in self.root.iterdir())
        self.assertEqual(names, [self.final.name, "staging"])
        self.assertNotIn(old.name, names)
        self.assertEqual([p.name for p in self.final.iterdir()], ["new"])

    @unittest.skipUnless(sys.platform == "darwin", _NOT_MACOS)
    def test_a_real_upgrade_leaves_the_old_bundle_at_the_staged_path(self) -> None:
        _folder_with(self.final, "old")
        app_install.swap_in(self.staged, self.final)
        self.assertEqual([p.name for p in self.final.iterdir()], ["new"])
        self.assertEqual([p.name for p in self.staged.iterdir()], ["old"])


class ExchangePathsTest(unittest.TestCase):
    """`exchange_paths`: `renamex_np` with `RENAME_SWAP`, its failure an OSError."""

    def setUp(self) -> None:
        self.root = _temporary_root(self)
        self.first = _folder_with(self.root / "first", "one")
        self.second = _folder_with(self.root / "second", "two")

    def test_the_flag_is_rename_swap(self) -> None:
        self.assertEqual(app_install.RENAME_SWAP, 0x00000002)

    @unittest.skipUnless(sys.platform == "darwin", _NOT_MACOS)
    def test_a_real_exchange_swaps_two_folders(self) -> None:
        app_install.exchange_paths(self.first, self.second)
        self.assertEqual([p.name for p in self.first.iterdir()], ["two"])
        self.assertEqual([p.name for p in self.second.iterdir()], ["one"])

    @unittest.skipUnless(sys.platform == "darwin", _NOT_MACOS)
    def test_a_real_exchange_with_an_absent_path_fails_and_moves_nothing(
        self,
    ) -> None:
        absent = self.root / "absent"
        with self.assertRaises(FileNotFoundError) as caught:
            app_install.exchange_paths(absent, self.second)
        self.assertEqual(caught.exception.filename, str(absent))
        self.assertEqual([p.name for p in self.second.iterdir()], ["two"])

    def fake_libc(self, returned: int) -> tuple[SimpleNamespace, list[tuple]]:
        """A C library whose `renamex_np` records its arguments and returns `returned`."""
        calls: list[tuple] = []

        def renamex_np(*args: object) -> int:
            calls.append(args)
            return returned

        return SimpleNamespace(renamex_np=renamex_np), calls

    def test_the_call_passes_both_paths_and_the_flag(self) -> None:
        libc, calls = self.fake_libc(0)
        with mock.patch.object(app_install.ctypes, "CDLL", return_value=libc) as cdll:
            app_install.exchange_paths(self.first, self.second)
        cdll.assert_called_once_with(None, use_errno=True)
        expected = (os.fsencode(self.first), os.fsencode(self.second), 2)
        self.assertEqual(calls, [expected])
        # Declared, so ctypes checks each argument instead of guessing its C type.
        call = libc.renamex_np
        argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_uint]
        self.assertEqual(call.argtypes, argtypes)
        self.assertIs(call.restype, ctypes.c_int)

    def test_a_nonzero_return_is_the_os_error_errno_names(self) -> None:
        libc, _ = self.fake_libc(-1)
        with (
            mock.patch.object(app_install.ctypes, "CDLL", return_value=libc),
            mock.patch.object(
                app_install.ctypes, "get_errno", return_value=errno.EXDEV
            ),
            self.assertRaises(OSError) as caught,
        ):
            app_install.exchange_paths(self.first, self.second)
        self.assertEqual(caught.exception.errno, errno.EXDEV)
        self.assertEqual(caught.exception.strerror, os.strerror(errno.EXDEV))
        self.assertEqual(caught.exception.filename, str(self.first))
        self.assertEqual(caught.exception.filename2, str(self.second))


class PidIsAliveTest(unittest.TestCase):
    """`pid_is_alive`: `kill(pid, 0)`, read as alive unless no such process exists."""

    def test_this_process_is_alive(self) -> None:
        self.assertTrue(app_install.pid_is_alive(os.getpid()))

    def test_a_pid_no_process_holds_is_dead(self) -> None:
        self.assertFalse(app_install.pid_is_alive(_DEAD_PID))

    def test_a_process_of_another_user_is_alive(self) -> None:
        with mock.patch.object(app_install.os, "kill", side_effect=PermissionError):
            self.assertTrue(app_install.pid_is_alive(_DEAD_PID))

    def test_a_pid_too_large_to_ask_about_is_kept_as_alive(self) -> None:
        self.assertTrue(app_install.pid_is_alive(2**80))


class SweepStaleWorkTest(unittest.TestCase):
    """`sweep_stale_work`: a dead install's folders go; everything else stays."""

    def setUp(self) -> None:
        self.data = _temporary_root(self) / "data"
        self.data.mkdir()
        self.err = io.StringIO()
        self.alive = {fx.PID + 1}

    def sweep(self) -> list[Path]:
        """Sweep the data folder as process `fx.PID`, with `self.alive` the live pids."""
        return app_install.sweep_stale_work(
            self.data, fx.PID, self.err, is_alive=self.alive.__contains__
        )

    def make(self, name: str) -> Path:
        """A folder `name` in the data folder, holding one file."""
        return _folder_with(self.data / name, "inside")

    def test_a_dead_install_s_staging_and_old_folders_are_removed(self) -> None:
        staging = self.make(f".staging-{_DEAD_PID}")
        old = self.make(f".old-{_DEAD_PID}-Invented Example.app")
        self.assertEqual(sorted(self.sweep()), sorted([staging, old]))
        self.assertEqual(list(self.data.iterdir()), [])
        self.assertEqual(self.err.getvalue(), "")

    def test_a_live_install_s_folders_are_kept(self) -> None:
        kept = [self.make(f".staging-{fx.PID + 1}"), self.make(f".old-{fx.PID + 1}-x")]
        self.assertEqual(self.sweep(), [])
        self.assertTrue(all(path.is_dir() for path in kept))

    def test_this_process_s_own_folders_are_kept(self) -> None:
        kept = [self.make(f".staging-{fx.PID}"), self.make(f".old-{fx.PID}-x")]
        self.assertEqual(self.sweep(), [])
        self.assertTrue(all(path.is_dir() for path in kept))

    def test_a_name_without_a_positive_integer_pid_is_kept(self) -> None:
        names = (
            ".staging-",
            ".staging-0",
            ".staging-12a",
            ".staging--5",
            ".staging-\N{ARABIC-INDIC DIGIT ONE}",
            ".old-12",
            ".old-12-",
            ".old-x-y",
            "staging-12",
            ".scratch",
        )
        for name in names:
            self.make(name)
        self.assertEqual(self.sweep(), [])
        self.assertEqual(sorted(p.name for p in self.data.iterdir()), sorted(names))

    def test_a_symbolic_link_is_kept_and_not_followed(self) -> None:
        target = _folder_with(self.data.parent / "target", "precious")
        link = self.data / f".staging-{_DEAD_PID}"
        link.symlink_to(target, target_is_directory=True)
        self.assertEqual(self.sweep(), [])
        self.assertTrue(link.is_symlink())
        self.assertTrue((target / "precious").is_file())

    def test_a_file_is_kept(self) -> None:
        file = self.data / f".old-{_DEAD_PID}-x"
        file.write_bytes(b"")
        self.assertEqual(self.sweep(), [])
        self.assertTrue(file.is_file())

    def test_a_folder_that_cannot_be_removed_warns_and_the_sweep_goes_on(
        self,
    ) -> None:
        stuck = self.make(f".staging-{_DEAD_PID}")
        other = self.make(f".staging-{_DEAD_PID + 1}")
        real_rmtree = app_install.shutil.rmtree

        def rmtree(path: Path) -> None:
            if Path(path) == stuck:
                raise PermissionError(errno.EACCES, "Permission denied", str(path))
            real_rmtree(path)

        with mock.patch.object(app_install.shutil, "rmtree", rmtree):
            self.assertEqual(self.sweep(), [other])
        (warning,) = self.err.getvalue().splitlines()
        self.assertTrue(warning.startswith("WARNING: could not remove"))
        self.assertIn(str(stuck), warning)
        self.assertIn("PermissionError", warning)
        self.assertTrue(stuck.is_dir())

    def test_the_real_liveness_check_is_the_default(self) -> None:
        dead = self.make(f".staging-{_DEAD_PID}")
        live = self.make(f".staging-{os.getpid()}")
        self.assertEqual(
            app_install.sweep_stale_work(self.data, fx.PID, self.err), [dead]
        )
        self.assertTrue(live.is_dir())


if __name__ == "__main__":
    unittest.main()
