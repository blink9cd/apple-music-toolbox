#!/usr/bin/env python3
"""Branch-complete tests for the tool-subdirectory conventions.

What these tests are actually defending
---------------------------------------
Every assertion corresponds to a way a convention could be adopted *silently
wrong*, where nothing in the gate family would go red:

* **The names.** Each is a collision count, not a spelling preference. Two real
  C / C# test trees are named ``test``; one real directory is named ``helpers``
  (which is also a delivery-zip carve-out); three are named ``shared``. A
  consumer that pruned any of those would remove a real tree from a gate's
  discovery and keep reporting PASS for code nobody was checking. The rejected
  names are pinned explicitly, not merely asserted unequal to something.
* **The public/private split.** ``tests`` is reached by a runner through an
  aggregator; ``lib`` and ``src`` serve only their own tool. Getting that
  backwards would apply the stray rule to the one directory whose entire purpose
  is holding ``test_*.py``, or omit it from the two where such a file silently
  cuts that directory out of the parent folder's run.
* **The fold.** ``folder_layout`` compares a stem to its folder name
  hyphen/underscore-folded, so a hyphenated folder is legitimately served by
  either spelling. An unfolded implementation would report such a folder as an
  orphan forever while its layout gate stayed green.
* **The orphan reports.** Pruning without checking reachability leaves code no
  runner reaches, invisibly. The tests assert on the *presence of a reason* and
  require it to name the file the reader must create.
* **The stray report.** The sharpest failure of the lot: a ``coverage.sh`` or
  ``test_*.py`` inside a private dir makes ``gate_tree`` register that directory
  as its own sweep unit, and the *parent tool folder* is gated without it --
  that code unmeasured by the tool's tests, sweep still PASS.

Each was confirmed to fail against a deliberately wrong stub before the real
module was written.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))

import tool_subdirs  # noqa: E402 - import follows the sys.path bootstrap above

# The grouped suites beside this file, and the FLOOR of tests each must contribute. A
# grouped file that stops being discovered (a rename, a lost ``load_tests``) would
# otherwise drop to zero silently: "no tests ran" and "every test passed" share an exit
# code, and a coverage figure cannot tell them apart.
_SUITE_DIR = _HERE / tool_subdirs.SUITE_DIR_NAME
_MIN_GROUPED_TESTS_BY_FILE: dict[str, int] = {"test_subdirs_suite_reach.py": 37}


class SuiteDirNameTests(unittest.TestCase):
    """The grouped-suite name, and the singular it must never be confused with."""

    def test_the_convention_name_is_the_plural_form(self) -> None:
        self.assertEqual(tool_subdirs.SUITE_DIR_NAME, "tests")

    def test_the_convention_name_is_recognized(self) -> None:
        self.assertTrue(tool_subdirs.is_suite_dir(tool_subdirs.SUITE_DIR_NAME))

    def test_the_singular_test_is_not_a_suite_dir(self) -> None:
        # Load-bearing: two real C / C# test trees are named `test`, and a
        # consumer pruning that name would silently stop gating both.
        self.assertFalse(tool_subdirs.is_suite_dir("test"))

    def test_a_name_merely_containing_the_convention_is_not_a_suite_dir(self) -> None:
        self.assertFalse(tool_subdirs.is_suite_dir("integration_tests"))

    def test_an_unrelated_name_is_not_a_suite_dir(self) -> None:
        self.assertFalse(tool_subdirs.is_suite_dir("samples"))


class LibDirNameTests(unittest.TestCase):
    """The sourced-shell-helper name, and the names it was measured against."""

    def test_the_convention_name_is_lib(self) -> None:
        self.assertEqual(tool_subdirs.LIB_DIR_NAME, "lib")

    def test_the_convention_name_is_recognized(self) -> None:
        self.assertTrue(tool_subdirs.is_lib_dir(tool_subdirs.LIB_DIR_NAME))

    def test_helpers_is_not_a_lib_dir(self) -> None:
        # Load-bearing twice over: `project/workflow_tasks/helpers` is a real
        # directory, and `helpers` is a build_delivery_zip carve-out, so pruning
        # this name would both un-gate a tree and ship a broken installer.
        self.assertFalse(tool_subdirs.is_lib_dir("helpers"))

    def test_shared_is_not_a_lib_dir(self) -> None:
        # Three real directories carry this name, one of them the parent of a
        # baselined installer script.
        self.assertFalse(tool_subdirs.is_lib_dir("shared"))

    def test_a_name_merely_containing_the_convention_is_not_a_lib_dir(self) -> None:
        self.assertFalse(tool_subdirs.is_lib_dir("libexec"))

    def test_the_match_is_case_sensitive(self) -> None:
        self.assertFalse(tool_subdirs.is_lib_dir("Lib"))


class SrcDirNameTests(unittest.TestCase):
    """The private-Python-module name."""

    def test_the_convention_name_is_src(self) -> None:
        self.assertEqual(tool_subdirs.SRC_DIR_NAME, "src")

    def test_the_convention_name_is_recognized(self) -> None:
        self.assertTrue(tool_subdirs.is_src_dir(tool_subdirs.SRC_DIR_NAME))

    def test_a_name_merely_containing_the_convention_is_not_a_src_dir(self) -> None:
        self.assertFalse(tool_subdirs.is_src_dir("src_gen"))

    def test_the_match_is_case_sensitive(self) -> None:
        self.assertFalse(tool_subdirs.is_src_dir("Src"))


class DirClassificationTests(unittest.TestCase):
    """The public/private split, and the all-three predicate."""

    def test_lib_is_private(self) -> None:
        self.assertTrue(tool_subdirs.is_private_dir(tool_subdirs.LIB_DIR_NAME))

    def test_src_is_private(self) -> None:
        self.assertTrue(tool_subdirs.is_private_dir(tool_subdirs.SRC_DIR_NAME))

    def test_the_suite_dir_is_not_private(self) -> None:
        # Its suites are reached by a runner through the aggregator, and holding
        # test_*.py is its whole purpose -- so the stray rule must not reach it.
        self.assertFalse(tool_subdirs.is_private_dir(tool_subdirs.SUITE_DIR_NAME))

    def test_an_unrelated_name_is_not_private(self) -> None:
        self.assertFalse(tool_subdirs.is_private_dir("samples"))

    def test_every_defined_name_is_a_tool_subdir(self) -> None:
        for name in (
            tool_subdirs.SUITE_DIR_NAME,
            tool_subdirs.LIB_DIR_NAME,
            tool_subdirs.SRC_DIR_NAME,
        ):
            with self.subTest(name=name):
                self.assertTrue(tool_subdirs.is_tool_subdir(name))

    def test_an_unrelated_name_is_not_a_tool_subdir(self) -> None:
        self.assertFalse(tool_subdirs.is_tool_subdir("samples"))

    def test_the_three_names_are_distinct(self) -> None:
        # A copy-paste that left two names equal would silently give one
        # convention the other's scope in every consumer at once.
        names = {
            tool_subdirs.SUITE_DIR_NAME,
            tool_subdirs.LIB_DIR_NAME,
            tool_subdirs.SRC_DIR_NAME,
        }
        self.assertEqual(len(names), 3)


class AggregatorFilenameTests(unittest.TestCase):
    """The ``test_<folder>.py`` python_gate's pairing rule requires."""

    def test_an_underscored_folder_maps_to_its_test_module(self) -> None:
        self.assertEqual(
            tool_subdirs.aggregator_filename("tool_subdirs"), "test_tool_subdirs.py"
        )

    def test_a_hyphenated_folder_folds_to_an_underscored_module(self) -> None:
        # `test_lock-phone.py` would be an unimportable module name.
        self.assertEqual(
            tool_subdirs.aggregator_filename("lock-phone"), "test_lock_phone.py"
        )

    def test_every_hyphen_is_folded_not_just_the_first(self) -> None:
        self.assertEqual(tool_subdirs.aggregator_filename("a-b-c"), "test_a_b_c.py")

    def test_this_folder_names_this_very_file(self) -> None:
        # Self-referential on purpose: the convention is only credible if the
        # library's own suite satisfies it.
        here = Path(__file__).resolve()
        self.assertEqual(tool_subdirs.aggregator_filename(here.parent.name), here.name)


