"""grant_probe: the read-only question it asks, how it reads the answer, and its result file.

osascript is a fake run in every test: nothing here starts a process, reaches Music.app
or raises a permission prompt. Each result is written under a temporary directory.
"""

from __future__ import annotations

import contextlib
import io
import json
import os
import subprocess
import sys
import unittest
from collections.abc import Sequence
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))

import grant_probe  # noqa: E402 - import follows the sys.path bootstrap above

#: What osascript writes when macOS refuses, or gives up on, the Apple event.
_DENIED = "32:60: execution error: Not authorized to send Apple events to Music. ({})\n"
_NO_ANSWER = (
    "32:60: execution error: Music got an error: AppleEvent timed out. (-1712)\n"
)


def _answers(
    code: int, out: str = "", err: str = ""
) -> tuple[grant_probe.RunFn, list[tuple[list[str], float]]]:
    """A fake osascript answering `code`, `out` and `err`, and the calls it received."""
    calls: list[tuple[list[str], float]] = []

    def run(argv: Sequence[str], timeout: float) -> subprocess.CompletedProcess[str]:
        calls.append((list(argv), timeout))
        return subprocess.CompletedProcess(list(argv), code, out, err)

    return run, calls


def _raises(error: Exception) -> grant_probe.RunFn:
    """A fake osascript that cannot finish: it raises `error`."""

    def run(argv: Sequence[str], timeout: float) -> subprocess.CompletedProcess[str]:
        raise error

    return run


class QuestionTest(unittest.TestCase):
    """What the probe asks, and how long it lets a person take to answer the prompt."""

    def test_it_asks_for_the_player_state_only_when_music_is_running(self) -> None:
        self.assertEqual(
            grant_probe.SCRIPT,
            'if application "Music" is running then tell application "Music" to get '
            "player state as text",
        )

    def test_it_never_asks_for_the_version(self) -> None:
        # AppleScript answers that from Music's bundle with no Apple event, so it would
        # report a grant that was never given.
        self.assertNotIn("version", grant_probe.SCRIPT)

    def test_the_script_holds_no_timeout_clause(self) -> None:
        # A short `with timeout` makes macOS withdraw the consent prompt before a person
        # has read it; AppleScript's own default is 120 s.
        self.assertNotIn("timeout", grant_probe.SCRIPT)

    def test_the_bound_outlives_applescript_s_own_default(self) -> None:
        run, calls = _answers(0, "paused\n")
        grant_probe.probe(run)
        ((argv, timeout),) = calls
        self.assertEqual(argv, ["/usr/bin/osascript", "-e", grant_probe.SCRIPT])
        self.assertGreaterEqual(timeout, 120)
        self.assertEqual(timeout, grant_probe.GRANT_PROBE_TIMEOUT_S)
        self.assertEqual(grant_probe.GRANT_PROBE_TIMEOUT_S, 150.0)


class OutcomeTest(unittest.TestCase):
    """Each answer osascript can give is one outcome."""

    def outcome(self, code: int, out: str = "", err: str = "") -> dict[str, str]:
        """The probe's result for one scripted osascript answer."""
        run, _ = _answers(code, out, err)
        return grant_probe.probe(run)

    def test_a_state_is_granted(self) -> None:
        self.assertEqual(
            self.outcome(0, "playing\n"), {"outcome": "granted", "detail": "playing"}
        )

    def test_no_state_is_music_not_running(self) -> None:
        self.assertEqual(
            self.outcome(0, "\n"), {"outcome": "not-running", "detail": ""}
        )

    def test_not_authorized_is_denied(self) -> None:
        for number in ("-1743", "-1744"):
            with self.subTest(number=number):
                result = self.outcome(1, err=_DENIED.format(number))
                self.assertEqual(result["outcome"], "denied")
                self.assertIn(number, result["detail"])

    def test_an_event_that_timed_out_is_timed_out(self) -> None:
        result = self.outcome(1, err=_NO_ANSWER)
        self.assertEqual(result["outcome"], "timed-out")
        self.assertIn("-1712", result["detail"])

    def test_a_probe_that_outlives_its_bound_is_timed_out(self) -> None:
        expired = subprocess.TimeoutExpired(["osascript"], 150.0)
        self.assertEqual(
            grant_probe.probe(_raises(expired)),
            {"outcome": "timed-out", "detail": "osascript did not finish in 150 s"},
        )

    def test_any_other_failure_is_an_error_with_its_first_line(self) -> None:
        result = self.outcome(1, err="0:5: syntax error: invented. (-2741)\nmore\n")
        self.assertEqual(
            result,
            {"outcome": "error", "detail": "0:5: syntax error: invented. (-2741)"},
        )

    def test_a_failure_that_says_nothing_names_its_exit(self) -> None:
        self.assertEqual(
            self.outcome(3), {"outcome": "error", "detail": "osascript exited 3"}
        )

    def test_an_error_number_inside_the_text_is_not_the_ending(self) -> None:
        result = self.outcome(1, err="about (-1743) but then something else\n")
        self.assertEqual(result["outcome"], "error")

    def test_an_osascript_that_cannot_start_is_an_error(self) -> None:
        missing = FileNotFoundError(2, "No such file or directory", "osascript")
        self.assertEqual(
            grant_probe.probe(_raises(missing)),
            {
                "outcome": "error",
                "detail": "could not run osascript (FileNotFoundError)",
            },
        )


