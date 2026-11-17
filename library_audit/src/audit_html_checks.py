r"""The HTML report's checks: each one's heading, note, columns and table row.

Pure, and the half of the page `audit_html` does not assemble: `CHECKS` lists every
check in the text report's order, each with its one-sentence note (what the finding
means and the usual fix) and the function turning one of its listed items into a row of
escaped cells. Every value from the library goes through the shared frame's
`html_page.escaped`: shown as the text report shows it (a control character as a visible
``\xNN``), and then escaped, quotes included, so no name can become markup.

The items are `audit_report.report_dict`'s, built in this process, so their shape is the
companion doc's JSON table; the accessors here narrow their ``object`` values with
`typing.cast` rather than validate them a second time.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import PurePath
from typing import cast

from audit_checks import missing_ranges
from html_page import Cell, Row, escaped
from report_html import DASH, Item, item_of, number_cell, text_cell

#: The range joiner on the page: ``2–4``, an en dash, where the text report has ``-``.
_EN_DASH = "–"
#: What a track with no location shows, as in the text report.
_NO_LOCATION = "no location"
#: What a split album that lacks no number, or a gap with no count tag, shows.
_NONE = "none"


# --- Cells ---------------------------------------------------------------------------


def _ranges(numbers: object) -> str:
    """Sorted *numbers* with each run collapsed, ``2–4, 7``; ``none`` when empty."""
    joined = missing_ranges(cast("list[int]", numbers))
    return joined.replace("-", _EN_DASH) if joined else _NONE


def _shown_path(path: object, library: str) -> str:
    """*path* relative to *library* when under it, else as given."""
    under, root = PurePath(str(path)), PurePath(library)
    if under != root and under.is_relative_to(root):
        return str(under.relative_to(root))
    return str(path)


def _where(path: object, library: str) -> Cell:
    """A path cell: relative to the library when under it; no location when empty."""
    if not path:
        return Cell(_NO_LOCATION)
    return text_cell(_shown_path(path, library))


# --- Each check's row ----------------------------------------------------------------


def _path_row(value: object, library: str) -> Row:
    """A bare path."""
    return (_where(value, library),)


def _reason_row(value: object, library: str) -> Row:
    """A path and why it failed."""
    item = item_of(value)
    return (_where(item["path"], library), text_cell(item["reason"]))


def _gone_row(value: object, library: str) -> Row:
    """A gone track: who, which album, disc and track, its cloud status, and where."""
    item = item_of(value)
    return (
        *_unchecked_row(item, library)[:4],
        text_cell(item["cloud_status"]),
        _where(item["location"], library),
    )


def _unchecked_row(value: object, library: str) -> Row:
    """A listed track: who, which album, disc and track, and where."""
    item = item_of(value)
    return (
        text_cell(item["artist"]),
        text_cell(item["album"]),
        number_cell(item["disc"]),
        number_cell(item["track"]),
        _where(item["location"], library),
    )


def _gap_row(value: object, _library: str) -> Row:
    """A gap: the group, the numbers it lacks, its files and its count tag."""
    item = item_of(value)
    count = item["track_count"]
    return (
        text_cell(item["artist"]),
        text_cell(item["album"]),
        number_cell(item["disc"]),
        Cell(_ranges(item["missing"])),
        number_cell(item["files"]),
        Cell(_NONE) if count is None else number_cell(count),
    )


def _spelling_markup(spelling: Item) -> str:
    """One spelling as tagged, and its tracks: ``A / B: tracks 1, 3``."""
    tracks = cast("list[int]", spelling["tracks"])
    noun = "track" if len(tracks) == 1 else "tracks"
    return (
        f"<li>{escaped(spelling['artist'])} / {escaped(spelling['album'])}:"
        f" {noun} {_ranges(tracks)}</li>"
    )


def _differs_markup(differs: Sequence[Item]) -> str:
    """Each pair's differing characters, the text report's note per name, as a list."""
    lines = [
        f"<li>{pair[0] + 1} and {pair[1] + 1} differ in the {name}: {escaped(note)}</li>"
        for d in differs
        for pair in [cast("list[int]", d["between"])]
        for name in ("artist", "album")
        if (note := d[name]) is not None
    ]
    return f'<ul class="differs">{"".join(lines)}</ul>' if lines else DASH


def _split_row(value: object, _library: str) -> Row:
    """A split album: its first spelling, disc, every spelling, how they differ."""
    item = item_of(value)
    spellings = cast("list[Item]", item["spellings"])
    return (
        text_cell(spellings[0]["artist"]),
        text_cell(spellings[0]["album"]),
        number_cell(item["disc"]),
        Cell(f"<ol>{''.join(map(_spelling_markup, spellings))}</ol>"),
        Cell(_differs_markup(cast("list[Item]", item["differs"]))),
        Cell(_ranges(item["still_missing"])),
    )


def _count_row(value: object, library: str) -> Row:
    """A group whose files and tracks differ: its names, or its folder, and both counts."""
    item = item_of(value)
    folder = item["folder"]
    return (
        text_cell(item["artist"]),
        text_cell(item["album"]),
        number_cell(item["disc"]),
        text_cell(None if folder is None else _shown_path(folder, library)),
        number_cell(item["files"]),
        number_cell(item["tracks"]),
    )


def _size_row(value: object, library: str) -> Row:
    """A size out of step: the file, and the two sizes."""
    item = item_of(value)
    return (
        _where(item["path"], library),
        number_cell(item["music_size"]),
        number_cell(item["file_size"]),
    )


# --- The checks, in report order ------------------------------------------------------


@dataclass(frozen=True)
class Check:
    """One check's section: its report key, heading, note, columns and row.

    A check with no columns is a count with no items (the unparsed rows).
    """

    key: str
    heading: str
    note: str
    columns: tuple[str, ...] = ()
    row: Callable[[object, str], Row] = _path_row

    @property
    def anchor(self) -> str:
        """The section's id, from its key."""
        return self.key.replace("_", "-")