class PrimaryScriptFilenameTests(unittest.TestCase):
    """The ``<folder>`` script that links a private dir's contents into the tool."""

    def test_a_lib_dir_pairs_with_a_shell_script(self) -> None:
        self.assertEqual(
            tool_subdirs.primary_script_filename("screen_record", "lib"),
            "screen_record.sh",
        )

    def test_a_src_dir_pairs_with_a_python_module(self) -> None:
        self.assertEqual(
            tool_subdirs.primary_script_filename("folder_layout", "src"),
            "folder_layout.py",
        )

    def test_a_hyphenated_folder_keeps_its_hyphens_for_shell(self) -> None:
        # Unlike a Python module name, a shell filename may contain a hyphen, so
        # the suggested spelling is the folder's own.
        self.assertEqual(
            tool_subdirs.primary_script_filename("lock-phone", "lib"),
            "lock-phone.sh",
        )

    def test_the_suite_dir_has_no_primary_script(self) -> None:
        # It pairs with an aggregator instead; answering anything here would be a
        # reachability report that cannot come true.
        with self.assertRaises(ValueError):
            tool_subdirs.primary_script_filename("widget", "tests")

    def test_an_unknown_dir_name_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            tool_subdirs.primary_script_filename("widget", "samples")


class PrivateOrphanReasonTests(unittest.TestCase):
    """Reporting a pruned lib/ or src/ that no primary script can reach."""

    def test_no_reason_when_a_lib_dirs_parent_holds_its_shell_script(self) -> None:
        self.assertIsNone(
            tool_subdirs.private_orphan_reason(
                "lib", "widget", ["widget.sh", "widget.md", "coverage.sh"]
            )
        )

    def test_no_reason_when_a_src_dirs_parent_holds_its_module(self) -> None:
        self.assertIsNone(
            tool_subdirs.private_orphan_reason(
                "src", "widget", ["widget.py", "test_widget.py"]
            )
        )

    def test_a_missing_shell_script_yields_a_reason(self) -> None:
        self.assertIsNotNone(
            tool_subdirs.private_orphan_reason("lib", "widget", ["widget.md"])
        )

    def test_python_cannot_source_a_shell_helper(self) -> None:
        # A lib/ beside a Python-only tool is unreachable however it is named.
        self.assertIsNotNone(
            tool_subdirs.private_orphan_reason("lib", "widget", ["widget.py"])
        )

    def test_shell_cannot_import_a_python_module(self) -> None:
        # The mirror case: a src/ beside a shell-only tool.
        self.assertIsNotNone(
            tool_subdirs.private_orphan_reason("src", "widget", ["widget.sh"])
        )

    def test_the_reason_names_the_file_the_reader_must_create(self) -> None:
        reason = tool_subdirs.private_orphan_reason("lib", "widget", ["widget.md"])
        assert reason is not None  # narrowed for mypy
        self.assertIn("widget.sh", reason)

    def test_the_reason_names_the_directory(self) -> None:
        reason = tool_subdirs.private_orphan_reason("src", "widget", ["widget.md"])
        assert reason is not None  # narrowed for mypy
        self.assertIn(tool_subdirs.SRC_DIR_NAME, reason)

    def test_the_lib_reason_says_source_and_the_src_reason_says_import(self) -> None:
        # The remediation differs by language; a reader told to "import" a shell
        # helper would write a line that cannot work.
        lib_reason = tool_subdirs.private_orphan_reason("lib", "widget", [])
        src_reason = tool_subdirs.private_orphan_reason("src", "widget", [])
        assert lib_reason is not None and src_reason is not None  # narrowed
        self.assertIn("source", lib_reason)
        self.assertIn("import", src_reason)

    def test_the_reason_is_a_single_line(self) -> None:
        reason = tool_subdirs.private_orphan_reason("lib", "widget", [])
        assert reason is not None  # narrowed for mypy
        self.assertNotIn("\n", reason)

    def test_another_tools_script_does_not_satisfy_the_rule(self) -> None:
        self.assertIsNotNone(
            tool_subdirs.private_orphan_reason("lib", "widget", ["gadget.sh"])
        )

    def test_the_coverage_driver_alone_does_not_satisfy_the_rule(self) -> None:
        # coverage.sh drives the subject; it is never the subject itself.
        self.assertIsNotNone(
            tool_subdirs.private_orphan_reason("lib", "widget", ["coverage.sh"])
        )

    def test_a_hyphenated_folder_is_satisfied_by_the_underscored_spelling(self) -> None:
        # folder_layout folds both ways, so this rule must agree with it rather
        # than invent a stricter one.
        self.assertIsNone(
            tool_subdirs.private_orphan_reason("lib", "lock-phone", ["lock_phone.sh"])
        )

    def test_a_hyphenated_folder_is_satisfied_by_its_own_spelling(self) -> None:
        self.assertIsNone(
            tool_subdirs.private_orphan_reason("lib", "lock-phone", ["lock-phone.sh"])
        )

    def test_the_suite_dir_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            tool_subdirs.private_orphan_reason("tests", "widget", ["widget.py"])


