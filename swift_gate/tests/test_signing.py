"""Grouped suite: the opt-in ``--sign`` stage and the signing setting it reads.

Every identity here is an obvious fake, and no test reaches the real ``codesign`` or the
real ``git``: both go through recording fakes. The fake identity's team ID is asserted
absent from every rendered line, because a log pasted into an issue must not carry it.
"""

from __future__ import annotations

import dataclasses
import io
import json
import os
import subprocess
import unittest
from collections.abc import Sequence
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

from _fixtures import (
    StagedRunner,
    completed,
    dump_package,
    export_data,
    make_package,
    write,
)

import swgate_manifest
import swgate_signing
import swgate_stages
import swift_gate
from swgate_model import (
    Configured,
    GateOptions,
    GateResult,
    NotConfigured,
    ParseError,
    SigningConfigError,
    SigningSetting,
    Subject,
)

TEAM_ID = "ABCDE12345"
IDENTITY = f"Apple Development: Example ({TEAM_ID})"
EXECUTABLE = {
    "name": "hello",
    "settings": [],
    "targets": ["Hello"],
    "type": {"executable": None},
}
LIBRARY = {
    "name": "L",
    "settings": [],
    "targets": ["Lib"],
    "type": {"library": ["automatic"]},
}


class FakeTool:
    """A recording fake for a process seam, answering by a substring of the argv."""

    def __init__(self, outcomes: Sequence[tuple[str, int, str, str]] = ()) -> None:
        self.outcomes = outcomes
        self.calls: list[list[str]] = []
        self.raises: BaseException | None = None

    def __call__(
        self, argv: Sequence[str], *, cwd: Path, timeout: float
    ) -> subprocess.CompletedProcess[str]:
        del cwd, timeout  # the fake never runs anything
        self.calls.append(list(argv))
        if self.raises is not None:
            raise self.raises
        joined = " ".join(argv)
        for needle, code, out, err in self.outcomes:
            if needle in joined:
                return completed(argv, code, out, err)
        return completed(argv, 0, "", "")


class ReadSettingTests(unittest.TestCase):
    """read_signing_identity: absent, configured, refused, malformed."""

    def setUp(self) -> None:
        tmp = TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.home = Path(tmp.name).resolve() / "home"
        self.checkout = Path(tmp.name).resolve() / "checkout"
        self.checkout.mkdir(parents=True)
        self.path = self.home / ".config" / "swift_gate" / "signing.toml"

    def read(self, roots: Sequence[Path] | None = None) -> object:
        """Read the setting with *roots* (the checkout by default) as the checkouts."""
        return swgate_signing.read_signing_identity(
            self.path, checkout_roots=roots if roots is not None else (self.checkout,)
        )

    def test_absent_file_is_not_configured(self) -> None:
        self.assertEqual(self.read(), NotConfigured(self.path))

    def test_identity_is_read(self) -> None:
        write(self.path, f'identity = "{IDENTITY}"\n')
        self.assertEqual(self.read(), Configured(IDENTITY))

    def test_file_under_a_checkout_is_refused(self) -> None:
        worktree = self.checkout / ".claude" / "worktrees" / "lane"
        for where in (self.checkout / "signing.toml", worktree / "x" / "signing.toml"):
            self.path = write(where, f'identity = "{IDENTITY}"\n')
            with self.subTest(where=where):
                with self.assertRaises(SigningConfigError) as ctx:
                    self.read((self.checkout, worktree))
                self.assertIn("outside every checkout", str(ctx.exception))
                self.assertNotIn(TEAM_ID, str(ctx.exception))

    def test_absent_file_under_a_checkout_is_still_refused(self) -> None:
        self.path = self.checkout / "signing.toml"
        with self.assertRaises(SigningConfigError):
            self.read()

    def test_each_malformed_shape_is_refused(self) -> None:
        for body in (
            f'identity = "{IDENTITY}\n',  # unterminated string: not TOML
            'name = "x"\n',  # no identity key
            'identity = ""\n',  # empty
            'identity = "   "\n',  # blank
            "identity = 5\n",  # not a string
            f'identity = ["{IDENTITY}"]\n',  # not a string
        ):
            write(self.path, body)
            with self.subTest(body=body):
                with self.assertRaises(SigningConfigError) as ctx:
                    self.read()
                self.assertNotIn(TEAM_ID, str(ctx.exception))

    def test_undecodable_or_unreadable_file_is_refused(self) -> None:
        self.path.parent.mkdir(parents=True)
        self.path.write_bytes(b'identity = "\xff"\n')
        with self.assertRaises(SigningConfigError):
            self.read()
        self.path.unlink()
        self.path.mkdir()  # a directory where the file should be
        with self.assertRaises(SigningConfigError):
            self.read()


