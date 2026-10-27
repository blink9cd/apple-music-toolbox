"""audit_splits: which gap groups are one album split by a difference in spelling.

Pure: the groups are built from invented tags through `audit_checks.album_numbers`,
as the entry point builds them, and nothing is read from disk. Every name is invented.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

_TOOL = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(_TOOL / "src"), str(_TOOL.parent / "tag_refresh" / "src")]

import audit_checks as ac  # noqa: E402 - import follows the sys.path bootstrap above
import audit_groups as ag  # noqa: E402 - import follows the sys.path bootstrap above
import audit_splits as asp  # noqa: E402 - import follows the sys.path bootstrap above
import audit_tags as at  # noqa: E402 - import follows the sys.path bootstrap above

_DUO = "The Split-Level Duo"
#: The same artist with a typographic hyphen, U+2010, in place of the ASCII one.
_DUO_TYPOGRAPHIC = "The Split‐Level Duo"
_ALBUM = "Invented Album"
#: The note for the two spellings above, in report order: the ASCII one sorts first.
_HYPHEN_NOTE = "U+002D HYPHEN-MINUS vs U+2010 HYPHEN"


def _files(
    artist: str,
    album: str,
    *numbers: int,
    total: int | None = None,
    disc: int = 1,
    compilation: bool = False,
) -> list[tuple[Path, at.FileTags]]:
    """One invented file per track number of *artist*'s *album*, disc *disc*."""
    folder = Path("/L") / artist / album
    return [
        (
            folder / f"{disc}-{n:02d}.mp3",
            at.FileTags(artist, album, disc, n, total, compilation),
        )
        for n in numbers
    ]


def _splits(*tagged: list[tuple[Path, at.FileTags]]) -> tuple[asp.Split, ...]:
    """The splits among every group *tagged* makes."""
    return asp.find_splits(
        ac.album_numbers([item for files in tagged for item in files])
    )


def _spellings(split: asp.Split) -> list[tuple[str, str, tuple[int, ...]]]:
    """Each spelling of *split* as its artist, album and tracks."""
    return [(s.group.artist, s.group.album, s.tracks) for s in split.spellings]


class LinkTest(unittest.TestCase):
    """Two gap groups are one album when every condition holds, and not otherwise."""

    def test_an_album_split_by_an_invisible_hyphen_is_one_split(self) -> None:
        (split,) = _splits(
            _files(_DUO_TYPOGRAPHIC, _ALBUM, 1, 3, total=4),
            _files(_DUO, _ALBUM, 2, 4, total=4),
        )
        self.assertEqual(
            _spellings(split),
            [(_DUO, _ALBUM, (2, 4)), (_DUO_TYPOGRAPHIC, _ALBUM, (1, 3))],
        )
        self.assertEqual(split.disc, 1)
        self.assertEqual(split.missing, ())
        self.assertEqual(split.differences, (asp.Difference(0, 1, _HYPHEN_NOTE, None),))

    def test_overlapping_numbers_are_two_albums(self) -> None:
        self.assertEqual(
            _splits(
                _files(_DUO_TYPOGRAPHIC, _ALBUM, 1, 3, total=4),
                _files(_DUO, _ALBUM, 3, 4, total=4),
            ),
            (),
        )

    def test_different_discs_are_never_one_album(self) -> None:
        self.assertEqual(
            _splits(
                _files(_DUO_TYPOGRAPHIC, _ALBUM, 1, 3, total=4, disc=1),
                _files(_DUO, _ALBUM, 2, 4, total=4, disc=2),
            ),
            (),
        )

    def test_complementary_numbers_under_unrelated_names_stay_apart(self) -> None:
        self.assertEqual(
            _splits(
                _files(_DUO, _ALBUM, 1, 3, total=4),
                _files("The Made-Up Trio", "Second Invented Album", 2, 4, total=4),
            ),
            (),
        )

    def test_the_artist_alone_matching_loosely_is_enough(self) -> None:
        (split,) = _splits(
            _files(_DUO_TYPOGRAPHIC, _ALBUM, 1, 3, total=4),
            _files(_DUO, "Invented Album (Remaster)", 2, 4, total=4),
        )
        self.assertEqual(len(split.spellings), 2)
        (difference,) = split.differences
        self.assertEqual(difference.artist, _HYPHEN_NOTE)
        self.assertIsNotNone(difference.album)

    def test_the_album_alone_matching_loosely_is_enough(self) -> None:
        (split,) = _splits(
            _files("Placeholder Band", "Don’t Invent", 1, 3, total=4),
            _files("The Placeholder Band", "Don't Invent", 2, 4, total=4),
        )
        self.assertEqual(
            _spellings(split),
            [
                ("Placeholder Band", "Don’t Invent", (1, 3)),
                ("The Placeholder Band", "Don't Invent", (2, 4)),
            ],
        )

    def test_each_must_fill_one_of_the_other_s_gaps(self) -> None:
        # The second fills the first's gaps 1 and 3; the first's 2 and 4 stay empty.
        self.assertEqual(
            _splits(
                _files(_DUO_TYPOGRAPHIC, _ALBUM, 1, 3, total=4),
                _files(_DUO, _ALBUM, 5, 6, total=6),
            ),
            (),
        )

    def test_a_group_with_no_gap_is_never_half_of_a_split(self) -> None:
        self.assertEqual(
            _splits(
                _files(_DUO_TYPOGRAPHIC, _ALBUM, 1, 2, 3),
                _files(_DUO, _ALBUM, 4, 5),
            ),
            (),
        )

    def test_numbers_still_missing_after_joining_are_kept(self) -> None:
        (split,) = _splits(
            _files(_DUO_TYPOGRAPHIC, _ALBUM, 1, 3, total=6),
            _files(_DUO, _ALBUM, 2),
        )
        self.assertEqual(split.missing, (4, 5, 6))

    def test_a_joined_album_with_a_pregap_track_ends_one_below_its_count(
        self,
    ) -> None:
        (split,) = _splits(
            _files(_DUO_TYPOGRAPHIC, _ALBUM, 0, 2, total=4),
            _files(_DUO, _ALBUM, 1, 3, total=4),
        )
        self.assertEqual(split.missing, ())

    def test_with_no_count_tag_the_joined_album_runs_to_its_highest_number(
        self,
    ) -> None:
        (split,) = _splits(
            _files(_DUO_TYPOGRAPHIC, _ALBUM, 1, 5),
            _files(_DUO, _ALBUM, 2, 4),
        )
        self.assertEqual(split.missing, (3,))


