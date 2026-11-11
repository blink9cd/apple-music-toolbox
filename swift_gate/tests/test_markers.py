"""Grouped suite: the ``// coverage: ignore`` marker, SWG003 and SWG004.

Regions are built by hand here rather than parsed, because what is under test is the
marker's reach: which regions a marker on a given line excludes.
"""

from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from _fixtures import write

import swgate_markers
from swgate_coverage import FunctionRegions, Region

FILE = "Sources/Lib/Lib.swift"

SOURCE = """\
public func covered(_ value: Int) -> Int {
  if value < 0 { return 0 }  // coverage: ignore: the caller clamps first
  return value
}

public func wrapped(  // coverage: ignore: a debugger-only aid
  _ value: Int
) -> Int {
  value + 1
}

public func reasonless() {  // coverage: ignore
}

let dead = 1  // coverage: ignore: nothing starts on this line
"""


def _region(file: Path, line: int, col: int, count: int = 0) -> Region:
    """A one-line code region starting at *line*:*col*."""
    return Region(file, line, col, line, col + 1, count)


class _MarkerCase(unittest.TestCase):
    """A temp package holding SOURCE, and the regions a compiler would give it."""

    def setUp(self) -> None:
        tmp = TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name).resolve()
        self.file = write(self.root / FILE, SOURCE)
        self.functions = (
            FunctionRegions(
                self.file,
                (
                    _region(self.file, 1, 42, 1),
                    _region(self.file, 2, 16),
                    _region(self.file, 3, 3, 1),
                ),
            ),
            FunctionRegions(
                self.file, (_region(self.file, 8, 10), _region(self.file, 9, 3))
            ),
            FunctionRegions(self.file, (_region(self.file, 12, 26),)),
        )

    def scan(self) -> tuple[tuple[swgate_markers.Marker, ...], list[str]]:
        """Markers and finding codes from SOURCE."""
        markers, findings = swgate_markers.scan_markers((self.file,), self.root)
        return markers, [f.code for f in findings]


class ScanTests(_MarkerCase):
    """SWG003 for a marker with no reason; the reasoned ones are kept."""

    def test_reasonless_marker_is_swg003(self) -> None:
        markers, codes = self.scan()
        self.assertEqual(codes, ["SWG003"])
        self.assertEqual([m.line for m in markers], [2, 6, 15])

    def test_blank_reason_is_swg003(self) -> None:
        write(self.file, "let x = 1  // coverage: ignore:   \n")
        _, codes = self.scan()
        self.assertEqual(codes, ["SWG003"])

    def test_function_marker_finds_the_brace_on_a_later_line(self) -> None:
        markers, _ = self.scan()
        wrapped = markers[1]
        self.assertTrue(wrapped.declares_function)
        self.assertEqual(wrapped.body_line, 8)

    def test_init_marker_declares_a_function(self) -> None:
        write(self.file, "  init() {  // coverage: ignore: unreachable here\n  }\n")
        markers, _ = self.scan()
        self.assertEqual(
            (markers[0].declares_function, markers[0].body_line), (True, 1)
        )

    def test_function_marker_without_a_brace_has_no_body(self) -> None:
        write(self.file, "func f()  // coverage: ignore: a protocol requirement\n")
        markers, _ = self.scan()
        self.assertIsNone(markers[0].body_line)


class ApplyTests(_MarkerCase):
    """What each reasoned marker excludes, and SWG004 for one that excludes nothing."""

    def apply(self) -> tuple[frozenset[tuple[object, ...]], list[str]]:
        markers, _ = self.scan()
        excluded, findings = swgate_markers.apply_markers(
            markers, self.functions, self.root
        )
        return excluded, [f.code for f in findings]

    def test_line_marker_excludes_its_lines_regions(self) -> None:
        excluded, _ = self.apply()
        self.assertIn(_region(self.file, 2, 16).key, excluded)
        self.assertNotIn(_region(self.file, 3, 3, 1).key, excluded)

    def test_func_marker_excludes_the_whole_wrapped_body(self) -> None:
        excluded, _ = self.apply()
        self.assertIn(_region(self.file, 8, 10).key, excluded)
        self.assertIn(_region(self.file, 9, 3).key, excluded)

    def test_dead_marker_is_swg004(self) -> None:
        _, codes = self.apply()
        self.assertEqual(codes, ["SWG004"])

    def test_marker_in_another_file_excludes_nothing_here(self) -> None:
        other = write(
            self.root / "Sources/Lib/Other.swift",
            "let y = 2  // coverage: ignore: n/a\n",
        )
        markers, _ = swgate_markers.scan_markers((other,), self.root)
        excluded, findings = swgate_markers.apply_markers(
            markers, self.functions, self.root
        )
        self.assertEqual(
            (excluded, [f.code for f in findings]), (frozenset(), ["SWG004"])
        )


if __name__ == "__main__":
    unittest.main()
