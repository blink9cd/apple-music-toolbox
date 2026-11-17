"""app_bundle: the swift build, the bundle it assembles, and the signing identity's handling.

Every tool is a fake from `_app_fixtures`, every path is under a temporary root, the
bundle's names are invented, and the signing identity is an invented one that must
appear in no output.
"""

from __future__ import annotations

import dataclasses
import plistlib
import stat
import sys
import unittest
from collections.abc import Sequence
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import _app_fixtures as fx  # noqa: E402 - import follows the sys.path bootstrap above
import app_bundle  # noqa: E402 - on sys.path once _app_fixtures is imported

#: The invented entry script, below the invented checkout.
_SCRIPT = "invented_tool/invented_tool.py"
#: An invented Automation prompt.
_PROMPT = "Invented Example reads an invented thing."


class BundleCase(unittest.TestCase):
    """A fresh kit per test, an invented bundle_info, and the folders a build uses."""

    def setUp(self) -> None:
        self.bundle_info = fx.InventedSpec()
        self.kit = fx.make_host_kit(
            self, script=_SCRIPT, product=self.bundle_info.executable
        )
        self.root = self.kit.home.parent
        self.package = self.kit.host.script.parent / "app"
        self.scratch = self.root / "scratch"
        self.out_dir = self.root / "out"
        self.out_dir.mkdir()

    def build(self) -> Path:
        """Run swift_build against the kit's package and scratch folder."""
        return app_bundle.swift_build(
            self.kit.host, self.package, self.scratch, self.bundle_info.executable
        )

    def plist(self) -> bytes:
        """The invented bundle's Info.plist, with no extra keys."""
        return app_bundle.info_plist(self.bundle_info, automation_prompt=_PROMPT)

    def assert_identity_hidden(self, text: str) -> None:
        """Neither the fake identity's name nor its team ID is in `text`."""
        for secret in (fx.FAKE_IDENTITY, fx.FAKE_NAME, fx.FAKE_TEAM):
            self.assertNotIn(secret, text)


class SwiftBuildTest(BundleCase):
    """swift_build builds in release into the scratch folder and finds the product."""

    def test_it_builds_release_and_returns_the_product_swift_names(self) -> None:
        built = self.build()
        build, where = self.kit.tools.calls
        self.assertEqual(
            build,
            [
                "swift",
                "build",
                "-c",
                "release",
                "--package-path",
                str(self.package),
                "--scratch-path",
                str(self.scratch),
            ],
        )
        self.assertEqual(where, [*build, "--show-bin-path"])
        self.assertEqual(built, self.scratch / "release" / self.bundle_info.executable)
        self.assertEqual(built.read_bytes(), fx.BUILT_BYTES)

    def test_a_failed_compile_fails_naming_its_last_line(self) -> None:
        self.kit.tools.build_rc = 1
        with self.assertRaises(app_bundle.BuildFailed) as caught:
            self.build()
        self.assertEqual(
            str(caught.exception),
            "swift build failed (exit 1): error: invented compile failure",
        )

    def test_a_failure_with_no_output_says_so(self) -> None:
        original = self.kit.tools._swift

        def silent(args: list[str]) -> fx.subprocess.CompletedProcess[str]:
            if "--show-bin-path" in args:
                return original(args)
            return fx.done(args, 4)

        self.kit.tools._swift = silent  # type: ignore[method-assign]
        with self.assertRaises(app_bundle.BuildFailed) as caught:
            self.build()
        self.assertEqual(
            str(caught.exception), "swift build failed (exit 4): no output"
        )

    def test_a_product_folder_swift_will_not_name_fails(self) -> None:
        self.kit.tools.bin_rc = 1
        with self.assertRaises(app_bundle.BuildFailed) as caught:
            self.build()
        self.assertIn("--show-bin-path", str(caught.exception))

    def test_a_build_that_leaves_no_product_fails_naming_it(self) -> None:
        original = self.kit.tools._swift

        def build_nothing(args: list[str]) -> fx.subprocess.CompletedProcess[str]:
            if "--show-bin-path" in args:
                return original(args)
            return fx.done(args, 0)

        self.kit.tools._swift = build_nothing  # type: ignore[method-assign]
        with self.assertRaises(app_bundle.BuildFailed) as caught:
            self.build()
        self.assertEqual(
            str(caught.exception),
            f"swift build left no {self.bundle_info.executable} in its product folder",
        )

    def test_a_swift_that_cannot_run_fails_naming_it(self) -> None:
        self.kit.tools.missing.add("swift")
        with self.assertRaises(app_bundle.BuildFailed) as caught:
            self.build()
        self.assertEqual(
            str(caught.exception), "could not run swift (FileNotFoundError)"
        )