class EmptyNameTest(unittest.TestCase):
    """A name that folds to nothing is no name: it never matches another."""

    def test_two_artists_with_an_empty_album_stay_apart(self) -> None:
        for second_total in (12, 10):
            with self.subTest(second_total=second_total):
                self.assertEqual(
                    _splits(
                        _files("Alpha Band", "", 3, total=10),
                        _files("Beta Band", "", 5, total=second_total),
                    ),
                    (),
                )

    def test_two_albums_with_an_empty_artist_stay_apart(self) -> None:
        for second_total in (11, 9):
            with self.subTest(second_total=second_total):
                self.assertEqual(
                    _splits(
                        _files("", "Record One", 2, total=9),
                        _files("", "Record Two", 4, total=second_total),
                    ),
                    (),
                )

    def test_a_name_of_punctuation_alone_is_empty_too(self) -> None:
        self.assertEqual(
            _splits(
                _files("Alpha Band", "...", 1, 3, total=4),
                _files("Beta Band", "!!", 2, 4, total=4),
            ),
            (),
        )


class CompilationAlbumTest(unittest.TestCase):
    """Two compilations pair only when their albums match: their key is no name."""

    def test_two_compilations_of_different_albums_stay_apart(self) -> None:
        for second_total in (18, 20):
            with self.subTest(second_total=second_total):
                self.assertEqual(
                    _splits(
                        _files(
                            "One Artist",
                            "Soundtrack A",
                            3,
                            7,
                            total=20,
                            compilation=True,
                        ),
                        _files(
                            "Other Artist",
                            "Soundtrack B",
                            5,
                            12,
                            total=second_total,
                            compilation=True,
                        ),
                    ),
                    (),
                )

    def test_two_compilations_of_one_album_under_the_fold_pair(self) -> None:
        (split,) = _splits(
            _files("One Artist", "Soundtrack & Score", 1, 3, total=4, compilation=True),
            _files(
                "Other Artist", "Soundtrack and Score", 2, 4, total=4, compilation=True
            ),
        )
        self.assertEqual([s.tracks for s in split.spellings], [(1, 3), (2, 4)])


class CountTagTest(unittest.TestCase):
    """Two groups whose track-count tags differ are two albums."""

    def test_different_count_tags_are_two_albums(self) -> None:
        self.assertEqual(
            _splits(
                _files("Same Placeholder", "Hits One", 3, total=12),
                _files("Same Placeholder", "Hits Two", 7, total=10),
            ),
            (),
        )

    def test_equal_count_tags_and_the_artist_alone_still_pair(self) -> None:
        (split,) = _splits(
            _files("Same Placeholder", "Inven ted Hits", 1, 3, total=4),
            _files("Same Placeholder", "Invented Hits", 2, 4, total=4),
        )
        self.assertEqual(split.missing, ())

    def test_a_count_tag_on_one_side_only_does_not_refuse(self) -> None:
        (split,) = _splits(
            _files(_DUO_TYPOGRAPHIC, _ALBUM, 1, 3, total=4),
            _files(_DUO, _ALBUM, 2, 4),
        )
        self.assertEqual(split.missing, ())


