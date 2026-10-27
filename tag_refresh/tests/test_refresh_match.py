"""The lookup's rows, parsed strictly, and matched to the named MP3s by inode.

Every path and persistent ID here is invented. The property tests feed the row parser
arbitrary text: its rows are built by a script from library data, so the parser must
never raise and never hand back a row of the wrong shape.
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

import refresh_core as rc  # noqa: E402 - import follows the sys.path bootstrap above
import refresh_fixtures as rf  # noqa: E402 - import follows the sys.path bootstrap above
import refresh_match as rm  # noqa: E402 - import follows the sys.path bootstrap above

settings.register_profile(
    "fuzz_gate_deterministic",
    derandomize=True,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow],
)
settings.load_profile("fuzz_gate_deterministic")

#: Invented persistent IDs, in the shape Music emits.
_PID_A = "0123456789ABCDEF"
_PID_B = "FEDCBA9876543210"


def _mp3(path: str, device: int, inode: int) -> rc.Mp3:
    """Return a named MP3 with this device and inode."""
    return rc.Mp3(Path(path), (device, inode))


class ParseRowsTest(unittest.TestCase):
    """parse_rows: the lookup's output, strictly, with malformed rows counted."""

    def test_well_formed_rows_are_read(self) -> None:
        text = f"12\t{_PID_A}\t/L/a.mp3\n345\t{_PID_B}\t/L/b c.mp3\n"
        self.assertEqual(
            rm.parse_rows(text),
            rm.ParsedRows(
                (rm.Row(12, _PID_A, "/L/a.mp3"), rm.Row(345, _PID_B, "/L/b c.mp3")),
                0,
            ),
        )

    def test_empty_segments_are_neither_rows_nor_counted(self) -> None:
        # osascript ends its output with a linefeed of its own after the last row's.
        text = f"12\t{_PID_A}\t/L/a.mp3\n\n"
        self.assertEqual(
            rm.parse_rows(text), rm.ParsedRows((rm.Row(12, _PID_A, "/L/a.mp3"),), 0)
        )

    def test_a_lowercase_persistent_id_is_read_as_emitted(self) -> None:
        text = f"12\t{_PID_A.lower()}\t/L/a.mp3\n"
        self.assertEqual(
            rm.parse_rows(text).rows, (rm.Row(12, _PID_A.lower(), "/L/a.mp3"),)
        )

    def test_an_empty_reply_holds_nothing(self) -> None:
        # osascript's reply to an empty string is its own linefeed alone.
        self.assertEqual(rm.parse_rows("\n"), rm.ParsedRows((), 0))

    def test_an_unterminated_last_row_is_counted_not_read(self) -> None:
        text = f"12\t{_PID_A}\t/L/a.mp3\n13\t{_PID_B}\t/L/b.mp3"
        self.assertEqual(rm.parse_rows(text).unparsed, 1)
        self.assertEqual(len(rm.parse_rows(text).rows), 1)

    def test_each_malformed_shape_is_counted(self) -> None:
        malformed = [
            f"x1\t{_PID_A}\t/L/a.mp3",  # id not decimal
            f"١٢\t{_PID_A}\t/L/a.mp3",  # digits \\d would take
            f"12\t{_PID_A[:-1]}G\t/L/a.mp3",  # not hex
            f"12\t{_PID_A[:-1]}\t/L/a.mp3",  # 15 hex digits
            f"12\t{_PID_A}\tL/a.mp3",  # relative path
            f"12\t{_PID_A}\t/L/a\tb.mp3",  # a tab in the path: four fields
            f"12\t{_PID_A}",  # two fields
            f"12\t{_PID_A}\t/L/a\r.mp3",  # a carriage return
            f"12\t{_PID_A}\t/L/a\x00.mp3",  # a NUL
            f"{'9' * 19}\t{_PID_A}\t/L/a.mp3",  # an id past any Music id
            f"0\t{_PID_A}\t/L/a.mp3",  # Music's ids start at 1
            f"012\t{_PID_A}\t/L/a.mp3",  # a leading zero Music never prints
        ]
        text = "".join(f"{row}\n" for row in malformed)
        self.assertEqual(rm.parse_rows(text), rm.ParsedRows((), len(malformed)))

    def test_empty_text_holds_nothing(self) -> None:
        self.assertEqual(rm.parse_rows(""), rm.ParsedRows((), 0))

    @given(st.text())
    def test_fuzz_parse_rows(self, text: str) -> None:
        parsed = rm.parse_rows(text)
        for row in parsed.rows:
            self.assertTrue(rm.is_row(row), row)
        self.assertLessEqual(len(parsed.rows) + parsed.unparsed, text.count("\n") + 1)

    @given(
        st.lists(
            st.tuples(
                st.integers(min_value=1, max_value=10**12),
                st.text(alphabet="0123456789ABCDEFabcdef", min_size=16, max_size=16),
                st.text(
                    alphabet=st.characters(
                        codec="utf-8",
                        blacklist_characters="\t\n\r\x00",
                    )
                ),
            )
        )
    )
    def test_any_well_formed_rows_round_trip(
        self, rows: list[tuple[int, str, str]]
    ) -> None:
        text = "".join(f"{tid}\t{pid}\t/{tail}\n" for tid, pid, tail in rows)
        expected = tuple(rm.Row(tid, pid, f"/{tail}") for tid, pid, tail in rows)
        self.assertEqual(rm.parse_rows(text), rm.ParsedRows(expected, 0))


