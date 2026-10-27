"""The HTML report: a well-formed, self-contained page, every value escaped.

`audit_html.format_html` is pure: it takes the report the JSON format builds (the dict
before ``json.dumps``) and returns the page, so these tests hand it invented reports and
parse what comes back with the standard library's ``html.parser``. Nothing here reaches
Music.app, a library or the network.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(_HERE), str(_HERE.parent)]

import library_audit  # noqa: E402, F401 - puts src/ and the seam on sys.path
import audit_html  # noqa: E402 - import follows the sys.path bootstrap above
import html_fixtures as hf  # noqa: E402 - import follows the sys.path bootstrap above


class WellFormedTest(unittest.TestCase):
    """Every element closed, ids unique, every link resolved, nothing fetched."""

    def setUp(self) -> None:
        """Render the report with something in every section."""
        super().setUp()
        self.page = audit_html.format_html(hf.full_report())
        self.parsed = hf.Page(self.page)

    def test_every_element_is_closed(self) -> None:
        self.assertEqual(self.parsed.stack, [])

    def test_ids_are_unique(self) -> None:
        self.assertEqual(len(self.parsed.ids), len(set(self.parsed.ids)))

    def test_every_link_resolves_to_an_id_on_the_page(self) -> None:
        self.assertGreater(len(self.parsed.links), 0)
        for link in self.parsed.links:
            with self.subTest(link=link):
                self.assertTrue(link.startswith("#"))
                self.assertIn(link[1:], self.parsed.ids)

    def test_nothing_is_fetched_and_nothing_runs(self) -> None:
        self.assertEqual(self.parsed.sources, [])
        lowered = self.page.lower()
        for marker in ("<script", "http", "//", "url(", "@import", "<link"):
            with self.subTest(marker=marker):
                self.assertNotIn(marker, lowered)

    def test_the_document_head(self) -> None:
        self.assertTrue(self.page.startswith("<!DOCTYPE html>\n"))
        self.assertIn('<html lang="en">', self.page)
        self.assertIn('<meta charset="utf-8">', self.page)
        self.assertIn(
            '<meta name="viewport" content="width=device-width, initial-scale=1">',
            self.page,
        )
        self.assertIn("<title>Library audit</title>", self.page)

    def test_colors_are_custom_properties_redefined_for_dark_mode(self) -> None:
        self.assertIn(":root {", self.page)
        self.assertIn("@media (prefers-color-scheme: dark)", self.page)
        self.assertIn("background: var(--bg)", self.page)
        self.assertIn("overflow-x: auto", self.page)

    def test_every_section_has_its_note_once(self) -> None:
        for anchor, note in hf.NOTES.items():
            with self.subTest(section=anchor):
                self.assertIn(f'<section id="{anchor}">', self.page)
                self.assertEqual(self.page.count(f'<p class="note">{note}</p>'), 1)

    def test_no_tagger_is_named(self) -> None:
        self.assertNotIn("Picard", self.page)

    def test_the_header_holds_the_library_and_the_tallies(self) -> None:
        text = "".join(self.parsed.text)
        self.assertIn("Library audit", text)
        self.assertIn(hf.LIBRARY, text)
        for tally in (
            "Audio files: 7",
            "Music.app tracks: 9",
            "Findings: 14",
            "Cloud-only: 1",
            "Outside the library: 2",
            "Sizes unknown: 3",
        ):
            with self.subTest(tally=tally):
                self.assertIn(tally, text)

    def test_the_decode_skipped_count_is_a_tally_when_the_decode_ran(self) -> None:
        page = audit_html.format_html(hf.full_report() | {"decode_skipped": 5})
        self.assertIn("<li>Decode skipped: 5</li>", page)
        self.assertIn("<li>Decode skipped: 0</li>", self.page)

    def test_no_decode_skipped_tally_when_the_decode_did_not_run(self) -> None:
        self.assertNotIn("Decode skipped", audit_html.format_html(hf.report()))

    def test_the_footer(self) -> None:
        text = "".join(self.parsed.text)
        self.assertIn(
            "Read-only: nothing in the library or Music.app was changed.", text
        )
        self.assertIn("The sync checks see this Mac only: Music.app cannot see", text)
        self.assertTrue(self.page.endswith(".</p>\n</footer>\n</body>\n</html>\n"))


class SectionTest(unittest.TestCase):
    """Each section's table, on a fixed report."""

    def setUp(self) -> None:
        """Render the report with something in every section."""
        super().setUp()
        self.page = audit_html.format_html(hf.full_report())

    def section(self, anchor: str) -> str:
        """The markup of the section *anchor*, from its opening tag to its close."""
        start = self.page.index(f'<section id="{anchor}">')
        return self.page[
            start : self.page.index("</section>", start) + len("</section>")
        ]

    def test_the_gaps_section_exactly(self) -> None:
        self.assertEqual(
            self.section("track-gaps"),
            '<section id="track-gaps">\n'
            '<h2>Track-number gaps <span class="count">1</span></h2>\n'
            f'<p class="note">{hf.NOTES["track-gaps"]}</p>\n'
            '<div class="wrap"><table>\n'
            "<thead><tr><th>Artist</th><th>Album</th><th>Disc</th><th>Missing</th>"
            "<th>Files</th><th>Track-count tag</th></tr></thead>\n"
            "<tbody>\n"
            "<tr><td>The Placeholder Band</td><td>Invented Album</td>"
            '<td class="num">1</td><td>2–4, 7</td><td class="num">3</td>'
            '<td class="num">12</td></tr>\n'
            "</tbody>\n"
            "</table></div>\n"
            "</section>",
        )

    def test_the_split_section_numbers_each_spelling_and_names_the_difference(
        self,
    ) -> None:
        section = self.section("split-albums")
        self.assertIn(
            "<th>Artist</th><th>Album</th><th>Disc</th><th>Spellings</th>"
            "<th>What differs</th><th>Still missing</th>",
            section,
        )
        self.assertIn(
            "<ol><li>The Split-Level Duo / Twin: track 2</li>"
            "<li>The Split‐Level Duo / Twin: tracks 1, 3</li></ol>",
            section,
        )
        self.assertIn(
            "<li>1 and 2 differ in the artist: U+002D HYPHEN-MINUS vs U+2010 HYPHEN</li>",
            section,
        )
        self.assertIn("<td>4</td>", section)

    def test_a_gone_track_shows_its_location_under_the_library(self) -> None:
        section = self.section("file-gone")
        self.assertIn(
            "<th>Artist</th><th>Album</th><th>Disc</th><th>Track</th>"
            "<th>Cloud status</th><th>Location</th>",
            section,
        )
        self.assertIn(
            "<td>local only</td><td>The Placeholder Band/Invented Album/02 b.mp3</td>",
            section,
        )

    def test_a_path_outside_the_library_stays_absolute(self) -> None:
        section = self.section("unreadable-paths")
        self.assertIn("<td>/elsewhere/locked</td><td>permission denied</td>", section)

    def test_an_unchecked_track_with_no_location_says_so(self) -> None:
        self.assertIn("<td>no location</td>", self.section("unchecked"))

    def test_a_folder_group_names_its_folder(self) -> None:
        section = self.section("count-differs")
        self.assertIn(
            "<th>Artist</th><th>Album</th><th>Disc</th><th>Folder</th>"
            "<th>Files</th><th>Music.app tracks</th>",
            section,
        )
        self.assertIn(
            "<td>—</td><td>—</td><td>—</td>"
            "<td>The Placeholder Band/Invented Album</td>"
            '<td class="num">1</td><td class="num">0</td>',
            section,
        )

    def test_a_tag_group_has_no_folder_and_a_gap_no_count_tag(self) -> None:
        report = hf.report(
            count_differs=[
                {
                    "grouped_by": "tags",
                    "artist": "A",
                    "album": "B",
                    "disc": 2,
                    "folder": None,
                    "files": 3,
                    "tracks": 4,
                }
            ],
            track_gaps=[
                {
                    "artist": "A",
                    "album": "B",
                    "disc": 1,
                    "missing": [2],
                    "files": 1,
                    "track_count": None,
                }
            ],
        )
        page = audit_html.format_html(report)
        self.assertIn(
            '<td>A</td><td>B</td><td class="num">2</td><td>—</td>'
            '<td class="num">3</td><td class="num">4</td>',
            page,
        )
        self.assertIn('<td>2</td><td class="num">1</td><td>none</td>', page)

    def test_the_sync_sections_columns(self) -> None:
        self.assertIn(
            "<th>Path</th><th>Music.app size</th><th>File size</th>",
            self.section("size-differs"),
        )
        self.assertIn(
            "<td>The Placeholder Band/Invented Album/06 f.mp3</td><td>decode error</td>",
            self.section("decode-failed"),
        )
        self.assertIn(
            "<td>The Placeholder Band/Invented Album/05 e.mp3</td>",
            self.section("icloud-placeholders"),
        )

    def test_unparsed_rows_are_a_count_with_no_table(self) -> None:
        section = self.section("unparsed-rows")
        self.assertIn('<span class="count">1</span>', section)
        self.assertNotIn("<table>", section)