class InfoPlistTest(BundleCase):
    """info_plist holds the bundle's names, the prompt, and the caller's extra keys."""

    def test_the_property_list_holds_exactly_its_keys(self) -> None:
        self.assertEqual(
            plistlib.loads(self.plist()),
            {
                "CFBundleIdentifier": "local.invented.example",
                "CFBundleName": "Invented Example",
                "CFBundleDisplayName": "Invented Example",
                "CFBundleExecutable": "invented",
                "CFBundlePackageType": "APPL",
                "CFBundleShortVersionString": "1.2.3",
                "CFBundleVersion": "1.2.3",
                "LSMinimumSystemVersion": app_bundle.MINIMUM_SYSTEM,
                "LSUIElement": True,
                "NSAppleEventsUsageDescription": _PROMPT,
            },
        )

    def test_the_minimum_system_is_the_package_floor(self) -> None:
        self.assertEqual(app_bundle.MINIMUM_SYSTEM, "14.0")

    def test_extra_keys_are_added(self) -> None:
        extra = {"InventedAllowlist": ["/invented/one", "/invented/two"]}
        plist = plistlib.loads(
            app_bundle.info_plist(
                self.bundle_info, automation_prompt=_PROMPT, extra=extra
            )
        )
        self.assertEqual(plist["InventedAllowlist"], ["/invented/one", "/invented/two"])
        self.assertEqual(plist["CFBundleExecutable"], "invented")

    def test_extra_keys_are_merged_last_so_they_win(self) -> None:
        extra = {"LSUIElement": False}
        plist = plistlib.loads(
            app_bundle.info_plist(
                self.bundle_info, automation_prompt=_PROMPT, extra=extra
            )
        )
        self.assertIs(plist["LSUIElement"], False)


class AssembleTest(BundleCase):
    """assemble lays out the bundle from the built executable and the plist given."""

    def test_the_bundle_holds_the_executable_and_the_property_list(self) -> None:
        bundle = app_bundle.assemble(
            self.bundle_info, self.out_dir, self.build(), self.plist()
        )
        self.assertEqual(bundle, self.out_dir / "Invented Example.app")
        executable = app_bundle.bundle_executable(bundle, self.bundle_info)
        self.assertEqual(executable, bundle / "Contents" / "MacOS" / "invented")
        self.assertEqual(executable.read_bytes(), fx.BUILT_BYTES)
        self.assertTrue(executable.stat().st_mode & stat.S_IXUSR)
        self.assertEqual(
            (bundle / "Contents" / "Info.plist").read_bytes(), self.plist()
        )

    def test_an_existing_bundle_is_refused_untouched(self) -> None:
        bundle = self.out_dir / "Invented Example.app"
        bundle.mkdir()
        with self.assertRaises(app_bundle.Refused) as caught:
            app_bundle.assemble(
                self.bundle_info, self.out_dir, self.build(), self.plist()
            )
        self.assertEqual(
            str(caught.exception),
            f"{bundle} already exists; remove it or choose another --out",
        )
        self.assertEqual(list(bundle.iterdir()), [])

    def test_a_bundle_that_cannot_be_written_fails(self) -> None:
        built = self.build()
        self.out_dir.rmdir()
        self.out_dir.write_text("a file, not a folder", encoding="utf-8", newline="\n")
        with self.assertRaises(app_bundle.BuildFailed) as caught:
            app_bundle.assemble(self.bundle_info, self.out_dir, built, self.plist())
        self.assertIn("could not assemble", str(caught.exception))


