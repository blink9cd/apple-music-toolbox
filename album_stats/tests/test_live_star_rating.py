"""One live call against the real Music.app, for the star-rating script.

`test_star_rating.py` fakes the `run` seam, which pins the rating script's text and
nothing about whether Music.app accepts it. The one failure that text cannot show is
Music's scripting dictionary rejecting the script at runtime (the `-10003 Access not
allowed` dictionary-collision error; album_stats.md, "Why a `whose` clause, and not a
loop"), so this file sends the rating script once, for real, and requires an answer.

The live test is run by hand against a real library, and runs only when every one of these
holds, and skips otherwise:

- the platform is macOS, where Music.app and `osascript` exist;
- `APPLE_MUSIC_TOOLBOX_OFFLINE` is unset: the project's "no Music.app, no network"
  switch, which the export sets on every run of its suite, alongside a fake
  `osascript`;
- Music.app is already running, asked in a way that never launches it.

The environment checks are class decorators, so an offline run never reaches the probe.

The probe asks `application "Music" is running`, which names Music outside any `tell`
block. A `tell application "Music"` block launches the application to deliver its
event, so a probe written that way would start Music.app on a host where it was not
running, which is the one thing a skip must not do. The `running` property is answered
by the system without sending Music an event. Only a reply of exactly `true` counts as
running; a failed call, a timeout, an absent `osascript`, or any other reply is a skip.
`NoLaunchProbeTest` pins that against a fake `run` seam, so it runs everywhere, offline
included, and never reaches `osascript`.

Whether Music.app is running is decided by that separate probe, not by the subject:
`album_facts` swallows every failure by contract, so a `None` from it cannot tell
"Music.app is not there" from "the script was refused", and telling those apart is the
reason this file exists. The probe calls `_real_run` directly, which does not swallow.

The album is not hardcoded, because any one name is a fact of one library. It is the
album Music.app itself reports as most recently added, so it exists: a `None` for it
means the rating script failed, not that the album is missing. `min_stars=1` asks for
any user rating at all, and an album with none still answers `favorited=0`, so the
test needs no rated tracks. No assertion message echoes the album's name, and the
script asks for counts only, never a title.
"""

from __future__ import annotations

import os
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from album_stats import AlbumFacts, album_facts  # noqa: E402 - import follows the sys.path bootstrap above
from recently_added import (  # noqa: E402 - import follows the sys.path bootstrap above
    _real_run,
    newest_albums_from_music,
)

#: This module, for the probe tests that swap its `_real_run` for a fake.
_THIS_MODULE = sys.modules[__name__]

#: The project's offline switch, shared with the toolbox's other live tests.
_OFFLINE_ENV = "APPLE_MUSIC_TOOLBOX_OFFLINE"

#: Bounds each scanning call: a `whose` clause visits every track in the library,
#: which takes many seconds on a large one. A short bound would misreport a slow but
#: working query as a refused script, since both answer `None`.
_SCANNING_TIMEOUT_SECONDS = 60.0

#: The probe scans nothing, so it gets a far tighter bound of its own.
_PROBE_TIMEOUT_SECONDS = 10.0

#: Whether Music.app is running, asked without launching it: Music is named outside any
#: `tell` block, so no event is sent to it (see the module docstring).
_PROBE_SCRIPT = 'application "Music" is running'

#: The probe's one reply that means running; anything else is a skip.
_RUNNING_REPLY = "true"

#: Any user rating at all qualifies, so the album needs no rated tracks.
_MIN_STARS = 1


