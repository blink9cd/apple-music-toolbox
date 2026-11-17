"""run_status: `status`'s three verdicts and what each prints.

codesign is the kit's `FakeTools`, and the installed app is one the kit writes under its
temporary home.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import _run_fixtures as fx  # noqa: E402 - import follows the sys.path bootstrap above
import run_status  # noqa: E402 - on sys.path once _run_fixtures is imported


class StatusTest(unittest.TestCase):
    """2 not installed, 1 a bundle that cannot be trusted, 0 otherwise."""

    def setUp(self) -> None:
        self.kit = fx.make_kit(self)

    def status(self) -> tuple[int, list[str]]:
        """Run status against the kit; its exit code and the lines it printed."""
        code = run_status.status(self.kit.host, self.kit.layout)
        self.assertEqual(self.kit.err.getvalue(), "")
        return code, self.kit.out.getvalue().splitlines()

    def test_no_bundle_is_exit_2(self) -> None:
        self.assertEqual(
            self.status(), (2, ["Apple Music Toolbox Runner: NOT INSTALLED (exit 2)"])
        )
        self.assertEqual(self.kit.tools.calls, [])

    def test_a_verified_bundle_is_exit_0_listing_what_it_may_start(self) -> None:
        self.kit.install_app()
        code, lines = self.status()
        allowed = self.kit.allowlist()
        self.assertEqual(code, 0)
        self.assertEqual(
            lines,
            [
                "Apple Music Toolbox Runner: HEALTHY (exit 0)",
                f"- app: {self.kit.paths.app_bundle}",
                "- signature: verifies, by the identity it was installed with",
                f"- interpreter: {allowed['python']}",
                *[f"- script: {script}" for script in allowed["scripts"]],
            ],
        )

    def test_the_signature_is_checked_strictly_against_the_recorded_signer(
        self,
    ) -> None:
        self.kit.install_app()
        self.status()
        self.assertEqual(
            self.kit.tools.calls,
            [
                [
                    "codesign",
                    "--verify",
                    "--strict",
                    "--verbose=2",
                    f"-R={fx.FAKE_REQUIREMENT}",
                    str(self.kit.paths.app_bundle),
                ]
            ],
        )

    def test_a_signature_that_does_not_verify_is_exit_1(self) -> None:
        self.kit.install_app()
        self.kit.tools.verify_rc = 1
        self.kit.tools.verify_output = f"{fx.FAKE_IDENTITY}: invented failure\n"
        code, lines = self.status()
        self.assertEqual(code, 1)
        self.assertEqual(
            lines,
            [
                "Apple Music Toolbox Runner: NEEDS ATTENTION (exit 1)",
                "- the app fails codesign --verify --strict (exit 1)",
            ],
        )
        # codesign's own output names the signing certificate, so none of it is shown.
        self.assertNotIn(fx.FAKE_NAME, self.kit.output())

    def test_a_codesign_that_cannot_run_is_exit_1(self) -> None:
        self.kit.install_app()
        self.kit.tools.missing.add("codesign")
        code, lines = self.status()
        self.assertEqual(code, 1)
        self.assertEqual(lines[1], "- codesign could not run (FileNotFoundError)")

    def test_a_bundle_with_no_allowlist_is_exit_1(self) -> None:
        self.kit.install_app(info={"CFBundleExecutable": "runner"})
        code, lines = self.status()
        self.assertEqual(code, 1)
        self.assertEqual(lines[1], "- the runner's allowlist is missing or malformed")


if __name__ == "__main__":
    unittest.main()
