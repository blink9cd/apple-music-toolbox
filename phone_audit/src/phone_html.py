"""The HTML report: one self-contained page of tables, from the JSON report's object.

Pure: `format_html` takes `phone_report.report_dict`'s object, the very one the JSON
format serializes, so the page and the JSON can never disagree, and returns the page.
The frame (the style, light and dark; the escaped cells; the tables; the summary; the
document around them) is the shared `html_page` library, found through the entry
point's bootstrap; this module supplies phone_audit's own wording: the title, when the
phone was read, the three sections with their notes, the summary figures, and the
read-only line.

The rows with no file are one table sorted by artist, album, disc and track, with an
album's names on its first row only and its other rows grouped beneath, so the albums
stand out when choosing which to trial a repair on.

The items are `report_dict`'s, built in this process, so their shape is the companion
doc's JSON table; the accessors here narrow their ``object`` values with
`typing.cast` rather than validate them a second time.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import cast

import html_page
import phone_compare
from html_page import Cell, Row, escaped

#: The report object, as `report_dict` builds it, and one listed item of it.
Report = Mapping[str, object]
Item = Mapping[str, object]

#: The page's title.
TITLE = "Phone audit"
#: The footer's line.
READ_ONLY = "Read-only: nothing on the iPhone was changed."
#: What a cell with no value shows: a size the database does not hold, say.
_DASH = "—"
#: The classes of a no-file row: the first of its album, or one grouped beneath it.
ALBUM_FIRST, ALBUM_REST = "album-first", "album-rest"

#: The page's own style, after the shared one: when the phone was read, and each
#: album's rows grouped, a heavier rule above its first row and none between the rest.
_CSS = """\
.read { color: var(--muted); overflow-wrap: anywhere; margin: 0; }
tbody tr.album-first td { border-top: 2px solid var(--line); }
tbody tr.album-first:first-child td { border-top: 0; }
tbody tr.album-rest td { border-top-style: hidden; }
"""

#: The summary figures, in the text report's order: each label and its summary key.
_FIGURES = (
    ("Findings", "findings"),
    ("Rows in the sync", "rows_in_sync"),
    ("Files", "files"),
    ("Outside the sync", "outside_sync"),
    ("Unparsed lines", "unparsed_lines"),
    ("Sizes unknown", "sizes_unknown"),
    ("Other entries", "other_entries"),
)


# --- Cells ---------------------------------------------------------------------------


def _item(value: object) -> Item:
    """One listed item of the report, as `report_dict` built it."""
    return cast("Item", value)


def _text(value: object) -> Cell:
    """A text cell."""
    return Cell(escaped(value))


def _number(value: object) -> Cell:
    """A number cell, set in even-width figures; None reads as a dash."""
    return Cell(_DASH) if value is None else Cell(escaped(value), numeric=True)


def _file(item: Item) -> Cell:
    """The phone file, as its sync folder and name: ``F00/ABCD.mp3``."""
    return _text(f"{item['folder']}/{item['name']}")


def _track(item: Item) -> Row:
    """A row's disc, track, title and phone file, after its artist and album."""
    return (
        _number(item["disc"]),
        _number(item["track"]),
        _text(item["title"]),
        _file(item),
    )


# --- Each section's rows -------------------------------------------------------------


def _phone_row(item: Item) -> phone_compare.PhoneRow:
    """The row *item* was built from, so it sorts by `phone_compare.row_order` itself."""
    return phone_compare.PhoneRow(
        item_pid=cast("int", item["item_pid"]),
        folder=cast("str", item["folder"]),
        name=cast("str", item["name"]),
        size=cast("int | None", item["database_size"]),
        title=cast("str", item["title"]),
        disc=cast("int", item["disc"]),
        track=cast("int", item["track"]),
        album=cast("str", item["album"]),
        artist=cast("str", item["artist"]),
    )


def _named(value: object) -> Cell:
    """An album's name on its first row; an empty one reads as a dash, not a blank."""
    return _text(value) if value else Cell(_DASH)