class CheckoutRootsTests(unittest.TestCase):
    """checkout_roots: the target's top level plus every listed worktree."""

    def test_top_level_and_worktrees_are_returned(self) -> None:
        with TemporaryDirectory() as tmp:
            top, lane = Path(tmp).resolve() / "top", Path(tmp).resolve() / "lane"
            git = FakeTool(
                [
                    ("--show-toplevel", 0, f"{top}\n", ""),
                    (
                        "worktree list",
                        0,
                        f"worktree {top}\nHEAD 0\nbranch main\n\nworktree {lane}\n",
                        "",
                    ),
                ]
            )
            roots = swgate_signing.checkout_roots(top, git, timeout=5.0)
        self.assertEqual(roots, (top, lane))
        self.assertEqual(
            git.calls[0], ["git", "-C", str(top), "rev-parse", "--show-toplevel"]
        )
        self.assertEqual(git.calls[1], ["git", "worktree", "list", "--porcelain"])

    def test_outside_any_repository_is_no_roots(self) -> None:
        git = FakeTool([("--show-toplevel", 128, "", "fatal: not a git repository")])
        self.assertEqual(swgate_signing.checkout_roots(Path("."), git, timeout=5.0), ())
        self.assertEqual(len(git.calls), 1)

    def test_a_failed_worktree_list_is_refused(self) -> None:
        git = FakeTool(
            [("--show-toplevel", 0, "/x\n", ""), ("worktree", 1, "", "boom")]
        )
        with self.assertRaises(SigningConfigError):
            swgate_signing.checkout_roots(Path("."), git, timeout=5.0)

    def test_git_that_cannot_run_is_refused(self) -> None:
        for exc in (FileNotFoundError("git"), subprocess.TimeoutExpired("git", 5.0)):
            git = FakeTool()
            git.raises = exc
            with self.subTest(exc=type(exc).__name__):
                with self.assertRaises(SigningConfigError):
                    swgate_signing.checkout_roots(Path("."), git, timeout=5.0)


class RenderTests(unittest.TestCase):
    """The identity is shown as its first word plus an ellipsis, and scrubbed."""

    def test_render_is_first_word_and_ellipsis(self) -> None:
        self.assertEqual(swgate_signing.render_identity(IDENTITY), "Apple…")
        self.assertEqual(swgate_signing.render_identity("-"), "<identity>…")

    def test_redact_scrubs_the_identity_and_its_team_id(self) -> None:
        text = f'"{IDENTITY}": ambiguous; also {TEAM_ID} alone'
        scrubbed = swgate_signing.redact(text, IDENTITY)
        self.assertNotIn(TEAM_ID, scrubbed)
        # The common name keeps only its type.
        self.assertIn("Apple Development: …", scrubbed)
        self.assertEqual(swgate_signing.redact("plain", "-"), "plain")


class ProductsTests(unittest.TestCase):
    """The executable products read from the dump."""

    def test_executables_are_the_executable_products_only(self) -> None:
        dump = dump_package(products=[EXECUTABLE, LIBRARY])
        facts = swgate_manifest.parse_dump_package(swift_gate_json(dump))
        self.assertEqual(facts.executables, ("hello",))

    def test_a_drifted_products_shape_is_untrusted(self) -> None:
        for products in ("none", [{"name": "x"}], [{"name": "x", "type": "exe"}]):
            dump = dump_package(products=products)
            with self.subTest(products=products), self.assertRaises(ParseError):
                swgate_manifest.parse_dump_package(swift_gate_json(dump))
        dump = dump_package()
        del dump["products"]
        with self.assertRaises(ParseError):
            swgate_manifest.parse_dump_package(swift_gate_json(dump))


def swift_gate_json(dump: dict[str, object]) -> str:
    """*dump* as the JSON text the manifest stage would read."""
    return json.dumps(dump)


class _SignCase(unittest.TestCase):
    """A passing package, its scratch and bin dirs, and a recording codesign fake."""

    def setUp(self) -> None:
        tmp = TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        base = Path(tmp.name).resolve()
        self.root = make_package(base / "checkout" / "pkg")
        self.opts = GateOptions(
            swift="swift", macos_floor="14", scratch_base=base / "scratch"
        )
        self.scratch = swgate_stages.scratch_for(self.root, self.opts.scratch_base)
        self.codecov = self.scratch / "codecov" / "Floor.json"
        self.bin = self.scratch / "out" / "Products" / "Debug"
        self.product = write(self.bin / "hello", "binary")
        write(self.root / "Sources/Floor/Floor.swift", "")
        self.codesign = FakeTool()

    def runner(self, outcomes: Sequence[tuple[str, int, str]] = ()) -> StagedRunner:
        """A fake whose dump declares the executable product, at 80% passing."""
        return StagedRunner(
            dump=dump_package(products=[EXECUTABLE, LIBRARY]),
            codecov=self.codecov,
            report=export_data(self.root, self.scratch),
            bin_path=self.bin,
            outcomes=outcomes,
        )

    def gate(self, runner: StagedRunner, signing: SigningSetting | None) -> GateResult:
        """Run the pipeline with *signing* on the options and the codesign fake."""
        opts = dataclasses.replace(self.opts, signing=signing, min_percent=80.0)
        return swgate_stages.run_stages(
            Subject(self.root), opts, runner, codesign=self.codesign
        )