class IsRowTest(unittest.TestCase):
    """is_row: the shape every row parse_rows returns must have."""

    def test_a_well_formed_row_passes(self) -> None:
        self.assertTrue(rm.is_row(rm.Row(1, _PID_A, "/L/a.mp3")))

    def test_each_bad_field_fails(self) -> None:
        for row in [
            rm.Row(-1, _PID_A, "/L/a.mp3"),
            rm.Row(0, _PID_A, "/L/a.mp3"),
            rm.Row(1, "0123456789ABCDEG", "/L/a.mp3"),
            rm.Row(1, _PID_A, "L/a.mp3"),
            rm.Row(1, _PID_A, "/L/a\n.mp3"),
        ]:
            with self.subTest(row=row):
                self.assertFalse(rm.is_row(row))


class MatchTracksTest(unittest.TestCase):
    """match_tracks: a row counts only when its own path stats to a named MP3."""

    def test_the_resolved_path_form_matches_by_inode(self) -> None:
        named = _mp3("/L/Music/Albums/A/01.mp3", 7, 70)
        rows = [rm.Row(12, _PID_A, "/L/Cloud Drive/Albums/A/01.mp3")]
        stat = rf.fake_stat({"/L/Cloud Drive/Albums/A/01.mp3": (7, 70)})
        matches = rm.match_tracks(rows, [named], stat=stat)
        self.assertEqual(matches.matched, ((named, ((12, _PID_A),)),))
        self.assertEqual(matches.not_in_music, ())

    def test_the_same_string_on_another_inode_does_not_match(self) -> None:
        named = _mp3("/L/A/01.mp3", 7, 70)
        rows = [rm.Row(12, _PID_A, "/L/A/01.mp3")]
        matches = rm.match_tracks(
            rows, [named], stat=rf.fake_stat({"/L/A/01.mp3": (7, 71)})
        )
        self.assertEqual(matches.matched, ())
        self.assertEqual(matches.not_in_music, (named,))

    def test_a_vanished_or_unreadable_path_is_no_match(self) -> None:
        named = _mp3("/L/A/01.mp3", 7, 70)

        def _refuse(path: str) -> os.stat_result:
            raise PermissionError(path)

        for stat in (rf.fake_stat({}), _refuse):
            with self.subTest(stat=stat):
                matches = rm.match_tracks(
                    [rm.Row(12, _PID_A, "/L/A/01.mp3")], [named], stat=stat
                )
                self.assertEqual(matches.not_in_music, (named,))

    def test_a_path_os_stat_refuses_is_no_match(self) -> None:
        # Rows reach match_tracks from callers too, not only from parse_rows, so a NUL
        # the parser would have refused still matches nothing rather than raising.
        named = _mp3("/L/A/01.mp3", 7, 70)
        matches = rm.match_tracks([rm.Row(12, _PID_A, "/L/A/0\x001.mp3")], [named])
        self.assertEqual(matches.not_in_music, (named,))

    def test_every_row_for_one_file_is_kept_once(self) -> None:
        named = _mp3("/L/A/01.mp3", 7, 70)
        other = _mp3("/L/A/02.mp3", 7, 71)
        rows = [
            rm.Row(12, _PID_A, "/L/A/01.mp3"),
            rm.Row(12, _PID_A, "/L/A/01.mp3"),
            rm.Row(40, _PID_B, "/L/A/01.mp3"),
        ]
        matches = rm.match_tracks(
            rows, [named, other], stat=rf.fake_stat({"/L/A/01.mp3": (7, 70)})
        )
        self.assertEqual(matches.matched, ((named, ((12, _PID_A), (40, _PID_B))),))
        self.assertEqual(matches.not_in_music, (other,))

    def test_a_forged_row_matches_only_what_its_own_path_stats_to(self) -> None:
        # A track whose path holds a linefeed and a whole row after it: the script
        # emits the path unescaped, so the split yields two well-formed rows. The forged
        # one names a named MP3's path STRING, but matching asks the file system, and
        # here that string reaches another file; a tab instead makes no row at all.
        named = _mp3("/L/A/01.mp3", 7, 70)
        forged_path = f"/L/evil\n99\t{_PID_B}\t/L/A/01.mp3"
        text = f"12\t{_PID_A}\t{forged_path}\n13\t{_PID_A}\t/L/x\t/L/A/01.mp3\n"
        parsed = rm.parse_rows(text)
        self.assertEqual(parsed.unparsed, 1)
        self.assertEqual(
            parsed.rows,
            (rm.Row(12, _PID_A, "/L/evil"), rm.Row(99, _PID_B, "/L/A/01.mp3")),
        )
        stat = rf.fake_stat({"/L/evil": (7, 1), "/L/A/01.mp3": (8, 70)})
        matches = rm.match_tracks(parsed.rows, [named], stat=stat)
        self.assertEqual(matches.matched, ())
        self.assertEqual(matches.not_in_music, (named,))

    def test_a_forged_row_naming_the_real_path_attaches_its_pair(self) -> None:
        # The realistic forgery: the forged path IS the named file's own path, so it
        # stats to the named key and its (id, persistent ID) pair is attached to that
        # MP3. Refreshing that pair rereads another track's tags, and nothing worse.
        named = _mp3("/L/A/01.mp3", 7, 70)
        text = f"12\t{_PID_A}\t/L/evil\n99\t{_PID_B}\t/L/A/01.mp3\n"
        stat = rf.fake_stat({"/L/A/01.mp3": (7, 70)})
        matches = rm.match_tracks(rm.parse_rows(text).rows, [named], stat=stat)
        self.assertEqual(matches.matched, ((named, ((99, _PID_B),)),))
        self.assertEqual(matches.not_in_music, ())
