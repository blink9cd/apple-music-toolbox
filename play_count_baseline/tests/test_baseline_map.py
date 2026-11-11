"""baseline_map: one test per mapped field, then the document.

Pure: every track is an invented `RawTrack`. Dates are mapped in a named zone, never
the machine's, so each expected Unix second is fixed. The property test holds
`track_entry` to the contract over arbitrary input: it never raises, and every entry it
writes passes the copied schema inside a one-track document.
"""

from __future__ import annotations

import dataclasses
import sys
import unittest
from pathlib import Path
from zoneinfo import ZoneInfo

from hypothesis import given
from hypothesis import strategies as st

_HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(_HERE), str(_HERE.parent / "src")]

import baseline_map as bm  # noqa: E402 - import follows the sys.path bootstrap above
import baseline_rows  # noqa: E402 - import follows the sys.path bootstrap above
import baseline_schema  # noqa: E402 - import follows the sys.path bootstrap above
from baseline_fixtures import INVENTED_TRACK  # noqa: E402 - bootstrap above

#: The zone every mapped date is read in.
_ZONE = ZoneInfo("America/New_York")
#: INVENTED_TRACK's played date, 2024-03-09 12:34:56 New York standard time.
_INVENTED_PLAYED_AT = 1710005696
#: An invented capture time and version for a document.
_CAPTURED_AT = 1793100000
_VERSION = "0.1.0"


def _track(**changes: object) -> baseline_rows.RawTrack:
    """INVENTED_TRACK with *changes* applied."""
    # The changes are typed object, as every caller's keyword mix differs; RawTrack's own
    # field types are what a wrong one would break, at once, under test.
    return dataclasses.replace(INVENTED_TRACK, **changes)  # type: ignore[arg-type]


def _entry(**changes: object) -> dict[str, object]:
    """The entry `track_entry` maps the changed invented track to; never an exclusion."""
    entry = bm.track_entry(_track(**changes), zone=_ZONE)
    assert isinstance(entry, dict), entry
    return entry


def _document(track: dict[str, object]) -> dict[str, object]:
    """A one-track baseline document around *track*."""
    return {
        "baseline_type": "play_counts",
        "captured_at": _CAPTURED_AT,
        "submission_client": "play_count_baseline",
        "submission_client_version": _VERSION,
        "tracks": [track],
    }


