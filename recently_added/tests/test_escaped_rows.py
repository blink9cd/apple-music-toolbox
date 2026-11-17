"""A name holding a delimiter reads back whole, and can forge no row of its own.

The query escapes each tab, line break, U+001F and percent sign in an album artist or
album, and the parser undoes it after the row's three fields are split. This tool keeps
its own copy of the shared escape, because media_feeds imports it from a toolbox whose
other folders it never checks, so the copy is pinned here to the one tag_refresh's
``src/script_text.py`` holds. Every test drives a fake `run`; nothing here spawns a
process or touches Music.app.
"""

from __future__ import annotations

import datetime as dt
import subprocess
import sys
import unittest
from pathlib import Path

from hypothesis import given
from hypothesis import strategies as st

_TOOL = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_TOOL))
sys.path.insert(0, str(_TOOL.parent / "tag_refresh" / "src"))
sys.path.insert(0, str(_TOOL / "tests"))

import _recently_added_fuzz_profile  # noqa: E402, F401 - loads the deterministic profile before any @given
import recently_added  # noqa: E402 - import follows the sys.path bootstrap above
import script_text  # noqa: E402 - import follows the sys.path bootstrap above
from recently_added import (  # noqa: E402 - import follows the sys.path bootstrap above
    AlbumRef,
    newest_albums_from_music,
)

#: The reference day every test injects, far from any date these tests run on.
_TODAY = dt.date(2000, 6, 15)
#: What the query writes for each character it escapes.
_ESCAPED = {char: f"%{ord(char):02X}" for char in "%\x1f\t\n\r"}
#: Text rich in what the escape turns on, mixed with any character at all.
_RICH_TEXT = st.text(alphabet=st.sampled_from("%\t\n\r\x1f0129ADF") | st.characters())


def _escaped(text: str) -> str:
    """*text* with each character the query escapes replaced by its escape."""
    return "".join(_ESCAPED.get(char, char) for char in text)


def _answering(stdout: str) -> recently_added.Runner:
    """A fake `run` whose Music.app prints exactly *stdout*."""

    def run(_args: list[str], _timeout: float) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(["osascript"], 0, stdout, "")

    return run


class SharedEscapeTest(unittest.TestCase):
    """This tool's copy of the escape is the shared one, and its query uses it."""

    def test_the_handler_is_the_shared_text(self) -> None:
        self.assertEqual(recently_added._ESCAPE_HANDLER, script_text.ESCAPE_HANDLER)

    def test_the_query_opens_with_the_handler_and_escapes_both_names(self) -> None:
        script = recently_added._MUSIC_SCRIPT
        self.assertTrue(script.startswith(recently_added._ESCAPE_HANDLER))
        self.assertIn(
            " & tab & (my escapedText(album artist of t))"
            " & tab & (my escapedText(album of t)) & linefeed",
            script,
        )

    def test_the_escapes_are_the_shared_ones(self) -> None:
        self.assertEqual(dict(recently_added._ESCAPES), dict(script_text.ESCAPES))

    @given(_RICH_TEXT)
    def test_the_decoder_agrees_with_the_shared_one(self, text: str) -> None:
        self.assertEqual(
            recently_added._unescape_field(text), script_text.unescape_field(text)
        )


class EscapedRowTest(unittest.TestCase):
    """Escaped names read back whole; a row inside a name stays inside it."""

    def test_names_holding_each_delimiter_read_back_exactly(self) -> None:
        artist, album = "The\tInvented\nQuartet", "Placeholder\x1fAlbum\r 100%"
        run = _answering(
            f"2000-06-01T10:00:00\t{_escaped(artist)}\t{_escaped(album)}\n"
        )
        refs = newest_albums_from_music(1, run=run, today=_TODAY)
        self.assertEqual(
            refs, [AlbumRef(artist=artist, album=album, added=dt.date(2000, 6, 1))]
        )

    def test_a_row_inside_an_album_name_forges_none(self) -> None:
        # Unescaped, this album's line break ended its row, and the date, artist and
        # album after it read as a row of their own, all of its author's choosing.
        album = "Real Album\n2000-06-14T10:00:00\tForged Artist\tForged Album"
        run = _answering(
            f"2000-06-01T10:00:00\tThe Invented Quartet\t{_escaped(album)}\n"
            "2000-05-01T10:00:00\tArtist A\tAn Album\n"
        )
        refs = newest_albums_from_music(5, run=run, today=_TODAY)
        self.assertNotIn("Forged Artist", [ref.artist for ref in refs])
        self.assertEqual([ref.album for ref in refs], [album, "An Album"])


if __name__ == "__main__":
    unittest.main()
