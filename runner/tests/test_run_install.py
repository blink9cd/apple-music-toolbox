"""run_install: the build, the bundle's allowlist, and install's order of steps.

Every tool and launchd are fakes from `_run_fixtures`; the order of steps is read from
the one log the fakes share, and the grant probe is a result file the fake launchd
writes when it bootstraps the grant agent. The signing identity is an invented one that
must appear in no output. Uninstall is `test_run_uninstall`'s.
"""

from __future__ import annotations

import dataclasses
import json
import plistlib
import shutil
import stat
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))

import _run_fixtures as fx  # noqa: E402 - import follows the sys.path bootstrap above
import app_bundle  # noqa: E402 - on sys.path once _run_fixtures is imported
import launchd_agent  # noqa: E402 - on sys.path once _run_fixtures is imported
import run_allowlist  # noqa: E402 - on sys.path once _run_fixtures is imported
import run_install  # noqa: E402 - on sys.path once _run_fixtures is imported

if sys.platform == "win32":
    # POSIX only, as the runner is; also lets a win32 type-check skip the mode checks.
    raise unittest.SkipTest("the runner runs on macOS only")  # pragma: only-on win32

#: The Automation prompt, restated so a changed wording fails a test.
_PROMPT = (
    "Apple Music Toolbox Runner runs the Apple Music tools you schedule on this Mac, "
    "so they can read your library while you are away. It never changes playback."
)
#: The Info.plist with every machine path as a placeholder, for reading by hand.
_SAMPLE = fx.TOOL_ROOT / "samples" / "Info.plist"
#: The bytes an earlier install left as the app's executable.
_OLD_BYTES = b"the earlier install\n"
_APP = "Apple Music Toolbox Runner.app"


class InstallCase(unittest.TestCase):
    """A fresh kit per test, and an output folder under its root."""

    def setUp(self) -> None:
        self.kit = fx.make_kit(self)
        self.out_dir = self.kit.home.parent / "out"
        self.out_dir.mkdir()

    def build(self, *, sign: bool = False) -> int:
        """Run the build command against the kit."""
        return run_install.run_build(
            self.kit.host, self.kit.layout, self.out_dir, sign=sign
        )

    def install(self) -> int:
        """Run install against the kit."""
        return run_install.install(self.kit.host, self.kit.layout)

    def info(self) -> dict[str, object]:
        """The built bundle's Info.plist."""
        plist = self.out_dir / _APP / "Contents" / "Info.plist"
        loaded: dict[str, object] = plistlib.loads(plist.read_bytes())
        return loaded

    def assert_identity_hidden(self) -> None:
        """Neither the fake identity's name nor its team ID reached any output."""
        for secret in (fx.FAKE_IDENTITY, fx.FAKE_NAME, fx.FAKE_TEAM):
            self.assertNotIn(secret, self.kit.output())

    def staging_folders(self) -> list[str]:
        """The staging folders, and any `.old-` folder, left in the data folder."""
        return sorted(
            entry.name
            for entry in self.kit.paths.data_dir.iterdir()
            if entry.name.startswith((".staging-", ".old-"))
        )


