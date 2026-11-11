"""scrob_agent: install's refusals, its order of steps, the bundle swap, and uninstall.

Every tool and launchd are fakes from `_scrob_fixtures`; the order of steps is read from
the one log the fakes share, and the app's start is a status.json the fake launchd
writes when it bootstraps the agent.
"""

from __future__ import annotations

import dataclasses
import plistlib
import stat
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))

import _scrob_fixtures as fx  # noqa: E402 - import follows the sys.path bootstrap above
import scrob_agent  # noqa: E402 - on sys.path once _scrob_fixtures is imported
import scrob_bundle  # noqa: E402 - on sys.path once _scrob_fixtures is imported

#: The bytes an earlier install left as the app's executable.
_OLD_BYTES = b"the earlier install\n"
#: The swap itself, kept before each test logs it.
_REAL_SWAP = scrob_agent.swap_in


class AgentCase(unittest.TestCase):
    """A fresh kit per test, with a signing setting, and the swap logged."""

    def setUp(self) -> None:
        self.kit = fx.make_kit(self)
        self.kit.write_identity()

        def logged_swap(staged: Path, final: Path, aside: Path) -> None:
            self.kit.log.append("swap")
            _REAL_SWAP(staged, final, aside)

        patcher = mock.patch.object(scrob_agent, "swap_in", logged_swap)
        patcher.start()
        self.addCleanup(patcher.stop)

    def app_starts(self) -> None:
        """Make the fake launchd start the app, which writes a fresh status.json."""
        self.kit.launchd.on_bootstrap = lambda: self.kit.write_status(
            started_at=self.kit.clock.wall + 1
        )

    def install(self) -> int:
        """Run install against the kit."""
        return scrob_agent.install(self.kit.host, self.kit.layout)

    def executable(self) -> Path:
        """The installed app's executable."""
        return self.kit.paths.app_bundle / "Contents" / "MacOS" / "scrobbler"


class InstallRefusalTest(AgentCase):
    """What install refuses, before anything is built."""

    def test_a_linked_worktree_is_refused(self) -> None:
        self.kit.tools.git_dir = ".git/worktrees/lane"
        with self.assertRaises(scrob_bundle.Refused) as caught:
            self.install()
        self.assertIn("linked git worktree", str(caught.exception))
        self.assertEqual(self.kit.log, ["git"])

    def test_a_folder_outside_every_repository_may_install(self) -> None:
        self.kit.tools.repos.clear()
        self.app_starts()
        self.assertEqual(self.install(), 0)

    def test_a_git_that_cannot_run_is_refused(self) -> None:
        self.kit.tools.missing.add("git")
        with self.assertRaises(scrob_bundle.Refused) as caught:
            self.install()
        self.assertIn("could not ask git", str(caught.exception))

    def test_a_git_that_fails_otherwise_is_refused(self) -> None:
        self.kit.tools.git_dir = ""
        self.kit.tools.common_dir = ""
        original = self.kit.tools._git

        def failing(args: list[str], cwd: Path) -> fx.subprocess.CompletedProcess[str]:
            if "--git-common-dir" in args:
                return fx.done(args, 128, err="fatal: invented unsafe repository\n")
            return original(args, cwd)

        self.kit.tools._git = failing  # type: ignore[method-assign]
        with self.assertRaises(scrob_bundle.Refused) as caught:
            self.install()
        self.assertIn("could not say", str(caught.exception))

    def test_no_signing_setting_is_refused_before_building(self) -> None:
        self.kit.paths.signing_config.unlink()
        with self.assertRaises(scrob_bundle.Refused) as caught:
            self.install()
        self.assertIn('identity = "<codesign identity>"', str(caught.exception))
        self.assertNotIn("build", self.kit.log)


