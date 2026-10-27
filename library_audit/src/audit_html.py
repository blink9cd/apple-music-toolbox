r"""The HTML report: one self-contained page of tables, from the JSON report's object.

Pure: `format_html` takes `audit_report.report_dict`'s object, the very one the JSON
format serializes, so the page and the JSON can never disagree, and returns the page.
The frame (the style, light and dark; the tables; the summary; the document around
them) is the shared `html_page`; this module supplies library_audit's own wording:
the title, the header's library folder and tallies, which sections appear, and the
footer. Each check's section, note and rows are `audit_html_checks`'s.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import cast

import html_page
from audit_html_checks import CHECKS, Check
from audit_report import MAC_ONLY
from html_page import escaped

#: The report object, as `report_dict` builds it.
Report = Mapping[str, object]

#: The page's title.
TITLE = "Library audit"
#: The footer's first line.
READ_ONLY = "Read-only: nothing in the library or Music.app was changed."


# --- The page ------------------------------------------------------------------------


def _items(value: object) -> list[object]:
    """A check's listed items; a bare count (or a check not run) lists none."""
    return cast("list[object]", value) if isinstance(value, list) else []


def _count_of(value: object) -> int | None:
    """How many a check found: its items, or its bare count; None when it did not run."""
    if value is None:
        return None
    return value if isinstance(value, int) else len(_items(value))


def _summary(report: Report) -> list[str]:
    """The summary section: every check in report order with its count.

    A check that found something links to its section; the others have none.
    """
    rows = []
    for check in CHECKS:
        count = _count_of(report[check.key])
        rows.append(
            html_page.summary_row(check.heading, count, check.anchor if count else None)
        )
    return html_page.summary_section(rows)


def _section(check: Check, report: Report, count: int) -> list[str]:
    """One check's section: its heading and count, its note, then its table."""
    library = str(report["library"])
    rows = [check.row(item, library) for item in _items(report[check.key])]
    table = html_page.table(check.columns, rows) if check.columns else []
    return html_page.section(check.anchor, check.heading, count, check.note, table)


def _sections(report: Report) -> list[str]:
    """A section for every check that found something, in report order."""
    lines: list[str] = []
    for check in CHECKS:
        count = _count_of(report[check.key])
        if count:
            lines += _section(check, report, count)
    return lines


def _header(report: Report) -> list[str]:
    """The page header under the title: the library folder, and the tallies."""
    tallies: tuple[tuple[str, object], ...] = (
        ("Audio files", report["audio_files"]),
        ("Music.app tracks", report["music_tracks"]),
        ("Findings", report["findings"]),
        ("Cloud-only", report["cloud_only"]),
        ("Outside the library", report["outside_library"]),
        ("Sizes unknown", report["sizes_unknown"]),
    )
    # The decode's skipped count is a tally only when the decode ran, as in the text.
    if report["decode_skipped"] is not None:
        tallies += (("Decode skipped", report["decode_skipped"]),)
    return [
        f'<p class="library">{escaped(report["library"])}</p>',
        '<ul class="tallies">',
        *(f"<li>{name}: {escaped(value)}</li>" for name, value in tallies),
        "</ul>",
    ]


def format_html(report: Report) -> str:
    """The HTML page of *report*, `audit_report.report_dict`'s object."""
    return html_page.page(
        title=TITLE,
        header=_header(report),
        main=[*_summary(report), *_sections(report)],
        read_only=READ_ONLY,
        # What the sync checks cannot see, as a sentence.
        footer=(f"{MAC_ONLY[0].upper()}{MAC_ONLY[1:]}.",),
    )
