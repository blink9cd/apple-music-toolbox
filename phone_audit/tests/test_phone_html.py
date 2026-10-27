"""phone_html: the HTML page, from the JSON report's object, every name escaped.

Pure: every report is invented here, built by `phone_report.report_dict` from an
invented audit, and each page is parsed back with the standard library's
``html.parser``, failing on any unclosed or misclosed element. Nothing here reaches a
phone or the network.
"""

from __future__ import annotations

import sys
import unittest
from datetime import datetime
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(_HERE), str(_HERE.parent)]

import phone_audit  # noqa: E402, F401 - puts src/ and the shared helpers on sys.path
import html_page  # noqa: E402 - import follows the sys.path bootstrap above
import phone_compare as pc  # noqa: E402 - import follows the sys.path bootstrap above
import phone_html  # noqa: E402 - import follows the sys.path bootstrap above
import phone_report as pr  # noqa: E402 - import follows the sys.path bootstrap above

#: When every invented page says the phone was read.
_READ_AT = datetime(2026, 10, 26, 14, 3)
_BAND, _ALBUM = "The Placeholder Band", "Invented Album"


def _row(pid: int, disc: int, track: int, **names: str) -> pc.PhoneRow:
    """An invented row in ``F00``, named after its track unless told otherwise."""
    fields = {"artist": _BAND, "album": _ALBUM, "title": f"Title {track}", **names}
    return pc.PhoneRow(
        pid,
        "F00",
        f"T{pid:03}.mp3",
        100,
        fields["title"],
        disc,
        track,
        fields["album"],
        fields["artist"],
    )


def _report(
    no_file: tuple[pc.PhoneRow, ...] = (),
    size_differs: tuple[pc.SizeDiffers, ...] = (),
    no_row: tuple[pc.PhoneFile, ...] = (),
) -> dict[str, object]:
    """The report object of an audit that found exactly these."""
    compared = pc.Compared(no_file, size_differs, no_row, 1)
    return pr.report_dict(pr.Audit(compared, 9, 8, 2, 0, 3))


def _page(report: dict[str, object]) -> str:
    """*report*'s page, read at the fixed time."""
    return phone_html.format_html(report, read_at=_READ_AT)


def _section(page: str, anchor: str) -> str:
    """The markup of the section *anchor*, from its opening tag to its close."""
    start = page.index(f'<section id="{anchor}">')
    return page[start : page.index("</section>", start) + len("</section>")]


_FULL = _report(
    (_row(1, 1, 2),),
    (pc.SizeDiffers(_row(2, 2, 3), 150),),
    (pc.PhoneFile("F01", "WXYZ.mp3", 512),),
)


