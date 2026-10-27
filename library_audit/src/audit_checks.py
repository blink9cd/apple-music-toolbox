"""The two per-album-group checks: track-number gaps, and files against tracks.

Pure: each takes what the walk, the tag reader, the listing and `audit_groups` already
produced, and nothing here reads a file or talks to Music.app. An album group is the
album artist (else artist, or one shared key for a compilation), album and disc, so
an album filed across two folders is judged as one, and a lone single beside another
album as its own.

`AlbumNumbers`, which `album_numbers` builds, is the per-group record both the gap
check and `audit_splits` read: the entry point finds the split albums first, then the gaps of every other group.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path

from audit_groups import Group, group_order, tags_group
from audit_tags import FileTags

#: A disc's first track number, and a pregap ("hidden track one") track's number.
_FIRST_TRACK, _PREGAP_TRACK = 1, 0


@dataclass(frozen=True)
class Gap:
    """One album group whose track numbers have holes.

    ``missing`` are the numbers the album should carry, as `missing_numbers` counts
    them, that no file carries; ``files`` counts the group's numbered
    files, and ``track_count`` is the highest track-count tag among them, if any.
    """

    group: Group
    missing: tuple[int, ...]
    files: int
    track_count: int | None


@dataclass(frozen=True)
class CountDiffers:
    """An album group whose audio files and Music.app tracks differ in number."""

    group: Group
    files: int
    tracks: int


@dataclass(frozen=True)
class AlbumNumbers:
    """One album group's track numbers, as the gap check and the split check read them.

    ``numbers`` are the distinct track numbers its files carry, ``files`` counts its
    numbered files, and ``track_count`` is the highest track-count tag among them, if
    any.
    """

    group: Group
    numbers: frozenset[int]
    files: int
    track_count: int | None

    @property
    def missing(self) -> tuple[int, ...]:
        """The numbers the album should carry that no file carries."""
        return missing_numbers([self.track_count], self.numbers)


def missing_numbers(
    track_counts: Iterable[int | None], numbers: Iterable[int]
) -> tuple[int, ...]:
    """The numbers an album should carry that *numbers* lacks, in order.

    An album runs from 1, or from 0 when it holds a pregap track numbered 0, to its
    highest track-count tag, or with none to its highest number. MusicBrainz numbers a
    disc with a pregap track 0 to total - 1, so there the count tag includes track 0
    and the album ends one below it. A count tag of 0 is read as none, as an absent
    one is.
    """
    present = frozenset(numbers)
    has_pregap = _PREGAP_TRACK in present
    first = _PREGAP_TRACK if has_pregap else _FIRST_TRACK
    counts = [count for count in track_counts if count]
    if counts:
        last = max(counts) - 1 if has_pregap else max(counts)
    else:
        last = max(present)
    return tuple(n for n in range(first, last + 1) if n not in present)


def _album_numbers(group: Group, numbered: Sequence[FileTags]) -> AlbumNumbers:
    """One group's numbers, from its numbered files' tags."""
    totals = [tags.total for tags in numbered if tags.total is not None]
    return AlbumNumbers(
        group,
        frozenset(tags.track for tags in numbered if tags.track is not None),
        len(numbered),
        max(totals) if totals else None,
    )


def album_numbers(tagged: Iterable[tuple[Path, FileTags]]) -> tuple[AlbumNumbers, ...]:
    """Every album group holding a numbered file, with its numbers, in report order.

    Files with no track number are left out. Each group is shown as its first file,
    in path order, spells it.
    """
    by_group: dict[Group, list[FileTags]] = {}
    for _path, tags in sorted(tagged, key=lambda item: item[0]):
        if tags.track is not None:
            group = tags_group(tags)
            by_group.setdefault(group, []).append(tags)
    return tuple(
        _album_numbers(group, by_group[group])
        for group in sorted(by_group, key=group_order)
    )


def gaps_of(albums: Iterable[AlbumNumbers]) -> tuple[Gap, ...]:
    """The gap in each of *albums* whose numbers have holes, in the order given.

    Fewer files than the track-count tag always leaves a number missing, so the one
    test covers both of the check's cases.
    """
    gaps = (
        Gap(album.group, album.missing, album.files, album.track_count)
        for album in albums
    )
    return tuple(gap for gap in gaps if gap.missing)


def compare_counts(
    file_side: Iterable[Group], music_side: Iterable[Group]
) -> tuple[CountDiffers, ...]:
    """Every group counted differently on the two sides, in report order.

    Each side holds one group a file, or a counted track. A group is shown as first
    seen, the files' side before Music.app's.
    """
    shown: dict[Group, Group] = {}
    files: Counter[Group] = Counter()
    tracks: Counter[Group] = Counter()
    for side, counts in ((file_side, files), (music_side, tracks)):
        for group in side:
            counts[shown.setdefault(group, group)] += 1
    return tuple(
        CountDiffers(group, files[group], tracks[group])
        for group in sorted(shown, key=group_order)
        if files[group] != tracks[group]
    )


def missing_ranges(numbers: Sequence[int]) -> str:
    """*numbers*, ascending, with each run collapsed: ``2-4, 7, 9-10``."""
    runs: list[list[int]] = []
    for number in numbers:
        if runs and number == runs[-1][1] + 1:
            runs[-1][1] = number
        else:
            runs.append([number, number])
    return ", ".join(str(a) if a == b else f"{a}-{b}" for a, b in runs)
