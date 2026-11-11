#!/usr/bin/env python3
"""Grouped suite: whether a ``tests/`` dir's suites are actually reached.

One of the modules under ``tests/`` that ``test_tool_subdirs.py`` aggregates. It owns
both halves of the grouped-suite reachability question: the aggregator's ABSENCE
(:func:`tool_subdirs.suite_orphan_reason`, a listing question) and, when it is present,
whether it reaches each suite at all (:func:`tool_subdirs.unreached_suites`, a source
question). The second half exists because the first was once the whole check: an
aggregator holding its own tests and no discovery code satisfied it, and a regression
test filed in the ``tests/`` beside it never ran while its folder gated PASS at 100%.
"""

from __future__ import annotations

import unittest

import tool_subdirs

# The direct listing of a tests/ dir as callers pass it: two suites, plus the kinds of
# file a suite dir legitimately holds that are NOT suites and must never be reported.
_LISTING = ["test_alpha.py", "test_beta.py", "_fixtures.py", "helpers.py", "README.md"]
# Both suites in _LISTING: the answer for an aggregator that reaches neither.
_SUITES = ["test_alpha.py", "test_beta.py"]
# The import spellings that reach a suite only beside a top-level load_tests.
_NON_STAR_SPELLINGS = (
    "import test_alpha",
    "import test_alpha as alpha",
    "from test_alpha import AlphaTests",
    "from tests import test_alpha",
    "from tests.test_alpha import AlphaTests",
    "import tests.test_alpha",
)
# unittest's load_tests protocol hook, defined at the aggregator's top level.
_LOAD_TESTS = "def load_tests(loader, tests, pattern):\n    return tests\n"


class SuiteOrphanReasonTests(unittest.TestCase):
    """Reporting a pruned tests/ whose suites nothing imports."""

    def test_no_reason_when_the_parent_holds_its_aggregator(self) -> None:
        self.assertIsNone(
            tool_subdirs.suite_orphan_reason(
                "widget", ["widget.py", "widget.md", "test_widget.py"]
            )
        )

    def test_a_missing_aggregator_yields_a_reason(self) -> None:
        self.assertIsNotNone(
            tool_subdirs.suite_orphan_reason("widget", ["widget.py", "widget.md"])
        )

    def test_the_reason_names_the_file_the_reader_must_create(self) -> None:
        reason = tool_subdirs.suite_orphan_reason("widget", ["widget.py"])
        assert reason is not None  # narrowed for mypy; asserted by the test above
        self.assertIn("test_widget.py", reason)

    def test_the_reason_names_the_convention(self) -> None:
        reason = tool_subdirs.suite_orphan_reason("widget", ["widget.py"])
        assert reason is not None  # narrowed for mypy
        self.assertIn(tool_subdirs.SUITE_DIR_NAME, reason)

    def test_the_reason_is_a_single_line(self) -> None:
        # Consumers splice it into a per-finding report row -- on either wording.
        for listing in (["widget.py"], ["widget.py", "test_gadget.py"]):
            with self.subTest(listing=listing):
                reason = tool_subdirs.suite_orphan_reason("widget", listing)
                assert reason is not None  # narrowed for mypy
                self.assertNotIn("\n", reason)

    def test_an_empty_parent_listing_is_an_orphan(self) -> None:
        self.assertIsNotNone(tool_subdirs.suite_orphan_reason("widget", []))

    def test_a_hyphenated_folder_is_satisfied_by_the_folded_aggregator(self) -> None:
        self.assertIsNone(
            tool_subdirs.suite_orphan_reason("lock-phone", ["test_lock_phone.py"])
        )

    def test_the_unfolded_spelling_does_not_satisfy_a_hyphenated_folder(self) -> None:
        self.assertIsNotNone(
            tool_subdirs.suite_orphan_reason("lock-phone", ["test_lock-phone.py"])
        )

    def test_another_tools_test_file_does_not_satisfy_the_aggregator(self) -> None:
        self.assertIsNotNone(
            tool_subdirs.suite_orphan_reason("widget", ["widget.py", "test_gadget.py"])
        )

    def test_another_test_module_is_named_rather_than_the_conclusion_drawn(
        self,
    ) -> None:
        # A delivery *area* names its suite for the SCRIPT, not the folder, so the
        # aggregator is absent while the suites are imported all the same.
        reason = tool_subdirs.suite_orphan_reason(
            "delivery", ["build_delivery_zip.sh", "test_build_delivery_zip.py"]
        )
        assert reason is not None  # narrowed for mypy; the aggregator is absent
        self.assertIn("test_build_delivery_zip.py", reason)
        self.assertNotIn("nothing runs them", reason)

    def test_the_conclusion_survives_where_no_test_module_could_import_them(
        self,
    ) -> None:
        # Pinned against over-correction: hedging this case too would trade a false
        # statement for a useless one.
        reason = tool_subdirs.suite_orphan_reason("widget", ["widget.py"])
        assert reason is not None  # narrowed for mypy
        self.assertIn("nothing runs them", reason)


