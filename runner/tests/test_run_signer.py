"""run_signer and its two callers: the signer install records, and the check against it.

`install` reads the new bundle's designated requirement and records it in the data
folder; `status` and `locate` then demand it of the installed bundle, so a bundle at the
installed path that another identity signed is told apart from one that does not verify
at all. codesign is the kit's `FakeTools`; the requirement is an invented one naming the
invented identity, so a test can assert it reaches no output.
"""

from __future__ import annotations

import stat
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))

import _run_fixtures as fx  # noqa: E402 - import follows the sys.path bootstrap above
import app_bundle  # noqa: E402 - on sys.path once _run_fixtures is imported
import run_install  # noqa: E402 - on sys.path once _run_fixtures is imported
import run_signer  # noqa: E402 - on sys.path once _run_fixtures is imported
import run_status  # noqa: E402 - on sys.path once _run_fixtures is imported

if sys.platform == "win32":
    # POSIX only, as the runner is; also lets a win32 type-check skip the mode checks.
    raise unittest.SkipTest("the runner runs on macOS only")  # pragma: only-on win32

#: codesign's exit when the signature is valid but the requirement -R names is not met.
_UNMET = 3
#: The bytes an earlier install left as the app's executable.
_OLD_BYTES = b"the earlier install\n"
_APP = "Apple Music Toolbox Runner.app"
_MISMATCH = "the app is not signed by the identity it was installed with"


class SignerCase(unittest.TestCase):
    """A fresh kit per test, and the secrets no output may hold."""

    def setUp(self) -> None:
        self.kit = fx.make_kit(self)

    def again(self) -> str:
        """The advice every signer refusal ends with."""
        return f"run {self.kit.host.script.name} install again"

    def assert_secrets_hidden(self, text: str) -> None:
        """Neither the requirement nor the identity's name or team ID is in `text`."""
        for secret in (fx.FAKE_REQUIREMENT, fx.FAKE_NAME, fx.FAKE_TEAM):
            self.assertNotIn(secret, text)


class RecordTest(SignerCase):
    """record_signer writes one line at mode 0600; recorded_signer reads it back."""

    def recorded(self) -> str:
        """recorded_signer against the kit."""
        return run_signer.recorded_signer(self.kit.host, self.kit.paths)

    def refusal(self) -> str:
        """The message recorded_signer refuses with."""
        with self.assertRaises(app_bundle.Refused) as caught:
            self.recorded()
        message = str(caught.exception)
        self.assert_secrets_hidden(message)
        return message

    def test_the_record_is_in_the_data_folder(self) -> None:
        self.assertEqual(self.kit.paths.signer_record.parent, self.kit.paths.data_dir)

    def test_a_record_is_one_line_at_mode_0600_and_reads_back(self) -> None:
        self.kit.paths.data_dir.mkdir(parents=True)
        run_signer.record_signer(self.kit.paths, fx.FAKE_REQUIREMENT)
        record = self.kit.paths.signer_record
        self.assertEqual(record.read_bytes(), f"{fx.FAKE_REQUIREMENT}\n".encode())
        self.assertEqual(stat.S_IMODE(record.stat().st_mode), 0o600)
        self.assertEqual(self.recorded(), fx.FAKE_REQUIREMENT)

    def test_a_record_replaces_the_one_before_it(self) -> None:
        self.kit.write_record("an earlier requirement")
        self.kit.paths.signer_record.chmod(0o644)
        run_signer.record_signer(self.kit.paths, fx.FAKE_REQUIREMENT)
        self.assertEqual(self.recorded(), fx.FAKE_REQUIREMENT)
        mode = stat.S_IMODE(self.kit.paths.signer_record.stat().st_mode)
        self.assertEqual(mode, 0o600)

    def test_a_record_that_cannot_be_written_fails_naming_the_kind(self) -> None:
        self.kit.paths.signer_record.mkdir(parents=True)
        with self.assertRaises(app_bundle.BuildFailed) as caught:
            run_signer.record_signer(self.kit.paths, fx.FAKE_REQUIREMENT)
        message = str(caught.exception)
        self.assertRegex(message, r"^could not record the app's signer \(\w+Error\)$")
        self.assert_secrets_hidden(message)

    def test_no_record_is_refused_saying_it_was_never_recorded(self) -> None:
        self.assertEqual(
            self.refusal(), f"the app's signer was never recorded; {self.again()}"
        )

    def test_a_record_that_cannot_be_read_is_refused_naming_the_kind(self) -> None:
        self.kit.paths.signer_record.mkdir(parents=True)
        self.assertEqual(
            self.refusal(),
            f"the app's recorded signer cannot be read (IsADirectoryError); "
            f"{self.again()}",
        )

    def test_a_malformed_record_is_refused(self) -> None:
        over = b"x" * (run_signer.MAX_RECORD_BYTES + 1) + b"\n"
        cases = {
            "empty": b"",
            "blank": b"\n",
            "spaces": b"   \n",
            "no newline": fx.FAKE_REQUIREMENT.encode(),
            "two lines": f"{fx.FAKE_REQUIREMENT}\nmore\n".encode(),
            "carriage return": f"{fx.FAKE_REQUIREMENT}\r\n".encode(),
            "padded": f" {fx.FAKE_REQUIREMENT}\n".encode(),
            "nul": f"{fx.FAKE_REQUIREMENT}\0\n".encode(),
            "not utf-8": b"\xff\xfe\n",
            "oversized": over,
        }
        self.kit.paths.data_dir.mkdir(parents=True)
        for name, content in cases.items():
            with self.subTest(case=name):
                self.kit.paths.signer_record.write_bytes(content)
                self.assertEqual(
                    self.refusal(),
                    f"the app's recorded signer is malformed; {self.again()}",
                )