class StrayReasonTests(unittest.TestCase):
    """Reporting a private dir holding a file that re-registers it as a unit."""

    def test_no_reason_for_a_lib_of_plain_helpers(self) -> None:
        self.assertIsNone(
            tool_subdirs.stray_reason("lib", ["state.sh", "preflight.sh"])
        )

    def test_no_reason_for_a_src_of_plain_modules(self) -> None:
        self.assertIsNone(tool_subdirs.stray_reason("src", ["report.py"]))

    def test_no_reason_for_an_empty_dir(self) -> None:
        self.assertIsNone(tool_subdirs.stray_reason("lib", []))

    def test_a_coverage_driver_yields_a_reason(self) -> None:
        # gate_tree's unit marker: this makes the dir a unit, and the parent tool
        # folder is then gated without it.
        self.assertIsNotNone(
            tool_subdirs.stray_reason("lib", ["state.sh", "coverage.sh"])
        )

    def test_a_test_module_yields_a_reason(self) -> None:
        self.assertIsNotNone(tool_subdirs.stray_reason("src", ["test_report.py"]))

    def test_the_reason_states_the_nested_unit_rule(self) -> None:
        # folder_layout prints this as its fix detail: it must describe what gate_tree
        # does today (gate the parent without the dir), not the dropped-parent rule.
        reason = tool_subdirs.stray_reason("src", ["test_report.py"]) or ""
        self.assertIn("gate the parent tool folder without it", reason)
        self.assertNotIn("drop the parent", reason)

    def test_the_reason_names_the_offending_file(self) -> None:
        reason = tool_subdirs.stray_reason("lib", ["state.sh", "coverage.sh"])
        assert reason is not None  # narrowed for mypy
        self.assertIn("coverage.sh", reason)

    def test_the_reason_is_a_single_line(self) -> None:
        reason = tool_subdirs.stray_reason("src", ["test_report.py"])
        assert reason is not None  # narrowed for mypy
        self.assertNotIn("\n", reason)

    def test_every_offender_is_named_not_just_the_first(self) -> None:
        # A reader who fixed only the file the report named would re-run the gate
        # and meet the next one; naming all of them makes the fix one pass.
        reason = tool_subdirs.stray_reason("lib", ["coverage.sh", "test_state.py"])
        assert reason is not None  # narrowed for mypy
        self.assertIn("coverage.sh", reason)
        self.assertIn("test_state.py", reason)

    def test_a_shell_test_script_is_not_a_stray(self) -> None:
        # gate_tree's marker is `test_*.py`, not `test_*.sh`, and the delivery zip
        # excludes the same two names -- so this rule stays pinned to the files
        # that cause the two failures, not to everything test-shaped.
        self.assertIsNone(tool_subdirs.stray_reason("lib", ["test_state.sh"]))

    def test_a_name_merely_starting_like_a_test_module_is_not_a_stray(self) -> None:
        self.assertIsNone(tool_subdirs.stray_reason("src", ["testing_utils.py"]))

    def test_asking_about_the_suite_dir_is_a_caller_bug(self) -> None:
        # Holding test_*.py is the suite dir's entire purpose, and gate_tree
        # prunes that name deliberately -- so there is no clean answer here.
        with self.assertRaises(ValueError):
            tool_subdirs.stray_reason("tests", ["test_parsing.py"])