class BuildTest(InstallCase):
    """`build` compiles outside the checkout and writes the allowlist into the bundle."""

    def test_the_bundle_holds_the_executable_and_the_property_list(self) -> None:
        self.assertEqual(self.build(), 0)
        executable = self.out_dir / _APP / "Contents" / "MacOS" / "runner"
        self.assertEqual(executable.read_bytes(), fx.BUILT_BYTES)
        self.assertEqual(self.kit.out.getvalue(), f"built {self.out_dir / _APP}\n")
        self.assertEqual(self.kit.log, ["build"])

    def test_the_property_list_holds_exactly_its_keys(self) -> None:
        self.build()
        layout = self.kit.layout
        self.assertEqual(
            self.info(),
            {
                "CFBundleIdentifier": "local.apple-music-toolbox.runner",
                "CFBundleName": "Apple Music Toolbox Runner",
                "CFBundleDisplayName": "Apple Music Toolbox Runner",
                "CFBundleExecutable": "runner",
                "CFBundlePackageType": "APPL",
                "CFBundleShortVersionString": layout.version,
                "CFBundleVersion": layout.version,
                "LSMinimumSystemVersion": "14.0",
                "LSUIElement": True,
                "NSAppleEventsUsageDescription": _PROMPT,
                "AMTRunnerAllowlist": {
                    "python": sys.executable,
                    "scripts": [
                        str(self.kit.checkout / entry) for entry in fx.repo_scripts()
                    ],
                },
            },
        )

    def test_the_allowlist_names_the_grant_probe_in_this_checkout(self) -> None:
        self.build()
        allowed = run_allowlist.from_info_value(self.info()["AMTRunnerAllowlist"])
        assert allowed is not None
        self.assertIn(str(self.kit.probe), allowed["scripts"])

    def test_the_sample_is_this_property_list_with_placeholders(self) -> None:
        self.build()
        plist = self.out_dir / _APP / "Contents" / "Info.plist"
        self.assertEqual(
            self.kit.with_placeholders(plist.read_bytes()), _SAMPLE.read_bytes()
        )

    def test_swift_builds_release_into_a_private_scratch_folder_in_the_data_folder(
        self,
    ) -> None:
        self.build()
        build, where = [call for call in self.kit.tools.calls if call[0] == "swift"]
        app = self.kit.host.script.parent / "app"
        scratch = Path(build[build.index("--scratch-path") + 1])
        self.assertEqual(
            build[:6], ["swift", "build", "-c", "release", "--package-path", str(app)]
        )
        self.assertEqual(where, [*build, "--show-bin-path"])
        self.assertEqual(scratch.parent, self.kit.paths.data_dir / ".scratch")
        self.assertFalse(scratch.is_relative_to(self.kit.checkout))
        self.assertEqual(
            scratch, run_install.scratch_path(self.kit.host, self.kit.layout)
        )
        for folder in (self.kit.paths.data_dir, scratch.parent, scratch):
            self.assertEqual(stat.S_IMODE(folder.stat().st_mode), 0o700, folder)

    def test_two_packages_get_two_scratch_folders(self) -> None:
        other = dataclasses.replace(
            self.kit.host, script=self.kit.home.parent / "elsewhere" / "runner.py"
        )
        self.assertNotEqual(
            run_install.scratch_path(self.kit.host, self.kit.layout),
            run_install.scratch_path(other, self.kit.layout),
        )

    def test_an_allowlisted_script_that_is_missing_is_refused_before_building(
        self,
    ) -> None:
        self.kit.probe.unlink()
        with self.assertRaises(app_bundle.Refused) as caught:
            self.build()
        self.assertIn("is not a file", str(caught.exception))
        self.assertNotIn("build", self.kit.log)

    def test_a_failed_compile_is_a_build_failure(self) -> None:
        self.kit.tools.build_rc = 1
        with self.assertRaises(app_bundle.BuildFailed):
            self.build()
        self.assertFalse((self.out_dir / _APP).exists())


class SignTest(InstallCase):
    """`build --sign`: the identity read, refused, used and never shown."""

    def test_a_signed_build_signs_then_verifies_strictly(self) -> None:
        self.kit.write_identity()
        self.assertEqual(self.build(sign=True), 0)
        self.assertEqual(self.kit.log, ["build", "sign", "verify"])
        sign, verify = self.kit.tools.calls[-2:]
        bundle = str(self.out_dir / _APP)
        self.assertEqual(
            sign,
            [
                "codesign",
                "--force",
                "--sign",
                fx.FAKE_IDENTITY,
                "--timestamp=none",
                bundle,
            ],
        )
        self.assertEqual(
            verify, ["codesign", "--verify", "--strict", "--verbose=2", bundle]
        )
        self.assertIn("signed and verified with Apple…", self.kit.out.getvalue())
        self.assert_identity_hidden()

    def test_no_signing_setting_is_refused_with_how_to_set_it(self) -> None:
        with self.assertRaises(app_bundle.Refused) as caught:
            self.build(sign=True)
        message = str(caught.exception)
        self.assertIn('identity = "<codesign identity>"', message)
        self.assertIn("~/.config/swift_gate/signing.toml", message)
        self.assertNotIn("build", self.kit.log)

    def test_a_failed_signature_never_shows_the_identity(self) -> None:
        self.kit.write_identity()
        self.kit.tools.sign_rc = 1
        self.kit.tools.sign_output = f"{fx.FAKE_IDENTITY}: invented failure\n"
        with self.assertRaises(app_bundle.BuildFailed) as caught:
            self.build(sign=True)
        self.assertNotIn(fx.FAKE_NAME, str(caught.exception))
        self.assertNotIn(fx.FAKE_TEAM, str(caught.exception))


