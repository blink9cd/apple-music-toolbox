"""scrob_status and a permission request still in flight: `automation_asked_at`.

The app writes when its request for Automation of Music began, and null once the answer
is in. A request that has waited past `PROMPT_LIMIT_S` is a prompt on the screen, or a
request that hung, and needs attention in `status` and in the session lines alike. The
field is optional: a status file from an app that predates it reads as no request.

Each test starts from a healthy install on a temporary home, all fakes, and changes the
one field.
"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import _scrob_fixtures as fx  # noqa: E402 - import follows the sys.path bootstrap above
import scrob_status  # noqa: E402 - on sys.path once _scrob_fixtures is imported

_ATTENTION = "needs attention"


class PromptCase(unittest.TestCase):
    """A healthy install per test, with a way to set how long a request has waited."""

    def setUp(self) -> None:
        self.kit = fx.make_kit(self)
        self.kit.install_app()
        self.kit.write_status()

    def asked(self, seconds_ago: float) -> None:
        """Rewrite the status with a request begun `seconds_ago`."""
        self.kit.write_status(automation_asked_at=self.kit.clock.wall - seconds_ago)

    def reasons(self) -> tuple[scrob_status.Reason, ...]:
        """The reasons of the kit's install."""
        return scrob_status.gather_status(self.kit.host, self.kit.layout).reasons


class PromptWaitingTest(PromptCase):
    """A request that has waited too long needs attention; a fresh or absent one does not."""

    def test_a_request_past_the_limit_needs_attention_with_its_wait(self) -> None:
        self.asked(11)
        (reason,) = self.reasons()
        self.assertEqual(reason.kind, _ATTENTION)
        for word in ("Automation prompt for Music", "11 s", "screen"):
            self.assertIn(word, reason.text)

    def test_a_request_at_the_limit_is_healthy(self) -> None:
        self.asked(scrob_status.PROMPT_LIMIT_S)
        self.assertEqual(self.reasons(), ())

    def test_no_request_is_healthy(self) -> None:
        self.kit.write_status(automation_asked_at=None)
        self.assertEqual(self.reasons(), ())

    def test_the_session_check_carries_the_reason(self) -> None:
        self.asked(45)
        (line,) = scrob_status.session_lines(self.kit.host, self.kit.layout)
        self.assertTrue(line.startswith("Listensmith Scrobbler: needs attention -- "))
        self.assertIn("Automation prompt for Music has waited 45 s", line)
        self.assertTrue(line.endswith("; details: scrobbler.py status"), line)

    def test_a_stopped_app_gives_its_heartbeat_reason_alone(self) -> None:
        # The app is not running, so the pending time is as stale as the heartbeat.
        for heartbeat_at in (self.kit.clock.wall - 500, None):
            with self.subTest(heartbeat_at=heartbeat_at):
                self.kit.write_status(
                    heartbeat_at=heartbeat_at,
                    automation_asked_at=self.kit.clock.wall - 500,
                )
                (reason,) = self.reasons()
                self.assertIn("heartbeat", reason.text)
                self.assertNotIn("prompt", reason.text)

    def test_a_heartbeat_at_its_limit_keeps_the_prompt_reason(self) -> None:
        self.kit.write_status(
            heartbeat_at=self.kit.clock.wall - scrob_status.HEARTBEAT_LIMIT_S,
            automation_asked_at=self.kit.clock.wall - 60,
        )
        (reason,) = self.reasons()
        self.assertIn("Automation prompt for Music has waited 60 s", reason.text)


class PromptFieldTest(PromptCase):
    """How the optional field is read."""

    def test_the_time_is_read_as_written(self) -> None:
        self.asked(3)
        status = scrob_status.read_app_status(self.kit.paths.status_file)
        self.assertEqual(status.automation_asked_at, self.kit.clock.wall - 3)

    def test_a_file_without_the_key_reads_as_no_request(self) -> None:
        # An app that predates the field writes format 1 too, and must stay readable.
        document = json.loads(self.kit.paths.status_file.read_text(encoding="utf-8"))
        del document["automation_asked_at"]
        self.kit.paths.status_file.write_text(
            json.dumps(document), encoding="utf-8", newline="\n"
        )
        status = scrob_status.read_app_status(self.kit.paths.status_file)
        self.assertIsNone(status.automation_asked_at)
        self.assertEqual(self.reasons(), ())

    def test_a_wrong_type_needs_attention_naming_the_field(self) -> None:
        for value in ("soon", True, [1]):
            with self.subTest(value=value):
                self.kit.write_status(automation_asked_at=value)
                (reason,) = self.reasons()
                self.assertEqual(reason.kind, _ATTENTION)
                self.assertIn("automation_asked_at", reason.text)

    def test_a_time_that_is_not_finite_is_refused(self) -> None:
        document = json.loads(self.kit.paths.status_file.read_text(encoding="utf-8"))
        document["automation_asked_at"] = float("inf")
        with self.assertRaises(scrob_status.StatusFileError) as caught:
            scrob_status.parse_app_status(document)
        self.assertIn("automation_asked_at", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
