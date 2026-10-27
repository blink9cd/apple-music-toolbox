r"""The report a run prints, in text or JSON, and the exit code it ends with. Pure.

The HTML page is `phone_html`'s, rendered from `report_dict`, the object the JSON is.

The wording is the companion doc's, which shows an example; the suites pin it whole.
Every text line goes through ``html_page.shown``, the shared escape, since a name read
from the phone is text this tool did not write: a control character in one would split
a line or drive the terminal, so each is printed as its ``\xNN`` escape. The JSON is
plain ASCII, every other character escaped.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import dataclass

import phone_compare
from html_page import shown

#: The JSON report's layout version.
SCHEMA = 1
#: Exit codes: nothing found, findings, could not run, Ctrl-C.
EXIT_OK = 0
EXIT_FINDINGS = 1
EXIT_USAGE = 2
EXIT_INTERRUPTED = 130

#: The notes under a section, printed only when it lists something.
NO_FILE_NOTE = (
    "note: a plain Finder sync does not repair these; add a character to each title,"
    ' sync, restore it and sync again (phone_audit.md, "Repairing a row with no file")'
)
NO_ROW_NOTE = "note: listed only; neither a sync nor this tool removes them"


@dataclass(frozen=True)
class Audit:
    """What a run found, and the counts its summary gives."""

    compared: phone_compare.Compared
    rows_in_sync: int
    files: int
    outside_sync: int
    unparsed_lines: int
    other_entries: int


def finding_count(audit: Audit) -> int:
    """Rows with no file, sizes that differ, and listing lines that could not be read."""
    found = audit.compared
    return len(found.no_file) + len(found.size_differs) + audit.unparsed_lines


def exit_code(audit: Audit) -> int:
    """1 when *audit* found anything, else 0."""
    return EXIT_FINDINGS if finding_count(audit) else EXIT_OK


# --- Text ----------------------------------------------------------------------------


def _row_line(row: phone_compare.PhoneRow) -> str:
    """A row as the report names it: who, which album, where, what, and its file."""
    return (
        f"{row.artist} / {row.album}, disc {row.disc} track {row.track}:"
        f" {row.title} [{row.folder}/{row.name}]"
    )


def _section(header: str, items: Iterable[str], note: str | None = None) -> list[str]:
    """A header with its count, each item indented, then *note* if any item was listed."""
    lines = [f"  {item}" for item in items]
    tail = [f"  {note}"] if lines and note is not None else []
    return [f"{header}: {len(lines)}", *lines, *tail]


def _summary(audit: Audit) -> str:
    """The closing line: findings, then every count."""
    return (
        f"summary: findings {finding_count(audit)}; rows in the sync {audit.rows_in_sync},"
        f" files {audit.files}; outside the sync {audit.outside_sync},"
        f" unparsed lines {audit.unparsed_lines},"
        f" sizes unknown {audit.compared.sizes_unknown},"
        f" other entries {audit.other_entries}"
    )


def format_text(audit: Audit) -> str:
    """The text report: three sections, then the summary."""
    found = audit.compared
    lines = [
        *_section(
            "rows with no file on the phone",
            (_row_line(r) for r in found.no_file),
            NO_FILE_NOTE,
        ),
        *_section(
            "size differs",
            (
                f"{_row_line(d.row)}: phone file {d.phone_size}, database {d.row.size}"
                for d in found.size_differs
            ),
        ),
        *_section(
            "files with no row",
            (f"{f.folder}/{f.name}: {f.size} bytes" for f in found.no_row),
            NO_ROW_NOTE,
        ),
        _summary(audit),
    ]
    return "".join(f"{shown(line)}\n" for line in lines)


# --- JSON ----------------------------------------------------------------------------


def _row_json(row: phone_compare.PhoneRow) -> dict[str, object]:
    """A row's fields, keyed as the companion doc lists."""
    return {
        "item_pid": row.item_pid,
        "artist": row.artist,
        "album": row.album,
        "disc": row.disc,
        "track": row.track,
        "title": row.title,
        "folder": row.folder,
        "name": row.name,
        "database_size": row.size,
    }


def report_dict(audit: Audit) -> dict[str, object]:
    """The report as one object, keyed as the companion doc lists.

    The JSON format serializes it and the HTML page (`phone_html`) is rendered from it,
    so the two can never disagree.
    """
    found = audit.compared
    return {
        "schema": SCHEMA,
        "no_file": [_row_json(r) for r in found.no_file],
        "size_differs": [
            {**_row_json(d.row), "phone_size": d.phone_size} for d in found.size_differs
        ],
        "files_no_row": [
            {"folder": f.folder, "name": f.name, "size": f.size} for f in found.no_row
        ],
        "summary": {
            "findings": finding_count(audit),
            "rows_in_sync": audit.rows_in_sync,
            "files": audit.files,
            "outside_sync": audit.outside_sync,
            "unparsed_lines": audit.unparsed_lines,
            "sizes_unknown": found.sizes_unknown,
            "other_entries": audit.other_entries,
        },
    }


def format_json(audit: Audit) -> str:
    """The JSON report: the text report's content, keyed as the companion doc lists."""
    # ensure_ascii, the default, escapes every non-ASCII character and lone surrogate,
    # so the report is plain ASCII whatever names it holds.
    return json.dumps(report_dict(audit), indent=2) + "\n"
