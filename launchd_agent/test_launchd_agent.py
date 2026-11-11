#!/usr/bin/env python3
"""Tests for launchd_agent: every launchctl step against a scripted fake, then one live run.

The fake answers each expected argv from a queue and fails the test on any other, so a test
pins both the order of the calls and that nothing else ran. A fake clock advances only when the
library sleeps, so a wait's deadline is reached in no real time. Temporary folders stand in for
``~/Library/LaunchAgents``: nothing here touches the real launchd, except the one live test, which
runs only under the operator's ``LAUNCHD_AGENT_LIVE=1`` opt-in.
"""

from __future__ import annotations

import os
import plistlib
import stat
import subprocess
import sys
import tempfile
import unittest
from collections.abc import Callable, Sequence
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import launchd_agent
from launchd_agent import AgentState, Launchctl, LaunchdError

#: The uid every fake domain is in: any fixed value, since the fake never asks the host.
_UID = 501
_LABEL = "local.launchd-agent.test"
_TARGET = f"gui/{_UID}/{_LABEL}"
_PRINT = [launchd_agent.LAUNCHCTL, "print", _TARGET]
_BOOTOUT = [launchd_agent.LAUNCHCTL, "bootout", _TARGET]
#: The operator's opt-in for the one test that mutates the real launchd.
_LIVE = os.environ.get("LAUNCHD_AGENT_LIVE") == "1"
_LIVE_LABEL = "local.launchd-agent.selftest"

#: One scripted answer: an exit code with stdout and stderr, or an exception run raises.
Answer = tuple[int, str, str] | BaseException


class FakeLaunchctl:
    """A scripted launchctl: each call pops the next expected argv and its answer.

    ``before_each``, when set, runs before each answer, so a test can observe the disk then.
    """

    def __init__(self, test: unittest.TestCase) -> None:
        self.test = test
        self.script: list[tuple[list[str], Answer]] = []
        self.calls: list[list[str]] = []
        self.timeouts: list[float] = []
        self.now = 0.0
        self.sleeps: list[float] = []
        self.before_each: Callable[[], None] | None = None

    def expect(self, argv: list[str], answer: Answer) -> FakeLaunchctl:
        """Queue *answer* for the next call, which must be *argv*."""
        self.script.append((argv, answer))
        return self

    def run(
        self, argv: Sequence[str], timeout: float
    ) -> subprocess.CompletedProcess[str]:
        """Answer *argv* from the script, failing the test on an unexpected one."""
        got = list(argv)
        self.calls.append(got)
        self.timeouts.append(timeout)
        if self.before_each is not None:
            self.before_each()
        if not self.script:
            self.test.fail(f"unexpected launchctl call: {got}")
        wanted, answer = self.script.pop(0)
        self.test.assertEqual(wanted, got)
        if isinstance(answer, BaseException):
            raise answer
        code, out, err = answer
        return subprocess.CompletedProcess(got, code, out, err)

    def clock(self) -> float:
        """The fake time, which only sleeping advances."""
        return self.now

    def sleep(self, seconds: float) -> None:
        """Advance the fake time by *seconds*."""
        self.sleeps.append(seconds)
        self.now += seconds

    def ctl(self) -> Launchctl:
        """The Launchctl the library is handed."""
        return Launchctl(run=self.run, uid=_UID, clock=self.clock, sleep=self.sleep)


_LOADED = (0, "state = running\n", "")
_ABSENT = (113, "", "Could not find service in domain\n")
_OK = (0, "", "")


class ServiceTargetTest(unittest.TestCase):
    """The names launchctl is handed."""

    def test_target_is_the_gui_domain_and_label(self) -> None:
        self.assertEqual(_TARGET, launchd_agent.service_target(_UID, _LABEL))

    def test_kickstart_argv_names_the_target(self) -> None:
        self.assertEqual(
            [launchd_agent.LAUNCHCTL, "kickstart", _TARGET],
            launchd_agent.kickstart_argv(_UID, _LABEL),
        )