class InstallRecordTest(SignerCase):
    """install records the new bundle's signer, or fails before it touches the old one."""

    def setUp(self) -> None:
        super().setUp()
        self.kit.write_identity()
        self.kit.probe_reports("granted")

    def install(self) -> int:
        """Run install against the kit."""
        return run_install.install(self.kit.host, self.kit.layout)

    def install_fails(self) -> str:
        """The BuildFailed message install stops with; no grant check may start."""
        with self.assertRaises(app_bundle.BuildFailed) as caught:
            self.install()
        self.assertNotIn("bootstrap", self.kit.log)
        message = str(caught.exception)
        self.assert_secrets_hidden(message)
        return message

    def staging_folders(self) -> list[str]:
        """The staging folders, and any `.old-` folder, left in the data folder."""
        return sorted(
            entry.name
            for entry in self.kit.paths.data_dir.iterdir()
            if entry.name.startswith((".staging-", ".old-"))
        )

    def test_install_records_the_signer_it_signed_with(self) -> None:
        self.assertEqual(self.install(), 0)
        record = self.kit.paths.signer_record
        self.assertEqual(record.read_text(encoding="utf-8"), f"{fx.FAKE_REQUIREMENT}\n")
        self.assertEqual(stat.S_IMODE(record.stat().st_mode), 0o600)
        self.assert_secrets_hidden(self.kit.output())

    def test_the_requirement_is_read_from_the_staged_bundle_once_verified(
        self,
    ) -> None:
        self.install()
        self.assertEqual(self.kit.log[1:5], ["build", "sign", "verify", "display"])
        (display,) = [call for call in self.kit.tools.calls if "-d" in call]
        staged = self.kit.paths.data_dir / f".staging-{fx.PID}" / _APP
        self.assertEqual(display, ["codesign", "-d", "-r-", str(staged)])

    def test_a_requirement_codesign_cannot_read_leaves_the_old_app(self) -> None:
        self.kit.install_app()
        self.kit.write_record("the earlier requirement")
        self.kit.executable.write_bytes(_OLD_BYTES)
        self.kit.tools.display_rc = 1
        self.kit.tools.display_output = f"invented failure naming {fx.FAKE_NAME}\n"
        self.assertEqual(
            self.install_fails(),
            "codesign could not read the app's designated requirement (exit 1)",
        )
        self.assertEqual(self.kit.executable.read_bytes(), _OLD_BYTES)
        self.assertEqual(self.staging_folders(), [])
        self.assertEqual(
            self.kit.paths.signer_record.read_text(encoding="utf-8"),
            "the earlier requirement\n",
        )

    def test_a_display_with_no_requirement_fails_the_install(self) -> None:
        self.kit.tools.display_output = ""
        self.assertEqual(
            self.install_fails(), "codesign did not print one designated requirement"
        )
        self.assertFalse(self.kit.paths.signer_record.exists())

    def test_a_record_that_cannot_be_written_fails_the_install(self) -> None:
        self.kit.paths.signer_record.mkdir(parents=True)
        message = self.install_fails()
        self.assertRegex(message, r"^could not record the app's signer \(\w+Error\)$")

    def test_a_record_write_the_system_refuses_fails_the_install(self) -> None:
        # The write comes after the swap: the new bundle stays, tidily, with the
        # earlier record untouched, and the grant check never runs.
        self.kit.install_app()
        self.kit.write_record("the earlier requirement")
        self.kit.executable.write_bytes(_OLD_BYTES)
        refused = PermissionError(13, "Permission denied", "invented")
        with mock.patch.object(
            run_signer.atomic_write, "replace_text", side_effect=refused
        ):
            self.assertEqual(
                self.install_fails(),
                "could not record the app's signer (PermissionError)",
            )
        self.assertEqual(self.kit.executable.read_bytes(), fx.BUILT_BYTES)
        self.assertEqual(self.staging_folders(), [])
        self.assertEqual(
            self.kit.paths.signer_record.read_text(encoding="utf-8"),
            "the earlier requirement\n",
        )


