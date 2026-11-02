"""The AppleScript calls tag_refresh makes, driven through a fake runner.

Every test here hands `music_calls` a fake runner that records each argv and answers
with a canned `CompletedProcess`; nothing spawns a real `osascript`, so nothing can
reach Music.app, the library or the host. The scripts are checked as text (no name
ever inside a body, the in-script bound present, no `tell` in the probe) and every
call's success, failure, timeout and garbage-reply branch is driven. The track-level
calls (the lookup by album names and the refresh by id) are in
`test_music_calls_tracks.py`.
"""

from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import music_calls  # noqa: E402 - import follows the sys.path bootstrap above

# The scripts that address Music.app, each of which must hold the in-script bound.
_MUSIC_SCRIPTS = (
    music_calls.COUNT_SCRIPT,
    music_calls.COUNT_TRACKS_SCRIPT,
    music_calls.REFRESH_RANGE_SCRIPT,
    music_calls.LOOKUP_SCRIPT,
    music_calls.REFRESH_IDS_SCRIPT,
)

# What osascript writes to stderr when one Apple event outlives the in-script bound.
_IN_SCRIPT_TIMEOUT_STDERR = (
    "0:120: execution error: Music got an error: AppleEvent timed out. (-1712)\n"
)


class FakeRunner:
    """A `Runner` that records every call and answers with one canned result.

    `answer` is either a `CompletedProcess` to return or an exception to raise,
    which is how a `bounded_run` kill (`subprocess.TimeoutExpired`) is simulated.
    """

    def __init__(
        self, answer: subprocess.CompletedProcess[str] | BaseException
    ) -> None:
        """Record nothing yet; answer every call with *answer*."""
        self.answer = answer
        self.calls: list[tuple[list[str], float]] = []

    def __call__(
        self, argv: list[str], timeout: float
    ) -> subprocess.CompletedProcess[str]:
        """Record the call, then return or raise the canned answer."""
        self.calls.append((list(argv), timeout))
        if isinstance(self.answer, BaseException):
            raise self.answer
        return self.answer


def completed(
    stdout: str = "", *, returncode: int = 0, stderr: str = ""
) -> subprocess.CompletedProcess[str]:
    """A finished `osascript` with the given streams and exit status."""
    return subprocess.CompletedProcess(
        args=["osascript"], returncode=returncode, stdout=stdout, stderr=stderr
    )


def stripped_lines(script: str) -> list[str]:
    """The lines of *script* without their indentation, for exact line assertions."""
    return [line.strip() for line in script.splitlines()]


def killed() -> subprocess.TimeoutExpired:
    """The exception `bounded_run` raises when its client-side bound kills the call."""
    return subprocess.TimeoutExpired(cmd=["osascript"], timeout=35.0)


class ScriptTextTest(unittest.TestCase):
    """The scripts as text: the bounds, and what the probe must not say."""

    def test_every_music_script_holds_the_in_script_timeout(self) -> None:
        bound = f"with timeout of {music_calls.IN_SCRIPT_TIMEOUT_SECONDS} seconds"
        for script in _MUSIC_SCRIPTS:
            with self.subTest(script=script.splitlines()[0]):
                self.assertIn(bound, script)
                self.assertIn("end timeout", script)
                self.assertIn('tell application "Music"', script)

    def test_the_probe_never_tells_music_anything(self) -> None:
        self.assertNotIn("tell", music_calls.IS_RUNNING_SCRIPT)
        self.assertEqual(
            music_calls.IS_RUNNING_SCRIPT, 'application "Music" is running'
        )

    def test_the_client_bound_outlasts_the_in_script_one(self) -> None:
        self.assertGreater(
            music_calls.CALL_TIMEOUT_SECONDS, music_calls.IN_SCRIPT_TIMEOUT_SECONDS
        )

    def test_scripts_that_take_values_read_them_from_argv(self) -> None:
        for script in (
            music_calls.REFRESH_RANGE_SCRIPT,
            music_calls.LOOKUP_SCRIPT,
            music_calls.REFRESH_IDS_SCRIPT,
        ):
            with self.subTest(script=script.splitlines()[0]):
                self.assertTrue(script.startswith("on run argv\n"))
                self.assertTrue(script.endswith("end run"))

    def test_the_refresh_by_id_re_raises_all_but_a_missing_track(self) -> None:
        # The whole re-raise line, not a fragment of it: the `on error errorText number
        # errorNumber` header alone holds "error errorText number errorNumber", so a
        # fragment passes with the re-raise deleted. Only -1728 (no such track) is
        # counted stale; Music's -1712 and everything else ends the call.
        lines = stripped_lines(music_calls.REFRESH_IDS_SCRIPT)
        header = lines.index("on error errorText number errorNumber")
        self.assertEqual(
            lines[header + 1],
            "if errorNumber is not -1728 then error errorText number errorNumber",
        )
        self.assertEqual(lines[header + 2], "end try")

    def test_the_lookup_swallows_no_error_at_all(self) -> None:
        # A catch-all `try` around each row turned Music's -1728 on the old
        # `POSIX path of (location of ...)` form into "not in Music" for every track.
        # The one expected absence, a track with no file, is an explicit `if`.
        lines = stripped_lines(music_calls.LOOKUP_SCRIPT)
        for keyword in ("try", "on error", "end try"):
            with self.subTest(keyword=keyword):
                self.assertFalse(
                    [line for line in lines if line.startswith(keyword)], lines
                )


