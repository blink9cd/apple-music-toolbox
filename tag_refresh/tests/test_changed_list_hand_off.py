"""The hand-off: a list lyricsmith's album writes is read cleanly by ``--tracks-from``.

album lives in another project, so the list is written by `hand_off_fakes`, a copy of
album's own writer, naming the tracks an album run saves on an album of placeholder
MP3s built under the test's own directory. It is then handed to this tool's entry point
with the fake Music.app, so nothing reaches Music.app, osascript, a real library or the
network. This reader owns the list file contract, so the hand-off is proven here, and
album's suites stay free of this macOS-only tool.

The property half holds the writer to the reader for any path at all: whatever
the formatter writes, `refresh_core.parse_list` reads back exactly and with no problem,
and whatever it leaves out is a path the reader could not have read back.
"""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

_HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(_HERE), str(_HERE.parent / "src")]

import cli_fixtures as cf  # noqa: E402 - import follows the sys.path bootstrap above

# Named as album's own writer module, which the fake copies, so each call reads as album's.
import hand_off_fakes as lyrics_changed  # noqa: E402 - follows the bootstrap above
import refresh_core  # noqa: E402 - import follows the sys.path bootstrap above
import refresh_fixtures as rf  # noqa: E402 - import follows the sys.path bootstrap above

settings.register_profile(
    "fuzz_gate_deterministic",
    derandomize=True,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow],
)
settings.load_profile("fuzz_gate_deterministic")

#: This tool's clean exit.
_OK = 0
#: The album's folder name, which is also the album name the fake Music files it under.
_ALBUM = lyrics_changed.ALBUM
#: Any text, lone surrogates included, as a path decoded from bytes that are not
#: UTF-8 holds them.
_ANY_TEXT = st.text(alphabet=st.characters(exclude_categories=()))


class HandOffTest(rf.TreeCase):
    """album's list, read by ``--tracks-from``, names exactly what it changed."""

    def setUp(self) -> None:
        """Build the album and write the list album's run on it writes."""
        super().setUp()
        self.keeper, self.orchard, self.mill = lyrics_changed.build_album(self.root)
        self.album = self.root / _ALBUM
        self.listed = lyrics_changed.write_changed_list(
            self.root / "changed.txt", (self.keeper, self.orchard)
        )
        # Music holds every track of the album, the unchanged one too.
        tracks = (self.keeper, self.orchard, self.mill)
        self.music = cf.FakeMusic(
            tracks=[
                cf.Track(n, cf.pid(n), _ALBUM, path)
                for n, path in enumerate(tracks, start=1)
            ]
        )

    def test_a_dry_run_reads_the_list_cleanly_and_would_refresh_the_changed(
        self,
    ) -> None:
        argv = ["--dry-run", "--tracks-from", str(self.listed)]
        result = cf.run_main(argv, cf.wiring(self.music))
        self.assertEqual(result.code, _OK, result.stderr)
        # Progress only: no line of the list was skipped.
        self.assertNotIn("--tracks-from", result.stderr)
        self.assertEqual(
            result.stderr.splitlines(),
            [f"album 1/2: {self.album}", f"album 2/2: {self.album / 'CD2'}"],
        )
        self.assertEqual(
            result.stdout,
            f"{self.album}: would refresh 1\n"
            f"{self.album / 'CD2'}: would refresh 1\n"
            "total: would refresh 2, not in Music 0, stale 0, errors 0, stopped 0"
            " (album folders 2, MP3s 2)\n",
        )
        self.assertNotIn(cf.REFRESH_IDS, self.music.kinds())

    def test_the_refresh_it_would_make_is_of_the_changed_tracks_alone(self) -> None:
        result = cf.run_main(["--tracks-from", str(self.listed)], cf.wiring(self.music))
        self.assertEqual(result.code, _OK, result.stderr)
        self.assertEqual(
            self.music.args_of(cf.REFRESH_IDS),
            [["1", cf.pid(1)], ["2", cf.pid(2)]],
        )


class WriterMeetsReaderTest(unittest.TestCase):
    """Everything the formatter writes, the reader reads; nothing it leaves out could be."""

    @given(st.lists(st.one_of(_ANY_TEXT, _ANY_TEXT.map(lambda text: "/" + text))))
    def test_every_written_line_parses_and_every_left_out_path_would_not(
        self, paths: list[str]
    ) -> None:
        data, left = lyrics_changed.format_changed_list(paths)
        parsed = refresh_core.parse_list(data, "changed.txt")
        self.assertEqual(parsed.problems, ())
        written = data.decode("utf-8").split("\n")[:-1] if data else []
        self.assertEqual([str(path) for _, path in parsed.paths], written)
        for item in left:
            alone = os.path.normpath(item.path).encode("utf-8", "surrogatepass")
            reread = refresh_core.parse_list(alone + b"\n", "changed.txt")
            read_back = [str(path) for _, path in reread.paths]
            self.assertFalse(
                not reread.problems and read_back == [os.path.normpath(item.path)]
            )
