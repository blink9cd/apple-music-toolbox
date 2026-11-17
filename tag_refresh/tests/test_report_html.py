"""report_html: the audits' HTML table cells, escaped, with None shown as a dash.

Pure functions over invented values; nothing here reads a library or a phone.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(_HERE.parent)]

import tag_refresh  # noqa: E402, F401 - puts src/ and html_page on sys.path
import html_page  # noqa: E402 - import follows the sys.path bootstrap above
import report_html  # noqa: E402 - import follows the sys.path bootstrap above


class TextCellTest(unittest.TestCase):
    """A text cell: escaped markup, never numeric."""

    def test_a_value_is_escaped_quotes_included(self) -> None:
        cell = report_html.text_cell('<b>"A" & B</b>')
        self.assertEqual(
            cell, html_page.Cell("&lt;b&gt;&quot;A&quot; &amp; B&lt;/b&gt;")
        )

    def test_a_control_character_is_shown_not_kept(self) -> None:
        self.assertEqual(report_html.text_cell("a\nb").markup, "a\\x0ab")

    def test_none_reads_as_a_dash(self) -> None:
        self.assertEqual(report_html.text_cell(None), html_page.Cell(report_html.DASH))
        self.assertEqual(report_html.DASH, "—")

    def test_a_number_given_as_text_is_not_numeric(self) -> None:
        self.assertEqual(report_html.text_cell(7), html_page.Cell("7"))


class NumberCellTest(unittest.TestCase):
    """A number cell: set in even-width figures, unless it is the dash."""

    def test_a_number_is_numeric(self) -> None:
        self.assertEqual(
            report_html.number_cell(1234), html_page.Cell("1234", numeric=True)
        )

    def test_zero_is_a_number_not_a_dash(self) -> None:
        self.assertEqual(report_html.number_cell(0), html_page.Cell("0", numeric=True))

    def test_none_reads_as_a_plain_dash(self) -> None:
        self.assertEqual(
            report_html.number_cell(None), html_page.Cell(report_html.DASH)
        )


class ItemOfTest(unittest.TestCase):
    """An item is narrowed, not copied or checked."""

    def test_the_same_mapping_comes_back(self) -> None:
        item = {"artist": "Invented Artist"}
        self.assertIs(report_html.item_of(item), item)


if __name__ == "__main__":
    unittest.main()