class LibrarySearchTest(unittest.TestCase):
    """The upward search for the shared libraries."""

    def test_a_tree_without_the_library_finds_none(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            start = Path(folder) / "a" / "b.py"
            self.assertIsNone(launchd_agent._nearest_library("atomic_write", start))

    def test_finds_the_nearest_holding_folder(self) -> None:
        found = launchd_agent._nearest_library("atomic_write", Path(__file__).resolve())
        self.assertIsNotNone(found)
        assert found is not None
        self.assertTrue((found / "atomic_write.py").is_file())

    @staticmethod
    def _plant(folder: Path, name: str) -> Path:
        """Create ``<folder>/<name>/<name>.py`` and return that library folder."""
        library = folder / name
        library.mkdir(parents=True)
        (library / f"{name}.py").write_text("", encoding="utf-8", newline="\n")
        return library

    def test_finds_a_library_beside_its_folder_in_a_flattened_export(self) -> None:
        # An export ships each vendored library in a folder of its own name directly
        # under the export root, with no utilities/ folder above it.
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder).resolve() / "export"
            library = self._plant(root, "atomic_write")
            start = root / "launchd_agent" / "launchd_agent.py"
            self.assertEqual(
                library, launchd_agent._nearest_library("atomic_write", start)
            )

    def test_finds_a_library_under_a_utilities_folder(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            utilities = Path(folder).resolve() / "repo" / "utilities"
            library = self._plant(utilities, "atomic_write")
            start = utilities / "launchd_agent" / "launchd_agent.py"
            self.assertEqual(
                library, launchd_agent._nearest_library("atomic_write", start)
            )

    def test_never_searches_above_the_folder_holding_its_own(self) -> None:
        # The library is absent where this module's layout puts it, and a same-named
        # folder sits higher up, as it could in a folder above a clone. A search that
        # climbed there would put a stranger's folder on sys.path.
        with tempfile.TemporaryDirectory() as folder:
            above = Path(folder).resolve()
            self._plant(above / "utilities", "atomic_write")
            self._plant(above, "atomic_write")
            start = above / "clone" / "launchd_agent" / "launchd_agent.py"
            self.assertIsNone(launchd_agent._nearest_library("atomic_write", start))


class AgentStateTest(unittest.TestCase):
    """One ``launchctl print`` has three answers, not two."""

    def _state(self, answer: Answer) -> AgentState:
        fake = FakeLaunchctl(self).expect(_PRINT, answer)
        state = launchd_agent.agent_state(fake.ctl(), _LABEL)
        self.assertEqual([launchd_agent.LAUNCHCTL_TIMEOUT_S], fake.timeouts)
        return state

    def test_exit_zero_is_loaded(self) -> None:
        self.assertIs(AgentState.LOADED, self._state(_LOADED))

    def test_exit_113_is_absent(self) -> None:
        self.assertIs(AgentState.ABSENT, self._state(_ABSENT))

    def test_any_other_exit_is_unknown(self) -> None:
        self.assertIs(AgentState.UNKNOWN, self._state((5, "", "Input/output error\n")))

    def test_a_timeout_is_unknown(self) -> None:
        timeout = subprocess.TimeoutExpired(_PRINT, launchd_agent.LAUNCHCTL_TIMEOUT_S)
        self.assertIs(AgentState.UNKNOWN, self._state(timeout))

    def test_a_launchctl_that_cannot_run_is_unknown(self) -> None:
        missing = FileNotFoundError(2, "No such file or directory")
        self.assertIs(AgentState.UNKNOWN, self._state(missing))

    # print_service (agent_state is its .state): stdout when loaded, reason when unknown.
    def _print(self, answer: Answer) -> launchd_agent.ServicePrint:
        fake = FakeLaunchctl(self).expect(_PRINT, answer)
        return launchd_agent.print_service(fake.ctl(), _LABEL)

    def test_loaded_keeps_stdout(self) -> None:
        got = self._print((0, "\tstate = running\n\tpid = 42\n", ""))
        self.assertIn("pid = 42", got.stdout)

    def test_absent_has_no_stdout(self) -> None:
        got = self._print((launchd_agent.PRINT_ABSENT_RC, "noise", ""))
        self.assertEqual((got.state, got.stdout), (AgentState.ABSENT, ""))

    def test_odd_exit_is_unknown_with_reason(self) -> None:
        got = self._print((5, "", "boom\nmore"))
        self.assertEqual((got.stdout, "boom" in got.why), ("", True))


class WaitForTest(unittest.TestCase):
    """Polling until launchd reports the wanted state."""

    def test_succeeds_after_two_polls(self) -> None:
        fake = FakeLaunchctl(self).expect(_PRINT, _LOADED).expect(_PRINT, _ABSENT)
        launchd_agent.wait_for(fake.ctl(), _LABEL, AgentState.ABSENT)
        self.assertEqual([launchd_agent.POLL_S], fake.sleeps)
        self.assertEqual([], fake.script)

    def test_unknown_fails_at_once_naming_the_exit_and_stderr(self) -> None:
        fake = FakeLaunchctl(self).expect(_PRINT, (5, "", "Input/output error\nmore\n"))
        with self.assertRaises(LaunchdError) as caught:
            launchd_agent.wait_for(fake.ctl(), _LABEL, AgentState.LOADED)
        message = str(caught.exception)
        self.assertIn("exit 5", message)
        self.assertIn("Input/output error", message)
        self.assertNotIn("more", message)
        self.assertEqual([], fake.sleeps)

    def test_a_timeout_fails_at_once_and_says_so(self) -> None:
        timeout = subprocess.TimeoutExpired(_PRINT, launchd_agent.LAUNCHCTL_TIMEOUT_S)
        fake = FakeLaunchctl(self).expect(_PRINT, timeout)
        with self.assertRaises(LaunchdError) as caught:
            launchd_agent.wait_for(fake.ctl(), _LABEL, AgentState.LOADED)
        self.assertIn("timed out", str(caught.exception))

    def test_unknown_with_empty_stderr_still_names_the_exit(self) -> None:
        fake = FakeLaunchctl(self).expect(_PRINT, (5, "", ""))
        with self.assertRaises(LaunchdError) as caught:
            launchd_agent.wait_for(fake.ctl(), _LABEL, AgentState.LOADED)
        self.assertIn("exit 5", str(caught.exception))

    def test_the_deadline_fails_with_the_state_still_read(self) -> None:
        fake = FakeLaunchctl(self)
        for _ in range(3):
            fake.expect(_PRINT, _LOADED)
        with self.assertRaises(LaunchdError) as caught:
            launchd_agent.wait_for(
                fake.ctl(), _LABEL, AgentState.ABSENT, deadline_s=1.0
            )
        self.assertEqual(f"{_LABEL}: still loaded after 1 s", str(caught.exception))
        self.assertEqual([], fake.script)

    def test_unknown_is_not_a_state_to_wait_for(self) -> None:
        fake = FakeLaunchctl(self)
        with self.assertRaises(ValueError):
            launchd_agent.wait_for(fake.ctl(), _LABEL, AgentState.UNKNOWN)
        self.assertEqual([], fake.calls)


class InstallAgentTest(unittest.TestCase):
    """Write the plist, boot out, wait absent, bootstrap, wait loaded."""

    def setUp(self) -> None:
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        # A missing LaunchAgents folder, as on an account that never had an agent.
        self.plist_path = Path(folder.name) / "LaunchAgents" / f"{_LABEL}.plist"
        self.bootstrap = [
            launchd_agent.LAUNCHCTL,
            "bootstrap",
            f"gui/{_UID}",
            str(self.plist_path),
        ]

    def _install(self, fake: FakeLaunchctl) -> None:
        launchd_agent.install_agent(
            fake.ctl(), label=_LABEL, plist_path=self.plist_path, plist=b"<plist/>"
        )

    def test_runs_the_four_steps_in_order_with_the_plist_written_first(self) -> None:
        seen: list[bool] = []
        fake = FakeLaunchctl(self)
        fake.before_each = lambda: seen.append(self.plist_path.is_file())
        fake.expect(_BOOTOUT, (3, "", "Boot-out failed: 3: No such process\n"))
        fake.expect(_PRINT, _ABSENT).expect(self.bootstrap, _OK).expect(_PRINT, _LOADED)
        self._install(fake)
        self.assertEqual([_BOOTOUT, _PRINT, self.bootstrap, _PRINT], fake.calls)
        self.assertEqual([True] * 4, seen)
        self.assertEqual(b"<plist/>", self.plist_path.read_bytes())
        if sys.platform != "win32":
            mode = stat.S_IMODE(self.plist_path.stat().st_mode)
            self.assertEqual(0o644, mode)

    def test_a_failed_bootstrap_still_succeeds_when_print_reads_loaded(self) -> None:
        fake = FakeLaunchctl(self).expect(_BOOTOUT, _OK).expect(_PRINT, _ABSENT)
        fake.expect(
            self.bootstrap, (5, "", "Bootstrap failed: 5: Input/output error\n")
        )
        fake.expect(_PRINT, _LOADED)
        self._install(fake)
        self.assertEqual([], fake.script)

    def test_a_bootout_that_times_out_is_not_the_check(self) -> None:
        timeout = subprocess.TimeoutExpired(_BOOTOUT, launchd_agent.LAUNCHCTL_TIMEOUT_S)
        fake = FakeLaunchctl(self).expect(_BOOTOUT, timeout).expect(_PRINT, _ABSENT)
        fake.expect(self.bootstrap, _OK).expect(_PRINT, _LOADED)
        self._install(fake)
        self.assertEqual([], fake.script)

    def test_an_agent_that_never_loads_fails(self) -> None:
        fake = FakeLaunchctl(self).expect(_BOOTOUT, _OK).expect(_PRINT, _ABSENT)
        fake.expect(self.bootstrap, _OK).expect(_PRINT, (5, "", "boom\n"))
        with self.assertRaises(LaunchdError) as caught:
            self._install(fake)
        self.assertNotIn("bootstrap failed", str(caught.exception))
        self.assertTrue(self.plist_path.is_file())

    def test_a_failed_bootstrap_that_never_loads_names_its_exit_and_stderr(
        self,
    ) -> None:
        fake = FakeLaunchctl(self).expect(_BOOTOUT, _OK).expect(_PRINT, _ABSENT)
        fake.expect(
            self.bootstrap, (5, "", "Bootstrap failed: 5: Input/output error\n")
        )
        for _ in range(3):
            fake.expect(_PRINT, _ABSENT)
        with self.assertRaises(LaunchdError) as caught:
            launchd_agent.install_agent(
                fake.ctl(),
                label=_LABEL,
                plist_path=self.plist_path,
                plist=b"<plist/>",
                deadline_s=1.0,
            )
        self.assertEqual(
            f"{_LABEL}: still absent after 1 s; launchctl bootstrap failed (exit 5): "
            "Bootstrap failed: 5: Input/output error",
            str(caught.exception),
        )
        self.assertIsInstance(caught.exception.__cause__, LaunchdError)

    def test_a_failed_bootstrap_with_only_stdout_names_stdout(self) -> None:
        fake = FakeLaunchctl(self).expect(_BOOTOUT, _OK).expect(_PRINT, _ABSENT)
        fake.expect(self.bootstrap, (5, "the reason\nmore\n", ""))
        fake.expect(_PRINT, (7, "", "boom\n"))
        with self.assertRaises(LaunchdError) as caught:
            self._install(fake)
        self.assertTrue(str(caught.exception).endswith("(exit 5): the reason"))

    def test_a_bootstrap_that_times_out_and_never_loads_keeps_the_wait_message(
        self,
    ) -> None:
        timeout = subprocess.TimeoutExpired(self.bootstrap, 10.0)
        fake = FakeLaunchctl(self).expect(_BOOTOUT, _OK).expect(_PRINT, _ABSENT)
        fake.expect(self.bootstrap, timeout).expect(_PRINT, (7, "", "boom\n"))
        with self.assertRaises(LaunchdError) as caught:
            self._install(fake)
        self.assertNotIn("bootstrap failed", str(caught.exception))


class UninstallAgentTest(unittest.TestCase):
    """Boot out, wait absent, and only then remove the plist."""

    def setUp(self) -> None:
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.plist_path = Path(folder.name) / f"{_LABEL}.plist"
        self.plist_path.write_bytes(b"<plist/>")

    def _uninstall(self, fake: FakeLaunchctl) -> None:
        launchd_agent.uninstall_agent(
            fake.ctl(), label=_LABEL, plist_path=self.plist_path, deadline_s=1.0
        )

    def test_removes_the_plist_once_launchd_confirms_absent(self) -> None:
        fake = FakeLaunchctl(self).expect(_BOOTOUT, _OK).expect(_PRINT, _ABSENT)
        self._uninstall(fake)
        self.assertFalse(self.plist_path.exists())
        self.assertEqual([_BOOTOUT, _PRINT], fake.calls)

    def test_keeps_the_plist_when_the_wait_fails(self) -> None:
        fake = FakeLaunchctl(self).expect(_BOOTOUT, _OK)
        for _ in range(3):
            fake.expect(_PRINT, _LOADED)
        with self.assertRaises(LaunchdError):
            self._uninstall(fake)
        self.assertTrue(self.plist_path.is_file())

    def test_an_absent_plist_is_not_an_error(self) -> None:
        self.plist_path.unlink()
        fake = FakeLaunchctl(self).expect(_BOOTOUT, _ABSENT).expect(_PRINT, _ABSENT)
        self._uninstall(fake)
        self.assertFalse(self.plist_path.exists())


class StopAgentTest(unittest.TestCase):
    """Boot out and wait absent, keeping the plist for the next load."""

    def setUp(self) -> None:
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.plist_path = Path(folder.name) / f"{_LABEL}.plist"
        self.plist_path.write_bytes(b"<plist/>")

    def test_stops_the_agent_and_keeps_its_plist(self) -> None:
        fake = FakeLaunchctl(self).expect(_BOOTOUT, _OK).expect(_PRINT, _ABSENT)
        launchd_agent.stop_agent(fake.ctl(), label=_LABEL, deadline_s=1.0)
        self.assertEqual([_BOOTOUT, _PRINT], fake.calls)
        self.assertEqual(self.plist_path.read_bytes(), b"<plist/>")

    def test_an_agent_that_stays_loaded_raises(self) -> None:
        fake = FakeLaunchctl(self).expect(_BOOTOUT, _OK)
        for _ in range(3):
            fake.expect(_PRINT, _LOADED)
        with self.assertRaises(LaunchdError):
            launchd_agent.stop_agent(fake.ctl(), label=_LABEL, deadline_s=1.0)
        self.assertTrue(self.plist_path.is_file())


class BuildKeepalivePlistTest(unittest.TestCase):
    """The always-running agent's plist."""

    def _build(self, label: str) -> bytes:
        return launchd_agent.build_keepalive_plist(
            label=label,
            program_arguments=[
                "/usr/bin/python3",
                "/opt/tool/serve.py",
                "--mode",
                "serve",
            ],
            working_directory="/opt/tool",
            log_paths=("/opt/tool/logs/out.log", "/opt/tool/logs/err.log"),
            path_value="/usr/bin:/bin",
        )

    def test_round_trips_to_the_exact_dictionary(self) -> None:
        expected = {
            "Label": _LABEL,
            "ProgramArguments": [
                "/usr/bin/python3",
                "/opt/tool/serve.py",
                "--mode",
                "serve",
            ],
            "WorkingDirectory": "/opt/tool",
            "RunAtLoad": True,
            "KeepAlive": True,
            "ThrottleInterval": 10,
            "ProcessType": "Background",
            "StandardOutPath": "/opt/tool/logs/out.log",
            "StandardErrorPath": "/opt/tool/logs/err.log",
            "EnvironmentVariables": {"PATH": "/usr/bin:/bin"},
        }
        self.assertEqual(expected, plistlib.loads(self._build(_LABEL)))

    def test_refuses_a_label_with_a_slash(self) -> None:
        with self.assertRaises(ValueError):
            self._build("local/escape")


@unittest.skipUnless(
    _LIVE and sys.platform == "darwin",
    "set LAUNCHD_AGENT_LIVE=1 on macOS: it installs a real LaunchAgent",
)
class LiveLaunchdTest(unittest.TestCase):  # pragma: no cover - operator opt-in only
    """Install, read, uninstall and read a real agent in this account's GUI domain."""

    def test_install_then_uninstall_reads_back(self) -> None:
        ctl = launchd_agent.real_launchctl()
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder)
            plist = launchd_agent.build_keepalive_plist(
                label=_LIVE_LABEL,
                program_arguments=["/usr/bin/true"],
                working_directory=str(base),
                log_paths=(str(base / "out.log"), str(base / "err.log")),
                path_value="/usr/bin:/bin",
            )
            plist_path = base / f"{_LIVE_LABEL}.plist"
            try:
                launchd_agent.install_agent(
                    ctl, label=_LIVE_LABEL, plist_path=plist_path, plist=plist
                )
                self.assertIs(
                    AgentState.LOADED, launchd_agent.agent_state(ctl, _LIVE_LABEL)
                )
            finally:
                launchd_agent.uninstall_agent(
                    ctl, label=_LIVE_LABEL, plist_path=plist_path
                )
            self.assertIs(
                AgentState.ABSENT, launchd_agent.agent_state(ctl, _LIVE_LABEL)
            )
            self.assertFalse(plist_path.exists())


if __name__ == "__main__":
    unittest.main()