class SignStageTests(_SignCase):
    """The stage after coverage: off, not configured, nothing to sign, sign + verify."""

    def test_signing_off_runs_no_sign_stage(self) -> None:
        runner = self.runner()
        result = self.gate(runner, None)
        self.assertEqual(result.returncode, 0)
        self.assertNotIn("bin-path", runner.stage_names())
        self.assertEqual(self.codesign.calls, [])
        self.assertNotIn("signing", result.detail)

    def test_not_configured_passes_with_the_message(self) -> None:
        path = Path("<home>/.config/swift_gate/signing.toml")
        result = self.gate(self.runner(), NotConfigured(path))
        self.assertEqual(result.returncode, 0)
        self.assertIn(f"signing: not configured ({path} absent)", result.detail)
        self.assertEqual(self.codesign.calls, [])

    def test_no_executable_product_is_nothing_to_sign(self) -> None:
        runner = self.runner()
        runner.dump = dump_package(products=[LIBRARY])
        result = self.gate(runner, Configured(IDENTITY))
        self.assertEqual(result.returncode, 0)
        self.assertIn("signing: nothing to sign", result.detail)
        self.assertEqual(self.codesign.calls, [])

    def test_configured_signs_then_verifies_a_copy_in_order(self) -> None:
        runner = self.runner()
        result = self.gate(runner, Configured(IDENTITY))
        self.assertEqual(result.returncode, 0, result.detail)
        self.assertEqual(runner.stage_names()[-1], "bin-path")
        sign, verify = self.codesign.calls
        copy = sign[-1]
        self.assertEqual(
            sign, ["codesign", "--force", "--sign", IDENTITY, "--timestamp=none", copy]
        )
        self.assertEqual(
            verify, ["codesign", "--verify", "--strict", "--verbose=2", copy]
        )
        self.assertEqual(Path(copy).name, "hello")
        self.assertNotEqual(Path(copy), self.product)
        self.assertNotIn(self.scratch, Path(copy).parents)
        self.assertIn("signed and verified hello with Apple…", result.detail)
        self.assertNotIn(TEAM_ID, result.detail)

    def test_codesign_failure_is_exit_one_with_its_stderr(self) -> None:
        for needle in ("--force", "--verify"):
            self.codesign = FakeTool(
                [(needle, 1, "", f"error: {IDENTITY}: no identity found")]
            )
            result = self.gate(self.runner(), Configured(IDENTITY))
            with self.subTest(step=needle):
                self.assertEqual(result.returncode, 1)
                self.assertIn("no identity found", result.detail)
                self.assertNotIn(TEAM_ID, result.detail)

    def test_a_failed_coverage_verdict_skips_signing(self) -> None:
        opts = dataclasses.replace(self.opts, signing=Configured(IDENTITY))
        result = swgate_stages.run_stages(
            Subject(self.root), opts, self.runner(), codesign=self.codesign
        )
        self.assertEqual(result.returncode, 1)
        self.assertIn("signing: skipped", result.detail)
        self.assertEqual(self.codesign.calls, [])

    def test_bin_path_failure_is_exit_one(self) -> None:
        runner = self.runner(outcomes=[("--show-bin-path", 1, "no")])
        result = self.gate(runner, Configured(IDENTITY))
        self.assertEqual(result.returncode, 1)
        self.assertIn("--show-bin-path", result.detail)

    def test_missing_built_product_is_exit_one(self) -> None:
        self.product.unlink()
        result = self.gate(self.runner(), Configured(IDENTITY))
        self.assertEqual(result.returncode, 1)
        self.assertIn("hello", result.detail)
        self.assertEqual(self.codesign.calls, [])

    def test_codesign_absent_is_exit_two(self) -> None:
        self.codesign.raises = FileNotFoundError("codesign")
        result = self.gate(self.runner(), Configured(IDENTITY))
        self.assertEqual(result.returncode, 2)
        self.assertIn("could not run codesign", result.detail)

    def test_codesign_timeout_names_the_sign_stage(self) -> None:
        self.codesign.raises = subprocess.TimeoutExpired("codesign", 5.0)
        result = self.gate(self.runner(), Configured(IDENTITY))
        self.assertEqual(result.returncode, 1)
        self.assertIn("sign stage timed out", result.detail)

    def test_the_swift_seam_serves_codesign_when_none_is_given(self) -> None:
        runner = self.runner()
        opts = dataclasses.replace(
            self.opts, signing=Configured(IDENTITY), min_percent=80.0
        )
        result = swgate_stages.run_stages(Subject(self.root), opts, runner)
        self.assertEqual(result.returncode, 0, result.detail)
        self.assertEqual(runner.calls[-1][:2], ["codesign", "--verify"])