class IsRunningTest(unittest.TestCase):
    """The probe: true, false, and each way it cannot answer."""

    def test_true_is_running(self) -> None:
        run = FakeRunner(completed("true\n"))
        self.assertTrue(music_calls.is_running(run=run))
        self.assertEqual(
            run.calls,
            [
                (
                    ["osascript", "-e", music_calls.IS_RUNNING_SCRIPT],
                    music_calls.CALL_TIMEOUT_SECONDS,
                )
            ],
        )

    def test_false_is_not_running(self) -> None:
        self.assertFalse(music_calls.is_running(run=FakeRunner(completed("false\n"))))

    def test_a_reply_without_its_linefeed_still_reads(self) -> None:
        self.assertTrue(music_calls.is_running(run=FakeRunner(completed("true"))))

    def test_garbage_is_a_failed_call(self) -> None:
        for reply in ("", "yes\n", "true\nfalse\n", " true\n", "TRUE\n"):
            with self.subTest(reply=reply):
                with self.assertRaises(music_calls.CallFailed) as caught:
                    music_calls.is_running(run=FakeRunner(completed(reply)))
                self.assertIn("unexpected reply", caught.exception.reason)

    def test_a_non_zero_exit_is_a_failed_call_naming_stderr(self) -> None:
        run = FakeRunner(completed(returncode=1, stderr="  \nsome error (-1743)\n\n"))
        with self.assertRaises(music_calls.CallFailed) as caught:
            music_calls.is_running(run=run)
        self.assertEqual(caught.exception.reason, "some error (-1743)")

    def test_a_non_zero_exit_with_silent_stderr_names_the_status(self) -> None:
        with self.assertRaises(music_calls.CallFailed) as caught:
            music_calls.is_running(run=FakeRunner(completed(returncode=3)))
        self.assertEqual(caught.exception.reason, "osascript exited 3")

    def test_a_client_kill_is_a_timeout(self) -> None:
        with self.assertRaises(music_calls.CallTimedOut) as caught:
            music_calls.is_running(run=FakeRunner(killed()))
        self.assertIn("35", caught.exception.reason)

    def test_a_missing_osascript_is_a_failed_call(self) -> None:
        run = FakeRunner(FileNotFoundError(2, "No such file", "osascript"))
        with self.assertRaises(music_calls.CallFailed) as caught:
            music_calls.is_running(run=run)
        self.assertIn("could not start osascript", caught.exception.reason)

    def test_the_outcomes_are_distinct_and_share_a_base(self) -> None:
        self.assertTrue(issubclass(music_calls.CallFailed, music_calls.MusicCallError))
        self.assertTrue(
            issubclass(music_calls.CallTimedOut, music_calls.MusicCallError)
        )
        self.assertFalse(issubclass(music_calls.CallTimedOut, music_calls.CallFailed))
        self.assertFalse(issubclass(music_calls.CallFailed, music_calls.CallTimedOut))
        self.assertEqual(str(music_calls.CallFailed("why")), "why")