class UnreachedSuitesTests(unittest.TestCase):
    """Which ``test_*.py`` files an aggregator's source never reaches."""

    def _unreached(self, source: str) -> list[str]:
        return tool_subdirs.unreached_suites(source, _LISTING)

    def test_a_discover_call_reaches_every_suite(self) -> None:
        source = "import unittest\nunittest.TestLoader().discover('tests')\n"
        self.assertEqual(self._unreached(source), [])

    def test_a_discover_call_through_a_bound_loader_reaches_every_suite(self) -> None:
        source = (
            "def _grouped(loader):\n"
            "    return loader.discover(str(DIR), top_level_dir=str(DIR))\n"
        )
        self.assertEqual(self._unreached(source), [])

    def test_a_bare_function_named_discover_is_not_unittest_discovery(self) -> None:
        # The rule keys on an ATTRIBUTE call, the shape TestLoader.discover takes.
        self.assertEqual(
            self._unreached("discover('tests')\n"), ["test_alpha.py", "test_beta.py"]
        )

    def test_naming_discover_without_calling_it_reaches_nothing(self) -> None:
        self.assertEqual(
            self._unreached("found = loader.discover\n"),
            ["test_alpha.py", "test_beta.py"],
        )

    def test_a_star_import_reaches_its_own_suite_only(self) -> None:
        # A star import binds the suite's TestCases into the aggregator's namespace,
        # where unittest's module load finds them -- no load_tests needed.
        for spelling in ("from test_alpha import *", "from tests.test_alpha import *"):
            with self.subTest(spelling=spelling):
                self.assertEqual(self._unreached(spelling + "\n"), ["test_beta.py"])

    def test_a_non_star_import_without_load_tests_reaches_nothing(self) -> None:
        """Count only what runs.

        unittest runs the TestCases a module DEFINES or binds at top level. A module
        import binds only the module, and a named import binds a helper, so neither
        runs the suite's tests -- they are imports, not reach.
        """
        for spelling in _NON_STAR_SPELLINGS:
            with self.subTest(spelling=spelling):
                self.assertEqual(self._unreached(spelling + "\n"), _SUITES)

    def test_any_import_spelling_reaches_its_suite_beside_a_load_tests(self) -> None:
        # A top-level load_tests is the hook through which an imported module's tests
        # can be added to the run, so beside one any import counts.
        for spelling in (*_NON_STAR_SPELLINGS, "from test_alpha import *"):
            with self.subTest(spelling=spelling):
                source = f"{spelling}\n\n{_LOAD_TESTS}"
                self.assertEqual(self._unreached(source), ["test_beta.py"])

    def test_a_load_tests_that_is_not_top_level_does_not_count(self) -> None:
        nested = "class Holder:\n    def load_tests(self, a, b, c):\n        pass\n"
        self.assertEqual(self._unreached(f"import test_alpha\n{nested}"), _SUITES)

    def test_one_import_statement_may_reach_several_suites(self) -> None:
        for spelling in (
            "import test_alpha, test_beta",
            "from tests import test_alpha, test_beta",
        ):
            with self.subTest(spelling=spelling):
                source = f"{spelling}\n\n{_LOAD_TESTS}"
                self.assertEqual(self._unreached(source), [])

    def test_a_star_importing_aggregator_missing_one_suite_names_that_one(
        self,
    ) -> None:
        # The control_page / parse_fidelity shape: tests/ on sys.path, one star import
        # per suite. Adding a suite file without its import line orphans it alone.
        listing = ["test_alpha.py", "test_beta.py", "test_gamma.py"]
        source = "from test_alpha import *\nfrom test_gamma import *\n"
        self.assertEqual(
            tool_subdirs.unreached_suites(source, listing), ["test_beta.py"]
        )

    def test_an_aggregator_reaching_nothing_reports_every_suite_sorted(self) -> None:
        listing = ["test_zeta.py", "test_alpha.py"]
        source = "import unittest\n\nclass OwnTests(unittest.TestCase):\n    pass\n"
        self.assertEqual(
            tool_subdirs.unreached_suites(source, listing),
            ["test_alpha.py", "test_zeta.py"],
        )

    def test_an_unparseable_aggregator_reaches_nothing(self) -> None:
        # Its syntax error is lint's finding; here it must not read as a clean answer.
        source = "import test_alpha\nloader.discover(\n"
        self.assertEqual(self._unreached(source), ["test_alpha.py", "test_beta.py"])

    def test_a_source_holding_a_null_byte_reaches_nothing(self) -> None:
        # Older interpreters raise ValueError here rather than SyntaxError.
        self.assertEqual(
            self._unreached("import test_alpha\0\n"), ["test_alpha.py", "test_beta.py"]
        )

    def test_a_relative_import_reaches_nothing(self) -> None:
        # An aggregator is a top-level module, not a package member, so `from .`
        # cannot load a suite beside it.
        self.assertEqual(self._unreached("from . import test_alpha\n"), _SUITES)

    def test_a_same_named_module_in_another_package_is_not_the_suite(self) -> None:
        self.assertEqual(
            self._unreached("from other.test_alpha import AlphaTests\n"), _SUITES
        )

    def test_files_that_are_not_suites_are_never_reported(self) -> None:
        self.assertEqual(
            tool_subdirs.unreached_suites("", ["_fixtures.py", "test_data.json"]), []
        )

    def test_an_empty_listing_has_nothing_to_reach(self) -> None:
        self.assertEqual(tool_subdirs.unreached_suites("", []), [])