def _music_is_running() -> bool:
    """True only when Music.app is already running, asked without launching it.

    A non-zero exit, an `OSError`, a timeout, or any reply but `true` counts as not
    running, so the live test skips rather than reaching for Music.app. `_real_run` is
    looked up at call time, which is what lets `NoLaunchProbeTest` swap in a fake.
    """
    try:
        result = _real_run(["osascript", "-e", _PROBE_SCRIPT], _PROBE_TIMEOUT_SECONDS)
    except (OSError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0 and result.stdout.strip() == _RUNNING_REPLY


@unittest.skipUnless(sys.platform == "darwin", "Music.app is macOS-only")
@unittest.skipIf(
    _OFFLINE_ENV in os.environ, f"{_OFFLINE_ENV} is set - live rating query skipped"
)
class LiveStarRatingTest(unittest.TestCase):
    """Music.app answers the star-rating script for an album it named itself."""

    def setUp(self) -> None:
        """Skip unless Music.app is running; the probe never launches it."""
        if not _music_is_running():
            self.skipTest("Music.app is not running")

    def test_the_rating_script_answers_for_the_newest_album(self) -> None:
        refs = newest_albums_from_music(1, timeout=_SCANNING_TIMEOUT_SECONDS)
        if not refs:
            self.skipTest("Music.app is running but names no recently added album")
        ref = refs[0]
        facts = album_facts(
            ref.artist,
            ref.album,
            timeout=_SCANNING_TIMEOUT_SECONDS,
            min_stars=_MIN_STARS,
        )
        # Music.app is running and named this exact album, so None here means the
        # rating script itself failed: refused by the dictionary (-10003), a clause
        # Music no longer accepts, or a reply that no longer parses.
        self.assertIsInstance(
            facts,
            AlbumFacts,
            "Music.app named an album but the star-rating script got no answer for"
            " it: the rating clause did not compile or run against Music.app",
        )
        assert facts is not None  # narrows for mypy; assertIsInstance does not
        self.assertGreater(facts.tracks, 0)
        self.assertGreaterEqual(facts.favorited, 0)
        self.assertLessEqual(facts.favorited, facts.tracks)


#: The one call `_music_is_running` makes, in full: Music named outside any `tell`.
_PROBE_ARGV = ["osascript", "-e", 'application "Music" is running']


class _RecordingRun:
    """A fake `run` seam that records every argv and answers one fixed result."""

    def __init__(self, returncode: int = 0, stdout: str = "", error: bool = False):
        self.calls: list[list[str]] = []
        self._returncode = returncode
        self._stdout = stdout
        self._error = error

    def __call__(
        self, args: list[str], timeout: float
    ) -> subprocess.CompletedProcess[str]:
        self.calls.append(list(args))
        if self._error:
            raise OSError("no osascript here")
        return subprocess.CompletedProcess(args, self._returncode, self._stdout, "")


class NoLaunchProbeTest(unittest.TestCase):
    """The running check asks without launching Music.app, and gates the live test.

    Runs everywhere, offline included: every call goes to a fake `run` seam, so
    nothing here reaches `osascript` or Music.app.
    """

    def _probe(self, run: _RecordingRun) -> bool:
        with mock.patch.object(_THIS_MODULE, "_real_run", run):
            return _music_is_running()

    def test_the_probe_names_music_outside_any_tell_block(self) -> None:
        # A `tell application "Music"` block launches Music.app to deliver its
        # event; the `running` property is answered without sending Music one.
        run = _RecordingRun(stdout="false\n")
        self._probe(run)
        self.assertEqual(run.calls, [_PROBE_ARGV])
        self.assertNotIn("tell", run.calls[0][-1])

    def test_a_running_music_answers_true(self) -> None:
        self.assertIs(self._probe(_RecordingRun(stdout="true\n")), True)

    def test_a_music_that_is_not_running_answers_false(self) -> None:
        self.assertIs(self._probe(_RecordingRun(stdout="false\n")), False)

    def test_an_unexpected_reply_is_not_running(self) -> None:
        self.assertIs(self._probe(_RecordingRun(stdout="")), False)

    def test_a_failed_probe_is_not_running(self) -> None:
        self.assertIs(self._probe(_RecordingRun(returncode=1)), False)

    def test_an_absent_osascript_is_not_running(self) -> None:
        self.assertIs(self._probe(_RecordingRun(error=True)), False)

    def test_a_timed_out_probe_is_not_running(self) -> None:
        def expire(args: list[str], timeout: float) -> subprocess.CompletedProcess[str]:
            raise subprocess.TimeoutExpired(args, timeout)

        with mock.patch.object(_THIS_MODULE, "_real_run", expire):
            self.assertIs(_music_is_running(), False)

    def test_the_live_test_skips_before_any_other_call(self) -> None:
        # setUp runs directly, past the class's own skip decorators, so this holds
        # offline too. A Music.app that is not running gets the probe and nothing
        # else: no album query and no rating query, either of which would launch it.
        run = _RecordingRun(stdout="false\n")
        refuse = mock.Mock(side_effect=AssertionError("Music.app was queried"))
        case = LiveStarRatingTest("test_the_rating_script_answers_for_the_newest_album")
        with (
            mock.patch.object(_THIS_MODULE, "_real_run", run),
            mock.patch.object(_THIS_MODULE, "newest_albums_from_music", refuse),
            mock.patch.object(_THIS_MODULE, "album_facts", refuse),
            self.assertRaisesRegex(unittest.SkipTest, "not running"),
        ):
            case.setUp()
        self.assertEqual(run.calls, [_PROBE_ARGV])
        refuse.assert_not_called()


if __name__ == "__main__":
    unittest.main()
