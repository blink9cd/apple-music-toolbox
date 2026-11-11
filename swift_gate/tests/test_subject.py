"""Grouped suite: what ``--path`` holds, and the exit code each shape gives.

Discovery is exercised directly and through ``main`` with the run seam patched, so no test
here builds anything.
"""

from __future__ import annotations

import io
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

from _fixtures import FLOORPKG, StagedRunner, export_data, make_package, write

import swgate_stages
import swgate_subject
import swift_gate
from swgate_model import SUBJECT_NOT_SWIFTPM, SUBJECT_NOTHING, SUBJECT_READY

PYPROJECT = '[tool.swift_gate]\nmacos_floor = "14"\nexclude = ["samples"]\n'


def _main(argv: list[str], runner: StagedRunner) -> tuple[int, str, str]:
    """Run main with the seam faked and the toolchain present."""
    out, err = io.StringIO(), io.StringIO()
    with (
        mock.patch.object(swift_gate, "_run_swift", runner),
        mock.patch.object(swift_gate, "locate_swift", return_value="/usr/bin/swift"),
        redirect_stdout(out),
        redirect_stderr(err),
    ):
        code = swift_gate.main(argv)
    return code, out.getvalue(), err.getvalue()


class DiscoveryTests(unittest.TestCase):
    """discover() classifies a tree three ways."""

    def setUp(self) -> None:
        tmp = TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name).resolve()

    def test_empty_tree_is_nothing(self) -> None:
        write(self.root / "README.md", "no Swift")
        self.assertEqual(swgate_subject.discover(self.root).status, SUBJECT_NOTHING)

    def test_loose_swift_is_not_swiftpm(self) -> None:
        write(self.root / "main.swift", "print(1)\n")
        found = swgate_subject.discover(self.root)
        self.assertEqual(
            (found.status, found.strays),
            (SUBJECT_NOT_SWIFTPM, (self.root / "main.swift",)),
        )

    def test_xcode_project_is_not_swiftpm(self) -> None:
        (self.root / "App.xcodeproj").mkdir()
        write(self.root / "App.xcodeproj" / "project.pbxproj", "")
        self.assertEqual(swgate_subject.discover(self.root).status, SUBJECT_NOT_SWIFTPM)

    def test_build_dirs_and_excludes_are_pruned(self) -> None:
        pkg = make_package(self.root / "pkg")
        make_package(pkg / ".build" / "checkouts" / "Dep")
        write(self.root / "samples" / "loose.swift", "let x = 1\n")
        found = swgate_subject.discover(self.root, (self.root / "samples",))
        self.assertEqual((found.status, found.packages), (SUBJECT_READY, (pkg,)))

    def test_an_excluded_file_is_no_stray(self) -> None:
        write(self.root / "loose.swift", "let x = 1\n")
        found = swgate_subject.discover(self.root, (self.root / "loose.swift",))
        self.assertEqual(found.status, SUBJECT_NOTHING)

    def test_an_excluded_xcode_project_is_no_stray(self) -> None:
        (self.root / "App.xcodeproj").mkdir()
        found = swgate_subject.discover(self.root, (self.root / "App.xcodeproj",))
        self.assertEqual(found.status, SUBJECT_NOTHING)

    def test_excluded_path_itself_is_nothing(self) -> None:
        write(self.root / "loose.swift", "let x = 1\n")
        found = swgate_subject.discover(self.root, (self.root,))
        self.assertEqual(found.status, SUBJECT_NOTHING)

    def test_package_sources_skip_tests_and_excludes(self) -> None:
        pkg = make_package(
            self.root / "pkg",
            {
                "Sources/A/A.swift": "",
                "Sources/A/Gen/G.swift": "",
                "Tests/ATests/ATests.swift": "",
            },
        )
        sources = swgate_subject.package_sources(pkg, (pkg / "Sources/A/Gen",))
        self.assertEqual(sources, (pkg / "Sources/A/A.swift",))


class SubjectExitTests(unittest.TestCase):
    """main(): nothing to gate is 0, Swift outside SwiftPM is 2, packages in turn."""

    def setUp(self) -> None:
        tmp = TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name).resolve()
        write(self.root / "pyproject.toml", PYPROJECT)

    def test_nothing_to_gate_exits_zero(self) -> None:
        runner = StagedRunner()
        code, out, _ = _main(["--path", str(self.root)], runner)
        self.assertEqual(code, 0)
        self.assertIn("nothing to gate", out)
        self.assertEqual(runner.calls, [])

    def test_xcode_only_folder_exits_two(self) -> None:
        (self.root / "App.xcworkspace").mkdir()
        write(self.root / "App" / "AppDelegate.swift", "")
        code, _, err = _main(["--path", str(self.root)], StagedRunner())
        self.assertEqual(code, 2)
        self.assertIn("swift_gate gates SwiftPM packages only", err)

    def test_configured_exclude_prunes_a_samples_folder(self) -> None:
        write(self.root / "samples" / "demo.swift", "let x = 1\n")
        code, out, _ = _main(["--path", str(self.root)], StagedRunner())
        self.assertEqual(code, 0)
        self.assertIn("nothing to gate", out)

    def test_two_packages_are_gated_in_turn(self) -> None:
        first = make_package(self.root / "a")
        second = make_package(self.root / "b")
        runner = StagedRunner(outcomes=[("build --build-tests", 1, "error: stop")])
        code, out, _ = _main(["--path", str(self.root)], runner)
        self.assertEqual(code, 1)
        self.assertEqual(runner.cwds, [first, first, second, second])
        self.assertIn("Gated 2 SwiftPM package(s)", out)

    def test_a_failing_first_package_fails_the_run(self) -> None:
        source = (FLOORPKG / "Sources/Floor/Floor.swift").read_text(encoding="utf-8")
        first = make_package(self.root / "a")
        second = make_package(self.root / "b", {"Sources/Floor/Floor.swift": source})
        base = self.root / "scratch"
        failing = swgate_stages.scratch_for(first, base)
        passing = swgate_stages.scratch_for(second, base)
        runner = StagedRunner(
            codecov=passing / "codecov" / "Floor.json",
            report=export_data(second, passing),
            outcomes=[(f"{failing} dump-package", 1, "error: bad manifest")],
        )
        argv = ["--path", str(self.root), "--scratch-path", str(base)]
        code, out, _ = _main(argv, runner)
        self.assertEqual(code, 1)
        self.assertEqual(out.count("PASS:"), 1)


if __name__ == "__main__":
    unittest.main()
