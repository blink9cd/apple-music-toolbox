"""The HTML page, pinned byte for byte on three representative reports.

`test_audit_html` checks the page's parts; this suite pins the whole page, so a change
to the shared page frame (`html_page`) that alters a single byte of `library_audit`'s
output fails here. Each page is pinned by its length
and SHA-256 digest rather than a committed copy, so no generated page enters the tree.
A deliberate change to the page re-derives the three pins from the new output, and the
diff shows that the page changed on purpose.
"""

from __future__ import annotations

import hashlib
import sys
import unittest
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(_HERE), str(_HERE.parent)]

import library_audit  # noqa: E402, F401 - puts src/ and the seam on sys.path
import audit_html  # noqa: E402 - import follows the sys.path bootstrap above
import html_fixtures as hf  # noqa: E402 - import follows the sys.path bootstrap above

#: A report whose one listed path needs escaping (markup, quotes, a control
#: character), with two tag checks not run and the decode run.
_ODD = hf.report(
    findings=1,
    no_track=[f'{hf.LIBRARY}/A <b>&amp; "q" \x07/x.mp3'],
    no_track_number=None,
    unreadable_tags=None,
    decode_skipped=2,
)

#: Each report's page: its length in characters and the SHA-256 of its UTF-8 bytes.
_PINS = {
    "every section": (
        hf.full_report(),
        9329,
        "03f1e85cf9d75c760fe423cee452ca1005f03413bc137f3de8af54163a74ffc5",
    ),
    "clean": (
        hf.report(),
        3407,
        "37abcb4ab0203a3a0e75ee050164868e0c1d5be1c0ea632691bb63244436caf3",
    ),
    "escaped, not run": (
        _ODD,
        3801,
        "852ae5a35338fad142584611a5c368a45d365cabbff5d869a0ea4b2f6d00970a",
    ),
}


class GoldenPageTest(unittest.TestCase):
    """Each representative report renders to exactly the pinned page."""

    def test_each_page_is_byte_identical_to_its_pin(self) -> None:
        for name, (report, length, digest) in _PINS.items():
            with self.subTest(report=name):
                page = audit_html.format_html(report)
                self.assertEqual(len(page), length)
                self.assertEqual(
                    hashlib.sha256(page.encode("utf-8")).hexdigest(), digest
                )


if __name__ == "__main__":
    unittest.main()
