"""Grouped suite: argv in, an exit code out, through patched seams.

The exit code is the product: a gate that finds the right defect and returns 0 has failed
at the only thing a build reads.
"""

from __future__ import annotations

import io
import json
import subprocess
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

from _fixtures import StagedRunner, export_data, make_package, write

import swgate_stages
import swift_gate

PYPROJECT = '[tool.swift_gate]\nmacos_floor = "14"\n'


class _CliCase(unittest.TestCase):
    """A temp tree with a floor and one package, and a main() runner."""

    def setUp(self) -> None:
        tmp = TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name).resolve()
        write(self.root / "pyproject.toml", PYPROJECT)
        self.pkg = make_package(self.root / "pkg")
        self.base = self.root / "scratch"

    def main(
        self,
        extra: list[str],
        runner: StagedRunner,
        *,
        swift: str | None = "/usr/bin/swift",
    ) -> tuple[int, str, str]:
        """Run main with the seam faked and the toolchain lookup patched."""
        out, err = io.StringIO(), io.StringIO()
        argv = ["--path", str(self.root), "--scratch-path", str(self.base), *extra]
        with (
            mock.patch.object(swift_gate, "_run_swift", runner),
            mock.patch.object(swift_gate, "locate_swift", return_value=swift),
            redirect_stdout(out),
            redirect_stderr(err),
        ):
            code = swift_gate.main(argv)
        return code, out.getvalue(), err.getvalue()


class ExitCodeTests(_CliCase):
    """0, 1 and 2 through main()."""

    def test_build_failure_exits_one(self) -> None:
        runner = StagedRunner(outcomes=[("build --build-tests", 1, "error: x")])
        code, out, _ = self.main([], runner)
        self.assertEqual(code, 1)
        self.assertIn("SWIFT_GATE FINAL RESULT: FAIL", out)

    def test_untrusted_dump_exits_two(self) -> None:
        code, out, _ = self.main([], StagedRunner(outcomes=[("dump-package", 0, "[]")]))
        self.assertEqual(code, 2)
        self.assertIn("ERROR:", out)

    def test_missing_tool_exits_two(self) -> None:
        runner = StagedRunner(raises={"dump-package": FileNotFoundError("swift")})
        code, out, _ = self.main([], runner)
        self.assertEqual(code, 2)
        self.assertIn("could not run swift", out)

    def test_an_unrunnable_tool_exits_two_without_a_traceback(self) -> None:
        # A driver that exists but cannot be executed raises PermissionError, not
        # FileNotFoundError: it is still "could not run", and the message names no path.
        driver = str(self.root / "bin" / "swift")
        denied = PermissionError(13, "Permission denied", driver)
        code, out, _ = self.main([], StagedRunner(raises={"dump-package": denied}))
        self.assertEqual(code, 2)
        self.assertIn("could not run swift: PermissionError", out)
        self.assertNotIn(driver, out)

    def test_bad_floor_exits_two(self) -> None:
        write(self.root / "pyproject.toml", '[tool.swift_gate]\nmacos_floor = "x"\n')
        code, _, _ = self.main([], StagedRunner())
        self.assertEqual(code, 2)

    def test_unreadable_config_exits_two(self) -> None:
        write(self.root / "pyproject.toml", "[tool.swift_gate\n")
        code, _, err = self.main([], StagedRunner())
        self.assertEqual(code, 2)
        self.assertIn("cannot read or parse", err)
        self.assertNotIn(str(self.root), err)  # no home path in a message

    def test_wrong_config_types_exit_two(self) -> None:
        for body in ('exclude = "x"\nmacos_floor = "14"\n', "macos_floor = 14\n"):
            write(self.root / "pyproject.toml", f"[tool.swift_gate]\n{body}")
            with self.subTest(body=body):
                self.assertEqual(self.main([], StagedRunner())[0], 2)

    def test_no_toolchain_exits_two_naming_the_group(self) -> None:
        code, _, err = self.main([], StagedRunner(), swift=None)
        self.assertEqual(code, 2)
        self.assertIn("'swift'", err)

    def test_clean_run_exits_zero_as_json(self) -> None:
        scratch = swgate_stages.scratch_for(self.pkg, self.base)
        codecov = scratch / "codecov" / "Floor.json"
        report = export_data(self.pkg, scratch)
        write(
            self.pkg / "Sources/Floor/Floor.swift", ""
        )  # the export's file, no markers
        runner = StagedRunner(codecov=codecov, report=report)
        code, out, _ = self.main(["--json", "--min-percent", "80"], runner)
        self.assertEqual(code, 0)
        payload = json.loads(out)
        self.assertEqual(
            payload["packages"][0]["misses"], ["Sources/Floor/Floor.swift:17:48"]
        )
        self.assertEqual(payload["min_percent"], 80.0)

    def test_text_report_lists_findings_and_misses(self) -> None:
        scratch = swgate_stages.scratch_for(self.pkg, self.base)
        codecov = scratch / "codecov" / "Floor.json"
        write(self.pkg / "Sources/Floor/Floor.swift", "// coverage: ignore\n")
        runner = StagedRunner(codecov=codecov, report=export_data(self.pkg, scratch))
        code, out, _ = self.main([], runner)
        self.assertEqual(code, 1)
        self.assertIn("SWG003 Sources/Floor/Floor.swift:1:", out)
        self.assertIn("miss Sources/Floor/Floor.swift:17:48", out)
        self.assertIn("region coverage 85.71%", out)

    def test_json_report_carries_findings(self) -> None:
        scratch = swgate_stages.scratch_for(self.pkg, self.base)
        write(self.pkg / "Sources/Floor/Floor.swift", "// coverage: ignore\n")
        runner = StagedRunner(
            codecov=scratch / "codecov" / "Floor.json",
            report=export_data(self.pkg, scratch),
        )
        code, out, _ = self.main(["--json"], runner)
        finding = json.loads(out)["packages"][0]["findings"][0]
        self.assertEqual((code, finding["code"], finding["line"]), (1, "SWG003", 1))

    def test_timeout_exits_one(self) -> None:
        runner = StagedRunner(raises={"build": subprocess.TimeoutExpired("swift", 1.0)})
        code, out, _ = self.main(["--timeout-seconds", "1"], runner)
        self.assertEqual(code, 1)
        self.assertIn("build stage timed out after 1s", out)

    def test_path_must_be_a_directory(self) -> None:
        with self.assertRaises(SystemExit) as ctx, redirect_stderr(io.StringIO()):
            swift_gate.main(["--path", str(self.root / "missing")])
        self.assertEqual(ctx.exception.code, 2)


