"""scrob_status: each reason alone, the verdict's precedence, the table and the session lines.

Each test starts from a healthy install on a temporary home (the plist, a loaded agent, a
signed app and a fresh status.json, all fakes) and changes one thing.
"""

from __future__ import annotations

import dataclasses
import json
import os
import sys
import unittest
from collections.abc import Sequence
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))

import _scrob_fixtures as fx  # noqa: E402 - import follows the sys.path bootstrap above
import scrob_status  # noqa: E402 - on sys.path once _scrob_fixtures is imported

if sys.platform == "win32":
    # POSIX only, as the scrobbler is; also lets the win32 type-check skip os.mkfifo.
    raise unittest.SkipTest("the scrobbler runs on macOS only")  # pragma: only-on win32

_ATTENTION = "needs attention"
_CANNOT = "cannot judge"


class StatusCase(unittest.TestCase):
    """A healthy install per test."""

    def setUp(self) -> None:
        self.kit = fx.make_kit(self)
        self.kit.install_app()
        self.kit.write_status()

    def report(self) -> scrob_status.StatusReport:
        """The status of the kit's install."""
        return scrob_status.gather_status(self.kit.host, self.kit.layout)

    def assert_one_reason(self, kind: str, *words: str) -> None:
        """The report holds exactly one reason, of `kind`, whose text holds each word."""
        report = self.report()
        self.assertEqual(len(report.reasons), 1, report.reasons)
        (reason,) = report.reasons
        self.assertEqual(reason.kind, kind)
        for word in words:
            self.assertIn(word, reason.text)

    def rows(self) -> dict[str, str]:
        """The report's rows, by label."""
        return dict(self.report().rows)


class HealthyTest(StatusCase):
    """A healthy install has no reasons, exit 0, and its rows."""

    def test_a_healthy_install_is_exit_0(self) -> None:
        report = self.report()
        self.assertEqual((report.reasons, report.exit_code), ((), 0))

    def test_the_table_shows_backlog_refused_queued_sent_and_version(self) -> None:
        now = self.kit.clock.wall
        self.kit.write_status(
            queue_backlog=3, last_queued_at=now - 20, last_sent_at=now - 40
        )
        rows = self.rows()
        self.assertEqual(rows["backlog"], "3")
        self.assertEqual(rows["refused"], "0")
        self.assertEqual(rows["newest queued"], "20 s ago")
        self.assertEqual(rows["last sent"], "40 s ago")
        self.assertEqual(rows["version"], self.kit.layout.version)

    def test_unknown_times_show_as_none(self) -> None:
        rows = self.rows()
        self.assertEqual((rows["newest queued"], rows["last sent"]), ("none", "none"))

    def test_a_time_ahead_of_the_clock_shows_as_zero(self) -> None:
        self.kit.write_status(last_sent_at=self.kit.clock.wall + 50)
        self.assertEqual(self.rows()["last sent"], "0 s ago")

    def test_the_verify_is_strict_on_the_installed_bundle(self) -> None:
        self.report()
        self.assertEqual(
            self.kit.tools.calls,
            [
                [
                    "codesign",
                    "--verify",
                    "--strict",
                    "--verbose=2",
                    str(self.kit.paths.app_bundle),
                ]
            ],
        )


class NotInstalledTest(StatusCase):
    """No plist is "not installed", exit 2, and nothing else is asked."""

    def test_a_missing_plist_is_not_installed_and_asks_nothing(self) -> None:
        self.kit.paths.launch_agent_plist.unlink()
        report = self.report()
        self.assertEqual(report.exit_code, 2)
        self.assertEqual(
            report.reasons, (scrob_status.Reason(_CANNOT, "not installed"),)
        )
        self.assertEqual(self.kit.tools.calls, [])