class SummaryTest(unittest.TestCase):
    """The summary: every check in report order, linked, zero, or not run."""

    def summary(self, report: dict[str, object]) -> str:
        """The summary section of *report*'s page."""
        page = audit_html.format_html(report)
        start = page.index('<section id="summary">')
        return page[start : page.index("</section>", start)]

    def test_a_check_with_findings_links_to_its_section(self) -> None:
        summary = self.summary(hf.report(no_track=[f"{hf.LIBRARY}/a.mp3"]))
        self.assertIn(
            '<tr><td><a href="#no-track">Files with no Music.app track</a></td>'
            '<td class="num">1</td></tr>',
            summary,
        )

    def test_a_clean_check_reads_zero_and_has_no_section(self) -> None:
        report = hf.report()
        self.assertIn(
            '<tr><td>Files with no track number</td><td class="num">0</td></tr>',
            self.summary(report),
        )
        # The summary is the only section a clean report's page holds.
        self.assertEqual(audit_html.format_html(report).count("<section id="), 1)

    def test_skipped_tag_checks_and_the_decode_read_not_run(self) -> None:
        report = hf.report(
            track_gaps=None,
            split_albums=None,
            no_track_number=None,
            unreadable_tags=None,
        )
        summary = self.summary(report)
        for check in (
            "Track-number gaps",
            "Albums split by spelling",
            "Files with no track number",
            "Unreadable tags",
            "Files that do not decode",
        ):
            with self.subTest(check=check):
                self.assertIn(f"<tr><td>{check}</td><td>not run</td></tr>", summary)

    def test_every_check_is_listed_in_report_order(self) -> None:
        summary = self.summary(hf.report())
        order = [
            "Files with no Music.app track",
            "Music.app tracks whose file is gone",
            "Track-number gaps",
            "Albums split by spelling",
            "Files with no track number",
            "Files and Music.app tracks differ",
            "Unreadable tags",
            "Unreadable files and folders",
            "iCloud placeholders",
            "Music.app size differs from the file",
            "Unchecked tracks",
            "Files that do not decode",
            "Unparsed listing rows",
        ]
        places = [summary.index(f"<td>{check}</td>") for check in order]
        self.assertEqual(places, sorted(places))


