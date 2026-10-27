"""The real album-tag reader: mutagen present, absent, and a tag that cannot be read.

The tags are written by mutagen itself into placeholder files under a temporary
directory, so the reader is exercised against real ID3 bytes and no real music.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock

from mutagen.id3 import ID3, TALB, TIT2

_HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(_HERE), str(_HERE.parent)]

import tag_refresh as amr  # noqa: E402 - import follows the sys.path bootstrap above
import cli_fixtures as cf  # noqa: E402 - import follows the sys.path bootstrap above


class TagReaderTest(cf.CliCase):
    """What the reader returns for each kind of file."""

    def tagged(self, name: str, *frames: object) -> Path:
        """An empty file given an ID3 tag holding *frames*."""
        path = self.touch(name, b"")
        tags = ID3()
        for frame in frames:
            tags.add(frame)
        tags.save(path)
        return path

    def reader(self) -> amr.refresh_core.TagReader:
        """The real reader; mutagen is installed wherever this suite runs."""
        found = amr.load_tag_reader()
        assert found is not None, "mutagen imports here"
        return found

    def test_the_album_tag_is_read(self) -> None:
        path = self.tagged("a.mp3", TALB(encoding=3, text=["Invented Album"]))
        self.assertEqual(self.reader()(path), "Invented Album")

    def test_the_first_of_several_album_values_is_read(self) -> None:
        path = self.tagged("a.mp3", TALB(encoding=3, text=["One", "Two"]))
        self.assertEqual(self.reader()(path), "One")

    def test_a_tag_with_no_album_frame_reads_none(self) -> None:
        path = self.tagged("a.mp3", TIT2(encoding=3, text=["A Title"]))
        self.assertIsNone(self.reader()(path))

    def test_an_album_frame_with_no_text_reads_none(self) -> None:
        path = self.tagged("a.mp3", TALB(encoding=3, text=[]))
        self.assertIsNone(self.reader()(path))

    def test_a_placeholder_with_no_tag_reads_none(self) -> None:
        self.assertIsNone(self.reader()(self.touch("a.mp3", b"")))

    def test_a_missing_file_reads_none(self) -> None:
        self.assertIsNone(self.reader()(self.root / "gone.mp3"))

    def test_a_folder_reads_none(self) -> None:
        self.assertIsNone(self.reader()(self.root))

    def test_no_mutagen_means_no_reader(self) -> None:
        with mock.patch.dict(sys.modules, {"mutagen": None, "mutagen.id3": None}):
            self.assertIsNone(amr.load_tag_reader())


if __name__ == "__main__":
    unittest.main()
