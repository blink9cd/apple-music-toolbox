"""One live call against the real Music.app, for the star-rating script.

`test_star_rating.py` fakes the `run` seam, which pins the rating script's TEXT and
nothing about whether Music.app accepts it. The one failure that text cannot show is
Music's scripting dictionary rejecting the script at runtime -- the `-10003 Access not
allowed` dictionary-collision error (album_stats.md, "Why a `whose` clause, and not a
loop") -- so this file sends the rating script once, for real, and requires an answer.

Run by hand against a real library, never by the gate. It runs only when every one of
these holds, and skips otherwise:

- the platform is macOS, where Music.app and `osascript` exist;
- `APPLE_MUSIC_TOOLBOX_OFFLINE` is unset: the project's "no Music.app, no network"
  switch, which the export sets on every run of its suite, alongside a fake
  `osascript`;
- Music.app answers a minimal, read-only probe.

The environment checks are class decorators, so an offline run never reaches the probe.

Reachability is decided by that separate probe, not by the subject: `album_facts`
swallows every failure by contract, so a `None` from it cannot tell "Music.app is
unreachable" from "the script was refused" -- and telling those apart is the reason
this file exists. The probe calls `_real_run` directly, which does not swallow.

The album is not hardcoded, because any one name is a fact of one library. It is the
album Music.app itself reports as most recently added, so it EXISTS: a `None` for it
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

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from album_stats import AlbumFacts, album_facts  # noqa: E402 - import follows the sys.path bootstrap above
from recently_added import (  # noqa: E402 - import follows the sys.path bootstrap above
    _real_run,
    newest_albums_from_music,
)

#: The project's offline switch, shared with the toolbox's other live tests.
_OFFLINE_ENV = "APPLE_MUSIC_TOOLBOX_OFFLINE"

#: Bounds each SCANNING call: a `whose` clause visits every track in the library,
#: which takes many seconds on a large one. A short bound would misreport a slow but
#: working query as a refused script, since both answer `None`.
_SCANNING_TIMEOUT_SECONDS = 60.0

#: The probe scans nothing, so it gets a far tighter bound of its own.
_REACHABILITY_TIMEOUT_SECONDS = 10.0

#: Read-only and minimal: a bare count of one playlist, never a track dump.
_PROBE_SCRIPT = 'tell application "Music" to (count of tracks of library playlist 1)'

#: Any user rating at all qualifies, so the album needs no rated tracks.
_MIN_STARS = 1


def _music_is_reachable() -> bool:
    """True unless Music.app cannot answer the minimal probe.

    A non-zero exit, an `OSError` or a timeout means Music.app is absent, not running,
    not scriptable or denied automation, and only that counts as a skip.
    """
    try:
        result = _real_run(
            ["osascript", "-e", _PROBE_SCRIPT], _REACHABILITY_TIMEOUT_SECONDS
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0


@unittest.skipUnless(sys.platform == "darwin", "Music.app is macOS-only")
@unittest.skipIf(
    _OFFLINE_ENV in os.environ, f"{_OFFLINE_ENV} is set - live rating query skipped"
)
class LiveStarRatingTest(unittest.TestCase):
    """Music.app answers the star-rating script for an album it named itself."""

    def setUp(self) -> None:
        """Skip only for genuine unreachability, decided apart from the subject."""
        if not _music_is_reachable():
            self.skipTest("Music.app is not reachable on this host")

    def test_the_rating_script_answers_for_the_newest_album(self) -> None:
        refs = newest_albums_from_music(1, timeout=_SCANNING_TIMEOUT_SECONDS)
        if not refs:
            self.skipTest("Music.app is reachable but names no recently added album")
        ref = refs[0]
        facts = album_facts(
            ref.artist,
            ref.album,
            timeout=_SCANNING_TIMEOUT_SECONDS,
            min_stars=_MIN_STARS,
        )
        # Music.app is reachable and named this exact album, so None here means the
        # rating script itself failed: refused by the dictionary (-10003), a clause
        # Music no longer accepts, or a reply that no longer parses.
        self.assertIsInstance(
            facts,
            AlbumFacts,
            "Music.app named an album but the star-rating script got no answer for"
            " it -- the rating clause did not compile or run against Music.app",
        )
        assert facts is not None  # narrows for mypy; assertIsInstance does not
        self.assertGreater(facts.tracks, 0)
        self.assertGreaterEqual(facts.favorited, 0)
        self.assertLessEqual(facts.favorited, facts.tracks)


if __name__ == "__main__":
    unittest.main()
