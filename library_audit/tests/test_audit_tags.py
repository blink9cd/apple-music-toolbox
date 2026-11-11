"""audit_tags: the grouping names and the numbers out of a file's tags, per format.

The pure half takes stand-ins for mutagen's tag objects, so every format's spelling is
driven without a real audio file of that format. The reader itself is driven once over
an invented MP3 holding nothing but an ID3 tag written here, and once with mutagen
made unimportable.
"""

from __future__ import annotations

import importlib.util
import struct
import sys
import unittest
import wave
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

_HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(_HERE), str(_HERE.parent / "src")]

import audit_fixtures as af  # noqa: E402 - import follows the sys.path bootstrap above
import audit_tags as at  # noqa: E402 - import follows the sys.path bootstrap above

_HAS_MUTAGEN = importlib.util.find_spec("mutagen") is not None


class ParseNumberPairTest(unittest.TestCase):
    """``n``, ``n/total`` and the spellings around them."""

    def test_each_spelling(self) -> None:
        cases = {
            "3/12": (3, 12),
            "3": (3, None),
            " 3 / 12 ": (3, 12),
            "3/": (3, None),
            "3/0": (3, None),
            "03/012": (3, 12),
        }
        for text, expected in cases.items():
            with self.subTest(text=text):
                self.assertEqual(at.parse_number_pair(text), expected)

    def test_text_holding_no_number_is_none(self) -> None:
        # "12345" is past any album's track count, and would make the gap check list
        # thousands of missing numbers for one stray tag.
        for text in ("", "x", "/12", "3/x", "three", "12345", "1/12345"):
            with self.subTest(text=text):
                self.assertIsNone(at.parse_number_pair(text))


def _read(tags: at.TagMapping) -> at.FileTags:
    """What *tags* says, which a tag object always does."""
    found = at.file_tags_from(tags)
    assert found is not None
    return found