class TrackEntryTest(unittest.TestCase):
    """`track_entry` follows the mapping table row by row."""

    def test_the_invented_track_maps_to_every_key(self) -> None:
        self.assertEqual(
            _entry(),
            {
                "track_name": "Invented Song",
                "artist_name": "The Placeholder Band",
                "release_name": "Invented Album",
                "ls_album_artist": "Placeholder Collective",
                "ls_disc_number": 1,
                "duration_ms": 215000,
                "play_count": 7,
                "last_played_at": _INVENTED_PLAYED_AT,
                "ls_genre": "Invented Genre",
                "ls_year": 2001,
                "ls_file_path": "/Invented/Library/Invented Song.m4a",
                "ls_persistent_id": "0123456789ABCDEF",
            },
        )

    def test_an_empty_name_is_excluded(self) -> None:
        self.assertIs(bm.track_entry(_track(name="")), bm.Exclusion.NO_NAME)

    def test_an_empty_artist_is_excluded(self) -> None:
        self.assertIs(bm.track_entry(_track(artist="")), bm.Exclusion.NO_ARTIST)

    def test_a_track_with_neither_counts_as_no_name(self) -> None:
        self.assertIs(bm.track_entry(_track(name="", artist="")), bm.Exclusion.NO_NAME)

    def test_an_empty_album_is_omitted(self) -> None:
        self.assertNotIn("release_name", _entry(album=""))

    def test_an_empty_album_artist_is_omitted(self) -> None:
        self.assertNotIn("ls_album_artist", _entry(album_artist=""))

    def test_an_album_artist_equal_to_the_artist_is_omitted(self) -> None:
        self.assertNotIn("ls_album_artist", _entry(album_artist="The Placeholder Band"))

    def test_disc_numbers_outside_1_to_999_are_omitted(self) -> None:
        for disc, kept in ((0, False), (1, True), (999, True), (1000, False)):
            with self.subTest(disc=disc):
                self.assertEqual("ls_disc_number" in _entry(disc_number=disc), kept)

    def test_durations_outside_the_contract_s_range_are_omitted(self) -> None:
        for duration, kept in (
            (None, False),
            (-1, False),
            (0, True),
            (2073600000, True),
            (2073600001, False),
        ):
            with self.subTest(duration=duration):
                entry = _entry(duration_ms=duration)
                self.assertEqual("duration_ms" in entry, kept)
                if kept:
                    self.assertEqual(entry["duration_ms"], duration)

    def test_the_play_count_is_always_written_zero_included(self) -> None:
        self.assertEqual(_entry(played_count=0)["play_count"], 0)

    def test_a_never_played_track_has_no_last_played_at(self) -> None:
        self.assertNotIn("last_played_at", _entry(played_date=""))

    def test_malformed_date_parts_are_omitted(self) -> None:
        self.assertNotIn("last_played_at", _entry(played_date="2024/13/1/0"))

    def test_a_played_date_outside_the_listened_at_range_is_omitted(self) -> None:
        # 2002-09-30 is the day before the range opens (1033430400 is 2002-10-01 UTC).
        self.assertNotIn("last_played_at", _entry(played_date="2002/9/30/0"))

    def test_the_range_s_first_second_is_kept(self) -> None:
        # 2002-10-01 00:00:00 UTC is 2002-09-30 20:00:00 in New York daylight time.
        self.assertEqual(
            _entry(played_date="2002/9/30/72000")["last_played_at"], 1033430400
        )
        self.assertNotIn("last_played_at", _entry(played_date="2002/9/30/71999"))

    def test_a_played_date_past_the_range_is_omitted(self) -> None:
        # 9999-12-31 23:59:59 in New York is past the range's last second in UTC.
        self.assertNotIn("last_played_at", _entry(played_date="9999/12/31/86399"))

    def test_an_empty_genre_is_omitted(self) -> None:
        self.assertNotIn("ls_genre", _entry(genre=""))

    def test_years_outside_1000_to_9999_are_omitted(self) -> None:
        for year, kept in ((0, False), (999, False), (1000, True), (9999, True)):
            with self.subTest(year=year):
                self.assertEqual("ls_year" in _entry(year=year), kept)
        self.assertNotIn("ls_year", _entry(year=10000))

    def test_a_cloud_only_track_has_no_file_path(self) -> None:
        self.assertNotIn("ls_file_path", _entry(path=""))

    def test_the_persistent_id_is_always_written(self) -> None:
        entry = _entry(
            album="",
            album_artist="",
            disc_number=0,
            duration_ms=None,
            played_date="",
            genre="",
            year=0,
            path="",
        )
        self.assertEqual(
            entry,
            {
                "track_name": "Invented Song",
                "artist_name": "The Placeholder Band",
                "play_count": 7,
                "ls_persistent_id": "0123456789ABCDEF",
            },
        )

    def test_with_no_zone_the_machine_s_rules_apply(self) -> None:
        entry = bm.track_entry(INVENTED_TRACK)
        assert isinstance(entry, dict)
        self.assertEqual(
            entry["last_played_at"], bm.local_to_unix(INVENTED_TRACK.played_date)
        )

    #: Any track as the parser could hand it over: a 16-hex persistent ID and counts in
    #: the parser's nine-digit domain; every other field arbitrary text or any integer.
    @given(
        st.builds(
            baseline_rows.RawTrack,
            persistent_id=st.from_regex(r"[0-9A-Fa-f]{16}", fullmatch=True),
            name=st.text(),
            artist=st.text(),
            album=st.text(),
            album_artist=st.text(),
            disc_number=st.integers(),
            duration_ms=st.none() | st.integers(),
            played_count=st.integers(min_value=0, max_value=999_999_999),
            played_date=st.text()
            | st.from_regex(
                r"[0-9]{1,4}/[0-9]{1,2}/[0-9]{1,2}/[0-9]{1,5}", fullmatch=True
            ),
            genre=st.text(),
            year=st.integers(),
            path=st.text(),
        )
    )
    def test_fuzz_track_entry(self, raw: baseline_rows.RawTrack) -> None:
        entry = bm.track_entry(raw, zone=_ZONE)
        if isinstance(entry, bm.Exclusion):
            self.assertIn("", (raw.name, raw.artist))
            return
        self.assertEqual(baseline_schema.findings(_document(entry)), [])


