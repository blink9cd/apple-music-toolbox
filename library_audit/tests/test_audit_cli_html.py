"""The entry point's ``--format html``: it needs ``--report``, and is never inferred.

Every run goes through `main` with an `audit_fixtures.FakeMusic` runner; nothing reaches
Music.app. The page itself is `test_audit_html`'s; here only how the CLI picks the
format, refuses it, and writes it.
"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(_HERE), str(_HERE.parent)]

import audit_fixtures as af  # noqa: E402 - import follows the sys.path bootstrap above

#: A tag reader that reads nothing: tag checks run, and find every file unreadable.
_NO_TAGS = af.tag_table({})


class HtmlFormatTest(af.AuditCase):
    """``--format html`` against a library of one file Music lacks."""

    def setUp(self) -> None:
        """One file Music lacks, and a folder outside the library for reports."""
        super().setUp()
        self.lost = self.album("Band/Album", "01 a.mp3")[0]
        (self.root / "out").mkdir()

    def test_html_without_a_report_is_refused_before_any_call(self) -> None:
        music = af.FakeMusic()
        result = self.audit(music, "--format", "html")
        self.assertEqual(result.code, af.USAGE)
        self.assertEqual(music.calls, [])
        self.assertEqual(result.stdout, "")
        self.assertEqual(len(result.stderr.strip().splitlines()), 1)
        self.assertIn("--format html needs --report", result.stderr)

    def test_html_with_a_report_inside_a_working_tree_is_refused(self) -> None:
        (self.root / "repo" / ".git").mkdir(parents=True)
        music = af.FakeMusic()
        target = self.root / "repo" / "audit.html"
        result = self.audit(music, "--format", "html", "--report", str(target))
        self.assertEqual(result.code, af.USAGE)
        self.assertIn("git working tree", result.stderr)
        self.assertEqual(music.calls, [])
        self.assertFalse(target.exists())

    def test_html_with_a_report_writes_the_page(self) -> None:
        target = self.root / "out" / "audit.html"
        result = self.audit(
            af.FakeMusic(),
            "--format",
            "html",
            "--report",
            str(target),
            tag_reader=_NO_TAGS,
        )
        self.assertEqual(result.code, af.FINDINGS)
        self.assertEqual(result.stdout, "")
        page = target.read_text(encoding="utf-8")
        self.assertTrue(page.startswith("<!DOCTYPE html>\n"))
        self.assertIn('<section id="no-track">', page)
        self.assertIn("<td>Band/Album/01 a.mp3</td>", page)

    def test_the_page_and_the_json_hold_the_same_counts(self) -> None:
        target = self.root / "out" / "audit.html"
        self.audit(
            af.FakeMusic(),
            "--format",
            "html",
            "--report",
            str(target),
            tag_reader=_NO_TAGS,
        )
        report = json.loads(
            self.audit(af.FakeMusic(), "--format", "json", tag_reader=_NO_TAGS).stdout
        )
        page = target.read_text(encoding="utf-8")
        self.assertIn(f"Findings: {report['findings']}<", page)
        self.assertIn(f"Audio files: {report['audio_files']}<", page)

    def test_an_html_report_name_with_the_default_format_writes_text(self) -> None:
        target = self.root / "out" / "audit.html"
        result = self.audit(af.FakeMusic(), "--report", str(target))
        self.assertEqual(result.code, af.FINDINGS)
        written = target.read_text(encoding="utf-8")
        self.assertTrue(written.startswith(f"library: {self.library}\n"))
        self.assertNotIn("<", written)

    def test_help_names_the_html_format_and_its_report(self) -> None:
        result = af.run_main(["--help"], None)
        self.assertIn("html", result.stdout)
        self.assertIn("--format html needs --report", result.stdout)


if __name__ == "__main__":
    unittest.main()
