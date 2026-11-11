"""Grouped suite: ``fixtures/floorpkg`` gated for real, by the real toolchain.

The unit suites fake the ``_run_swift`` seam wholesale, so only this suite proves the
argv, the scratch layout and the export shape against SwiftPM itself. Each run gates a
copy of the fixture in a temp dir, beside a temp ``pyproject.toml`` carrying the floor,
with the scratch dir in the same temp dir, so nothing is written into the checkout and
nothing outlives the test. Skipped with a reason off macOS or without ``swift``.
"""

from __future__ import annotations

import io
import shutil
import sys
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory

from _fixtures import FLOORPKG, write

import swift_gate

_SWIFT = shutil.which("swift")
_LIVE = sys.platform == "darwin" and _SWIFT is not None
_SKIP_REASON = "needs macOS and the swift toolchain (prerequisite group 'swift')"
_UNTESTED_CASE = """\
@Test func zeroIsZero() {
  #expect(classify(0) == .zero)
}
"""


@unittest.skipUnless(_LIVE, _SKIP_REASON)
class LiveFloorPackageTests(unittest.TestCase):
    """The real build, test and coverage export, end to end."""

    def gate_copy(self, *, drop_test: bool) -> tuple[int, str]:
        """Copy floorpkg to a temp tree, optionally minus one test, and gate it."""
        with TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            write(root / "pyproject.toml", '[tool.swift_gate]\nmacos_floor = "14"\n')
            package = root / "floorpkg"
            shutil.copytree(FLOORPKG, package)
            if drop_test:
                tests = package / "Tests" / "FloorTests" / "FloorTests.swift"
                text = tests.read_text(encoding="utf-8")
                self.assertIn(_UNTESTED_CASE, text)
                write(tests, text.replace(_UNTESTED_CASE, ""))
            out = io.StringIO()
            with redirect_stdout(out), redirect_stderr(out):
                code = swift_gate.main(
                    ["--path", str(root), "--scratch-path", str(root / "scratch")]
                )
            return code, out.getvalue()

    def test_floorpkg_passes_at_full_region_coverage(self) -> None:
        code, out = self.gate_copy(drop_test=False)
        self.assertEqual(code, 0, out)
        self.assertIn("region coverage 100.00%", out)

    def test_a_missing_test_names_the_uncovered_region(self) -> None:
        code, out = self.gate_copy(drop_test=True)
        self.assertEqual(code, 1, out)
        self.assertIn("miss Sources/Floor/Floor.swift:13:23", out)


if __name__ == "__main__":
    unittest.main()