class BuildDocumentTest(unittest.TestCase):
    """`build_document` writes the sorted tracks and counts what it left out."""

    def _build(
        self, rows: list[baseline_rows.RawTrack]
    ) -> tuple[dict[str, object], bm.Summary]:
        return bm.build_document(
            rows, captured_at=_CAPTURED_AT, version=_VERSION, zone=_ZONE
        )

    def test_the_document_s_header(self) -> None:
        document, _ = self._build([INVENTED_TRACK])
        self.assertEqual(
            {key: value for key, value in document.items() if key != "tracks"},
            {
                "baseline_type": "play_counts",
                "captured_at": _CAPTURED_AT,
                "submission_client": "play_count_baseline",
                "submission_client_version": _VERSION,
            },
        )

    def test_the_document_passes_the_schema(self) -> None:
        document, _ = self._build([INVENTED_TRACK, _track(persistent_id="0" * 16)])
        self.assertEqual(baseline_schema.findings(document), [])

    def test_tracks_are_sorted_by_persistent_id(self) -> None:
        ids = ("C000000000000003", "A000000000000001", "B000000000000002")
        document, _ = self._build([_track(persistent_id=pid) for pid in ids])
        tracks = document["tracks"]
        assert isinstance(tracks, list)
        self.assertEqual([track["ls_persistent_id"] for track in tracks], sorted(ids))

    def test_the_summary_counts_read_written_excluded_and_missing(self) -> None:
        rows = [
            INVENTED_TRACK,
            _track(persistent_id="1" * 16, name=""),
            _track(persistent_id="2" * 16, artist=""),
            _track(persistent_id="3" * 16, artist=""),
            _track(persistent_id="4" * 16, genre="", path=""),
        ]
        document, summary = self._build(rows)
        self.assertEqual((summary.read, summary.written), (5, 2))
        self.assertEqual(
            dict(summary.excluded),
            {bm.Exclusion.NO_NAME: 1, bm.Exclusion.NO_ARTIST: 2},
        )
        expected_missing = dict.fromkeys(bm.OPTIONAL_KEYS, 0)
        expected_missing.update({"ls_genre": 1, "ls_file_path": 1})
        self.assertEqual(dict(summary.missing), expected_missing)
        tracks = document["tracks"]
        assert isinstance(tracks, list)
        self.assertEqual(len(tracks), summary.written)

    def test_the_optional_keys_are_every_omittable_key(self) -> None:
        self.assertEqual(
            set(bm.OPTIONAL_KEYS),
            {
                "release_name",
                "ls_album_artist",
                "ls_disc_number",
                "duration_ms",
                "last_played_at",
                "ls_genre",
                "ls_year",
                "ls_file_path",
            },
        )

    def test_an_empty_library_gives_no_tracks_and_zero_counts(self) -> None:
        document, summary = self._build([])
        self.assertEqual(document["tracks"], [])
        self.assertEqual((summary.read, summary.written), (0, 0))
        self.assertEqual(dict(summary.excluded), dict.fromkeys(bm.Exclusion, 0))

    def test_the_summary_s_counts_are_read_only(self) -> None:
        _, summary = self._build([INVENTED_TRACK])
        with self.assertRaises(TypeError):
            # Deliberately writes through the read-only Mapping, to show it refuses.
            summary.missing["ls_genre"] = 9  # type: ignore[index]


if __name__ == "__main__":
    unittest.main()
