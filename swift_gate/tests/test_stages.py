"""Grouped suite: the stage pipeline for one package, driven through ``StagedRunner``.

No test here reaches the host: every command goes through the fake seam, which writes the
captured coverage export where a real ``swift test`` would.
"""

from __future__ import annotations

import dataclasses
import subprocess
import unittest
from collections.abc import Sequence
from pathlib import Path
from tempfile import TemporaryDirectory

from _fixtures import (
    FLOORPKG,
    StagedRunner,
    dump_package,
    export_data,
    make_package,
    write,
)

import swgate_stages
from swgate_model import GateOptions, ParseError, Subject

FLOOR_SOURCE = (FLOORPKG / "Sources" / "Floor" / "Floor.swift").read_text(
    encoding="utf-8"
)


class _StageCase(unittest.TestCase):
    """A temp package shaped like floorpkg, a scratch base, and the export pointing at it."""

    def setUp(self) -> None:
        tmp = TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        base = Path(tmp.name).resolve()
        self.root = make_package(
            base / "floorpkg", {"Sources/Floor/Floor.swift": FLOOR_SOURCE}
        )
        self.opts = GateOptions(
            swift="swift", macos_floor="14", scratch_base=base / "scratch"
        )
        self.scratch = swgate_stages.scratch_for(self.root, self.opts.scratch_base)
        self.codecov = (
            self.scratch / "out" / "Products" / "Debug" / "codecov" / "Floor.json"
        )
        self.subject = Subject(self.root)

    def runner(
        self,
        *,
        dump: dict[str, object] | None = None,
        outcomes: Sequence[tuple[str, int, str]] = (),
        raises: dict[str, BaseException] | None = None,
    ) -> StagedRunner:
        """A fake whose test run writes the captured export for this package."""
        return StagedRunner(
            dump=dump,
            codecov=self.codecov,
            report=export_data(self.root, self.scratch),
            outcomes=outcomes,
            raises=raises,
        )

    def gate(
        self,
        runner: StagedRunner,
        *,
        timeout: float = 1200.0,
        min_percent: float = 100.0,
    ) -> swgate_stages.GateResult:
        """Run the pipeline with a timeout and threshold applied to the options."""
        opts = dataclasses.replace(self.opts, timeout=timeout, min_percent=min_percent)
        return swgate_stages.run_stages(self.subject, opts, runner)


class OrderTests(_StageCase):
    """The pipeline order, and which failures stop it."""

    def test_run_order_is_manifest_build_test_codecov_path(self) -> None:
        runner = self.runner()
        result = self.gate(runner)
        self.assertEqual(
            runner.stage_names(), ["manifest", "build", "test", "codecov-path"]
        )
        self.assertEqual((result.returncode, result.percent), (0, 100.0))

    def test_build_argv_carries_the_injected_bar(self) -> None:
        runner = self.runner()
        self.gate(runner)
        build = runner.calls[1]
        for flag in ("--build-tests", "--enable-code-coverage", "-warnings-as-errors"):
            self.assertIn(flag, build)
        self.assertEqual(build[build.index("--scratch-path") + 1], str(self.scratch))

    def test_test_argv_runs_the_tests_serially(self) -> None:
        # Profile counters are plain increments, so tests run in parallel can lose one,
        # and a region counted by subtraction then reads 0: the flake this pins out.
        runner = self.runner()
        self.gate(runner)
        test = runner.calls[2]
        self.assertIn("--skip-build", test)
        self.assertIn("--no-parallel", test)

    def test_build_failure_stops_before_test(self) -> None:
        runner = self.runner(outcomes=[("build --build-tests", 1, "error: boom")])
        result = self.gate(runner)
        self.assertEqual(runner.stage_names(), ["manifest", "build"])
        self.assertEqual(result.returncode, 1)
        self.assertIn("error: boom", result.detail)

    def test_test_failure_is_exit_one(self) -> None:
        runner = self.runner(outcomes=[("--skip-build", 1, "Test failed")])
        result = self.gate(runner)
        self.assertEqual(result.returncode, 1)
        self.assertIn("swift test failed", result.detail)

    def test_manifest_failure_is_exit_one(self) -> None:
        result = self.gate(self.runner(outcomes=[("dump-package", 1, "bad manifest")]))
        self.assertEqual(result.returncode, 1)
        self.assertIn("bad manifest", result.detail)

    def test_unparseable_dump_raises(self) -> None:
        runner = self.runner(outcomes=[("dump-package", 0, "not json")])
        with self.assertRaises(ParseError):
            self.gate(runner)