class FileTagsFromTest(unittest.TestCase):
    """One reading for ID3 frames and MP4 atoms alike."""

    def test_id3_frames(self) -> None:
        tags = {
            "TRCK": af.Frame("2/5"),
            "TPOS": af.Frame("1/2"),
            "TPE2": af.Frame("The Placeholder Band"),
            "TALB": af.Frame("Invented Album"),
        }
        self.assertEqual(
            at.file_tags_from(tags),
            at.FileTags("The Placeholder Band", "Invented Album", 1, 2, 5),
        )

    def test_mp4_atoms(self) -> None:
        tags = {
            "trkn": [(4, 10)],
            "disk": [(2, 2)],
            "aART": ["The Made-Up Trio"],
            "\xa9alb": ["Second Invented Album"],
        }
        self.assertEqual(
            at.file_tags_from(tags),
            at.FileTags("The Made-Up Trio", "Second Invented Album", 2, 4, 10),
        )

    def test_the_compilation_flag_is_read_in_each_format(self) -> None:
        cases: tuple[tuple[dict[str, object], bool], ...] = (
            ({}, False),
            ({"TCMP": af.Frame("1")}, True),
            ({"TCMP": af.Frame(" 1 ")}, True),
            ({"TCMP": af.Frame("0")}, False),
            ({"TCMP": af.Frame()}, False),
            ({"cpil": True}, True),
            ({"cpil": False}, False),
            ({"cpil": [True]}, True),
            ({"cpil": []}, False),
        )
        for tags, expected in cases:
            with self.subTest(tags=tags):
                self.assertIs(_read(tags).compilation, expected)

    def test_the_artist_stands_in_for_an_absent_or_empty_album_artist(self) -> None:
        for album_artist in ({}, {"TPE2": af.Frame("")}, {"aART": [""]}):
            with self.subTest(album_artist=album_artist):
                tags = {"TPE1": af.Frame("Solo Placeholder"), **album_artist}
                self.assertEqual(_read(tags).artist, "Solo Placeholder")
        self.assertEqual(_read({"\xa9ART": ["Mp4 Solo"]}).artist, "Mp4 Solo")

    def test_absent_names_read_as_empty_text(self) -> None:
        self.assertEqual(
            at.file_tags_from({"TRCK": af.Frame("7")}), at.FileTags("", "", 1, 7, None)
        )

    def test_mp4_zero_total_is_no_total(self) -> None:
        self.assertEqual(_read({"trkn": [(4, 0)]}).total, None)

    def test_an_id3_track_zero_is_a_pregap_track(self) -> None:
        # MusicBrainz numbers a pregap ("hidden track one") track 0, and Picard writes it.
        self.assertEqual(
            _read({"TRCK": af.Frame("0/14")}), at.FileTags("", "", 1, 0, 14)
        )
        self.assertEqual(_read({"TRCK": af.Frame("0")}).track, 0)

    def test_an_mp4_track_zero_is_no_track_number(self) -> None:
        # iTunes stores a blank number beside a set total as (0, total).
        found = _read({"trkn": [(0, 12)]})
        self.assertIsNone(found.track)
        self.assertIsNone(found.total)

    def test_a_missing_disc_reads_as_disc_one(self) -> None:
        for disc in ({}, {"TPOS": af.Frame("0")}, {"TPOS": af.Frame("x")}):
            with self.subTest(disc=disc):
                tags = {"TRCK": af.Frame("7"), **disc}
                self.assertEqual(_read(tags).disc, 1)

    def test_tags_with_no_usable_track_number_read_with_track_none(self) -> None:
        # Read, but not numbered: the audit counts these apart from unreadable tags.
        cases: tuple[dict[str, object], ...] = (
            {},
            {"TRCK": af.Frame()},
            {"TRCK": af.Frame("x")},
            {"trkn": []},
            {"TRCK": "7"},  # a bare string, not a list of values
        )
        for tags in cases:
            with self.subTest(tags=tags):
                found = at.file_tags_from({"TALB": af.Frame("Invented Album"), **tags})
                assert found is not None
                self.assertIsNone(found.track)
                self.assertIsNone(found.total)
                self.assertEqual(found.album, "Invented Album")

    def test_no_tag_object_at_all_is_unreadable(self) -> None:
        self.assertIsNone(at.file_tags_from(None))

    def test_vorbis_spellings_are_no_longer_read(self) -> None:
        # No collected suffix carries Vorbis comments (Music.app imports no FLAC).
        self.assertIsNone(_read({"tracknumber": ["3"]}).track)