class IdentityTest(BundleCase):
    """read_identity: the setting read, or refused, and never shown."""

    def setUp(self) -> None:
        super().setUp()
        self.setting = self.kit.home / ".config" / "invented" / "signing.toml"

    def write_setting(self, text: str) -> None:
        """Write `text` as the signing setting."""
        self.setting.parent.mkdir(parents=True, exist_ok=True)
        self.setting.write_text(text, encoding="utf-8", newline="\n")

    def read(self) -> str:
        """read_identity against the kit and the setting."""
        return app_bundle.read_identity(self.kit.host, self.setting)

    def test_a_configured_identity_is_returned(self) -> None:
        self.write_setting(f'identity = "{fx.FAKE_IDENTITY}"\n')
        self.assertEqual(self.read(), fx.FAKE_IDENTITY)

    def test_no_setting_is_refused_with_how_to_set_it(self) -> None:
        with self.assertRaises(app_bundle.Refused) as caught:
            self.read()
        self.assertEqual(
            str(caught.exception),
            'no signing identity is set: write identity = "<codesign identity>" to '
            "~/.config/invented/signing.toml, a file outside every checkout, then run "
            "this again",
        )

    def test_a_setting_inside_a_checkout_is_refused(self) -> None:
        self.write_setting(f'identity = "{fx.FAKE_IDENTITY}"\n')
        self.kit.tools.repos.append(self.kit.home)
        with self.assertRaises(app_bundle.Refused) as caught:
            self.read()
        self.assertIn("outside every checkout", str(caught.exception))
        self.assert_identity_hidden(str(caught.exception))

    def test_a_malformed_setting_is_refused_without_its_content(self) -> None:
        self.write_setting(f"identity = 7 # {fx.FAKE_TEAM}\n")
        with self.assertRaises(app_bundle.Refused) as caught:
            self.read()
        self.assertNotIn(fx.FAKE_TEAM, str(caught.exception))


class SignTest(BundleCase):
    """sign_bundle signs then verifies strictly, and redacts what codesign says."""

    def setUp(self) -> None:
        super().setUp()
        self.bundle = self.out_dir / "Invented Example.app"

    def sign(self) -> None:
        """sign_bundle on the invented bundle with the fake identity."""
        app_bundle.sign_bundle(self.kit.host, self.bundle, fx.FAKE_IDENTITY)

    def test_it_signs_then_verifies_strictly(self) -> None:
        self.sign()
        self.assertEqual(self.kit.log, ["sign", "verify"])
        sign, verify = self.kit.tools.calls
        bundle = str(self.bundle)
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
        self.assertEqual(verify, app_bundle.verify_argv(self.bundle))
        self.assertEqual(
            verify, ["codesign", "--verify", "--strict", "--verbose=2", bundle]
        )
        self.assert_identity_hidden(self.kit.output())

    def test_tools_run_from_the_entry_script_s_folder(self) -> None:
        cwds: list[Path] = []
        original = self.kit.tools.run

        def logged(
            argv: Sequence[str], *, cwd: Path, timeout: float
        ) -> fx.subprocess.CompletedProcess[str]:
            cwds.append(cwd)
            return original(argv, cwd=cwd, timeout=timeout)

        host = dataclasses.replace(self.kit.host, run=logged)
        app_bundle.sign_bundle(host, self.bundle, fx.FAKE_IDENTITY)
        self.assertEqual(cwds, [self.kit.host.script.parent] * 2)

    def test_a_codesign_failure_prints_its_output_redacted(self) -> None:
        self.kit.tools.sign_rc = 1
        # codesign quotes each identity an ambiguous one matched; swift_gate's redaction
        # keeps a label only where a common name starts, which a quote marks here.
        self.kit.tools.sign_output = (
            f'{fx.FAKE_IDENTITY}: ambiguous (matches "{fx.FAKE_IDENTITY}" and '
            f'"Apple Development: {fx.FAKE_NAME} ({fx.FAKE_TEAM})")\n'
            f"{self.kit.home}/invented/keychain: not found\n"
        )
        with self.assertRaises(app_bundle.BuildFailed) as caught:
            self.sign()
        message = str(caught.exception)
        self.assertTrue(message.startswith("codesign sign failed (exit 1):\n"), message)
        self.assertNotIn(str(self.kit.home), message)
        self.assertIn("Apple Development: …", message)
        self.assert_identity_hidden(message)
        self.assertNotIn("verify", self.kit.log)

    def test_a_failed_verify_fails_redacted(self) -> None:
        self.kit.tools.verify_rc = 3
        self.kit.tools.verify_output = f"invalid signature for team {fx.FAKE_TEAM}\n"
        with self.assertRaises(app_bundle.BuildFailed) as caught:
            self.sign()
        self.assertIn("codesign verify failed (exit 3)", str(caught.exception))
        self.assertNotIn(fx.FAKE_TEAM, str(caught.exception))

    def test_a_codesign_that_cannot_run_fails_naming_it(self) -> None:
        self.kit.tools.missing.add("codesign")
        with self.assertRaises(app_bundle.BuildFailed) as caught:
            self.sign()
        self.assertEqual(
            str(caught.exception), "could not run codesign (FileNotFoundError)"
        )


