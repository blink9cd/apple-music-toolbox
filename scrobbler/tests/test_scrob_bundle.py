"""scrob_bundle: the build, the bundle it assembles, and the signing identity's handling.

Every tool is a fake from `_scrob_fixtures`, every path is under a temporary root, and the
signing identity is an invented one that must appear in no output. The generic steps'
own failures (a failed compile, codesign, an unwritable bundle, a refused setting, a
private folder) are tested in signed_app's suites, beside the code that holds them.
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
import scrob_layout  # noqa: E402 - on sys.path once _scrob_fixtures is imported

if sys.platform == "win32":
    # POSIX only, as the scrobbler is; also lets the win32 type-check skip os.getuid.
    raise unittest.SkipTest("the scrobbler runs on macOS only")  # pragma: only-on win32

#: The Automation prompt, restated so a changed wording fails a test.
_PROMPT = (
    "Listensmith Scrobbler reads the track Music is playing so it can log your plays "
    "on this Mac. It never changes playback or your library."
)
#: The Info.plist bytes the shipped layout builds, checked in so any change is seen.
_GOLDEN_PLIST = Path(__file__).resolve().parent / "golden" / "info_plist.xml"


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
        bundle = self.out_dir / "Listensmith Scrobbler.app"
        executable = bundle / "Contents" / "MacOS" / "scrobbler"
        self.assertEqual(executable.read_bytes(), fx.BUILT_BYTES)
        self.assertIn(str(bundle), self.kit.out.getvalue())
        self.assertEqual(self.kit.log, ["build"])

    def test_the_property_list_holds_exactly_its_keys(self) -> None:
        self.build()
        plist = self.out_dir / "Listensmith Scrobbler.app" / "Contents" / "Info.plist"
        layout = self.kit.layout
        self.assertEqual(
            plistlib.loads(plist.read_bytes()),
            {
                "CFBundleIdentifier": layout.bundle_id,
                "CFBundleName": "Listensmith Scrobbler",
                "CFBundleDisplayName": "Listensmith Scrobbler",
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

    def test_the_property_list_s_bytes_match_the_golden_file(self) -> None:
        self.assertEqual(
            scrob_bundle.info_plist(scrob_layout.load_layout()),
            _GOLDEN_PLIST.read_bytes(),
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


class NameTest(unittest.TestCase):
    """The Automation prompt names the app as macOS shows it."""

    def test_the_prompt_opens_with_the_display_name(self) -> None:
        display_name = scrob_layout.load_layout().display_name
        self.assertTrue(scrob_bundle.AUTOMATION_PROMPT.startswith(f"{display_name} "))


class SignTest(BundleCase):
    """`build --sign`: the identity read, refused, used and never shown."""

    def test_a_signed_build_signs_then_verifies_strictly(self) -> None:
        self.kit.write_identity()
        self.assertEqual(self.build(sign=True), 0)
        self.assertEqual(self.kit.log, ["build", "sign", "verify"])
        sign, verify = self.kit.tools.calls[-2:]
        bundle = str(self.out_dir / "Listensmith Scrobbler.app")
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


if __name__ == "__main__":
    unittest.main()