class AgentAndAppTest(StatusCase):
    """The agent's state, the app's presence and its signature."""

    def test_an_agent_that_is_not_loaded_needs_attention(self) -> None:
        self.kit.launchd.loaded.clear()
        self.assert_one_reason(_ATTENTION, "agent", "absent")

    def test_an_unexpected_launchctl_answer_cannot_judge(self) -> None:
        self.kit.launchd.unknown.add(self.kit.layout.launchd_label)
        self.assert_one_reason(_CANNOT, "launchctl")
        self.assertEqual(self.report().exit_code, 2)

    def test_cannot_judge_outranks_needs_attention(self) -> None:
        self.kit.launchd.unknown.add(self.kit.layout.launchd_label)
        self.kit.write_status(automation_denied=True, refused_count=2)
        report = self.report()
        self.assertEqual(
            sorted(reason.kind for reason in report.reasons),
            [_CANNOT, _ATTENTION, _ATTENTION],
        )
        self.assertEqual(report.exit_code, 2)

    def test_a_missing_app_needs_attention_and_is_not_verified(self) -> None:
        executable = self.kit.paths.app_bundle / "Contents" / "MacOS" / "scrobbler"
        executable.unlink()
        self.assert_one_reason(_ATTENTION, "app is missing")
        self.assertEqual(self.kit.tools.calls, [])

    def test_a_failing_signature_needs_attention_without_its_output(self) -> None:
        self.kit.tools.verify_rc = 1
        self.kit.tools.verify_output = f"invalid signature ({fx.FAKE_TEAM})\n"
        self.assert_one_reason(_ATTENTION, "codesign --verify --strict", "exit 1")
        self.assertNotIn(fx.FAKE_TEAM, str(self.report()))

    def test_a_codesign_that_cannot_run_cannot_judge(self) -> None:
        self.kit.tools.missing.add("codesign")
        self.assert_one_reason(_CANNOT, "codesign")