class RequirementTest(BundleCase):
    """designated_requirement reads the signer's requirement; verify_argv can demand one."""

    def setUp(self) -> None:
        super().setUp()
        self.bundle = self.out_dir / "Invented Example.app"

    def read(self) -> str:
        """designated_requirement on the invented bundle."""
        return app_bundle.designated_requirement(self.kit.host, self.bundle)

    def failure(self) -> str:
        """The message designated_requirement fails with; nothing may be printed."""
        with self.assertRaises(app_bundle.BuildFailed) as caught:
            self.read()
        self.assertEqual(self.kit.output(), "")
        return str(caught.exception)

    def test_it_reads_the_designated_line_of_codesign_s_display(self) -> None:
        self.assertEqual(self.read(), fx.FAKE_REQUIREMENT)
        self.assertEqual(
            self.kit.tools.calls, [["codesign", "-d", "-r-", str(self.bundle)]]
        )
        self.assertEqual(self.kit.output(), "")

    def test_an_implicit_requirement_s_comment_mark_is_dropped(self) -> None:
        # An ad hoc signature's requirement is implicit, which codesign marks with "# ".
        self.kit.tools.display_output = '# designated => cdhash H"00ff"\n'
        self.assertEqual(self.read(), 'cdhash H"00ff"')

    def test_other_lines_are_ignored(self) -> None:
        self.kit.tools.display_output = (
            f"Executable=/invented\ndesignated => {fx.FAKE_REQUIREMENT}\n\n"
        )
        self.assertEqual(self.read(), fx.FAKE_REQUIREMENT)

    def test_a_display_that_fails_is_a_build_failure_without_its_output(self) -> None:
        self.kit.tools.display_rc = 1
        self.kit.tools.display_output = f"invented failure naming {fx.FAKE_NAME}\n"
        message = self.failure()
        self.assertEqual(
            message, "codesign could not read the app's designated requirement (exit 1)"
        )

    def test_no_designated_line_or_two_is_a_build_failure(self) -> None:
        line = f"designated => {fx.FAKE_REQUIREMENT}\n"
        for shown in ("", "Executable=/invented\n", "designated => \n", line * 2):
            with self.subTest(shown=shown):
                self.kit.tools.display_output = shown
                message = self.failure()
                self.assertEqual(
                    message, "codesign did not print one designated requirement"
                )
                self.assert_identity_hidden(message)

    def test_a_codesign_that_cannot_run_fails_naming_it(self) -> None:
        self.kit.tools.missing.add("codesign")
        self.assertEqual(self.failure(), "could not run codesign (FileNotFoundError)")

    def test_verify_argv_demands_a_requirement_when_given_one(self) -> None:
        # codesign takes the requirement's text as -R's value with a leading "=".
        self.assertEqual(
            app_bundle.verify_argv(self.bundle, requirement=fx.FAKE_REQUIREMENT),
            [
                "codesign",
                "--verify",
                "--strict",
                "--verbose=2",
                f"-R={fx.FAKE_REQUIREMENT}",
                str(self.bundle),
            ],
        )

    def test_verify_argv_without_a_requirement_is_unchanged(self) -> None:
        self.assertEqual(
            app_bundle.verify_argv(self.bundle, requirement=None),
            app_bundle.verify_argv(self.bundle),
        )


if __name__ == "__main__":
    unittest.main()
