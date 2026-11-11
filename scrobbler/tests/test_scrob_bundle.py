"""scrob_bundle: the build, the bundle it assembles, and the signing identity's handling.

Every tool is a fake from `_scrob_fixtures`, every path is under a temporary root, and the
signing identity is an invented one that must appear in no output.
"""

from __future__ import annotations

import dataclasses
import plistlib
import stat
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import _scrob_fixtures as fx  # noqa: E402 - import follows the sys.path bootstrap above
import scrob_bundle  # noqa: E402 - on sys.path once _scrob_fixtures is imported
import scrob_host  # noqa: E402 - on sys.path once _scrob_fixtures is imported

#: The Automation prompt, restated so a changed wording fails a test.
_PROMPT = (
    "listensmith scrobbler reads the track Music is playing so it can log your plays "
    "on this Mac. It never changes playback or your library."
)


class BundleCase(unittest.TestCase):
    """A fresh kit per test, and an output folder under its root."""

    def setUp(self) -> None:
        self.kit = fx.make_kit(self)
        self.out_dir = self.kit.home.parent / "out"
        self.out_dir.mkdir()

    def build(self, *, sign: bool = False) -> int:
        """Run the build command against the kit."""
        return scrob_bundle.run_build(
            self.kit.host, self.kit.layout, self.out_dir, sign=sign
        )

    def assert_identity_hidden(self) -> None:
        """Neither the fake identity's name nor its team ID reached any output."""
        for secret in (fx.FAKE_IDENTITY, fx.FAKE_NAME, fx.FAKE_TEAM):
            self.assertNotIn(secret, self.kit.output())


class BuildTest(BundleCase):
    """`build` compiles outside the checkout and assembles the bundle exactly."""

    def test_the_bundle_holds_the_executable_and_the_property_list(self) -> None:
        self.assertEqual(self.build(), 0)
        bundle = self.out_dir / "listensmith scrobbler.app"
        executable = bundle / "Contents" / "MacOS" / "scrobbler"
        self.assertEqual(executable.read_bytes(), fx.BUILT_BYTES)
        self.assertIn(str(bundle), self.kit.out.getvalue())
        self.assertEqual(self.kit.log, ["build"])

    def test_the_property_list_holds_exactly_its_keys(self) -> None:
        self.build()
        plist = self.out_dir / "listensmith scrobbler.app" / "Contents" / "Info.plist"
        layout = self.kit.layout
        self.assertEqual(
            plistlib.loads(plist.read_bytes()),
            {
                "CFBundleIdentifier": layout.bundle_id,
                "CFBundleName": "listensmith scrobbler",
                "CFBundleDisplayName": "listensmith scrobbler",
                "CFBundleExecutable": layout.executable,
                "CFBundlePackageType": "APPL",
                "CFBundleShortVersionString": layout.version,
                "CFBundleVersion": layout.version,
                "LSMinimumSystemVersion": "14.0",
                "LSUIElement": True,
                "NSAppleEventsUsageDescription": _PROMPT,
                # Plain http to the loopback store, and nothing wider.
                "NSAppTransportSecurity": {"NSAllowsLocalNetworking": True},
            },
        )

    def test_swift_builds_release_into_a_private_scratch_folder_in_the_data_folder(
        self,
    ) -> None:
        self.build()
        build, where = self.kit.tools.calls[:2]
        app = self.kit.checkout / "scrobbler" / "app"
        scratch = Path(build[build.index("--scratch-path") + 1])
        self.assertEqual(
            build[:6], ["swift", "build", "-c", "release", "--package-path", str(app)]
        )
        self.assertEqual(where, [*build, "--show-bin-path"])
        self.assertEqual(scratch.parent, self.kit.paths.data_dir / ".scratch")
        self.assertFalse(scratch.is_relative_to(self.kit.checkout))
        self.assertEqual(
            scratch, scrob_bundle.scratch_path(self.kit.host, self.kit.layout)
        )
        for folder in (self.kit.paths.data_dir, scratch.parent, scratch):
            self.assertEqual(stat.S_IMODE(folder.stat().st_mode), 0o700, folder)

    def test_two_packages_get_two_scratch_folders(self) -> None:
        other = dataclasses.replace(
            self.kit.host, script=self.kit.home.parent / "elsewhere" / "scrobbler.py"
        )
        self.assertNotEqual(
            scrob_bundle.scratch_path(self.kit.host, self.kit.layout),
            scrob_bundle.scratch_path(other, self.kit.layout),
        )

    def test_a_symlinked_scratch_folder_is_refused(self) -> None:
        elsewhere = self.kit.home.parent / "elsewhere"
        elsewhere.mkdir()
        elsewhere.chmod(0o755)
        self.kit.paths.data_dir.mkdir(parents=True)
        (self.kit.paths.data_dir / ".scratch").symlink_to(elsewhere)
        with self.assertRaises(scrob_bundle.Refused) as caught:
            self.build()
        self.assertIn("symbolic link", str(caught.exception))
        self.assertEqual(stat.S_IMODE(elsewhere.stat().st_mode), 0o755)
        self.assertNotIn("build", self.kit.log)

    def test_the_bundle_s_executable_keeps_its_execute_bit(self) -> None:
        self.build()
        executable = self.out_dir / "listensmith scrobbler.app" / "Contents" / "MacOS"
        mode = (executable / "scrobbler").stat().st_mode
        self.assertTrue(mode & stat.S_IXUSR)

    def test_a_failed_compile_is_exit_1_naming_its_last_line(self) -> None:
        self.kit.tools.build_rc = 1
        with self.assertRaises(scrob_bundle.BuildFailed) as caught:
            self.build()
        self.assertIn("invented compile failure", str(caught.exception))

    def test_a_product_folder_swift_will_not_name_fails(self) -> None:
        self.kit.tools.bin_rc = 1
        with self.assertRaises(scrob_bundle.BuildFailed) as caught:
            self.build()
        self.assertIn("--show-bin-path", str(caught.exception))

    def test_a_build_that_leaves_no_product_fails(self) -> None:
        self.kit.tools.build_rc = 0
        original = self.kit.tools._swift

        def build_nothing(args: list[str]) -> fx.subprocess.CompletedProcess[str]:
            if "--show-bin-path" in args:
                return original(args)
            return fx.done(args, 0)

        self.kit.tools._swift = build_nothing  # type: ignore[method-assign]
        with self.assertRaises(scrob_bundle.BuildFailed) as caught:
            self.build()
        self.assertIn("left no scrobbler", str(caught.exception))

    def test_a_swift_that_cannot_run_fails_naming_it(self) -> None:
        self.kit.tools.missing.add("swift")
        with self.assertRaises(scrob_bundle.BuildFailed) as caught:
            self.build()
        self.assertIn("could not run swift", str(caught.exception))

    def test_an_existing_bundle_is_refused_untouched(self) -> None:
        bundle = self.out_dir / "listensmith scrobbler.app"
        bundle.mkdir()
        with self.assertRaises(scrob_bundle.Refused):
            self.build()
        self.assertEqual(list(bundle.iterdir()), [])

    def test_a_bundle_that_cannot_be_written_fails(self) -> None:
        self.out_dir.rmdir()
        self.out_dir.write_text("a file, not a folder", encoding="utf-8", newline="\n")
        with self.assertRaises(scrob_bundle.BuildFailed) as caught:
            self.build()
        self.assertIn("could not assemble", str(caught.exception))