class WellFormedTest(unittest.TestCase):
    """Every element closed, ids unique, every link resolved, nothing fetched."""

    def setUp(self) -> None:
        """Render a report with something in every section."""
        super().setUp()
        self.page = _page(_FULL)
        self.parsed = html_page.ParsedPage(self.page)

    def test_every_element_is_closed(self) -> None:
        self.assertEqual(self.parsed.stack, [])

    def test_ids_are_unique_and_every_link_resolves(self) -> None:
        self.assertEqual(len(self.parsed.ids), len(set(self.parsed.ids)))
        self.assertEqual(
            self.parsed.links, ["#no-file", "#size-differs", "#files-no-row"]
        )
        for link in self.parsed.links:
            self.assertIn(link[1:], self.parsed.ids)

    def test_nothing_is_fetched_and_nothing_runs(self) -> None:
        self.assertEqual(self.parsed.sources, [])
        lowered = self.page.lower()
        for marker in ("<script", "http", "//", "url(", "@import", "<link", "src="):
            with self.subTest(marker=marker):
                self.assertNotIn(marker, lowered)

    def test_the_shared_frame_and_its_own_style(self) -> None:
        self.assertTrue(self.page.startswith("<!DOCTYPE html>\n"))
        self.assertIn("<title>Phone audit</title>", self.page)
        self.assertIn(f"<style>\n{html_page.CSS}", self.page)
        self.assertIn("tr.album-first", self.page)

    def test_the_header_says_when_the_phone_was_read(self) -> None:
        self.assertIn(
            '<header>\n<h1>Phone audit</h1>\n<p class="read">'
            "Read from the iPhone on 2026-10-26 at 14:03.</p>\n</header>",
            self.page,
        )

    def test_the_order_summary_sections_figures(self) -> None:
        places = [
            self.page.index(marker)
            for marker in (
                '<section id="summary">',
                '<section id="no-file">',
                '<section id="size-differs">',
                '<section id="files-no-row">',
                '<section id="figures">',
                "<footer>",
            )
        ]
        self.assertEqual(places, sorted(places))

    def test_the_summary_counts_each_section(self) -> None:
        summary = _section(self.page, "summary")
        for anchor, heading in (
            ("no-file", "Tracks with no file on the phone"),
            ("size-differs", "Size differs"),
            ("files-no-row", "Files with no row"),
        ):
            with self.subTest(section=anchor):
                self.assertIn(
                    f'<tr><td><a href="#{anchor}">{heading}</a></td>'
                    '<td class="num">1</td></tr>',
                    summary,
                )

    def test_the_figures(self) -> None:
        figures = _section(self.page, "figures")
        for label, value in (
            ("Findings", 2),
            ("Rows in the sync", 9),
            ("Files", 8),
            ("Outside the sync", 2),
            ("Unparsed lines", 0),
            ("Sizes unknown", 1),
            ("Other entries", 3),
        ):
            with self.subTest(figure=label):
                self.assertIn(
                    f'<tr><td>{label}</td><td class="num">{value}</td></tr>', figures
                )

    def test_the_footer_says_nothing_was_changed(self) -> None:
        self.assertTrue(
            self.page.endswith(
                "<footer>\n<p>Read-only: nothing on the iPhone was changed.</p>\n"
                "</footer>\n</body>\n</html>\n"
            )
        )


class SectionTest(unittest.TestCase):
    """Each section's note and table, exactly."""

    def test_the_size_section_exactly(self) -> None:
        self.assertEqual(
            _section(_page(_FULL), "size-differs"),
            '<section id="size-differs">\n'
            '<h2>Size differs <span class="count">1</span></h2>\n'
            '<p class="note">The phone\'s copy differs from what its database'
            " expects.</p>\n"
            '<div class="wrap"><table>\n'
            "<thead><tr><th>Artist</th><th>Album</th><th>Disc</th><th>Track</th>"
            "<th>Title</th><th>Phone file</th><th>Phone size</th>"
            "<th>Database size</th></tr></thead>\n"
            "<tbody>\n"
            f"<tr><td>{_BAND}</td><td>{_ALBUM}</td>"
            '<td class="num">2</td><td class="num">3</td><td>Title 3</td>'
            '<td>F00/T002.mp3</td><td class="num">150</td><td class="num">100</td>'
            "</tr>\n"
            "</tbody>\n"
            "</table></div>\n"
            "</section>",
        )

    def test_the_no_row_section_exactly(self) -> None:
        self.assertEqual(
            _section(_page(_FULL), "files-no-row"),
            '<section id="files-no-row">\n'
            '<h2>Files with no row <span class="count">1</span></h2>\n'
            '<p class="note">Listed only; neither a sync nor this tool removes them'
            " (not a finding).</p>\n"
            '<div class="wrap"><table>\n'
            "<thead><tr><th>Phone file</th><th>Size</th></tr></thead>\n"
            "<tbody>\n"
            '<tr><td>F01/WXYZ.mp3</td><td class="num">512</td></tr>\n'
            "</tbody>\n"
            "</table></div>\n"
            "</section>",
        )

    def test_the_no_file_note_names_the_proven_repair(self) -> None:
        self.assertIn(
            '<p class="note">A plain Finder sync does not repair these: add a'
            " character to each title, sync, then restore the title and sync again."
            ' See phone_audit.md, "Repairing a row with no file".</p>',
            _section(_page(_FULL), "no-file"),
        )

    def test_an_unknown_size_reads_as_a_dash(self) -> None:
        unsized = pc.PhoneRow(2, "F00", "T002.mp3", None, "T", 1, 1, "A", "B")
        report = _report(size_differs=(pc.SizeDiffers(unsized, 150),))
        self.assertIn('<td class="num">150</td><td>—</td>', _page(report))

    def test_an_empty_section_has_its_heading_count_and_note_but_no_table(
        self,
    ) -> None:
        page = _page(_report())
        for anchor in ("no-file", "size-differs", "files-no-row"):
            with self.subTest(section=anchor):
                section = _section(page, anchor)
                self.assertIn('<span class="count">0</span></h2>', section)
                self.assertIn('<p class="note">', section)
                self.assertNotIn("<table>", section)