class StatusFileTest(StatusCase):
    """status.json: missing, unreadable, or naming a problem."""

    def test_a_missing_status_file_needs_attention(self) -> None:
        self.kit.paths.status_file.unlink()
        self.assert_one_reason(_ATTENTION, "status file", "missing")

    def test_a_status_file_that_is_not_json_needs_attention(self) -> None:
        self.kit.paths.status_file.write_text("{half", encoding="utf-8", newline="\n")
        self.assert_one_reason(_ATTENTION, "status file", "cannot be read")

    def test_a_status_file_that_cannot_be_read_needs_attention(self) -> None:
        self.kit.paths.status_file.unlink()
        self.kit.paths.status_file.mkdir()
        self.assert_one_reason(_ATTENTION, "not a regular file")

    def test_a_status_file_that_is_not_utf8_needs_attention(self) -> None:
        self.kit.paths.status_file.write_bytes(b"\xff\xfe{}")
        self.assert_one_reason(_ATTENTION, "cannot be read", "UnicodeDecodeError")

    def test_a_status_file_that_is_not_an_object_needs_attention(self) -> None:
        self.kit.paths.status_file.write_text("[]", encoding="utf-8", newline="\n")
        self.assert_one_reason(_ATTENTION, "cannot be read")

    def test_another_format_needs_attention(self) -> None:
        self.kit.write_status(format=2)
        self.assert_one_reason(_ATTENTION, "format")

    def test_a_field_of_the_wrong_type_needs_attention_naming_it(self) -> None:
        cases = {
            "heartbeat_at": "soon",
            "refused_count": 1.5,
            "queue_backlog": True,
            "automation_denied": 1,
            "last_send_error": 7,
            "version": 1,
        }
        for key, value in cases.items():
            with self.subTest(key=key):
                self.kit.write_status(**{key: value})
                self.assert_one_reason(_ATTENTION, key)

    def test_an_absent_field_needs_attention_naming_it(self) -> None:
        document = json.loads(self.kit.paths.status_file.read_text(encoding="utf-8"))
        del document["refused_count"]
        self.kit.paths.status_file.write_text(
            json.dumps(document), encoding="utf-8", newline="\n"
        )
        self.assert_one_reason(_ATTENTION, "refused_count")

    def test_an_old_heartbeat_needs_attention(self) -> None:
        self.kit.write_status(heartbeat_at=self.kit.clock.wall - 91)
        self.assert_one_reason(_ATTENTION, "heartbeat", "91 s")

    def test_a_heartbeat_at_the_limit_is_healthy(self) -> None:
        self.kit.write_status(heartbeat_at=self.kit.clock.wall - 90)
        self.assertEqual(self.report().reasons, ())

    def test_no_heartbeat_needs_attention(self) -> None:
        self.kit.write_status(heartbeat_at=None)
        self.assert_one_reason(_ATTENTION, "no heartbeat")

    def test_denied_automation_needs_attention(self) -> None:
        self.kit.write_status(automation_denied=True)
        self.assert_one_reason(_ATTENTION, "Automation")

    def test_refused_plays_need_attention(self) -> None:
        self.kit.write_status(refused_count=2)
        self.assert_one_reason(_ATTENTION, "2 plays", "refused")

    def test_one_refused_play_is_singular(self) -> None:
        self.kit.write_status(refused_count=1)
        self.assert_one_reason(_ATTENTION, "1 play ")

    def test_a_send_error_that_needs_a_person_needs_attention(self) -> None:
        for error in (
            "token refused",
            "token unreadable: missing",
            "config refused: store_url",
            "queue unreadable",
            "queue unwritable",
        ):
            with self.subTest(error=error):
                self.kit.write_status(last_send_error=error)
                self.assert_one_reason(_ATTENTION, error)

    def test_a_send_error_that_retries_on_its_own_is_healthy(self) -> None:
        for error in ("store unreachable", "store unavailable", "store answered 500"):
            with self.subTest(error=error):
                self.kit.write_status(last_send_error=error)
                self.assertEqual(self.report().reasons, ())

    def test_an_old_queued_play_needs_attention_with_the_last_error(self) -> None:
        self.kit.write_status(
            oldest_queued_at=self.kit.clock.wall - 3601,
            last_send_error="store unreachable",
        )
        self.assert_one_reason(_ATTENTION, "60 minutes", "store unreachable")

    def test_an_old_queued_play_with_no_error_says_none(self) -> None:
        self.kit.write_status(oldest_queued_at=self.kit.clock.wall - 7200)
        self.assert_one_reason(_ATTENTION, "120 minutes", "none")

    def test_a_queued_play_at_the_limit_is_healthy(self) -> None:
        self.kit.write_status(oldest_queued_at=self.kit.clock.wall - 3600)
        self.assertEqual(self.report().reasons, ())