class LoadTagReaderTest(unittest.TestCase):
    """The real reader, and its absence when mutagen cannot be imported."""

    def test_without_mutagen_there_is_no_reader(self) -> None:
        with mock.patch.dict(sys.modules, {"mutagen": None}):
            self.assertIsNone(at.load_tag_reader())

    @unittest.skipUnless(_HAS_MUTAGEN, "mutagen is not installed")
    def test_an_mp3_holding_only_an_id3_tag_is_read(self) -> None:
        from mutagen.id3 import ID3, TALB, TPE1, TPOS, TRCK

        with TemporaryDirectory() as scratch:
            path = Path(scratch) / "01 invented.mp3"
            path.write_bytes(b"")
            tags = ID3()
            tags.add(TRCK(encoding=3, text="2/5"))
            tags.add(TPOS(encoding=3, text="1/1"))
            tags.add(TPE1(encoding=3, text="The Placeholder Band"))
            tags.add(TALB(encoding=3, text="Invented Album"))
            tags.save(path)
            reader = at.load_tag_reader()
            assert reader is not None
            self.assertEqual(
                reader(path),
                at.FileTags("The Placeholder Band", "Invented Album", 1, 2, 5),
            )

    @unittest.skipUnless(_HAS_MUTAGEN, "mutagen is not installed")
    def test_an_mp3_flagged_as_a_compilation_reads_as_one(self) -> None:
        from mutagen.id3 import ID3, TCMP, TRCK

        with TemporaryDirectory() as scratch:
            path = Path(scratch) / "01 invented.mp3"
            path.write_bytes(b"")
            tags = ID3()
            tags.add(TRCK(encoding=3, text="1"))
            tags.add(TCMP(encoding=3, text="1"))
            tags.save(path)
            reader = at.load_tag_reader()
            assert reader is not None
            found = reader(path)
            assert found is not None
            self.assertTrue(found.compilation)

    @unittest.skipUnless(_HAS_MUTAGEN, "mutagen is not installed")
    def test_an_mp3_whose_tag_has_no_track_number_reads_with_track_none(self) -> None:
        from mutagen.id3 import ID3, TALB

        with TemporaryDirectory() as scratch:
            path = Path(scratch) / "invented.mp3"
            path.write_bytes(b"")
            tags = ID3()
            tags.add(TALB(encoding=3, text="Invented Album"))
            tags.save(path)
            reader = at.load_tag_reader()
            assert reader is not None
            self.assertEqual(
                reader(path), at.FileTags("", "Invented Album", 1, None, None)
            )

    @unittest.skipUnless(_HAS_MUTAGEN, "mutagen is not installed")
    def test_another_format_is_read_through_format_detection(self) -> None:
        # A WAV of a few silent frames, made here, carrying an ID3 chunk.
        from mutagen.id3 import TRCK
        from mutagen.wave import WAVE

        with TemporaryDirectory() as scratch:
            path = Path(scratch) / "01 invented.wav"
            with wave.open(str(path), "wb") as out:
                out.setnchannels(1)
                out.setsampwidth(2)
                out.setframerate(8000)
                out.writeframes(b"\x00\x00" * 8)
            reader = at.load_tag_reader()
            assert reader is not None
            self.assertIsNone(reader(path), "a WAV with no tag object is unreadable")
            audio = WAVE(path)
            audio.add_tags()
            assert audio.tags is not None
            audio.tags.add(TRCK(encoding=3, text="3/9"))
            audio.save()
            self.assertEqual(reader(path), at.FileTags("", "", 1, 3, 9))

    @unittest.skipUnless(_HAS_MUTAGEN, "mutagen is not installed")
    def test_a_file_that_cannot_be_read_is_none(self) -> None:
        with TemporaryDirectory() as scratch:
            empty_mp3 = Path(scratch) / "empty.mp3"
            empty_mp3.write_bytes(b"")
            empty_m4a = Path(scratch) / "empty.m4a"
            empty_m4a.write_bytes(b"")
            garbage_m4a = Path(scratch) / "garbage.m4a"
            garbage_m4a.write_bytes(b"not really an mp4 container")
            reader = at.load_tag_reader()
            assert reader is not None
            for path in (
                empty_mp3,
                empty_m4a,
                garbage_m4a,
                Path(scratch) / "gone.mp3",
            ):
                with self.subTest(path=path.name):
                    self.assertIsNone(reader(path))

    @unittest.skipUnless(_HAS_MUTAGEN, "mutagen is not installed")
    def test_any_error_the_parser_raises_is_unreadable_not_a_crash(self) -> None:
        # Regression: mutagen has let struct.error, KeyError and IndexError escape on
        # crafted frames, which crashed the whole audit instead of listing one file.
        for error in (KeyError("TRCK"), struct.error("unpack"), IndexError("frame")):
            for name, target in (
                ("crafted.mp3", "mutagen.id3.ID3"),
                ("crafted.m4a", "mutagen.File"),
            ):
                with (
                    self.subTest(error=type(error).__name__, path=name),
                    mock.patch(target, side_effect=error),
                ):
                    reader = at.load_tag_reader()
                    assert reader is not None
                    self.assertIsNone(reader(Path("/invented") / name))


if __name__ == "__main__":
    unittest.main()