def _album_rows(items: Sequence[Item]) -> tuple[list[Row], list[str | None]]:
    """The no-file rows, sorted, each album's names on its first row only; their classes.

    An album is its artist and album name together, across all its discs.
    """
    rows: list[Row] = []
    classes: list[str | None] = []
    previous: tuple[object, object] | None = None
    for item in sorted(items, key=lambda i: phone_compare.row_order(_phone_row(i))):
        album = (item["artist"], item["album"])
        if album == previous:
            rows.append((Cell(""), Cell(""), *_track(item)))
            classes.append(ALBUM_REST)
        else:
            rows.append((_named(item["artist"]), _named(item["album"]), *_track(item)))
            classes.append(ALBUM_FIRST)
        previous = album
    return rows, classes


def _no_file_table(items: Sequence[Item], columns: Sequence[str]) -> list[str]:
    """The rows with no file: one table, grouped by album."""
    rows, classes = _album_rows(items)
    return html_page.table(columns, rows, classes)


def _size_row(item: Item) -> Row:
    """A row whose file's size differs: who, what, where, and the two sizes."""
    return (
        _text(item["artist"]),
        _text(item["album"]),
        *_track(item),
        _number(item["phone_size"]),
        _number(item["database_size"]),
    )


def _no_row_row(item: Item) -> Row:
    """A file with no row: where, and its size."""
    return (_file(item), _number(item["size"]))


def _plain_table(
    row: Callable[[Item], Row],
) -> Callable[[Sequence[Item], Sequence[str]], list[str]]:
    """A builder of a table with one *row* per item, in report order."""

    def build(items: Sequence[Item], columns: Sequence[str]) -> list[str]:
        """The table of *items*."""
        return html_page.table(columns, [row(item) for item in items])

    return build


# --- The sections, in report order ---------------------------------------------------


@dataclass(frozen=True)
class Section:
    """One section: its report key, anchor, heading, note, columns and table builder."""

    key: str
    anchor: str
    heading: str
    note: str
    columns: tuple[str, ...]
    table: Callable[[Sequence[Item], Sequence[str]], list[str]]


_TRACK = ("Artist", "Album", "Disc", "Track", "Title", "Phone file")

#: Every section, in the text report's order, each with its note.
SECTIONS = (
    Section(
        "no_file",
        "no-file",
        "Tracks with no file on the phone",
        "A plain Finder sync does not repair these: add a character to each title,"
        " sync, then restore the title and sync again. See phone_audit.md,"
        ' "Repairing a row with no file".',
        _TRACK,
        _no_file_table,
    ),
    Section(
        "size_differs",
        "size-differs",
        "Size differs",
        "The phone's copy differs from what its database expects.",
        (*_TRACK, "Phone size", "Database size"),
        _plain_table(_size_row),
    ),
    Section(
        "files_no_row",
        "files-no-row",
        "Files with no row",
        "Listed only; neither a sync nor this tool removes them (not a finding).",
        ("Phone file", "Size"),
        _plain_table(_no_row_row),
    ),
)


# --- The page ------------------------------------------------------------------------


def _items(report: Report, section: Section) -> list[Item]:
    """*section*'s listed items."""
    return [_item(value) for value in cast("list[object]", report[section.key])]


def _section(report: Report, section: Section) -> list[str]:
    """One section: its heading, count and note, then its table when it lists any."""
    items = _items(report, section)
    table = section.table(items, section.columns) if items else []
    return html_page.section(
        section.anchor, section.heading, len(items), section.note, table
    )


def _summary(report: Report) -> list[str]:
    """The summary: every section with its count, each linked to its section."""
    return html_page.summary_section(
        [
            html_page.summary_row(s.heading, len(_items(report, s)), s.anchor)
            for s in SECTIONS
        ]
    )


def _figures(report: Report) -> list[str]:
    """The summary figures: findings, then every count, in a table."""
    summary = _item(report["summary"])
    rows = [(Cell(label), _number(summary[key])) for label, key in _FIGURES]
    return [
        '<section id="figures">',
        "<h2>Summary figures</h2>",
        *html_page.table(("Figure", "Count"), rows),
        "</section>",
    ]


def format_html(report: Report, *, read_at: datetime) -> str:
    """The HTML page of *report*, `phone_report.report_dict`'s object.

    *read_at* is when the phone was read, shown in the header to the minute.
    """
    main = [*_summary(report)]
    for section in SECTIONS:
        main += _section(report, section)
    return html_page.page(
        title=TITLE,
        header=[
            f'<p class="read">Read from the iPhone on {read_at:%Y-%m-%d at %H:%M}.</p>'
        ],
        main=[*main, *_figures(report)],
        read_only=READ_ONLY,
        extra_css=_CSS,
    )