class InstallRefusalTest(InstallCase):
    """What install refuses, before anything is built."""

    def setUp(self) -> None:
        super().setUp()
        self.kit.write_identity()

    def test_a_linked_worktree_is_refused(self) -> None:
        self.kit.tools.git_dir = ".git/worktrees/lane"
        with self.assertRaises(app_bundle.Refused) as caught:
            self.install()
        self.assertIn("linked git worktree", str(caught.exception))
        self.assertEqual(self.kit.log, ["git"])

    def test_no_signing_setting_is_refused_before_building(self) -> None:
        self.kit.paths.signing_config.unlink()
        with self.assertRaises(app_bundle.Refused) as caught:
            self.install()
        self.assertIn('identity = "<codesign identity>"', str(caught.exception))
        self.assertNotIn("build", self.kit.log)

    def test_an_allowlist_without_the_grant_probe_is_refused_before_building(
        self,
    ) -> None:
        others = [e for e in fx.repo_scripts() if Path(e).name != fx.PROBE_NAME]
        trimmed = self.kit.home.parent / "allowlist.json"
        trimmed.write_text(
            json.dumps({"scripts": others}), encoding="utf-8", newline="\n"
        )
        with (
            mock.patch.object(run_allowlist, "ALLOWLIST_FILE", trimmed),
            self.assertRaises(app_bundle.Refused) as caught,
        ):
            self.install()
        self.assertIn(fx.PROBE_NAME, str(caught.exception))
        self.assertNotIn("build", self.kit.log)