class _CliCase(_SignCase):
    """main() against the package, with every seam faked and the setting outside."""

    def setUp(self) -> None:
        super().setUp()
        self.top = self.root.parent
        write(self.top / "pyproject.toml", '[tool.swift_gate]\nmacos_floor = "14"\n')
        self.config = self.top.parent / "home" / "signing.toml"  # outside the checkout
        self.git = FakeTool([("--show-toplevel", 0, f"{self.top}\n", "")])

    def main(self, extra: list[str]) -> tuple[int, str, str]:
        """Run main against the package with every seam faked."""
        out, err = io.StringIO(), io.StringIO()
        argv = ["--path", str(self.top), "--scratch-path", str(self.opts.scratch_base)]
        with (
            mock.patch.object(swift_gate, "_run_swift", self.runner()),
            mock.patch.object(swift_gate, "_run_codesign", self.codesign),
            mock.patch.object(swift_gate, "_run_git", self.git),
            mock.patch.object(swift_gate, "locate_swift", return_value="swift"),
            redirect_stdout(out),
            redirect_stderr(err),
        ):
            code = swift_gate.main([*argv, "--min-percent", "80", *extra])
        return code, out.getvalue(), err.getvalue()


class SignCliTests(_CliCase):
    """main(): --sign on and off, the setting's path, and what reaches the streams."""

    def test_sign_off_never_reads_the_setting(self) -> None:
        write(self.config, "not toml at all [")
        with mock.patch.object(swift_gate, "read_signing_identity") as reader:
            code, out, _ = self.main(["--signing-config", str(self.config)])
        self.assertEqual(code, 0)
        reader.assert_not_called()
        self.assertEqual(self.git.calls, [])
        self.assertNotIn("signing", out)

    def test_absent_setting_passes_with_the_message(self) -> None:
        code, out, _ = self.main(["--sign", "--signing-config", str(self.config)])
        self.assertEqual(code, 0, out)
        self.assertIn(f"signing: not configured ({self.config} absent)", out)

    def test_setting_inside_the_checkout_exits_two(self) -> None:
        inside = write(self.top / "signing.toml", f'identity = "{IDENTITY}"\n')
        code, out, err = self.main(["--sign", "--signing-config", str(inside)])
        self.assertEqual(code, 2)
        self.assertIn("outside every checkout", err)
        self.assertNotIn(TEAM_ID, out + err)
        self.assertEqual(self.codesign.calls, [])

    def test_malformed_setting_exits_two(self) -> None:
        write(self.config, "identity = 5\n")
        code, _, err = self.main(["--sign", "--signing-config", str(self.config)])
        self.assertEqual(code, 2)
        self.assertIn("identity", err)

    def test_configured_signs_and_never_prints_the_team_id(self) -> None:
        write(self.config, f'identity = "{IDENTITY}"\n')
        code, out, err = self.main(["--sign", "--signing-config", str(self.config)])
        self.assertEqual(code, 0, out + err)
        self.assertEqual(
            [call[1] for call in self.codesign.calls], ["--force", "--verify"]
        )
        self.assertIn("Apple…", out)
        self.assertNotIn(TEAM_ID, out + err)

    def test_codesign_failure_exits_one_without_the_team_id(self) -> None:
        write(self.config, f'identity = "{IDENTITY}"\n')
        self.codesign = FakeTool([("--force", 1, "", f"{IDENTITY}: not found")])
        code, out, err = self.main(["--sign", "--signing-config", str(self.config)])
        self.assertEqual(code, 1)
        self.assertIn("not found", out)
        self.assertNotIn(TEAM_ID, out + err)

    def test_default_setting_path_is_under_home(self) -> None:
        with mock.patch.dict(os.environ, {"HOME": "/h"}):
            default = (
                swift_gate.build_parser().parse_args(["--path", "."]).signing_config
            )
            home = Path.home()
        self.assertEqual(default, Path("/h/.config/swift_gate/signing.toml"))
        self.assertTrue(default.is_relative_to(home))


if __name__ == "__main__":
    unittest.main()