class ToolchainTests(unittest.TestCase):
    """locate_swift: macOS only, --swift first, else PATH."""

    def test_non_darwin_exits_two(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            write(root / "pyproject.toml", PYPROJECT)
            make_package(root / "pkg")
            err = io.StringIO()
            with (
                mock.patch.object(swift_gate.sys, "platform", "linux"),
                redirect_stdout(io.StringIO()),
                redirect_stderr(err),
            ):
                code = swift_gate.main(["--path", tmp])
        self.assertEqual(code, 2)
        self.assertIn("host linux", err.getvalue())

    def test_explicit_swift_must_exist(self) -> None:
        with TemporaryDirectory() as tmp:
            driver = write(Path(tmp) / "swift", "")
            self.assertEqual(
                swift_gate.locate_swift(str(driver), "darwin"), str(driver)
            )
            self.assertIsNone(
                swift_gate.locate_swift(str(Path(tmp) / "nope"), "darwin")
            )

    def test_a_bare_explicit_name_is_looked_up_on_path(self) -> None:
        # `--swift swift` names a command, not a file in the cwd: resolve it like PATH.
        with mock.patch.object(
            swift_gate.shutil, "which", return_value="/opt/swift"
        ) as which:
            self.assertEqual(swift_gate.locate_swift("swift", "darwin"), "/opt/swift")
        which.assert_called_once_with("swift")
        with mock.patch.object(swift_gate.shutil, "which", return_value=None):
            self.assertIsNone(swift_gate.locate_swift("swift", "darwin"))

    def test_path_lookup_is_used_without_explicit(self) -> None:
        with mock.patch.object(swift_gate.shutil, "which", return_value="/opt/swift"):
            self.assertEqual(swift_gate.locate_swift(None, "darwin"), "/opt/swift")


class HelpTests(unittest.TestCase):
    """--help shows each default and the prerequisites epilog."""

    def test_help_shows_defaults_and_epilog(self) -> None:
        text = " ".join(swift_gate.build_parser().format_help().split())
        self.assertIn("(default: 100.0)", text)
        self.assertIn("(default: 1200.0)", text)
        self.assertIn("Prerequisites:", text)
        self.assertIn("SWG005", text)


if __name__ == "__main__":
    unittest.main()