class InstallOutcomeTest(InstallCase):
    """install builds, signs, verifies, swaps the bundle in, then checks the grant."""

    def setUp(self) -> None:
        super().setUp()
        self.kit.write_identity()

    def error_line(self) -> str:
        """The one ERROR line on the kit's stderr."""
        (line,) = self.kit.err.getvalue().splitlines()
        self.assertTrue(line.startswith("ERROR: "), line)
        return line

    def assert_installed_and_tidy(self) -> None:
        """The new bundle is in place, and no agent, plist or staging folder is left."""
        self.assertEqual(self.kit.executable.read_bytes(), fx.BUILT_BYTES)
        self.assertEqual(self.staging_folders(), [])
        self.assertFalse(self.kit.paths.grant_plist.exists())
        self.assertEqual(self.kit.launchd.loaded, set())

    def test_granted_is_exit_0_after_every_step_in_order(self) -> None:
        self.kit.install_app()
        self.kit.executable.write_bytes(_OLD_BYTES)
        seen: list[dict[str, object]] = []

        def started() -> None:
            seen.append(plistlib.loads(self.kit.paths.grant_plist.read_bytes()))
            self.kit.write_result("granted", "playing")

        self.kit.launchd.on_bootstrap = started
        self.assertEqual(self.install(), 0)
        steps = "git build sign verify display bootout bootstrap bootout"
        self.assertEqual(self.kit.log, steps.split())
        self.assert_installed_and_tidy()
        self.assertEqual(
            seen[0]["ProgramArguments"],
            [
                str(self.kit.executable),
                "--python",
                sys.executable,
                "--script",
                str(self.kit.probe),
                "--",
                "--result",
                str(self.kit.paths.grant_result),
            ],
        )
        out = self.kit.out.getvalue().splitlines()
        self.assertEqual(len(out), 2, out)
        self.assertIn(str(self.kit.paths.app_bundle), out[0])
        self.assertEqual(out[1], "Apple Music Toolbox Runner may control Music.")
        self.assertEqual(self.kit.err.getvalue(), "")
        self.assert_identity_hidden()

    def test_the_installed_bundle_carries_the_allowlist(self) -> None:
        self.kit.probe_reports("granted")
        self.install()
        plist = self.kit.paths.app_bundle / "Contents" / "Info.plist"
        info = plistlib.loads(plist.read_bytes())
        self.assertEqual(info["AMTRunnerAllowlist"], self.kit.allowlist())

    def test_the_bundle_is_signed_where_it_is_staged_in_the_data_folder(self) -> None:
        self.kit.probe_reports("granted")
        self.install()
        (sign,) = [call for call in self.kit.tools.calls if "--sign" in call]
        staged = self.kit.paths.data_dir / f".staging-{fx.PID}" / _APP
        self.assertEqual(sign[-1], str(staged))

    def test_music_not_running_is_exit_1(self) -> None:
        self.kit.probe_reports("not-running")
        self.assertEqual(self.install(), 1)
        self.assertIn("open Music and run install again", self.error_line())
        self.assert_installed_and_tidy()

    def test_denied_is_exit_1_naming_the_setting(self) -> None:
        self.kit.probe_reports("denied", "invented (-1743)")
        self.assertEqual(self.install(), 1)
        self.assertIn(
            "System Settings > Privacy & Security > Automation > "
            "Apple Music Toolbox Runner",
            self.error_line(),
        )
        self.assert_installed_and_tidy()

    def test_timed_out_is_exit_1(self) -> None:
        self.kit.probe_reports("timed-out", "invented (-1712)")
        self.assertEqual(self.install(), 1)
        self.assertIn(
            "the permission prompt was not answered; run install again",
            self.error_line(),
        )
        self.assert_installed_and_tidy()

    def test_no_result_by_the_deadline_is_exit_1(self) -> None:
        self.assertEqual(self.install(), 1)
        self.assertIn(
            "the permission prompt was not answered; run install again",
            self.error_line(),
        )
        self.assertGreaterEqual(self.kit.clock.mono, 180.0)
        self.assert_installed_and_tidy()

    def test_a_probe_error_is_exit_1_with_its_detail(self) -> None:
        self.kit.probe_reports("error", "invented failure")
        self.assertEqual(self.install(), 1)
        self.assertEqual(
            self.error_line(), "ERROR: the grant check failed: invented failure"
        )
        self.assert_installed_and_tidy()

    def test_a_folder_outside_every_repository_is_refused(self) -> None:
        # The allowlist's paths are relative to a checkout's root, so there must be one.
        self.kit.tools.repos.clear()
        with self.assertRaises(app_bundle.Refused) as caught:
            self.install()
        self.assertIn("could not find the checkout", str(caught.exception))
        self.assertNotIn("build", self.kit.log)