class SuiteReachReasonTests(unittest.TestCase):
    """The report line for an aggregator that exists but does not reach its suites."""

    def test_no_reason_when_discovery_reaches_every_suite(self) -> None:
        source = "unittest.TestLoader().discover('tests')\n"
        self.assertIsNone(tool_subdirs.suite_reach_reason("widget", source, _LISTING))

    def test_no_reason_when_there_is_no_suite_to_reach(self) -> None:
        self.assertIsNone(tool_subdirs.suite_reach_reason("widget", "", ["helpers.py"]))

    def test_the_reason_names_every_unreached_suite_so_one_pass_fixes_all(
        self,
    ) -> None:
        reason = tool_subdirs.suite_reach_reason(
            "widget", "", ["test_b.py", "test_a.py"]
        )
        assert reason is not None  # narrowed for mypy
        self.assertIn("test_a.py, test_b.py", reason)
        self.assertIn("nothing runs them", reason)

    def test_the_reason_names_the_aggregator_and_the_convention(self) -> None:
        reason = tool_subdirs.suite_reach_reason("lock-phone", "", _LISTING)
        assert reason is not None  # narrowed for mypy
        self.assertIn("test_lock_phone.py", reason)
        self.assertIn(f"{tool_subdirs.SUITE_DIR_NAME}/", reason)

    def test_the_reason_is_a_single_line(self) -> None:
        reason = tool_subdirs.suite_reach_reason("widget", "", _LISTING)
        assert reason is not None  # narrowed for mypy
        self.assertNotIn("\n", reason)

    def test_an_aggregator_holding_only_its_own_tests_orphans_its_suite_dir(
        self,
    ) -> None:
        """Regression: an aggregator that runs only its own tests.

        The aggregator EXISTED, so the listing check passed -- but it held its own test
        classes and imported only its subject, never the tests/ beside it, so a
        regression test filed there never ran while the folder gated PASS at 100%.
        """
        source = (
            "import unittest\n"
            "import corpus_reader\n\n"
            "class CorpusTests(unittest.TestCase):\n"
            "    def test_parse(self) -> None:\n"
            "        self.assertTrue(corpus_reader.parse(''))\n"
        )
        reason = tool_subdirs.suite_reach_reason(
            "corpus_reader", source, ["test_regression.py"]
        )
        assert reason is not None  # the bug: this was reported reachable
        self.assertIn("test_regression.py", reason)
        self.assertIn("test_corpus_reader.py", reason)


class UnreadableAggregatorReasonTests(unittest.TestCase):
    """An aggregator that cannot be read reaches nothing, and the line says why."""

    _ERROR = UnicodeDecodeError("utf-8", b"\xff", 0, 1, "invalid start byte")

    def test_the_reason_names_the_read_failure_and_every_suite(self) -> None:
        reason = tool_subdirs.unreadable_aggregator_reason(
            "widget", self._ERROR, ["test_b.py", "test_a.py", "helpers.py"]
        )
        assert reason is not None  # narrowed for mypy
        self.assertIn("test_widget.py", reason)
        self.assertIn("could not be read", reason)
        self.assertIn("UnicodeDecodeError", reason)
        self.assertIn("test_a.py, test_b.py", reason)
        self.assertIn("nothing runs them", reason)

    def test_the_reason_is_a_single_line_whatever_the_error_says(self) -> None:
        error = OSError("first line\nsecond line")
        reason = tool_subdirs.unreadable_aggregator_reason("widget", error, _LISTING)
        assert reason is not None  # narrowed for mypy
        self.assertNotIn("\n", reason)

    def test_no_reason_when_there_is_no_suite_to_reach(self) -> None:
        self.assertIsNone(
            tool_subdirs.unreadable_aggregator_reason(
                "widget", self._ERROR, ["helpers.py"]
            )
        )


if __name__ == "__main__":
    unittest.main()