class ClusterTest(unittest.TestCase):
    """Links join transitively, and a cluster never holds one number twice."""

    def test_a_three_way_split_is_one_split(self) -> None:
        (split,) = _splits(
            _files(_DUO_TYPOGRAPHIC, _ALBUM, 1, 4, total=6),
            _files(_DUO, _ALBUM, 2, 5, total=6),
            _files("The Split Level Duo", _ALBUM, 3, 6, total=6),
        )
        self.assertEqual(
            [tracks for _a, _b, tracks in _spellings(split)],
            [(3, 6), (2, 5), (1, 4)],
        )
        self.assertEqual(split.missing, ())
        self.assertEqual(
            [(d.first, d.second) for d in split.differences], [(0, 1), (0, 2), (1, 2)]
        )
        self.assertEqual(
            split.differences[0].artist, "U+0020 SPACE vs U+002D HYPHEN-MINUS"
        )

    def test_a_group_that_would_repeat_a_number_is_left_out(self) -> None:
        # The stray links with the typographic half too, but the pair holding the
        # most tracks joins first, and the stray would then repeat track 2.
        typographic = _files(_DUO_TYPOGRAPHIC, _ALBUM, 1, 3, total=4)
        ascii_half = _files(_DUO, _ALBUM, 2, 4, total=4)
        stray = _files("The Split Level Duo", _ALBUM, 2, total=4)
        (split,) = _splits(typographic, ascii_half, stray)
        self.assertEqual(
            [tracks for _a, _b, tracks in _spellings(split)], [(2, 4), (1, 3)]
        )
        joined = asp.split_groups((split,))
        self.assertEqual({group.artist for group in joined}, {_DUO, _DUO_TYPOGRAPHIC})

    def test_a_group_joins_only_when_it_matches_every_member(self) -> None:
        # P/X and P/Y share the artist, P/Y and R/Y the album, but P/X and R/Y share
        # neither, so the three are never one album. Both links hold four tracks, so
        # report order breaks the tie: P/X with P/Y joins first, and R/Y is left out.
        (split,) = _splits(
            _files("Placeholder Pair", "Invented Ex", 1, 4, total=6),
            _files("Placeholder Pair", "Invented Why", 2, 5, total=6),
            _files("Rival Placeholders", "Invented Why", 3, 6, total=6),
        )
        self.assertEqual(
            [(a, b) for a, b, _tracks in _spellings(split)],
            [
                ("Placeholder Pair", "Invented Ex"),
                ("Placeholder Pair", "Invented Why"),
            ],
        )
        self.assertEqual(split.missing, (3, 6))

    def test_splits_come_in_report_order(self) -> None:
        splits = _splits(
            _files("The Zeta Placeholders", _ALBUM, 1, total=2),
            _files("The Zeta‐Placeholders", _ALBUM, 2, total=2),
            _files(_DUO_TYPOGRAPHIC, _ALBUM, 1, total=2),
            _files(_DUO, _ALBUM, 2, total=2),
        )
        self.assertEqual(
            [split.spellings[0].group.artist for split in splits],
            [_DUO, "The Zeta Placeholders"],
        )


class GroupKindTest(unittest.TestCase):
    """Folder groups never pair; compilations pair on their shared key alone."""

    def test_folder_groups_never_pair(self) -> None:
        first = ac.AlbumNumbers(ag.folder_group(Path("/L/a")), frozenset({1}), 1, 2)
        second = ac.AlbumNumbers(ag.folder_group(Path("/L/b")), frozenset({2}), 1, 2)
        self.assertEqual(asp.find_splits([first, second]), ())

    def test_two_compilation_groups_pair_like_any_other(self) -> None:
        (split,) = _splits(
            _files("One Artist", "Invented‐Hits", 1, 3, total=4, compilation=True),
            _files("Other Artist", "Invented-Hits", 2, 4, total=4, compilation=True),
        )
        self.assertEqual(
            [s.group.artist for s in split.spellings], ["(compilation)"] * 2
        )
        self.assertEqual(split.differences, (asp.Difference(0, 1, None, _HYPHEN_NOTE),))

    def test_a_compilation_never_pairs_with_an_artist_named_like_its_key(
        self,
    ) -> None:
        self.assertEqual(
            _splits(
                _files("One Artist", "Invented Hits", 1, 3, total=4, compilation=True),
                _files("(Compilation)", "Other Hits", 2, 4, total=4),
            ),
            (),
        )


if __name__ == "__main__":
    unittest.main()