class InstallFailureTest(InstallCase):
    """A failure on the way leaves the earlier app in place and nothing half-made."""

    def setUp(self) -> None:
        super().setUp()
        self.kit.write_identity()
        self.kit.install_app()
        self.kit.executable.write_bytes(_OLD_BYTES)

    def test_a_build_failure_leaves_no_staging_folder_and_the_old_bundle(self) -> None:
        self.kit.tools.build_rc = 1
        with self.assertRaises(app_bundle.BuildFailed):
            self.install()
        self.assertEqual(self.kit.executable.read_bytes(), _OLD_BYTES)
        self.assertEqual(self.staging_folders(), [])
        self.assertNotIn("bootstrap", self.kit.log)

    def test_a_signature_that_does_not_verify_leaves_the_old_bundle(self) -> None:
        self.kit.tools.verify_rc = 1
        with self.assertRaises(app_bundle.BuildFailed):
            self.install()
        self.assertEqual(self.kit.executable.read_bytes(), _OLD_BYTES)
        self.assertEqual(self.staging_folders(), [])
        self.assertNotIn("bootstrap", self.kit.log)

    def test_a_staging_folder_an_earlier_run_left_is_replaced(self) -> None:
        stale = self.kit.paths.data_dir / f".staging-{fx.PID}" / _APP
        stale.mkdir(parents=True)
        self.kit.probe_reports("granted")
        self.assertEqual(self.install(), 0)
        self.assertEqual(self.kit.executable.read_bytes(), fx.BUILT_BYTES)
        self.assertEqual(self.staging_folders(), [])

    def test_a_swap_that_fails_is_a_build_failure_with_the_old_bundle_back(
        self,
    ) -> None:
        refused = PermissionError(13, "Permission denied", "invented")
        with (
            mock.patch.object(run_install, "swap_in", side_effect=refused),
            self.assertRaises(app_bundle.BuildFailed) as caught,
        ):
            self.install()
        self.assertIn("PermissionError", str(caught.exception))
        self.assertEqual(self.kit.executable.read_bytes(), _OLD_BYTES)
        self.assertEqual(self.staging_folders(), [])
        self.assertNotIn("bootstrap", self.kit.log)

    def test_an_old_bundle_that_cannot_be_removed_is_a_warning_only(self) -> None:
        real_rmtree = shutil.rmtree
        staging = self.kit.paths.data_dir / f".staging-{fx.PID}"

        def rmtree(path: Path, ignore_errors: bool = False) -> None:
            # Only the removal after a swap that worked: it is the one not ignoring errors.
            if Path(path) == staging and not ignore_errors:
                raise PermissionError(13, "Permission denied", "invented")
            real_rmtree(path, ignore_errors=ignore_errors)

        self.kit.probe_reports("granted")
        with mock.patch.object(run_install.shutil, "rmtree", rmtree):
            self.assertEqual(self.install(), 0)
        (warning,) = self.kit.err.getvalue().splitlines()
        self.assertTrue(warning.startswith("WARNING: the new app is in place"))
        self.assertIn(str(staging), warning)
        self.assertIn("PermissionError", warning)
        self.assertEqual(self.kit.executable.read_bytes(), fx.BUILT_BYTES)
        # The exchange left the old bundle in the staging folder it could not remove.
        old = staging / _APP / "Contents" / "MacOS" / "runner"
        self.assertEqual(old.read_bytes(), _OLD_BYTES)

    def test_the_upgrade_leaves_no_old_bundle_beside_the_new_one(self) -> None:
        self.kit.probe_reports("granted")
        self.assertEqual(self.install(), 0)
        self.assertEqual(self.staging_folders(), [])
        self.assertEqual(self.kit.err.getvalue(), "")

    def test_a_dead_install_s_work_folders_are_swept_before_staging(self) -> None:
        # Swept even when the build then fails: the sweep comes first.
        left = [
            self.kit.paths.data_dir / f".staging-{fx.DEAD_PID}" / _APP,
            self.kit.paths.data_dir / f".old-{fx.DEAD_PID}-{_APP}",
        ]
        for folder in left:
            folder.mkdir(parents=True)
        self.kit.tools.build_rc = 1
        with self.assertRaises(app_bundle.BuildFailed):
            self.install()
        self.assertEqual(self.staging_folders(), [])
        self.assertEqual(self.kit.executable.read_bytes(), _OLD_BYTES)

    def test_a_grant_agent_launchd_will_not_load_fails_with_the_new_app_in_place(
        self,
    ) -> None:
        self.kit.launchd.unknown.add(self.kit.layout.grant_label)
        with self.assertRaises(launchd_agent.LaunchdError):
            self.install()
        self.assertEqual(self.kit.executable.read_bytes(), fx.BUILT_BYTES)


if __name__ == "__main__":
    unittest.main()
