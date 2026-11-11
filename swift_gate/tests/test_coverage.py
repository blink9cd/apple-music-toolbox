"""Grouped suite: the llvm-cov export parsed into code regions, and the percent over them.

The fixture is the trimmed real export captured from ``fixtures/floorpkg``: the library's
two functions, its three tests, and the SwiftPM-generated test runner, which lives under
the scratch dir and so stands in for every file outside the package's ``Sources/``.
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from hypothesis import given
from hypothesis import strategies as st

from _fixtures import export_data, export_functions

import swgate_coverage
from swgate_model import ParseError

LIB = "Sources/Floor/Floor.swift"


class _ExportCase(unittest.TestCase):
    """A temp package root and scratch dir the export's placeholders point at."""

    def setUp(self) -> None:
        tmp = TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name).resolve() / "floorpkg"
        self.scratch = Path(tmp.name).resolve() / "scratch"
        self.data = export_data(self.root, self.scratch)

    def parse(
        self, excludes: tuple[Path, ...] = ()
    ) -> tuple[swgate_coverage.FunctionRegions, ...]:
        """Parse the (possibly edited) export against this case's root."""
        return swgate_coverage.parse_export(json.dumps(self.data), self.root, excludes)


class ParseExportTests(_ExportCase):
    """Only the package's own Sources/, and only code regions, are measured."""

    def test_only_library_functions_are_kept(self) -> None:
        functions = self.parse()
        self.assertEqual(len(functions), 2)
        self.assertEqual({f.file for f in functions}, {self.root / LIB})

    def test_test_and_dependency_files_are_ignored(self) -> None:
        dependency = (
            self.scratch / "checkouts" / "Dep" / "Sources" / "Dep" / "Dep.swift"
        )
        export_functions(self.data)[0]["filenames"] = [str(dependency)]
        names = {f.file.name for f in self.parse()}
        self.assertEqual(names, {"Floor.swift"})

    def test_non_code_region_kinds_are_ignored(self) -> None:
        classify = export_functions(self.data)[-2]
        regions = classify["regions"]
        assert isinstance(regions, list)
        regions.append([12, 4, 12, 5, 0, 0, 0, 3])  # a gap region, never executed
        regions.append([13, 1, 13, 2, 0, 0, 0, 2])  # a skipped region
        measured = swgate_coverage.measure(self.parse(), frozenset(), self.root)
        self.assertEqual(measured.total, 7)

    def test_excluded_sources_are_ignored(self) -> None:
        self.assertEqual(self.parse((self.root / "Sources" / "Floor",)), ())

    def test_malformed_exports_are_parse_errors(self) -> None:
        for bad in (
            "{",
            "[]",
            '{"data": []}',
            '{"data": [{"functions": [{}]}]}',
            '{"data": [{"functions": {}}]}',
            '{"data": [{"functions": [[]]}]}',
        ):
            with self.subTest(bad=bad), self.assertRaises(ParseError):
                swgate_coverage.parse_export(bad, self.root, ())

    def test_a_short_region_tuple_is_a_parse_error(self) -> None:
        export_functions(self.data)[-1]["regions"] = [[17, 48, 19, 2, 0]]
        with self.assertRaises(ParseError):
            self.parse()

    @given(st.text(max_size=200))
    def test_fuzz_parse_export(self, text: str) -> None:
        """Never-crash: any text gives regions or raises ParseError, nothing else."""
        try:
            swgate_coverage.parse_export(text, Path("/pkg"), ())
        except ParseError:
            pass


class MeasureTests(_ExportCase):
    """The percent, the misses as file:line:col, and the vacuous case."""

    def test_percent_from_the_fixture_export(self) -> None:
        measured = swgate_coverage.measure(self.parse(), frozenset(), self.root)
        self.assertEqual((measured.covered, measured.total), (6, 7))
        self.assertAlmostEqual(measured.percent or 0.0, 600 / 7)

    def test_misses_render_as_file_line_col(self) -> None:
        measured = swgate_coverage.measure(self.parse(), frozenset(), self.root)
        self.assertEqual(measured.misses, (f"{LIB}:17:48",))

    def test_excluded_regions_leave_the_total(self) -> None:
        functions = self.parse()
        excluded = frozenset(r.key for r in functions[-1].regions)
        measured = swgate_coverage.measure(functions, excluded, self.root)
        self.assertEqual(
            (measured.covered, measured.total, measured.percent), (6, 6, 100.0)
        )

    def test_duplicate_spans_count_once_and_covered_if_any_is(self) -> None:
        functions = export_functions(self.data)
        twin = json.loads(json.dumps(functions[-1]))
        twin["regions"][0][4] = 5
        functions.append(twin)
        measured = swgate_coverage.measure(self.parse(), frozenset(), self.root)
        self.assertEqual((measured.covered, measured.total), (7, 7))

    def test_zero_regions_is_vacuous(self) -> None:
        measured = swgate_coverage.measure((), frozenset(), self.root)
        self.assertIsNone(measured.percent)
        self.assertEqual(measured.total, 0)


if __name__ == "__main__":
    unittest.main()
