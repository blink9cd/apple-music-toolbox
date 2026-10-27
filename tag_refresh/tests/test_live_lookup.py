"""One live, read-only lookup against the real Music.app, for the lookup's contract.

`test_music_calls_tracks.py` reads `LOOKUP_SCRIPT` as text and drives a fake runner,
which proves what this side sends and nothing about what Music answers. The lookup's
first form passed every one of those tests and returned NO rows live: inside
`tell application "Music"`, `POSIX path of (location of t)` went to Music as part of
the object specifier and Music answered -1728 for every track. Only a real call can
catch that class of defect, so this file makes exactly one.

**Read-only by construction.** It calls `is_running` (which never launches Music)
and `lookup_by_albums`, and never `refresh_range` or `refresh_ids`: refreshing the
real library is left to a person, never a test.

It runs only when every one of these holds, and skips otherwise:

- the platform is macOS, where Music.app and `osascript` exist;
- `APPLE_MUSIC_TOOLBOX_OFFLINE` is unset: the project's "no Music.app, no network" switch,
  which the export sets on every run of its suite, alongside a fake `osascript`;
- `TAG_REFRESH_LIVE_ALBUM` names an album folder, chosen by whoever runs
  this, whose folder name is the album's name in Music and which holds at least one
  MP3. No album is hardcoded, because any one name is a fact of one library;
- Music.app is running, asked through `is_running` itself.

The environment checks come first, so the gate and the export never spawn the probe.
"""

from __future__ import annotations

import os
import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import music_calls  # noqa: E402 - import follows the sys.path bootstrap above

# The album folder whoever runs this chose; its name is the album name looked up.
_ALBUM_ENV = "TAG_REFRESH_LIVE_ALBUM"
# The project's offline switch, shared with album_scan's live tests.
_OFFLINE_ENV = "APPLE_MUSIC_TOOLBOX_OFFLINE"

# The three fields of one row, each in the shape Music reports it.
_TRACK_ID = re.compile(r"[0-9]+")
_PERSISTENT_ID = re.compile(r"[0-9A-Fa-f]{16}")
_FIELDS_PER_ROW = 3


def _file_identities(folder: Path) -> set[tuple[int, int]]:
    """The (device, inode) of every MP3 directly inside *folder*."""
    return {
        (status.st_dev, status.st_ino)
        for status in (
            entry.stat()
            for entry in folder.iterdir()
            if entry.is_file() and entry.suffix.lower() == ".mp3"
        )
    }


def _matching_rows(reply: str, identities: set[tuple[int, int]]) -> list[str]:
    """The rows of *reply* that are well formed and name one of *identities*."""
    matches = []
    for row in reply.splitlines():
        fields = row.split("\t")
        if len(fields) != _FIELDS_PER_ROW:
            continue
        track_id, persistent_id, path = fields
        if _TRACK_ID.fullmatch(track_id) is None:
            continue
        if _PERSISTENT_ID.fullmatch(persistent_id) is None:
            continue
        try:
            status = os.stat(path)
        except OSError:
            continue
        if (status.st_dev, status.st_ino) in identities:
            matches.append(row)
    return matches


@unittest.skipUnless(sys.platform == "darwin", "Music.app is macOS-only")
@unittest.skipIf(
    _OFFLINE_ENV in os.environ, f"{_OFFLINE_ENV} is set - live lookup skipped"
)
@unittest.skipUnless(
    os.environ.get(_ALBUM_ENV), f"{_ALBUM_ENV} names no album folder - skipped"
)
class LiveLookupTest(unittest.TestCase):
    """The real lookup answers rows that name the files of the named album."""

    def setUp(self) -> None:
        """Skip unless Music.app is running; the probe never launches it."""
        try:
            running = music_calls.is_running(run=music_calls.real_run)
        except music_calls.MusicCallError as exc:
            self.skipTest(f"cannot ask whether Music.app is running: {exc.reason}")
        if not running:
            self.skipTest("Music.app is not running")

    def test_the_named_album_answers_rows_matching_its_files_by_inode(self) -> None:
        folder = Path(os.environ[_ALBUM_ENV])
        identities = _file_identities(folder)
        self.assertTrue(identities, f"{_ALBUM_ENV} names a folder holding no MP3")
        reply = music_calls.lookup_by_albums([folder.name], run=music_calls.real_run)
        rows = [row for row in reply.splitlines() if row]
        self.assertTrue(
            _matching_rows(reply, identities),
            f"none of the {len(rows)} row(s) Music answered names one of the"
            f" {len(identities)} MP3(s) in the folder by device and inode",
        )


if __name__ == "__main__":
    unittest.main()
