"""report_file's delivery half: the audits' ``--format`` and ``--report``, checked and written.

Each audit's own CLI suite proves the whole run; this one pins the shared helpers
alone, on a bare parser, so a change to one is caught here before either audit runs.
Every tree is made under a fresh temporary directory, and the "working tree" is only a
folder holding a ``.git`` entry; no git command is run.
"""

from __future__ import annotations

import argparse
import contextlib
import io
import sys
import unittest
from pathlib import Path
from unittest import mock

_HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(_HERE), str(_HERE.parent / "src")]

import refresh_fixtures as rf  # noqa: E402 - import follows the sys.path bootstrap above
import report_file  # noqa: E402 - import follows the sys.path bootstrap above

#: argparse's exit code for a refused option.
_USAGE = 2


def _parser() -> argparse.ArgumentParser:
    """A bare parser declaring ``--format`` and ``--report`` as both audits do."""
    parser = argparse.ArgumentParser(prog="audit")
    parser.add_argument(
        "--format", choices=report_file.FORMATS, default=report_file.FORMAT_TEXT
    )
    parser.add_argument("--report", type=Path)
    return parser


class FormatsTest(unittest.TestCase):
    """The ``--format`` values both audits offer."""

    def test_the_formats_are_text_json_and_html_in_that_order(self) -> None:
        self.assertEqual(report_file.FORMATS, ("text", "json", "html"))
        self.assertEqual(
            (report_file.FORMAT_TEXT, report_file.FORMAT_JSON, report_file.FORMAT_HTML),
            report_file.FORMATS,
        )


class RefuseBadReportTest(rf.TreeCase):
    """A ``--report`` that cannot be written is refused before any work."""

    def refused(self, *argv: str) -> tuple[int | None, str]:
        """Parse *argv* and check the report; the exit code (None: accepted), stderr."""
        parser = _parser()
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            try:
                report_file.refuse_bad_report(parser, parser.parse_args(argv))
            except SystemExit as stop:
                return int(str(stop.code)), stderr.getvalue()
        return None, stderr.getvalue()

    def test_no_report_is_accepted(self) -> None:
        self.assertEqual(self.refused(), (None, ""))

    def test_a_writable_report_is_accepted(self) -> None:
        self.assertEqual(self.refused("--report", str(self.root / "r.txt")), (None, ""))

    def test_a_report_inside_a_working_tree_exits_two_through_the_parser(self) -> None:
        (self.root / "repo" / ".git").mkdir(parents=True)
        code, stderr = self.refused("--report", str(self.root / "repo" / "r.txt"))
        self.assertEqual(code, _USAGE)
        self.assertIn("audit: error: --report: ", stderr)
        self.assertIn("git working tree", stderr)


class RefuseHtmlToStdoutTest(unittest.TestCase):
    """HTML goes to a file only."""

    def test_html_with_no_report_is_refused_with_the_shared_reason(self) -> None:
        args = _parser().parse_args(["--format", "html"])
        self.assertEqual(
            report_file.refuse_html_to_stdout(args), report_file.HTML_NEEDS_REPORT
        )
        self.assertEqual(
            report_file.HTML_NEEDS_REPORT,
            "--format html needs --report: the page is written to a file only",
        )

    def test_html_with_a_report_and_every_other_format_are_accepted(self) -> None:
        for argv in (
            ["--format", "html", "--report", "r.html"],
            ["--format", "json"],
            [],
        ):
            with self.subTest(argv=argv):
                args = _parser().parse_args(argv)
                self.assertIsNone(report_file.refuse_html_to_stdout(args))


class DeliverReportTest(rf.TreeCase):
    """The report printed, or written whole; a refusal said and reported as False."""

    def setUp(self) -> None:
        """Collect every notice the delivery gives, and what it prints."""
        super().setUp()
        self.notices: list[str] = []
        self.out = io.StringIO()

    def deliver(self, report: Path | None, text: str = "the report\n") -> bool:
        """Deliver *text* to *report*, as the tool ``audit``."""
        return report_file.deliver_report(
            text, report, prog="audit", out=self.out, notice=self.notices.append
        )

    def test_no_report_prints_the_text_unchanged(self) -> None:
        self.assertTrue(self.deliver(None, "one\ntwo"))
        self.assertEqual(self.out.getvalue(), "one\ntwo")
        self.assertEqual(self.notices, [])

    def test_a_report_is_written_as_utf8_and_nothing_printed(self) -> None:
        target = self.root / "r.txt"
        self.assertTrue(self.deliver(target, "café\n"))
        self.assertEqual(self.out.getvalue(), "")
        self.assertEqual(target.read_bytes(), "café\n".encode())
        self.assertEqual(self.notices, [])

    def test_a_report_refused_at_delivery_is_said_and_not_written(self) -> None:
        (self.root / "repo" / ".git").mkdir(parents=True)
        target = self.root / "repo" / "r.txt"
        self.assertFalse(self.deliver(target))
        self.assertFalse(target.exists())
        self.assertEqual(len(self.notices), 1)
        self.assertTrue(self.notices[0].startswith("audit: --report: "))

    def test_a_failed_write_names_the_report_and_the_os_reason(self) -> None:
        target = self.root / "r.txt"
        failure = OSError(28, "No space left on device")
        with mock.patch.object(report_file, "write_atomically", side_effect=failure):
            self.assertFalse(self.deliver(target))
        self.assertEqual(
            self.notices,
            [f"audit: cannot write the report {target}: No space left on device"],
        )

    def test_a_failed_write_with_no_os_reason_names_the_error(self) -> None:
        target = self.root / "r.txt"
        with mock.patch.object(
            report_file, "write_atomically", side_effect=OSError("invented")
        ):
            self.assertFalse(self.deliver(target))
        self.assertEqual(
            self.notices, [f"audit: cannot write the report {target}: invented"]
        )

    def test_ctrl_c_during_the_write_reaches_the_caller(self) -> None:
        with (
            mock.patch.object(
                report_file, "write_atomically", side_effect=KeyboardInterrupt
            ),
            self.assertRaises(KeyboardInterrupt),
        ):
            self.deliver(self.root / "r.txt")


if __name__ == "__main__":
    unittest.main()