class ConventionContentTests(unittest.TestCase):
    """Telling a real convention dir from a directory that only shares its name."""

    def test_a_src_of_python_modules_holds_its_convention(self) -> None:
        self.assertTrue(
            tool_subdirs.holds_convention_content("src", ["report.py", "parse.py"])
        )

    def test_a_c_source_tree_named_src_does_not(self) -> None:
        # The case this predicate exists for: a native project's src/ is the
        # LANGUAGE's layout, so no <folder>.py will ever import it and demanding
        # one is a finding that can never be acted on.
        self.assertFalse(
            tool_subdirs.holds_convention_content(
                "src", ["app.c", "app.h", "main.c", "sign_logic.c"]
            )
        )

    def test_a_csharp_source_tree_named_src_does_not(self) -> None:
        self.assertFalse(
            tool_subdirs.holds_convention_content(
                "src", ["Program.cs", "Sign.cs", "SignClassifier.csproj"]
            )
        )

    def test_a_web_source_tree_named_src_does_not(self) -> None:
        # Nested .js/.css do not count: the parent puts src/ itself on sys.path, so
        # a private module is imported top-level and lives in the DIRECT listing.
        self.assertFalse(tool_subdirs.holds_convention_content("src", ["index.html"]))

    def test_a_lib_of_shell_helpers_holds_its_convention(self) -> None:
        self.assertTrue(
            tool_subdirs.holds_convention_content("lib", ["state.sh", "preflight.sh"])
        )

    def test_the_coverage_driver_counts_as_shell_content(self) -> None:
        # Load-bearing: a lib/ holding ONLY coverage.sh is a real sourced-helper dir
        # with a stray in it (folder_layout reports BOTH findings), not a name
        # collision -- so narrowing the orphan question must not reach it.
        self.assertTrue(tool_subdirs.holds_convention_content("lib", ["coverage.sh"]))

    def test_a_lib_of_python_does_not(self) -> None:
        # The mirror of the src/ case: shell cannot source a .py, so a lib/ of
        # Python is not the sourced-helper convention however it is named.
        self.assertFalse(tool_subdirs.holds_convention_content("lib", ["state.py"]))

    def test_a_suite_dir_of_python_holds_its_convention(self) -> None:
        self.assertTrue(
            tool_subdirs.holds_convention_content("tests", ["test_parsing.py"])
        )

    def test_a_native_test_tree_named_tests_does_not(self) -> None:
        # Same rule, third name: a C project's tests/ of test_*.c is not the
        # decomposed-Python-suite convention, so no test_<folder>.py is demanded.
        self.assertFalse(
            tool_subdirs.holds_convention_content("tests", ["test_app.c", "harness.h"])
        )

    def test_an_empty_dir_holds_nothing(self) -> None:
        # An empty directory hides no code, so there is nothing for the orphan
        # finding to protect -- the one case where "not the convention" and
        # "nothing was skipped" give the same answer for different reasons.
        self.assertFalse(tool_subdirs.holds_convention_content("src", []))

    def test_an_unknown_dir_name_is_rejected(self) -> None:
        # Same stance as stray_reason: a name this module does not define has no
        # convention to hold, so a clean answer would be a silent wrong one.
        with self.assertRaises(ValueError):
            tool_subdirs.holds_convention_content("helpers", ["state.sh"])