class InstallOrderTest(AgentCase):
    """install builds, signs and verifies, stops the old agent, swaps, loads, confirms."""

    def test_an_upgrade_runs_every_step_in_order(self) -> None:
        self.kit.install_app()
        self.executable().write_bytes(_OLD_BYTES)
        self.app_starts()
        self.assertEqual(self.install(), 0)
        self.assertEqual(
            self.kit.log,
            [
                "git",
                "build",
                "sign",
                "verify",
                "bootout",
                "swap",
                "bootout",
                "bootstrap",
            ],
        )
        self.assertEqual(self.executable().read_bytes(), fx.BUILT_BYTES)
        self.assertIn("Automation", self.kit.out.getvalue())

    def test_a_first_install_has_no_agent_to_stop(self) -> None:
        self.app_starts()
        self.assertEqual(self.install(), 0)
        self.assertEqual(
            self.kit.log,
            ["git", "build", "sign", "verify", "swap", "bootout", "bootstrap"],
        )

    def test_the_verify_is_strict_and_on_the_staged_bundle(self) -> None:
        self.app_starts()
        self.install()
        verify = self.kit.tools.calls[-1]
        self.assertEqual(
            verify[:4], ["codesign", "--verify", "--strict", "--verbose=2"]
        )
        self.assertEqual(Path(verify[4]).parent.name, f".staging-{fx.PID}")

    def test_the_swap_leaves_no_staging_or_old_bundle_behind(self) -> None:
        self.kit.install_app()
        self.app_starts()
        self.install()
        names = sorted(path.name for path in self.kit.paths.data_dir.iterdir())
        # The scratch folder stays: it is SwiftPM's incremental build cache.
        self.assertEqual(
            names, [".scratch", "listensmith scrobbler.app", "logs", "state"]
        )

    def test_the_plist_runs_the_installed_app_from_the_data_folder(self) -> None:
        self.app_starts()
        self.install()
        plist = plistlib.loads(self.kit.paths.launch_agent_plist.read_bytes())
        paths = self.kit.paths
        self.assertEqual(plist["Label"], self.kit.layout.launchd_label)
        self.assertEqual(plist["ProgramArguments"], [str(self.executable()), "run"])
        self.assertEqual(plist["WorkingDirectory"], str(paths.data_dir))
        self.assertEqual(plist["StandardOutPath"], str(paths.out_log))
        self.assertEqual(plist["StandardErrorPath"], str(paths.err_log))
        self.assertEqual(plist["EnvironmentVariables"], {"PATH": "/usr/bin:/bin"})
        self.assertTrue(paths.logs_dir.is_dir())

    def test_the_identity_is_never_shown(self) -> None:
        self.app_starts()
        self.install()
        for secret in (fx.FAKE_IDENTITY, fx.FAKE_NAME, fx.FAKE_TEAM):
            self.assertNotIn(secret, self.kit.output())