class MainTest(unittest.TestCase):
    """`--result FILE` writes the outcome as one JSON document, replaced in one step."""

    def setUp(self) -> None:
        scratch = TemporaryDirectory()
        self.addCleanup(scratch.cleanup)
        self.folder = Path(scratch.name)
        self.result = self.folder / "result.json"

    def run_main(self, *argv: str, run: grant_probe.RunFn) -> tuple[int, str, str]:
        """Run the probe's command line in-process, uncolored, with a fake osascript."""
        out, err = io.StringIO(), io.StringIO()
        with (
            mock.patch.dict(os.environ, {"NO_COLOR": "1"}),
            contextlib.redirect_stdout(out),
            contextlib.redirect_stderr(err),
        ):
            for forcing in ("FORCE_COLOR", "PYTHON_COLORS"):
                os.environ.pop(forcing, None)
            try:
                code = grant_probe.main(list(argv), prog="grant_probe", run=run)
            except SystemExit as stopped:
                code = int(stopped.code or 0)
        return code, out.getvalue(), err.getvalue()

    def test_the_result_file_holds_the_outcome_and_its_detail(self) -> None:
        run, _ = _answers(0, "stopped\n")
        code, out, err = self.run_main("--result", str(self.result), run=run)
        self.assertEqual((code, out, err), (0, "granted: stopped\n", ""))
        self.assertEqual(
            json.loads(self.result.read_text(encoding="utf-8")),
            {"outcome": "granted", "detail": "stopped"},
        )
        self.assertEqual(
            [entry.name for entry in self.folder.iterdir()], ["result.json"]
        )

    def test_an_earlier_result_is_replaced(self) -> None:
        self.result.write_text("stale", encoding="utf-8", newline="\n")
        run, _ = _answers(1, err=_DENIED.format("-1743"))
        self.assertEqual(self.run_main("--result", str(self.result), run=run)[0], 0)
        document = json.loads(self.result.read_text(encoding="utf-8"))
        self.assertEqual(document["outcome"], "denied")

    def test_only_its_user_may_read_the_result(self) -> None:
        run, _ = _answers(0, "playing\n")
        self.run_main("--result", str(self.result), run=run)
        self.assertEqual(self.result.stat().st_mode & 0o777, 0o600)

    def test_a_result_that_cannot_be_written_is_one_error_line_and_exit_1(self) -> None:
        run, _ = _answers(0, "playing\n")
        absent = self.folder / "absent" / "result.json"
        code, out, err = self.run_main("--result", str(absent), run=run)
        self.assertEqual((code, out), (1, ""))
        self.assertTrue(err.startswith("ERROR: could not write the result ("), err)
        self.assertEqual(err.count("\n"), 1)
        self.assertNotIn(str(self.folder), err)

    def test_the_result_file_is_required(self) -> None:
        run, calls = _answers(0, "playing\n")
        code, _, err = self.run_main(run=run)
        self.assertEqual(code, 2)
        self.assertIn("--result", err)
        self.assertEqual(calls, [])

    def test_help_states_what_it_needs_and_that_it_changes_nothing(self) -> None:
        run, calls = _answers(0, "playing\n")
        code, out, _ = self.run_main("--help", run=run)
        self.assertEqual(code, 0)
        self.assertIn("usage: grant_probe", out)
        self.assertIn("Prerequisites", out)
        self.assertEqual(calls, [])

    def test_the_program_name_defaults_to_argv0(self) -> None:
        with mock.patch.object(sys, "argv", ["renamed-probe"]):
            self.assertEqual(grant_probe.build_parser().prog, "renamed-probe")


if __name__ == "__main__":
    unittest.main()