class SignTest(BundleCase):
    """`build --sign`: the identity read, refused, used and never shown."""

    def test_a_signed_build_signs_then_verifies_strictly(self) -> None:
        self.kit.write_identity()
        self.assertEqual(self.build(sign=True), 0)
        self.assertEqual(self.kit.log, ["build", "sign", "verify"])
        sign, verify = self.kit.tools.calls[-2:]
        bundle = str(self.out_dir / "listensmith scrobbler.app")
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
        with self.assertRaises(scrob_bundle.Refused) as caught:
            self.build(sign=True)
        message = str(caught.exception)
        self.assertIn('identity = "<codesign identity>"', message)
        self.assertIn("~/.config/swift_gate/signing.toml", message)
        self.assertNotIn("build", self.kit.log)

    def test_a_signing_setting_inside_a_checkout_is_refused(self) -> None:
        self.kit.write_identity()
        self.kit.tools.repos.append(self.kit.home)
        with self.assertRaises(scrob_bundle.Refused) as caught:
            self.build(sign=True)
        self.assertIn("outside every checkout", str(caught.exception))
        self.assertNotIn("build", self.kit.log)

    def test_a_malformed_signing_setting_is_refused_without_its_content(self) -> None:
        self.kit.paths.signing_config.parent.mkdir(parents=True)
        self.kit.paths.signing_config.write_text(
            f"identity = 7 # {fx.FAKE_TEAM}\n", encoding="utf-8", newline="\n"
        )
        with self.assertRaises(scrob_bundle.Refused) as caught:
            self.build(sign=True)
        self.assertNotIn(fx.FAKE_TEAM, str(caught.exception))

    def test_a_codesign_failure_prints_its_output_redacted(self) -> None:
        self.kit.write_identity()
        self.kit.tools.sign_rc = 1
        self.kit.tools.sign_output = (
            f"{fx.FAKE_IDENTITY}: ambiguous (matches {fx.FAKE_IDENTITY} and "
            f'"Apple Development: {fx.FAKE_NAME} ({fx.FAKE_TEAM})")\n'
            f"{self.kit.home}/invented/keychain: not found\n"
        )
        with self.assertRaises(scrob_bundle.BuildFailed) as caught:
            self.build(sign=True)
        message = str(caught.exception)
        self.assertIn("codesign sign failed (exit 1)", message)
        self.assertNotIn(str(self.kit.home), message)
        self.assertIn("Apple Development: …", message)
        for secret in (fx.FAKE_IDENTITY, fx.FAKE_NAME, fx.FAKE_TEAM):
            self.assertNotIn(secret, message)
        self.assertNotIn("verify", self.kit.log)

    def test_a_failed_verify_is_exit_1_redacted(self) -> None:
        self.kit.write_identity()
        self.kit.tools.verify_rc = 3
        self.kit.tools.verify_output = f"invalid signature for team {fx.FAKE_TEAM}\n"
        with self.assertRaises(scrob_bundle.BuildFailed) as caught:
            self.build(sign=True)
        self.assertIn("codesign verify failed (exit 3)", str(caught.exception))
        self.assertNotIn(fx.FAKE_TEAM, str(caught.exception))


class HostTest(unittest.TestCase):
    """The host seam's one pure helper."""

    def test_tools_speak_untranslated_english_and_ignore_inherited_git_settings(
        self,
    ) -> None:
        inherited = {
            "LANG": "fr_FR.UTF-8",
            "GIT_DIR": "/invented/.git",
            "GIT_WORK_TREE": "/invented",
            "GIT_COMMON_DIR": "/invented/.git",
            "GIT_CEILING_DIRECTORIES": "/invented",
        }
        self.assertEqual(
            scrob_host.tool_environment(inherited),
            {"LANG": "fr_FR.UTF-8", "LC_ALL": "C"},
        )


if __name__ == "__main__":
    unittest.main()