class InstallFailureTest(AgentCase):
    """A failed build keeps the old app running; an app that never starts is exit 1."""

    def test_a_failed_build_keeps_the_old_app_and_agent(self) -> None:
        self.kit.install_app()
        self.executable().write_bytes(_OLD_BYTES)
        self.kit.tools.verify_rc = 1
        with self.assertRaises(scrob_bundle.BuildFailed):
            self.install()
        self.assertEqual(self.executable().read_bytes(), _OLD_BYTES)
        self.assertIn(self.kit.layout.launchd_label, self.kit.launchd.loaded)
        self.assertFalse((self.kit.paths.data_dir / f".staging-{fx.PID}").exists())

    def test_a_launchd_failure_leaves_no_staging_folder(self) -> None:
        self.kit.install_app()
        self.executable().write_bytes(_OLD_BYTES)
        refusal = scrob_agent.launchd_agent.LaunchdError("invented: still loaded")
        with mock.patch.object(
            scrob_agent.launchd_agent, "stop_agent", side_effect=refusal
        ):
            with self.assertRaises(scrob_agent.launchd_agent.LaunchdError):
                self.install()
        self.assertFalse((self.kit.paths.data_dir / f".staging-{fx.PID}").exists())
        self.assertEqual(self.executable().read_bytes(), _OLD_BYTES)

    def test_a_staging_folder_left_by_an_earlier_run_is_replaced(self) -> None:
        leftover = self.kit.paths.data_dir / f".staging-{fx.PID}" / "stale"
        leftover.mkdir(parents=True)
        self.app_starts()
        self.assertEqual(self.install(), 0)
        self.assertFalse(leftover.parent.exists())

    def test_a_status_that_never_updates_times_out_with_exit_1(self) -> None:
        self.kit.write_status(started_at=self.kit.clock.wall - 600)
        self.assertEqual(self.install(), 1)
        self.assertIn("did not report a start", self.kit.err.getvalue())
        slept = self.kit.clock.slept
        self.assertEqual(slept[:4], [0.5, 1.0, 2.0, 4.0])
        self.assertTrue(all(wait <= 4.0 for wait in slept))
        self.assertAlmostEqual(sum(slept), 30.0)

    def test_an_unreadable_status_is_waited_through(self) -> None:
        def start_late() -> None:
            self.kit.paths.status_file.parent.mkdir(parents=True, exist_ok=True)
            self.kit.paths.status_file.write_text(
                "{half", encoding="utf-8", newline="\n"
            )

        self.kit.launchd.on_bootstrap = start_late
        real_sleep = self.kit.clock.sleep

        def sleep_then_start(seconds: float) -> None:
            real_sleep(seconds)
            if len(self.kit.clock.slept) == 3:
                self.kit.write_status(started_at=self.kit.clock.wall)

        self.kit.host = dataclasses.replace(self.kit.host, sleep=sleep_then_start)
        self.assertEqual(self.install(), 0)

    def test_a_failed_rename_puts_the_old_bundle_back(self) -> None:
        final = self.kit.home / "final.app"
        final.mkdir()
        aside = self.kit.home / "aside.app"
        staged = self.kit.home / "absent.app"
        with self.assertRaises(OSError):
            _REAL_SWAP(staged, final, aside)
        self.assertTrue(final.is_dir())
        self.assertFalse(aside.exists())

    def test_a_swap_that_cannot_rename_is_build_failed(self) -> None:
        self.app_starts()
        with mock.patch.object(Path, "rename", side_effect=PermissionError("invented")):
            with self.assertRaises(scrob_bundle.BuildFailed) as caught:
                self.install()
        self.assertIn("could not swap", str(caught.exception))


