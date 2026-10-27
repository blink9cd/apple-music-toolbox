#!/usr/bin/env python3
"""The shared page frame: the escape, cells, tables, the summary, a section and the page.

`html_page` is the tool-neutral half of an HTML report, imported by each tool that writes
one, so these tests pin its own contract: what each piece takes and the markup it
returns. A tool's whole page is pinned byte for byte by that tool's own suite.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import html_page  # noqa: E402 - import follows the sys.path bootstrap above
from html_page import Cell  # noqa: E402 - import follows the sys.path bootstrap above


class ShownTest(unittest.TestCase):
    """Text from outside, with each control character and lone surrogate escaped."""

    def test_c0_del_and_c1_are_spelled_as_hex_escapes(self) -> None:
        self.assertEqual(
            html_page.shown("a\nb\tc\x1b[0m\x7f\x85\x9f"),
            "a\\x0ab\\x09c\\x1b[0m\\x7f\\x85\\x9f",
        )

    def test_a_lone_surrogate_is_spelled_as_its_escape(self) -> None:
        self.assertEqual(html_page.shown("a\udcffb"), "a\\udcffb")

    def test_other_text_comes_back_unchanged(self) -> None:
        text = "caf\u00e9 \u00a0\u200f \u2028 \\x07 <b>"
        self.assertEqual(html_page.shown(text), text)


class EscapedTest(unittest.TestCase):
    """A value becomes page text: control characters shown, markup escaped."""

    def test_markup_and_quotes_are_escaped(self) -> None:
        self.assertEqual(html_page.escaped("<b>&\"'"), "&lt;b&gt;&amp;&quot;&#x27;")

    def test_a_control_character_is_shown_as_its_escape(self) -> None:
        self.assertEqual(html_page.escaped("a\x07b"), "a\\x07b")

    def test_a_non_string_is_shown_as_text(self) -> None:
        self.assertEqual(html_page.escaped(42), "42")


class TableTest(unittest.TestCase):
    """A table in its scrolling wrapper; numbers and row classes marked."""

    def test_a_table_with_a_numeric_cell(self) -> None:
        lines = html_page.table(("A & B", "N"), [(Cell("x"), Cell("3", numeric=True))])
        self.assertEqual(
            lines,
            [
                '<div class="wrap"><table>',
                "<thead><tr><th>A &amp; B</th><th>N</th></tr></thead>",
                "<tbody>",
                '<tr><td>x</td><td class="num">3</td></tr>',
                "</tbody>",
                "</table></div>",
            ],
        )

    def test_row_classes_apply_in_order_and_may_be_left_out(self) -> None:
        rows = [(Cell("a"),), (Cell("b"),), (Cell("c"),)]
        lines = html_page.table(("H",), rows, ("first", None))
        self.assertEqual(
            lines[3:6],
            [
                '<tr class="first"><td>a</td></tr>',
                "<tr><td>b</td></tr>",
                "<tr><td>c</td></tr>",
            ],
        )


class SummaryTest(unittest.TestCase):
    """The summary table: a linked heading, a bare count, or not run."""

    def test_a_row_with_an_anchor_links_its_heading(self) -> None:
        self.assertEqual(
            html_page.summary_row("A <b>", 2, "a-b"),
            (Cell('<a href="#a-b">A &lt;b&gt;</a>'), Cell("2", numeric=True)),
        )

    def test_a_row_with_no_anchor_is_not_linked(self) -> None:
        self.assertEqual(
            html_page.summary_row("A", 0, None),
            (Cell("A"), Cell("0", numeric=True)),
        )

    def test_a_check_that_did_not_run(self) -> None:
        self.assertEqual(
            html_page.summary_row("A", None, "a"), (Cell("A"), Cell("not run"))
        )

    def test_the_summary_section(self) -> None:
        lines = html_page.summary_section([html_page.summary_row("A", 1, "a")])
        self.assertEqual(lines[:2], ['<section id="summary">', "<h2>Summary</h2>"])
        self.assertIn("<thead><tr><th>Check</th><th>Found</th></tr></thead>", lines)
        self.assertEqual(lines[-1], "</section>")


class SectionTest(unittest.TestCase):
    """One section: its heading and count, its note, then its body."""

    def test_a_section_with_a_body(self) -> None:
        self.assertEqual(
            html_page.section("x-y", "X & Y", 3, 'One "note" <here>.', ["<p>b</p>"]),
            [
                '<section id="x-y">',
                '<h2>X &amp; Y <span class="count">3</span></h2>',
                '<p class="note">One "note" &lt;here&gt;.</p>',
                "<p>b</p>",
                "</section>",
            ],
        )

    def test_an_empty_section_has_no_body(self) -> None:
        lines = html_page.section("x", "X", 0, "N.", [])
        self.assertEqual(lines[-2:], ['<p class="note">N.</p>', "</section>"])


class PageTest(unittest.TestCase):
    """The whole document: head, header, main and footer, well formed."""

    def setUp(self) -> None:
        """A page with every part filled in."""
        super().setUp()
        self.page = html_page.page(
            title="A <title>",
            header=["<p>head</p>"],
            main=["<p>body</p>"],
            read_only="Nothing was changed.",
            footer=('It sees "this" only',),
            extra_css=".extra { color: red; }\n",
        )

    def test_the_page_is_well_formed(self) -> None:
        self.assertEqual(html_page.ParsedPage(self.page).stack, [])
        self.assertEqual(html_page.page_problems(self.page), [])

    def test_the_title_is_escaped_in_the_head_and_the_heading(self) -> None:
        self.assertIn("<title>A &lt;title&gt;</title>", self.page)
        self.assertIn("<header>\n<h1>A &lt;title&gt;</h1>\n<p>head</p>\n", self.page)

    def test_the_style_is_the_shared_css_then_the_extra(self) -> None:
        self.assertIn(
            f"<style>\n{html_page.CSS}.extra {{ color: red; }}\n</style>", self.page
        )

    def test_the_main_and_the_footer(self) -> None:
        self.assertIn("<main>\n<p>body</p>\n</main>\n", self.page)
        self.assertTrue(
            self.page.endswith(
                "<footer>\n<p>Nothing was changed.</p>\n"
                '<p>It sees "this" only</p>\n</footer>\n</body>\n</html>\n'
            )
        )

    def test_no_script_and_nothing_fetched(self) -> None:
        lowered = self.page.lower()
        for marker in ("<script", "http", "//", "url(", "@import", "<link"):
            with self.subTest(marker=marker):
                self.assertNotIn(marker, lowered)


#: A small whole page, well formed, for the check's tests to break one way at a time.
_CLEAN = (
    '<html><head><meta charset="utf-8"></head><body><p id="a">One<br>two</p>'
    '<a href="#a">to a</a></body></html>'
)


class ParsedPageTest(unittest.TestCase):
    """The strict parse: what stays open, the ids, links, sources and text."""

    def test_it_records_ids_links_sources_and_text(self) -> None:
        parsed = html_page.ParsedPage(
            '<p id="x"><a href="#x">go</a><i src="s">t</i></p>'
        )
        self.assertEqual(parsed.ids, ["x"])
        self.assertEqual(parsed.links, ["#x"])
        self.assertEqual(parsed.sources, ["s"])
        self.assertEqual(parsed.text, ["go", "t"])
        self.assertEqual(parsed.stack, [])

    def test_a_void_element_is_never_left_open(self) -> None:
        for tag in sorted(html_page.VOID_ELEMENTS):
            with self.subTest(tag=tag):
                self.assertEqual(html_page.ParsedPage(f"<p><{tag}></p>").stack, [])

    def test_an_unclosed_element_stays_on_the_stack(self) -> None:
        self.assertEqual(html_page.ParsedPage("<main><p>x").stack, ["main", "p"])

    def test_a_misclosed_element_raises(self) -> None:
        with self.assertRaisesRegex(ValueError, r"</p> closes \['div'\]"):
            html_page.ParsedPage("<p><div></p>")

    def test_a_stray_end_tag_raises(self) -> None:
        with self.assertRaisesRegex(ValueError, r"</p> closes \[\]"):
            html_page.ParsedPage("</p>")


class PageProblemsTest(unittest.TestCase):
    """Each way a page can fail the check is named; a sound page has none."""

    def test_a_sound_page_has_no_problem(self) -> None:
        self.assertEqual(html_page.page_problems(_CLEAN), [])

    def test_an_element_left_open(self) -> None:
        self.assertEqual(
            html_page.page_problems("<main><p>x</p>"), ["left open: ['main']"]
        )

    def test_a_misclosed_element_is_a_problem_not_a_raise(self) -> None:
        self.assertEqual(
            html_page.page_problems("<p><div></p>"), ["</p> closes ['div']"]
        )

    def test_a_repeated_id(self) -> None:
        page = '<p id="a"></p><p id="a"></p><p id="b"></p>'
        self.assertEqual(html_page.page_problems(page), ["id repeated: a"])

    def test_a_link_to_no_id_on_the_page(self) -> None:
        self.assertEqual(
            html_page.page_problems('<a href="#gone">x</a>'),
            ["link not on the page: #gone"],
        )

    def test_a_link_off_the_page_also_fetches(self) -> None:
        self.assertEqual(
            html_page.page_problems('<a href="https://example.com/">x</a>'),
            [
                "link not on the page: https://example.com/",
                "fetches or runs: http",
                "fetches or runs: //",
            ],
        )

    def test_a_source_is_named(self) -> None:
        self.assertEqual(
            html_page.page_problems('<img src="a.png">'),
            ["source: a.png", "fetches or runs:  src="],
        )

    def test_each_fetching_marker_is_named_whatever_its_case(self) -> None:
        for marker in html_page.FETCHING:
            with self.subTest(marker=marker):
                # In a comment, so the parse stays sound and only the marker is found.
                page = f"<p>x</p><!-- {marker.upper()} -->"
                self.assertIn(
                    f"fetches or runs: {marker}", html_page.page_problems(page)
                )


if __name__ == "__main__":
    unittest.main()