_PATH = ("Path",)
_TRACK = ("Artist", "Album", "Disc", "Track")
_GROUP = ("Artist", "Album", "Disc")

#: Every check, in the text report's order, each with its note.
CHECKS = (
    Check(
        "no_track",
        "Files with no Music.app track",
        "On disk but never imported. Add them to Music.app, or remove leftovers.",
        _PATH,
    ),
    Check(
        "file_gone",
        "Music.app tracks whose file is gone",
        "Music.app points at a file that no longer exists.",
        (*_TRACK, "Cloud status", "Location"),
        _gone_row,
    ),
    Check(
        "track_gaps",
        "Track-number gaps",
        "These albums are missing track numbers: a partial copy, a single filed with"
        " an album, or a split the spelling check could not pair.",
        (*_GROUP, "Missing", "Files", "Track-count tag"),
        _gap_row,
    ),
    Check(
        "split_albums",
        "Albums split by spelling",
        # Names no tagger: the companion doc gives one tagger's setting as an example.
        "One album under two spellings of its artist or title, so Music.app shows two"
        " albums. Give both halves one spelling in your tagger, then run tag_refresh.",
        (*_GROUP, "Spellings", "What differs", "Still missing"),
        _split_row,
    ),
    Check(
        "no_track_number",
        "Files with no track number",
        "The tags hold no track number.",
        _PATH,
    ),
    Check(
        "count_differs",
        "Files and Music.app tracks differ",
        "This album has a different number of files than Music.app tracks.",
        (*_GROUP, "Folder", "Files", "Music.app tracks"),
        _count_row,
    ),
    Check(
        "unreadable_tags",
        "Unreadable tags",
        "The file's tags could not be read.",
        _PATH,
    ),
    Check(
        "unreadable_paths",
        "Unreadable files and folders",
        "The tool could not read these.",
        ("Path", "Reason"),
        _reason_row,
    ),
    Check(
        "icloud_placeholders",
        "iCloud placeholders",
        "The audio is in iCloud only, so a Finder sync cannot copy it.",
        _PATH,
    ),
    Check(
        "size_differs",
        "Music.app size differs from the file",
        "Music.app's record is stale; tag_refresh makes it reread the file.",
        ("Path", "Music.app size", "File size"),
        _size_row,
    ),
    Check(
        "unchecked",
        "Unchecked tracks",
        "Skipped only when the phone syncs only checked songs.",
        (*_TRACK, "Location"),
        _unchecked_row,
    ),
    Check(
        "decode_failed",
        "Files that do not decode",
        "afconvert could not decode these; a pass is not proof a file is sound.",
        ("Path", "Reason"),
        _reason_row,
    ),
    Check(
        "unparsed_rows",
        "Unparsed listing rows",
        "Listing rows the tool could not read; that part of the picture is incomplete.",
    ),
)