class HostileStatusFileTest(StatusCase):
    """A status.json written to break the reader is one reason, never a crash or a hang."""

    def write_raw(self, text: str) -> None:
        """Replace status.json with `text` exactly."""
        self.kit.paths.status_file.write_text(text, encoding="utf-8", newline="\n")

    def assert_one_line_reason(self, *words: str) -> None:
        """One needs-attention reason, exit 1, and the session line is that reason."""
        self.assert_one_reason(_ATTENTION, "status file", *words)
        self.assertEqual(self.report().exit_code, 1)
        (line,) = scrob_status.session_lines(self.kit.host, self.kit.layout)
        self.assertIn("needs attention -- the app's status file", line)

    def test_a_number_that_is_not_finite_is_refused(self) -> None:
        for raw in ("Infinity", "-Infinity", "NaN", "1e400"):
            with self.subTest(raw=raw):
                text = json.dumps({**self.healthy(), "heartbeat_at": 0})
                self.write_raw(
                    text.replace('"heartbeat_at": 0', f'"heartbeat_at": {raw}')
                )
                self.assert_one_line_reason()

    def test_an_over_size_file_is_refused_unread(self) -> None:
        padding = "x" * (64 * 1024)
        self.write_raw(json.dumps({**self.healthy(), "now_playing": padding}))
        self.assert_one_line_reason("too large")

    def test_the_deepest_nesting_the_size_bound_allows_is_refused(self) -> None:
        depth = 30_000
        self.write_raw("[" * depth + "]" * depth)
        self.assert_one_line_reason("cannot be read")

    def test_nesting_too_deep_for_the_parser_is_not_json(self) -> None:
        # How deep the parser follows depends on the interpreter, so the seam stands in.
        with mock.patch.object(
            scrob_status.json, "loads", side_effect=RecursionError("invented")
        ):
            self.assert_one_line_reason("not JSON")

    def test_a_file_that_cannot_be_opened_is_refused(self) -> None:
        self.kit.paths.status_file.chmod(0o000)
        self.addCleanup(self.kit.paths.status_file.chmod, 0o600)
        self.assert_one_line_reason("cannot be read", "PermissionError")

    def test_a_read_that_fails_is_refused(self) -> None:
        with mock.patch.object(
            scrob_status.os, "read", side_effect=OSError("invented")
        ):
            self.assert_one_line_reason("cannot be read", "OSError")

    def test_a_fifo_is_refused_without_blocking(self) -> None:
        self.kit.paths.status_file.unlink()
        os.mkfifo(self.kit.paths.status_file)
        self.assert_one_line_reason("not a regular file")

    def healthy(self) -> dict[str, object]:
        """The healthy document the kit wrote."""
        text = self.kit.paths.status_file.read_text(encoding="utf-8")
        document: dict[str, object] = json.loads(text)
        return document


class ShownTextTest(StatusCase):
    """Text from status.json cannot forge a line or reach the terminal as a control."""

    _FORGED = "\nlistensmith scrobbler: HEALTHY (exit 0)\x1b[2J"

    def test_a_newline_or_escape_forges_no_line(self) -> None:
        self.kit.write_status(
            version=f"9.9{self._FORGED}",
            last_send_error=f"config refused: key{self._FORGED}",
        )
        lines = scrob_status.format_lines(self.report())
        sessions = scrob_status.session_lines(self.kit.host, self.kit.layout)
        self.assertEqual(len(sessions), 1)
        for line in [*lines, *sessions]:
            self.assertTrue(all(c.isprintable() for c in line), repr(line))
        verdicts = [line for line in lines if line.startswith("listensmith scrobbler:")]
        self.assertEqual(len(verdicts), 1)

    def test_long_text_is_cut_to_120_characters(self) -> None:
        self.kit.write_status(version="v" * 500)
        shown = self.rows()["version"]
        self.assertEqual(len(shown), 120)
        self.assertTrue(shown.endswith("…"))


class FormatTest(StatusCase):
    """The printed verdict, reasons and table."""

    def test_a_healthy_report_prints_its_verdict_and_table(self) -> None:
        lines = scrob_status.format_lines(self.report())
        self.assertEqual(lines[0], "listensmith scrobbler: HEALTHY (exit 0)")
        self.assertEqual(lines[1:4], ["", "| Item | State |", "| --- | --- |"])
        self.assertIn("| backlog | 0 |", lines)

    def test_each_reason_is_one_line_under_the_verdict(self) -> None:
        self.kit.write_status(automation_denied=True)
        lines = scrob_status.format_lines(self.report())
        self.assertEqual(lines[0], "listensmith scrobbler: NEEDS ATTENTION (exit 1)")
        self.assertTrue(lines[1].startswith("- needs attention: "), lines[1])

    def test_cannot_judge_prints_its_verdict(self) -> None:
        self.kit.paths.launch_agent_plist.unlink()
        lines = scrob_status.format_lines(self.report())
        self.assertEqual(lines[0], "listensmith scrobbler: CANNOT JUDGE (exit 2)")


