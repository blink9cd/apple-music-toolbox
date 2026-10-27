"""Which album groups are one album split by a difference in spelling.

An album whose files spell its artist or its title two ways (a typographic hyphen
against an ASCII one, ``&`` against ``and``, curly against straight quotes) is two
groups to Music.app, and so two to the audit: each half has holes the other fills, and
the gap check would report each half on its own. This module finds such halves so the
report can name them once, as one split album, instead.

Two groups are linked when every one of these holds:

- both are grouped by tags (a group by folder has no names to compare), and both are on
  the same disc;
- no track number is in both;
- each has a gap, and holds a number in the other's gap: a group with no gap is a whole
  album, never half of one;
- their names match: their artists, or their albums, are equal under
  `audit_spelling.loose_fold`. A name folding to nothing is no name and matches
  nothing. A compilation's artist is the fixed compilation key, which is no name
  either, so two compilations match only on their albums, and a compilation never
  matches an artist merely named like its key;
- their track-count tags agree: two groups each carrying one, and carrying different
  ones, are two albums.

Links join into clusters, so an album split three ways is one split, but never by
chaining: a group joins a cluster only when its names and count tag match every
member's, and a joined album never holds one number twice. Links are taken in order of
the tracks the pair holds together, most first, then in report order, and a link that
would break either rule is not taken. So of two groups that each complete a third, the
one completing it more joins.

Pure: it reads only what `audit_checks.album_numbers` made, and nothing here reads a
file or talks to Music.app.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass
from itertools import combinations

from audit_checks import AlbumNumbers, missing_numbers
from audit_groups import COMPILATION_KEY, Group, group_order
from audit_spelling import differing_characters, loose_fold

__all__ = ["Difference", "Spelling", "Split", "find_splits", "split_groups"]


@dataclass(frozen=True)
class Spelling:
    """One spelling of a split album: its group, shown as first seen, and its tracks."""

    group: Group
    tracks: tuple[int, ...]


@dataclass(frozen=True)
class Difference:
    """How spellings ``first`` and ``second`` (indexes into the split's) differ.

    ``artist`` and ``album`` each name the differing characters, or are None where the
    two spell that name alike.
    """

    first: int
    second: int
    artist: str | None
    album: str | None


@dataclass(frozen=True)
class Split:
    """One album split across several spellings.

    ``spellings`` are in report order; ``missing`` are the numbers the joined album
    still lacks, counted as `audit_checks.missing_numbers` counts them.
    """

    spellings: tuple[Spelling, ...]
    missing: tuple[int, ...]
    differences: tuple[Difference, ...]

    @property
    def disc(self) -> int:
        """The disc every spelling shares."""
        return self.spellings[0].group.disc


def _artist_key(group: Group) -> str:
    """The artist as pairing compares it, loosely folded; "" when it is no name.

    A compilation's artist is the fixed compilation key, the same for every
    compilation, so it says nothing about which album a group is.
    """
    if group.artist_key == COMPILATION_KEY:
        return ""
    return loose_fold(group.artist)


def _album_key(group: Group) -> str:
    """The album as pairing compares it, loosely folded; "" when it is no name."""
    return loose_fold(group.album)


def _keys_match(first: str, second: str) -> bool:
    """Whether two folded names are one name: an empty key is none, and matches none."""
    # Defense in depth: `_candidate_pairs` already never buckets an empty key, so this
    # check refuses nothing today; it keeps the rule true for any future caller.
    return bool(first) and first == second


def _names_match(first: Group, second: Group) -> bool:
    """Whether the artists, or the albums, of two groups are one name spelled loosely."""
    return _keys_match(_artist_key(first), _artist_key(second)) or _keys_match(
        _album_key(first), _album_key(second)
    )


def _counts_agree(first: AlbumNumbers, second: AlbumNumbers) -> bool:
    """Whether two groups' count tags allow one album: unequal only when both carry one.

    A count tag of 0 is read as none, as `audit_checks.missing_numbers` reads it.
    """
    return not (
        first.track_count
        and second.track_count
        and first.track_count != second.track_count
    )


def _matching(first: AlbumNumbers, second: AlbumNumbers) -> bool:
    """Whether two groups could be one album by their names and count tags."""
    return _names_match(first.group, second.group) and _counts_agree(first, second)


def _linked(first: AlbumNumbers, second: AlbumNumbers) -> bool:
    """Whether two gap groups are halves of one album, as the module docstring says."""
    return (
        first.group.disc == second.group.disc
        and not first.numbers & second.numbers
        and bool(first.numbers.intersection(second.missing))
        and bool(second.numbers.intersection(first.missing))
        and _matching(first, second)
    )


def _candidate_pairs(albums: Sequence[AlbumNumbers]) -> Iterator[tuple[int, int]]:
    """Each pair of indexes into *albums* sharing a disc and a loose name, once.

    Bucketing by name first keeps a large library from comparing every group with
    every other. A name that is no name (`_artist_key`, `_album_key`) buckets nothing.
    """
    buckets: dict[tuple[str, int, str], list[int]] = {}
    for index, album in enumerate(albums):
        disc = album.group.disc
        for kind, key in (
            ("artist", _artist_key(album.group)),
            ("album", _album_key(album.group)),
        ):
            if key:
                buckets.setdefault((kind, disc, key), []).append(index)
    seen: set[tuple[int, int]] = set()
    for members in buckets.values():
        for pair in combinations(members, 2):
            if pair not in seen:
                seen.add(pair)
                yield pair


class _Clusters:
    """Union-find over album indexes, each cluster holding its members and numbers."""

    def __init__(self, albums: Sequence[AlbumNumbers]) -> None:
        """One cluster an album, each holding that album and its numbers."""
        self.albums = albums
        self.parent = list(range(len(albums)))
        self.joined = [[index] for index in range(len(albums))]
        self.numbers = [set(album.numbers) for album in albums]

    def root(self, index: int) -> int:
        """The cluster *index* belongs to."""
        while self.parent[index] != index:
            index = self.parent[index]
        return index

    def _all_match(self, one: int, other: int) -> bool:
        """Whether every member of cluster *one* matches every member of *other*."""
        return all(
            _matching(self.albums[i], self.albums[j])
            for i in self.joined[one]
            for j in self.joined[other]
        )

    def join(self, first: int, second: int) -> None:
        """Join the clusters of *first* and *second*, as the module docstring allows.

        Not when that would repeat a number, nor when some member of one does not
        match some member of the other: a link never chains two unmatched groups.
        """
        one, other = self.root(first), self.root(second)
        if (
            one == other
            or self.numbers[one] & self.numbers[other]
            or not self._all_match(one, other)
        ):
            return
        low, high = min(one, other), max(one, other)
        self.parent[high] = low
        self.joined[low] += self.joined[high]
        self.numbers[low] |= self.numbers[high]

    def members(self) -> list[list[int]]:
        """Every cluster of more than one album, its indexes ascending, in order."""
        clusters: dict[int, list[int]] = {}
        for index in range(len(self.parent)):
            clusters.setdefault(self.root(index), []).append(index)
        return [members for members in clusters.values() if len(members) > 1]


def _differences(groups: Sequence[Group]) -> tuple[Difference, ...]:
    """How each pair of *groups* differs.

    Every pair differs in one name at least: two groups on one disc are two groups only
    because their names compare apart, and identical names never do.
    """
    return tuple(
        Difference(
            i,
            j,
            differing_characters(first.artist, second.artist) or None,
            differing_characters(first.album, second.album) or None,
        )
        for (i, first), (j, second) in combinations(enumerate(groups), 2)
    )


def _split(members: Sequence[AlbumNumbers]) -> Split:
    """The split album *members*, already in report order, make together."""
    union = frozenset().union(*(album.numbers for album in members))
    return Split(
        tuple(Spelling(album.group, tuple(sorted(album.numbers))) for album in members),
        missing_numbers((album.track_count for album in members), union),
        _differences([album.group for album in members]),
    )


def find_splits(albums: Iterable[AlbumNumbers]) -> tuple[Split, ...]:
    """Every album split by spelling among *albums*, in report order."""
    candidates = sorted(
        (a for a in albums if a.group.folder is None and a.missing),
        key=lambda album: group_order(album.group),
    )
    links = [
        pair
        for pair in _candidate_pairs(candidates)
        if _linked(candidates[pair[0]], candidates[pair[1]])
    ]
    # The pair holding the most tracks first, so the fullest join wins a contest.
    links.sort(
        key=lambda p: (-len(candidates[p[0]].numbers | candidates[p[1]].numbers), p)
    )
    clusters = _Clusters(candidates)
    for first, second in links:
        clusters.join(first, second)
    return tuple(
        _split([candidates[index] for index in members])
        for members in clusters.members()
    )


def split_groups(splits: Iterable[Split]) -> frozenset[Group]:
    """Every group that is one spelling of a split album in *splits*."""
    return frozenset(s.group for split in splits for s in split.spellings)
