"""phone_report: the text and JSON reports, pinned whole, and the exit code.

Pure: every audit is invented here.
"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(_HERE), str(_HERE.parent)]

import phone_audit  # noqa: E402, F401 - puts src/ and the shared helpers on sys.path
import phone_compare as pc  # noqa: E402 - import follows the sys.path bootstrap above
import phone_report as pr  # noqa: E402 - import follows the sys.path bootstrap above

_GONE = pc.PhoneRow(
    1,
    "F01",
    "ABCD.mp3",
    100,
    "Second Title",
    1,
    2,
    "Invented Album",
    "The Placeholder Band",
)
_SIZED = pc.PhoneRow(
    2,
    "F02",
    "EFGH.m4a",
    200,
    "Third Title",
    2,
    3,
    "Invented Album",
    "The Placeholder Band",
)
_STRAY = pc.PhoneFile("F03", "WXYZ.mp3", 512)

_FULL_TEXT = """\
rows with no file on the phone: 1
  The Placeholder Band / Invented Album, disc 1 track 2: Second Title [F01/ABCD.mp3]
  note: a plain Finder sync does not repair these; add a character to each title, sync, restore it and sync again (phone_audit.md, "Repairing a row with no file")
size differs: 1
  The Placeholder Band / Invented Album, disc 2 track 3: Third Title [F02/EFGH.m4a]: phone file 150, database 200
files with no row: 1
  F03/WXYZ.mp3: 512 bytes
  note: listed only; neither a sync nor this tool removes them
summary: findings 3; rows in the sync 4, files 4; outside the sync 1, unparsed lines 1, sizes unknown 1, other entries 2
"""

_EMPTY_TEXT = """\
rows with no file on the phone: 0
size differs: 0
files with no row: 0
summary: findings 0; rows in the sync 0, files 0; outside the sync 0, unparsed lines 0, sizes unknown 0, other entries 0
"""


def _full() -> pr.Audit:
    """An audit with one of everything."""
    compared = pc.Compared((_GONE,), (pc.SizeDiffers(_SIZED, 150),), (_STRAY,), 1)
    return pr.Audit(
        compared,
        rows_in_sync=4,
        files=4,
        outside_sync=1,
        unparsed_lines=1,
        other_entries=2,
    )


def _empty() -> pr.Audit:
    """An audit that found nothing at all."""
    return pr.Audit(pc.Compared((), (), (), 0), 0, 0, 0, 0, 0)


class TextTest(unittest.TestCase):
    """Each section, its notes only when it lists something, then the summary."""

    def test_the_full_report(self) -> None:
        self.assertEqual(pr.format_text(_full()), _FULL_TEXT)

    def test_an_empty_report_has_no_notes(self) -> None:
        self.assertEqual(pr.format_text(_empty()), _EMPTY_TEXT)

    def test_a_control_character_in_a_name_cannot_split_a_line(self) -> None:
        row = pc.PhoneRow(1, "F01", "A\nB", 5, "T\x1b[31m", 1, 1, "Al\tbum", "Band\x7f")
        text = pr.format_text(pr.Audit(pc.Compared((row,), (), (), 0), 1, 0, 0, 0, 0))
        line = text.splitlines()[1]
        self.assertEqual(
            line, "  Band\\x7f / Al\\x09bum, disc 1 track 1: T\\x1b[31m [F01/A\\x0aB]"
        )
        self.assertEqual(len(text.splitlines()), 6)


class JsonTest(unittest.TestCase):
    """The same content, keyed, schema 1, plain ASCII."""

    def test_the_full_report(self) -> None:
        report = json.loads(pr.format_json(_full()))
        self.assertEqual(report["schema"], 1)
        self.assertEqual(
            report["no_file"],
            [
                {
                    "item_pid": 1,
                    "artist": "The Placeholder Band",
                    "album": "Invented Album",
                    "disc": 1,
                    "track": 2,
                    "title": "Second Title",
                    "folder": "F01",
                    "name": "ABCD.mp3",
                    "database_size": 100,
                }
            ],
        )
        self.assertEqual(report["size_differs"][0]["phone_size"], 150)
        self.assertEqual(report["size_differs"][0]["database_size"], 200)
        self.assertEqual(
            report["files_no_row"], [{"folder": "F03", "name": "WXYZ.mp3", "size": 512}]
        )
        self.assertEqual(
            report["summary"],
            {
                "findings": 3,
                "rows_in_sync": 4,
                "files": 4,
                "outside_sync": 1,
                "unparsed_lines": 1,
                "sizes_unknown": 1,
                "other_entries": 2,
            },
        )

    def test_the_json_is_the_report_object_serialized(self) -> None:
        # The HTML page is rendered from this very object, so the two cannot disagree.
        for audit in (_full(), _empty()):
            with self.subTest(audit=audit):
                self.assertEqual(
                    json.loads(pr.format_json(audit)), pr.report_dict(audit)
                )

    def test_it_is_plain_ascii_whatever_the_names(self) -> None:
        row = pc.PhoneRow(1, "F01", "é\ud800", None, "", 1, 1, "", "")
        text = pr.format_json(pr.Audit(pc.Compared((row,), (), (), 0), 1, 0, 0, 0, 0))
        text.encode("ascii")
        self.assertIsNone(json.loads(text)["no_file"][0]["database_size"])


class ExitCodeTest(unittest.TestCase):
    """1 when anything was found, an unparsed line included; else 0."""

    def test_findings(self) -> None:
        self.assertEqual(pr.finding_count(_full()), 3)
        self.assertEqual(pr.exit_code(_full()), pr.EXIT_FINDINGS)

    def test_nothing_found(self) -> None:
        self.assertEqual(pr.exit_code(_empty()), pr.EXIT_OK)

    def test_files_with_no_row_alone_are_not_findings(self) -> None:
        audit = pr.Audit(pc.Compared((), (), (_STRAY,), 0), 0, 1, 0, 0, 0)
        self.assertEqual(pr.exit_code(audit), pr.EXIT_OK)

    def test_an_unparsed_line_alone_is_a_finding(self) -> None:
        audit = pr.Audit(pc.Compared((), (), (), 0), 0, 0, 0, 1, 0)
        self.assertEqual(pr.exit_code(audit), pr.EXIT_FINDINGS)


if __name__ == "__main__":
    unittest.main()
