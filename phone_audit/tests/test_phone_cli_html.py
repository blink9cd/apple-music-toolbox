"""The entry point's ``--format html``: it needs ``--report``, and is never inferred.

Every run goes through `main` with a `phone_fixtures.FakePhone` runner; nothing reaches
a phone. The page itself is `test_phone_html`'s; here only how the CLI picks the format,
refuses it, stamps when the phone was read, and writes it.
"""

from __future__ import annotations

import json
import sys
import unittest
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory

_HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(_HERE), str(_HERE.parent)]

import phone_audit as pa  # noqa: E402 - import follows the sys.path bootstrap above
import phone_fixtures as pf  # noqa: E402 - import follows the sys.path bootstrap above
import afc_calls  # noqa: E402 - import follows the sys.path bootstrap above

#: When the fixed clock says the phone was read.
_READ_AT = datetime(2026, 10, 26, 14, 3)


def _phone() -> pf.FakePhone:
    """A phone with one row whose file is gone."""
    gone = pf.Row(1, pf.base("F00"), "BBBB.mp3", 100, "Second Title", 1, 2)
    return pf.phone_with([gone], {"F00": {}})


def _wiring(phone: pf.FakePhone) -> pa.Wiring:
    """*phone* as the runner, afcclient found, and the fixed clock."""
    return pa.Wiring(run=phone, which=lambda _name: pf.BINARY, clock=lambda: _READ_AT)


class HtmlFormatTest(unittest.TestCase):
    """``--format html`` against a phone with one row and no file."""

    def setUp(self) -> None:
        """A scratch folder outside any repository for reports."""
        super().setUp()
        scratch = TemporaryDirectory()
        self.addCleanup(scratch.cleanup)
        self.out = Path(scratch.name)

    def test_html_without_a_report_is_refused_before_any_call(self) -> None:
        phone = _phone()
        result = pf.run_main(["--format", "html"], _wiring(phone))
        self.assertEqual(result.code, pf.USAGE)
        self.assertEqual(phone.calls, [])
        self.assertEqual(result.stdout, "")
        self.assertEqual(len(result.stderr.strip().splitlines()), 1)
        self.assertIn("--format html needs --report", result.stderr)

    def test_html_with_a_report_inside_a_working_tree_is_refused(self) -> None:
        (self.out / "repo" / ".git").mkdir(parents=True)
        phone = _phone()
        target = self.out / "repo" / "phone.html"
        result = pf.run_main(
            ["--format", "html", "--report", str(target)], _wiring(phone)
        )
        self.assertEqual(result.code, pf.USAGE)
        self.assertIn("git working tree", result.stderr)
        self.assertEqual(phone.calls, [])
        self.assertFalse(target.exists())

    def test_html_with_a_report_writes_the_page(self) -> None:
        target = self.out / "phone.html"
        result = pf.run_main(
            ["--format", "html", "--report", str(target)], _wiring(_phone())
        )
        self.assertEqual(result.code, pf.FINDINGS)
        self.assertEqual(result.stdout, "")
        page = target.read_text(encoding="utf-8")
        self.assertTrue(page.startswith("<!DOCTYPE html>\n"))
        self.assertIn("Read from the iPhone on 2026-10-26 at 14:03.", page)
        self.assertIn("<td>F00/BBBB.mp3</td>", page)
        self.assertEqual(target.stat().st_mode & 0o777, 0o600)

    def test_the_page_and_the_json_hold_the_same_counts(self) -> None:
        target = self.out / "phone.html"
        pf.run_main(["--format", "html", "--report", str(target)], _wiring(_phone()))
        report = json.loads(pf.run_main(["--format", "json"], _wiring(_phone())).stdout)
        page = target.read_text(encoding="utf-8")
        for label, key in (("Findings", "findings"), ("Files", "files")):
            with self.subTest(figure=label):
                self.assertIn(
                    f'<td>{label}</td><td class="num">{report["summary"][key]}</td>',
                    page,
                )

    def test_an_html_report_name_with_the_default_format_writes_text(self) -> None:
        target = self.out / "phone.html"
        result = pf.run_main(["--report", str(target)], _wiring(_phone()))
        self.assertEqual(result.code, pf.FINDINGS)
        written = target.read_text(encoding="utf-8")
        self.assertTrue(written.startswith("rows with no file on the phone: 1\n"))
        self.assertNotIn("<", written)

    def test_help_names_the_html_format_and_its_report(self) -> None:
        text = pa.build_parser().format_help()
        self.assertIn("html", text)
        self.assertIn("--format html needs --report", text)


class ClockTest(unittest.TestCase):
    """The real clock: the local time, aware of its zone."""

    def test_the_real_wiring_reads_the_local_clock(self) -> None:
        self.assertIs(pa.real_wiring().clock, pa.local_now)
        self.assertEqual(
            pa.real_wiring(),
            pa.Wiring(afc_calls.real_run, pa.shutil.which, pa.local_now),
        )

    def test_local_now_is_aware(self) -> None:
        self.assertIsNotNone(pa.local_now().tzinfo)


if __name__ == "__main__":
    unittest.main()