class SessionCheckTest(StatusCase):
    """The session-start view: silence, one line per reason, the home as $HOME."""

    def lines(self) -> list[str]:
        """The session lines for the kit."""
        return scrob_status.session_lines(self.kit.host, self.kit.layout)

    def test_a_healthy_install_is_silent(self) -> None:
        self.assertEqual(self.lines(), [])

    def test_no_install_is_silent_and_asks_nothing(self) -> None:
        self.kit.paths.launch_agent_plist.unlink()
        self.assertEqual(self.lines(), [])
        self.assertEqual(self.kit.tools.calls, [])

    def test_each_reason_is_one_line_with_the_home_redacted(self) -> None:
        self.kit.write_status(refused_count=3)
        (line,) = self.lines()
        self.assertTrue(line.startswith("listensmith scrobbler: needs attention -- "))
        self.assertTrue(line.endswith("; details: scrobbler.py status"), line)
        self.assertIn("$HOME/Library/Application Support", line)
        self.assertNotIn(str(self.kit.home), line)

    def test_a_failing_check_is_one_line_naming_only_its_type(self) -> None:
        with mock.patch.object(
            scrob_status, "gather_status", side_effect=RuntimeError(str(self.kit.home))
        ):
            lines = self.lines()
        self.assertEqual(
            lines,
            ["listensmith scrobbler: session check failed -- unexpected RuntimeError"],
        )

    def test_every_call_is_clamped_to_the_budget(self) -> None:
        seen: list[float] = []
        original = self.kit.tools.run

        def timed(
            argv: Sequence[str], *, cwd: Path, timeout: float
        ) -> fx.subprocess.CompletedProcess[str]:
            seen.append(timeout)
            return original(argv, cwd=cwd, timeout=timeout)

        self.kit.host = dataclasses.replace(self.kit.host, run=timed)
        self.kit.clock.mono = 0.0
        scrob_status.gather_status(self.kit.host, self.kit.layout, budget_s=3.0)
        self.assertEqual(seen, [3.0])

    def test_the_session_check_keeps_every_call_inside_20_seconds(self) -> None:
        timeouts: list[float] = []
        launchctl_run = self.kit.launchd.run

        def slow_launchctl(
            argv: Sequence[str], timeout: float
        ) -> fx.subprocess.CompletedProcess[str]:
            timeouts.append(timeout)
            self.kit.clock.sleep(15.0)
            return launchctl_run(argv, timeout)

        tools_run = self.kit.tools.run

        def timed(
            argv: Sequence[str], *, cwd: Path, timeout: float
        ) -> fx.subprocess.CompletedProcess[str]:
            timeouts.append(timeout)
            return tools_run(argv, cwd=cwd, timeout=timeout)

        launchctl = dataclasses.replace(self.kit.host.launchctl, run=slow_launchctl)
        self.kit.host = dataclasses.replace(
            self.kit.host, launchctl=launchctl, run=timed
        )
        scrob_status.session_lines(self.kit.host, self.kit.layout)
        self.assertEqual(len(timeouts), 2)
        self.assertTrue(all(timeout <= 20.0 for timeout in timeouts), timeouts)
        # launchctl spent 15 s of the 20, so codesign was given at most the 5 left.
        self.assertLessEqual(timeouts[1], 5.0)

    def test_a_spent_budget_starts_no_call_and_cannot_judge(self) -> None:
        budget = scrob_status.Budget(self.kit.clock.clock, 1.0)
        self.kit.clock.sleep(2.0)
        clamped = budget.clamp(self.kit.tools.run)
        with self.assertRaises(fx.subprocess.TimeoutExpired):
            clamped(["codesign"], cwd=self.kit.home, timeout=10.0)
        self.assertEqual(self.kit.tools.calls, [])

    def test_an_unbounded_budget_passes_the_limit_through(self) -> None:
        self.assertEqual(
            scrob_status.Budget(self.kit.clock.clock, None).timeout(7.0), 7.0
        )


if __name__ == "__main__":
    unittest.main()