class EscapingTest(unittest.TestCase):
    """Every value from the library is escaped, control characters shown."""

    _HOSTILE = 'Bad <script>alert(1)</script> & "quoted" \x07bell'

    def test_a_hostile_name_is_text_not_markup(self) -> None:
        report = hf.report(
            no_track=[f"{hf.LIBRARY}/{self._HOSTILE}.mp3"],
            file_gone=[
                {
                    **hf.track(artist=self._HOSTILE, album=self._HOSTILE),
                    "cloud_status": "x",
                }
            ],
        )
        page = audit_html.format_html(report)
        self.assertNotIn("<script", page.lower())
        self.assertNotIn("\x07", page)
        escaped = (
            "Bad &lt;script&gt;alert(1)&lt;/script&gt; &amp; &quot;quoted&quot;"
            " \\x07bell"
        )
        self.assertIn(f"<td>{escaped}.mp3</td>", page)
        self.assertIn(f"<td>{escaped}</td><td>{escaped}</td>", page)
        self.assertEqual(hf.Page(page).stack, [])

    def test_a_hostile_library_path_is_escaped_in_the_header(self) -> None:
        page = audit_html.format_html(hf.report(library=f"/{self._HOSTILE}"))
        self.assertNotIn("<script", page.lower())
        self.assertIn("&lt;script&gt;", page)

    def test_hand_built_split_and_reason_cells_are_escaped(self) -> None:
        hostile = f"{self._HOSTILE} \udcff"
        report = hf.report(
            split_albums=[
                {
                    "disc": 1,
                    "spellings": [
                        {"artist": hostile, "album": hostile, "tracks": [1]},
                        {"artist": "Plain", "album": "Plain", "tracks": [2]},
                    ],
                    "still_missing": [],
                    "differs": [{"between": [0, 1], "artist": hostile, "album": None}],
                }
            ],
            unreadable_paths=[{"path": "/elsewhere/x", "reason": hostile}],
        )
        page = audit_html.format_html(report)
        page.encode("utf-8")
        self.assertNotIn("<script", page.lower())
        self.assertNotIn("\x07", page)
        escaped = (
            "Bad &lt;script&gt;alert(1)&lt;/script&gt; &amp; &quot;quoted&quot;"
            " \\x07bell \\udcff"
        )
        self.assertIn(f"<li>{escaped} / {escaped}: track 1</li>", page)
        self.assertIn(f"<li>1 and 2 differ in the artist: {escaped}</li>", page)
        self.assertIn(f"<td>/elsewhere/x</td><td>{escaped}</td>", page)
        self.assertEqual(hf.Page(page).stack, [])

    def test_a_lone_surrogate_is_shown_not_raised(self) -> None:
        page = audit_html.format_html(hf.report(no_track=[f"{hf.LIBRARY}/a\udcff.mp3"]))
        self.assertIn("<td>a\\udcff.mp3</td>", page)
        page.encode("utf-8")


if __name__ == "__main__":
    unittest.main()