class CheckTest(SignerCase):
    """status and locate demand the recorded signer before they read the allowlist."""

    def status(self) -> tuple[int, list[str]]:
        """Run status; its exit code and the lines it printed."""
        code = run_status.status(self.kit.host, self.kit.layout)
        self.assert_secrets_hidden(self.kit.output())
        return code, self.kit.out.getvalue().splitlines()

    def locate_refusal(self) -> str:
        """The message locate refuses with; nothing may be printed."""
        with self.assertRaises(app_bundle.Refused) as caught:
            run_status.locate(
                self.kit.host,
                self.kit.layout,
                python=sys.executable,
                script=str(self.kit.probe),
            )
        self.assertEqual(self.kit.output(), "")
        message = str(caught.exception)
        self.assert_secrets_hidden(message)
        return message

    def assert_status_attention(self, reason: str) -> None:
        """status is exit 1 with `reason` as its one reason line."""
        self.assertEqual(
            self.status(),
            (
                1,
                [
                    "Apple Music Toolbox Runner: NEEDS ATTENTION (exit 1)",
                    f"- {reason}",
                ],
            ),
        )

    def test_a_matching_signer_is_healthy_and_located(self) -> None:
        self.kit.install_app()
        code, lines = self.status()
        self.assertEqual(code, 0)
        self.assertIn(
            "- signature: verifies, by the identity it was installed with", lines
        )
        self.assertEqual(
            run_status.locate(
                self.kit.host,
                self.kit.layout,
                python=sys.executable,
                script=str(self.kit.probe),
            ),
            0,
        )

    def test_the_recorded_requirement_is_what_codesign_is_asked_for(self) -> None:
        self.kit.install_app()
        self.kit.write_record('identifier "local.invented.other"')
        self.status()
        (call,) = self.kit.tools.calls
        self.assertIn('-R=identifier "local.invented.other"', call)
        self.assertEqual(call[-1], str(self.kit.paths.app_bundle))

    def test_another_signer_is_attention_and_refused(self) -> None:
        self.kit.install_app()
        self.kit.tools.verify_rc = _UNMET
        self.assert_status_attention(_MISMATCH)
        self.kit.out.truncate(0)
        self.kit.out.seek(0)
        self.assertEqual(self.locate_refusal(), _MISMATCH)

    def test_a_signature_that_does_not_verify_is_still_its_own_reason(self) -> None:
        self.kit.install_app()
        self.kit.tools.verify_rc = 1
        self.assert_status_attention(
            "the app fails codesign --verify --strict (exit 1)"
        )

    def test_no_record_is_attention_and_refused_before_codesign_runs(self) -> None:
        self.kit.install_app()
        self.kit.paths.signer_record.unlink()
        reason = f"the app's signer was never recorded; {self.again()}"
        self.assert_status_attention(reason)
        self.kit.out.truncate(0)
        self.kit.out.seek(0)
        self.assertEqual(self.locate_refusal(), reason)
        self.assertEqual(self.kit.tools.calls, [])

    def test_an_unreadable_record_is_attention_and_refused(self) -> None:
        self.kit.install_app()
        self.kit.paths.signer_record.unlink()
        self.kit.paths.signer_record.mkdir()
        reason = (
            f"the app's recorded signer cannot be read (IsADirectoryError); "
            f"{self.again()}"
        )
        self.assert_status_attention(reason)
        self.kit.out.truncate(0)
        self.kit.out.seek(0)
        self.assertEqual(self.locate_refusal(), reason)
        self.assertEqual(self.kit.tools.calls, [])

    def test_a_malformed_record_is_attention_and_refused(self) -> None:
        self.kit.install_app()
        self.kit.paths.signer_record.write_bytes(b"")
        reason = f"the app's recorded signer is malformed; {self.again()}"
        self.assert_status_attention(reason)
        self.kit.out.truncate(0)
        self.kit.out.seek(0)
        self.assertEqual(self.locate_refusal(), reason)
        self.assertEqual(self.kit.tools.calls, [])

    def test_another_signer_is_refused_before_the_allowlist_is_read(self) -> None:
        # The Info.plist is unreadable, so only the signer check can be what refuses.
        self.kit.install_app(info={})
        self.kit.tools.verify_rc = _UNMET
        self.assertEqual(self.locate_refusal(), _MISMATCH)
        self.assertEqual(self.kit.log, ["verify"])


if __name__ == "__main__":
    unittest.main()