def _grouped_suite() -> unittest.TestSuite:
    """Every ``test_*.py`` under ``tests/``, loaded as top-level modules."""
    loader = unittest.TestLoader()
    return loader.discover(str(_SUITE_DIR), top_level_dir=str(_SUITE_DIR))


def load_tests(
    _loader: unittest.TestLoader, tests: unittest.TestSuite, _pattern: str | None
) -> unittest.TestSuite:
    """unittest's hook: run this module's own tests plus every grouped suite."""
    return unittest.TestSuite([tests, _grouped_suite()])


def _tests_by_module(suite: unittest.TestSuite) -> dict[str, int]:
    """Flatten a possibly-nested suite into a per-file test count."""
    counts: dict[str, int] = {}
    for item in suite:
        if isinstance(item, unittest.TestSuite):
            for module, count in _tests_by_module(item).items():
                counts[module] = counts.get(module, 0) + count
        else:
            filename = f"{type(item).__module__}.py"
            counts[filename] = counts.get(filename, 0) + 1
    return counts


class GroupedSuiteDiscoveryTest(unittest.TestCase):
    """Fail loudly when this module's REAL test load is missing a grouped suite.

    Built from ``loadTestsFromModule`` -- what a bare run and python_gate's coverage run
    use, and what honors ``load_tests`` -- rather than by calling ``_grouped_suite()``
    directly: a guard that called the helper would stay green with ``load_tests``
    deleted and every grouped suite unrun.
    """

    def test_module_load_includes_the_grouped_suites(self) -> None:
        loaded = unittest.TestLoader().loadTestsFromModule(sys.modules[__name__])
        counts = _tests_by_module(loaded)
        for filename, floor in _MIN_GROUPED_TESTS_BY_FILE.items():
            self.assertGreaterEqual(counts.get(filename, 0), floor, filename)


if __name__ == "__main__":
    unittest.main()
