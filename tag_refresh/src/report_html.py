r"""The audits' HTML table cells: library_audit's and phone_audit's pages share them.

Pure. Each cell's markup goes through the shared frame's `html_page.escaped`: shown as
the text report shows it (a control character as a visible ``\xNN``), then escaped,
quotes included, so no name can become markup. A missing value (None) reads as a dash.
`html_page` is reached through each entry point's bootstrap, so this module is
imported by the audits only, never by tag_refresh's own run.

The items are each audit's ``report_dict``'s, built in the same process, so `item_of`
narrows a listed value with `typing.cast` rather than validate it a second time.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import cast

from html_page import Cell, escaped

#: One listed item of a report, as its ``report_dict`` builds it.
Item = Mapping[str, object]

#: What a cell with no value shows.
DASH = "—"


def text_cell(value: object) -> Cell:
    """A text cell; None reads as a dash."""
    return Cell(DASH if value is None else escaped(value))


def number_cell(value: object) -> Cell:
    """A number cell, set in even-width figures; None reads as a dash."""
    return Cell(DASH) if value is None else Cell(escaped(value), numeric=True)


def item_of(value: object) -> Item:
    """One listed item of a report, as its ``report_dict`` built it."""
    return cast("Item", value)
