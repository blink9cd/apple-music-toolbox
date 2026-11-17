"""run_status.locate: the installed executable's path, or the reason a job may not use it.

codesign is the kit's `FakeTools`, and the installed app is one the kit writes under its
temporary home. Every refusal is `app_bundle.Refused`, which the command line turns into
one ERROR line and exit 2.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import _run_fixtures as fx  # noqa: E402 - import follows the sys.path bootstrap above
import app_bundle  # noqa: E402 - on sys.path once _run_fixtures is imported
import run_status  # noqa: E402 - on sys.path once _run_fixtures is imported


class LocateTest(unittest.TestCase):
    """`locate` answers only for a verified bundle whose allowlist holds both paths."""

    def setUp(self) -> None:
        self.kit = fx.make_kit(self)

    def locate(self, *, python: str | None = None, script: str | None = None) -> int:
        """Locate the runner for `python` and `script`, the kit's own by default."""
        return run_status.locate(
            self.kit.host,
            self.kit.layout,
            python=sys.executable if python is None else python,
            script=str(self.kit.probe) if script is None else script,
        )

    def refusal(self, **asked: str) -> str:
        """The message `locate` refuses with; nothing may be printed."""
        with self.assertRaises(app_bundle.Refused) as caught:
            self.locate(**asked)
        self.assertEqual(self.kit.output(), "")
        return str(caught.exception)

    def test_it_prints_the_executable_s_path_on_one_line(self) -> None:
        self.kit.install_app()
        self.assertEqual(self.locate(), 0)
        self.assertEqual(self.kit.out.getvalue(), f"{self.kit.executable}\n")
        self.assertTrue(self.kit.executable.is_absolute())
        self.assertEqual(self.kit.err.getvalue(), "")

    def test_every_allowlisted_script_is_located(self) -> None:
        self.kit.install_app()
        for script in self.kit.allowlist()["scripts"]:
            with self.subTest(script=Path(script).name):
                self.assertEqual(self.locate(script=script), 0)

    def test_not_installed_is_refused_saying_how_to_install(self) -> None:
        message = self.refusal()
        self.assertIn("Apple Music Toolbox Runner is not installed", message)
        self.assertIn(f"{self.kit.host.script.name} install", message)
        self.assertEqual(self.kit.tools.calls, [])

    def test_a_signature_that_does_not_verify_is_refused(self) -> None:
        self.kit.install_app()
        self.kit.tools.verify_rc = 1
        self.kit.tools.verify_output = f"{fx.FAKE_IDENTITY}: invented failure\n"
        message = self.refusal()
        self.assertEqual(message, "the runner's own signature does not verify")

    def test_the_signature_is_checked_before_the_allowlist_is_read(self) -> None:
        # Only a verified bundle's Info.plist is trusted, as in the runner itself.
        self.kit.install_app(info={})
        self.kit.tools.verify_rc = 1
        self.assertEqual(self.refusal(), "the runner's own signature does not verify")
        self.assertEqual(self.kit.log, ["verify"])

    def test_a_codesign_that_cannot_run_is_refused(self) -> None:
        self.kit.install_app()
        self.kit.tools.missing.add("codesign")
        self.assertEqual(self.refusal(), "codesign could not run (FileNotFoundError)")

    def test_another_interpreter_is_refused(self) -> None:
        self.kit.install_app()
        self.assertEqual(
            self.refusal(python=fx.OTHER_PYTHON),
            f"not in the runner's allowlist: {fx.OTHER_PYTHON}",
        )

    def test_another_script_is_refused(self) -> None:
        self.kit.install_app()
        other = str(self.kit.checkout / "elsewhere.py")
        self.assertEqual(
            self.refusal(script=other), f"not in the runner's allowlist: {other}"
        )

    def test_a_bundle_with_no_allowlist_is_refused(self) -> None:
        self.kit.install_app(info={"CFBundleExecutable": "runner"})
        self.assertEqual(
            self.refusal(), "the runner's allowlist is missing or malformed"
        )

    def test_a_bundle_with_no_property_list_is_refused(self) -> None:
        self.kit.install_app()
        (self.kit.paths.app_bundle / "Contents" / "Info.plist").unlink()
        self.assertEqual(
            self.refusal(), "the runner's allowlist is missing or malformed"
        )

    def test_a_property_list_that_does_not_parse_is_refused(self) -> None:
        self.kit.install_app()
        plist = self.kit.paths.app_bundle / "Contents" / "Info.plist"
        for damaged in (b"<plist><dict><key>", b"not a property list", b""):
            with self.subTest(damaged=damaged):
                plist.write_bytes(damaged)
                self.assertEqual(
                    self.refusal(), "the runner's allowlist is missing or malformed"
                )

    def test_a_property_list_that_is_not_a_dictionary_is_refused(self) -> None:
        self.kit.install_app()
        plist = self.kit.paths.app_bundle / "Contents" / "Info.plist"
        plist.write_bytes(
            b'<?xml version="1.0" encoding="UTF-8"?>\n<plist version="1.0">'
            b"<array><string>invented</string></array></plist>\n"
        )
        self.assertEqual(
            self.refusal(), "the runner's allowlist is missing or malformed"
        )


if __name__ == "__main__":
    unittest.main()