class ReplaceSafetyTest(AgentCase):
    """What install must never do to a running app it cannot safely replace."""

    def test_an_unknown_agent_state_refuses_before_any_swap(self) -> None:
        self.kit.install_app()
        self.executable().write_bytes(_OLD_BYTES)
        self.kit.launchd.unknown.add(self.kit.layout.launchd_label)
        with self.assertRaises(scrob_agent.launchd_agent.LaunchdError):
            self.install()
        self.assertEqual(self.executable().read_bytes(), _OLD_BYTES)
        self.assertEqual(
            self.kit.paths.launch_agent_plist.read_bytes(), b"invented plist"
        )
        self.assertNotIn("swap", self.kit.log)

    def test_a_start_written_by_the_old_agent_during_the_build_does_not_count(
        self,
    ) -> None:
        # The old agent, restarted by KeepAlive while the build ran, reports a start that
        # is newer than the install command but older than the new agent's load.
        self.kit.install_app()
        original = self.kit.tools._swift

        def build_while_the_old_app_restarts(
            args: list[str],
        ) -> fx.subprocess.CompletedProcess[str]:
            if "--show-bin-path" not in args:
                self.kit.write_status(started_at=self.kit.clock.wall + 1)
                self.kit.clock.sleep(5)
            return original(args)

        self.kit.tools._swift = build_while_the_old_app_restarts  # type: ignore[method-assign]
        self.assertEqual(self.install(), 1)

    def test_a_failed_swap_keeps_the_plist_so_status_sees_the_install(self) -> None:
        self.kit.install_app()
        with mock.patch.object(Path, "rename", side_effect=PermissionError("invented")):
            with self.assertRaises(scrob_bundle.BuildFailed):
                self.install()
        self.assertTrue(self.kit.paths.launch_agent_plist.is_file())

    def test_an_old_bundle_that_cannot_be_removed_is_its_own_message(self) -> None:
        self.kit.install_app()
        self.app_starts()
        real_rmtree = scrob_agent.shutil.rmtree

        def refuse_the_aside(path: Path, ignore_errors: bool = False) -> None:
            if Path(path).name.startswith(".old-"):
                raise PermissionError("invented")
            real_rmtree(path, ignore_errors=ignore_errors)

        with mock.patch.object(scrob_agent.shutil, "rmtree", refuse_the_aside):
            self.assertEqual(self.install(), 0)
        self.assertEqual(self.executable().read_bytes(), fx.BUILT_BYTES)
        self.assertIn("could not remove the old app", self.kit.err.getvalue())

    def test_a_stale_aside_folder_from_a_recycled_pid_is_replaced(self) -> None:
        self.kit.install_app()
        layout = self.kit.layout
        stale = self.kit.paths.data_dir / f".old-{fx.PID}-{layout.app_name}" / "x"
        stale.mkdir(parents=True)
        self.app_starts()
        self.assertEqual(self.install(), 0)
        self.assertFalse(stale.parent.exists())
        self.assertEqual(self.executable().read_bytes(), fx.BUILT_BYTES)

    def test_a_symlinked_data_folder_is_refused(self) -> None:
        elsewhere = self.kit.home.parent / "elsewhere"
        elsewhere.mkdir()
        elsewhere.chmod(0o755)
        self.kit.paths.data_dir.parent.mkdir(parents=True)
        self.kit.paths.data_dir.symlink_to(elsewhere)
        with self.assertRaises(scrob_bundle.Refused) as caught:
            self.install()
        self.assertIn("symbolic link", str(caught.exception))
        self.assertEqual(stat.S_IMODE(elsewhere.stat().st_mode), 0o755)

    def test_a_symlinked_state_folder_is_refused_before_the_old_app_is_touched(
        self,
    ) -> None:
        self.kit.install_app()
        self.executable().write_bytes(_OLD_BYTES)
        elsewhere = self.kit.home.parent / "elsewhere"
        elsewhere.mkdir()
        self.kit.paths.state_dir.symlink_to(elsewhere)
        with self.assertRaises(scrob_bundle.Refused) as caught:
            self.install()
        self.assertIn("symbolic link", str(caught.exception))
        self.assertEqual(self.executable().read_bytes(), _OLD_BYTES)
        self.assertEqual(
            self.kit.paths.launch_agent_plist.read_bytes(), b"invented plist"
        )
        self.assertNotIn("bootout", self.kit.log)
        self.assertNotIn("swap", self.kit.log)

    def test_an_unwritable_launch_agents_folder_is_one_failure(self) -> None:
        launch_folder = self.kit.paths.launch_agents_dir
        launch_folder.mkdir(parents=True)
        launch_folder.chmod(0o500)
        self.addCleanup(launch_folder.chmod, 0o700)
        with self.assertRaises(scrob_bundle.BuildFailed) as caught:
            self.install()
        self.assertIn("PermissionError", str(caught.exception))


class UninstallTest(AgentCase):
    """uninstall unloads the agent and keeps everything else."""

    def test_it_unloads_the_agent_and_keeps_the_app_queue_state_and_config(
        self,
    ) -> None:
        self.kit.install_app()
        self.kit.write_status()
        queued = self.kit.paths.queue_dir / "play.json"
        queued.parent.mkdir(parents=True)
        queued.write_text("{}", encoding="utf-8", newline="\n")
        self.kit.paths.config_file.parent.mkdir(parents=True, exist_ok=True)
        self.kit.paths.config_file.write_text("{}", encoding="utf-8", newline="\n")
        scrob_agent.uninstall(self.kit.host, self.kit.layout)
        self.assertNotIn(self.kit.layout.launchd_label, self.kit.launchd.loaded)
        self.assertFalse(self.kit.paths.launch_agent_plist.exists())
        for kept in (
            self.executable(),
            queued,
            self.kit.paths.status_file,
            self.kit.paths.config_file,
            self.kit.paths.signing_config,
        ):
            self.assertTrue(kept.is_file(), kept)
        self.assertIn("kept", self.kit.out.getvalue())


if __name__ == "__main__":
    unittest.main()
