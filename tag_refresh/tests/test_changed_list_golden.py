"""hand_off_fakes: the copy of album's list writer makes album's golden bytes.

`hand_off_fakes` copies the writer from lyricsmith's ``album/src/lyrics_changed.py``,
which lives in another project, so nothing imports one from the other. This suite and
lyricsmith's ``album/tests/test_lyrics_changed_golden.py`` each pin the same literal
corpus, output bytes and left-out reasons: lyricsmith's against its writer, this one
against the copy. A change to album's format fails there until its literal changes, and
the twin literal here must then change with it, which fails here until the copy does.
The corpus covers every rule: a carriage return inside a name is written, a path
breaking two rules takes the first rule's reason, and a path is judged as normalized
but named as given. Every path is invented.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(_HERE), str(_HERE.parent / "src")]

import hand_off_fakes  # noqa: E402 - import follows the sys.path bootstrap above

#: The golden corpus, in the order it is handed to the writer. lyricsmith's
#: ``test_lyrics_changed_golden.py`` holds a twin of this tuple and of the two literals
#: below: change all of them together.
GOLDEN_PATHS = (
    "/music/Artist/Album/01 Track.mp3",
    "/music/Artist/Album/./CD2/../02 Track.mp3",
    "/music/Artist/Album/01 Track.mp3",
    "/music/Artist/Café/03 Track.mp3",
    "/music/Artist/Album/04\nTrack.mp3",
    "/music/Artist/Album/05 Track.mp3\r",
    "/music/Artist/Album/06\x00Track.mp3",
    "/music/Artist/Album/07 Track\udcff.mp3",
    "Album/./08 Track.mp3",
    "Album/./08 Track.mp3",
    "/music/Artist/Album/09\rTrack.mp3",
    "/music/Artist/Album/10 Track\r/.",
    "Album/11\x00Track.mp3",
    "/music/Artist/Album/12\n\x00Track.mp3",
    "/music/Artist/Album/13\x00Track.mp3\r",
    "/music/Artist/Album/14 Track\udcff.mp3\r",
    "Album/15 Track\udcff.mp3",
)

#: The exact file bytes album's writer makes of `GOLDEN_PATHS`.
GOLDEN_BYTES = (
    b"/music/Artist/Album/01 Track.mp3\n"
    b"/music/Artist/Album/02 Track.mp3\n"
    b"/music/Artist/Caf\xc3\xa9/03 Track.mp3\n"
    b"/music/Artist/Album/09\rTrack.mp3\n"
)

#: Each path of `GOLDEN_PATHS` left out, as it was given, with the exact reason text.
GOLDEN_LEFT_OUT = (
    (
        "/music/Artist/Album/04\nTrack.mp3",
        "holds a linefeed, which would split it into two lines",
    ),
    (
        "/music/Artist/Album/05 Track.mp3\r",
        "ends in a carriage return, which reads as a CRLF line ending",
    ),
    ("/music/Artist/Album/06\x00Track.mp3", "holds a NUL"),
    ("/music/Artist/Album/07 Track\udcff.mp3", "is not UTF-8"),
    ("Album/./08 Track.mp3", "is not an absolute path"),
    (
        "/music/Artist/Album/10 Track\r/.",
        "ends in a carriage return, which reads as a CRLF line ending",
    ),
    ("Album/11\x00Track.mp3", "holds a NUL"),
    (
        "/music/Artist/Album/12\n\x00Track.mp3",
        "holds a linefeed, which would split it into two lines",
    ),
    ("/music/Artist/Album/13\x00Track.mp3\r", "holds a NUL"),
    (
        "/music/Artist/Album/14 Track\udcff.mp3\r",
        "ends in a carriage return, which reads as a CRLF line ending",
    ),
    ("Album/15 Track\udcff.mp3", "is not UTF-8"),
)


class GoldenFormatTest(unittest.TestCase):
    """The copied writer turns the golden corpus into album's golden output."""

    def setUp(self) -> None:
        """Format the golden corpus once per test."""
        self.data, self.left = hand_off_fakes.format_changed_list(GOLDEN_PATHS)

    def test_the_bytes_written_are_the_golden_bytes(self) -> None:
        self.assertEqual(self.data, GOLDEN_BYTES)

    def test_the_paths_left_out_and_their_reasons_are_the_golden_ones(self) -> None:
        got = tuple((item.path, item.reason) for item in self.left)
        self.assertEqual(got, GOLDEN_LEFT_OUT)

    def test_no_paths_make_an_empty_file(self) -> None:
        self.assertEqual(hand_off_fakes.format_changed_list(()), (b"", ()))