class GroupedByAlbumTest(unittest.TestCase):
    """One table by artist, album, disc and track; an album's names once."""

    def setUp(self) -> None:
        """Two albums, given out of order, the first across two discs."""
        super().setUp()
        rows = (
            _row(5, 1, 1, album="Second Album"),
            _row(3, 2, 1),
            _row(1, 1, 2),
            _row(2, 1, 1),
            _row(4, 1, 9, artist="A Band First"),
        )
        self.section = _section(_page(_report(rows)), "no-file")

    def body(self) -> list[str]:
        """The table's body rows, in order."""
        return [line for line in self.section.splitlines() if line.startswith("<tr")]

    def test_the_header(self) -> None:
        self.assertIn(
            "<thead><tr><th>Artist</th><th>Album</th><th>Disc</th><th>Track</th>"
            "<th>Title</th><th>Phone file</th></tr></thead>",
            self.section,
        )

    def test_sorted_and_named_on_each_album_s_first_row_only(self) -> None:
        def cells(disc: int, track: int, pid: int) -> str:
            return (
                f'<td class="num">{disc}</td><td class="num">{track}</td>'
                f"<td>Title {track}</td><td>F00/T{pid:03}.mp3</td></tr>"
            )

        self.assertEqual(
            self.body(),
            [
                '<tr class="album-first"><td>A Band First</td>'
                f"<td>{_ALBUM}</td>{cells(1, 9, 4)}",
                f'<tr class="album-first"><td>{_BAND}</td><td>{_ALBUM}</td>'
                f"{cells(1, 1, 2)}",
                f'<tr class="album-rest"><td></td><td></td>{cells(1, 2, 1)}',
                f'<tr class="album-rest"><td></td><td></td>{cells(2, 1, 3)}',
                f'<tr class="album-first"><td>{_BAND}</td><td>Second Album</td>'
                f"{cells(1, 1, 5)}",
            ],
        )

    def test_an_empty_name_on_an_album_s_first_row_reads_as_a_dash(self) -> None:
        rows = (_row(1, 1, 1, artist="", album=""), _row(2, 1, 2, artist="", album=""))
        body = [
            line
            for line in _section(_page(_report(rows)), "no-file").splitlines()
            if line.startswith("<tr")
        ]
        self.assertTrue(
            body[0].startswith('<tr class="album-first"><td>—</td><td>—</td>')
        )
        self.assertTrue(body[1].startswith('<tr class="album-rest"><td></td><td></td>'))


class EscapedTest(unittest.TestCase):
    """A name from the phone is text on the page, never markup."""

    def test_markup_quotes_and_control_characters_render_as_text(self) -> None:
        hostile = "<b>&\"'\x1b[31m"
        rows = (_row(1, 1, 1, artist=hostile, album=hostile, title=hostile),)
        stray = (pc.PhoneFile("F01", hostile, 1),)
        page = _page(_report(rows, (pc.SizeDiffers(rows[0], 5),), stray))
        self.assertNotIn("<b>", page)
        self.assertNotIn("\x1b", page)
        shown = "&lt;b&gt;&amp;&quot;&#x27;\\x1b[31m"
        self.assertIn(f"<td>{shown}</td><td>{shown}</td>", page)
        self.assertIn(f"<td>F01/{shown}</td>", page)
        parsed = html_page.ParsedPage(page)
        self.assertEqual(parsed.stack, [])
        self.assertIn("<b>&\"'\\x1b[31m", parsed.text)


if __name__ == "__main__":
    unittest.main()