class TimeoutTests(_StageCase):
    """A stage outliving its bound is exit 1 naming the stage."""

    def test_timeout_names_the_stage(self) -> None:
        for needle, stage in (
            ("dump-package", "manifest"),
            ("build --build-tests", "build"),
            ("--skip-build", "test"),
            ("--show-codecov-path", "codecov-path"),
        ):
            runner = self.runner(
                raises={needle: subprocess.TimeoutExpired("swift", 5.0)}
            )
            result = self.gate(runner, timeout=5.0)
            with self.subTest(stage=stage):
                self.assertEqual(result.returncode, 1)
                self.assertIn(f"{stage} stage timed out after 5s", result.detail)


class ScratchTests(_StageCase):
    """The scratch path is outside the package, per package, and stale reports go."""

    def test_scratch_path_is_outside_the_package(self) -> None:
        runner = self.runner()
        self.gate(runner)
        self.assertNotIn(self.root, self.scratch.parents)
        self.assertEqual(self.scratch.parent, self.opts.scratch_base)
        self.assertEqual(len(self.scratch.name), 16)

    def test_default_base_is_under_the_temp_dir(self) -> None:
        base = swgate_stages.default_scratch_base()
        self.assertEqual(base.name, "swift_gate")
        self.assertNotIn(self.root, base.parents)

    def test_stale_report_is_deleted_and_never_read(self) -> None:
        write(self.codecov, "{}")
        runner = StagedRunner(codecov=self.codecov)  # this run writes no report
        result = self.gate(runner)
        self.assertEqual(result.returncode, 1)
        self.assertIn("no coverage report", result.detail)

    def test_codecov_path_failure_is_no_report(self) -> None:
        runner = self.runner(outcomes=[("--show-codecov-path", 1, "")])
        self.assertIn("no coverage report", self.gate(runner).detail)


class VerdictTests(_StageCase):
    """Findings, the threshold, the vacuous case, and the dead marker."""

    def test_floor_finding_fails_after_full_coverage(self) -> None:
        runner = self.runner(dump=dump_package(platforms=[]))
        result = self.gate(runner)
        self.assertEqual(result.returncode, 1)
        self.assertEqual([f.code for f in result.findings], ["SWG001"])
        self.assertEqual(result.percent, 100.0)

    def test_below_min_percent_lists_the_miss(self) -> None:
        write(
            self.root / "Sources/Floor/Floor.swift",
            FLOOR_SOURCE.replace("  // coverage: ignore: a debugger-only aid", ""),
        )
        result = self.gate(self.runner())
        self.assertEqual(result.returncode, 1)
        self.assertIn("< 100%", result.detail)
        self.assertEqual(result.misses, ("Sources/Floor/Floor.swift:17:48",))

    def test_dead_marker_is_swg004(self) -> None:
        write(
            self.root / "Sources/Floor/Extra.swift",
            "let x = 1  // coverage: ignore: gone\n",
        )
        result = self.gate(self.runner())
        self.assertEqual([f.code for f in result.findings], ["SWG004"])

    def test_lower_min_percent_passes_the_miss(self) -> None:
        write(
            self.root / "Sources/Floor/Floor.swift",
            FLOOR_SOURCE.replace("  // coverage: ignore: a debugger-only aid", ""),
        )
        result = self.gate(self.runner(), min_percent=80.0)
        self.assertEqual((result.returncode, result.detail), (0, ""))

    def test_nothing_measured_is_swg005(self) -> None:
        excluded = Subject(self.root, (self.root / "Sources",))
        vacuous = swgate_stages.run_stages(excluded, self.opts, self.runner())
        self.assertEqual([f.code for f in vacuous.findings], ["SWG005"])
        self.assertIsNone(vacuous.percent)


if __name__ == "__main__":
    unittest.main()
