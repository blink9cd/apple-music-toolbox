"""Grouped suite: which OS errors main() calls a swift launch failure.

Only the swift launch itself may print "could not run swift". The ``--sign`` stage's
temporary directory and its copy of each product, and the coverage report's read, fail
with an ``OSError`` of their own, and each is reported under a neutral label that names
no tool. Every path, identity and team ID here is an obvious fake.
"""

from __future__ import annotations

import unittest
from pathlib import Path
from unittest import mock

from _fixtures import write

# The sign fixtures are reached through the module, so discovery does not collect its
# cases here a second time.
import test_signing
from test_signing import IDENTITY, TEAM_ID

import swgate_stages

LAUNCH = "could not run swift"
NEUTRAL = "ERROR: an OS error stopped the gate: PermissionError: Permission denied"


def _error_line(text: str) -> str:
    """The one ``ERROR:`` line in *text*."""
    lines = [line for line in text.splitlines() if line.startswith("ERROR:")]
    assert len(lines) == 1, text
    return lines[0]


class NonLaunchErrorTests(test_signing._CliCase):
    """An OSError outside the swift launch exits 2 under the neutral label."""

    def setUp(self) -> None:
        super().setUp()
        write(self.config, f'identity = "{IDENTITY}"\n')
        self.denied = PermissionError(13, "Permission denied", str(self.root / "x"))

    def sign(self) -> tuple[int, str, str]:
        """Run main with --sign and the configured fake identity."""
        return self.main(["--sign", "--signing-config", str(self.config)])

    def assert_neutral(self, code: int, out: str) -> None:
        """Exit 2, the neutral label, and no launch claim or absolute path."""
        self.assertEqual(code, 2, out)
        line = _error_line(out)
        self.assertEqual(line, NEUTRAL)
        self.assertNotIn(LAUNCH, out)
        self.assertNotIn(str(self.root), line)
        self.assertNotIn(TEAM_ID, out)

    def test_the_sign_temp_dir_failure_does_not_claim_a_swift_launch(self) -> None:
        with mock.patch.object(
            swgate_stages.tempfile, "TemporaryDirectory", side_effect=self.denied
        ):
            code, out, _ = self.sign()
        self.assert_neutral(code, out)

    def test_the_product_copy_failure_does_not_claim_a_swift_launch(self) -> None:
        with mock.patch.object(swgate_stages.shutil, "copy2", side_effect=self.denied):
            code, out, _ = self.sign()
        self.assert_neutral(code, out)
        self.assertEqual(self.codesign.calls, [])

    def test_the_report_read_failure_does_not_claim_a_swift_launch(self) -> None:
        real_read = Path.read_text
        report = self.codecov
        denied = self.denied

        def read_text(path: Path, *args: object, **kwargs: object) -> str:
            if path == report:
                raise denied
            return real_read(path, *args, **kwargs)  # type: ignore[arg-type]

        with mock.patch.object(Path, "read_text", read_text):
            code, out, _ = self.main([])
        self.assert_neutral(code, out)


class LaunchErrorTests(test_signing._CliCase):
    """The swift launch itself still says so, at every stage that launches swift."""

    def setUp(self) -> None:
        super().setUp()
        write(self.config, f'identity = "{IDENTITY}"\n')

    def test_a_launch_failure_at_a_late_stage_says_could_not_run_swift(self) -> None:
        for needle in ("dump-package", "--show-codecov-path", "--show-bin-path"):
            denied = PermissionError(13, "Permission denied", "/opt/x/swift")
            with self.subTest(stage=needle):
                runner = self.runner()
                runner.raises = {needle: denied}
                with mock.patch.object(self, "runner", return_value=runner):
                    code, out, _ = self.main(
                        ["--sign", "--signing-config", str(self.config)]
                    )
                self.assertEqual(code, 2, out)
                self.assertEqual(
                    _error_line(out),
                    "ERROR: could not run swift: PermissionError: Permission denied",
                )

    def test_the_launch_error_carries_the_os_error(self) -> None:
        denied = PermissionError(13, "Permission denied", "/opt/x/swift")
        error = swgate_stages.SwiftLaunchError(denied)
        self.assertIs(error.error, denied)
        self.assertNotIsInstance(error, OSError)


if __name__ == "__main__":
    unittest.main()