class CountTracksTest(unittest.TestCase):
    """The count of file tracks, strictly a decimal."""

    def test_a_count_reads_as_an_int(self) -> None:
        run = FakeRunner(completed("21000\n"))
        self.assertEqual(music_calls.count_file_tracks(run=run), 21000)
        self.assertEqual(
            run.calls,
            [
                (
                    ["osascript", "-e", music_calls.COUNT_SCRIPT],
                    music_calls.CALL_TIMEOUT_SECONDS,
                )
            ],
        )

    def test_zero_is_a_count(self) -> None:
        self.assertEqual(
            music_calls.count_file_tracks(run=FakeRunner(completed("0\n"))), 0
        )

    def test_garbage_is_a_failed_call(self) -> None:
        for reply in ("", "\n", "-1\n", "12.0\n", "1 2\n", "١٢\n", "7\n\n"):
            with self.subTest(reply=reply):
                with self.assertRaises(music_calls.CallFailed):
                    music_calls.count_file_tracks(run=FakeRunner(completed(reply)))

    def test_a_non_zero_exit_is_a_failed_call(self) -> None:
        run = FakeRunner(completed(returncode=1, stderr="boom (-1728)\n"))
        with self.assertRaises(music_calls.CallFailed) as caught:
            music_calls.count_file_tracks(run=run)
        self.assertEqual(caught.exception.reason, "boom (-1728)")

    def test_the_in_script_timeout_is_a_timeout(self) -> None:
        run = FakeRunner(completed(returncode=1, stderr=_IN_SCRIPT_TIMEOUT_STDERR))
        with self.assertRaises(music_calls.CallTimedOut) as caught:
            music_calls.count_file_tracks(run=run)
        self.assertIn("-1712", caught.exception.reason)

    def test_only_a_trailing_minus_1712_is_a_timeout(self) -> None:
        # The error number osascript reports ends its reason line; "(-1712)" quoted
        # earlier in the text (a track or album name, say) is not the error.
        for stderr in (
            'execution error: Can\'t get album "(-1712)". (-1728)\n',
            "execution error: AppleEvent timed out. (-1712)\nnot allowed (-1743)\n",
            "execution error: timed out. (-17120)\n",
        ):
            with self.subTest(stderr=stderr):
                run = FakeRunner(completed(returncode=1, stderr=stderr))
                with self.assertRaises(music_calls.CallFailed):
                    music_calls.count_file_tracks(run=run)

    def test_a_trailing_minus_1712_with_trailing_space_is_a_timeout(self) -> None:
        run = FakeRunner(completed(returncode=1, stderr="timed out. (-1712)  \n\n"))
        with self.assertRaises(music_calls.CallTimedOut):
            music_calls.count_file_tracks(run=run)

    def test_a_client_kill_is_a_timeout(self) -> None:
        with self.assertRaises(music_calls.CallTimedOut):
            music_calls.count_file_tracks(run=FakeRunner(killed()))


class RefreshRangeTest(unittest.TestCase):
    """A 1-based inclusive range, passed as argv after `--`."""

    def test_the_range_travels_as_argv(self) -> None:
        run = FakeRunner(completed("\n"))
        music_calls.refresh_range(501, 1000, run=run)
        self.assertEqual(
            run.calls,
            [
                (
                    [
                        "osascript",
                        "-e",
                        music_calls.REFRESH_RANGE_SCRIPT,
                        "--",
                        "501",
                        "1000",
                    ],
                    music_calls.CALL_TIMEOUT_SECONDS,
                )
            ],
        )

    def test_a_one_track_range_is_allowed(self) -> None:
        run = FakeRunner(completed(""))
        music_calls.refresh_range(7, 7, run=run)
        self.assertEqual(run.calls[0][0][-2:], ["7", "7"])

    def test_an_impossible_range_is_refused_before_any_call(self) -> None:
        for first, last in ((0, 5), (5, 4), (-1, 3)):
            with self.subTest(first=first, last=last):
                run = FakeRunner(completed(""))
                with self.assertRaises(ValueError):
                    music_calls.refresh_range(first, last, run=run)
                self.assertEqual(run.calls, [])

    def test_a_non_zero_exit_is_a_failed_call(self) -> None:
        run = FakeRunner(
            completed(returncode=1, stderr="Can't get file track 9 (-1728)")
        )
        with self.assertRaises(music_calls.CallFailed):
            music_calls.refresh_range(1, 9, run=run)

    def test_the_in_script_timeout_is_a_timeout(self) -> None:
        run = FakeRunner(completed(returncode=1, stderr=_IN_SCRIPT_TIMEOUT_STDERR))
        with self.assertRaises(music_calls.CallTimedOut):
            music_calls.refresh_range(1, 500, run=run)

    def test_a_client_kill_is_a_timeout(self) -> None:
        with self.assertRaises(music_calls.CallTimedOut):
            music_calls.refresh_range(1, 500, run=FakeRunner(killed()))


if __name__ == "__main__":
    unittest.main()
