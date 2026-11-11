"""Grouped suite: the checkout guard's bypasses, codesign's redacted echo, and paths.

Regression tests for the security review of ``--sign``: a case variant of a checkout path,
a ``git rev-parse`` failure other than "not a git repository", a setting inside an
unrelated repository, codesign echoing every matching certificate's common name, a
single-word identity, and absolute home paths in diagnostics. Every identity and team ID
is an obvious fake, and ``git`` is a recording fake throughout.
"""

from __future__ import annotations

import io
import json
import subprocess
import unittest
from collections.abc import Sequence
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

from _fixtures import dump_package, write

# The base cases are reached through the module, so discovery does not collect them here a
# second time; FakeTool and the fakes' names are shared, not restated.
import test_signing
from test_signing import IDENTITY, LIBRARY, TEAM_ID, FakeTool

import swgate_manifest
import swgate_signing
import swift_gate
from swgate_model import Configured, NotConfigured, SigningConfigError

OTHER_ID = "FGHIJ67890"
AMBIGUOUS = (
    f"Apple Development: Example Person ({TEAM_ID}): ambiguous (matches "
    f'"Apple Development: Example Person ({TEAM_ID})" and '
    f'"Apple Development: Other Person ({OTHER_ID})" in <keychain>)'
)
SHA1 = "0123456789abcdef0123456789abcdef01234567"
NOT_A_REPO = "fatal: not a git repository (or any of the parent directories): .git"
DUBIOUS = "fatal: detected dubious ownership in repository at '<dir>'"


class CaseBypassTests(unittest.TestCase):
    """A case variant of a checkout path is the same directory on APFS: refuse it."""

    def test_a_case_variant_of_the_checkout_is_refused(self) -> None:
        with TemporaryDirectory() as tmp:
            checkout = Path(tmp).resolve() / "checkout"
            checkout.mkdir()
            variant = checkout.parent / "CHECKOUT"
            if not variant.exists():
                self.skipTest(
                    "the temp volume is case-sensitive; no case variant exists"
                )
            with self.assertRaises(SigningConfigError) as ctx:
                swgate_signing.read_signing_identity(
                    variant / "signing.toml", checkout_roots=(checkout,)
                )
        self.assertIn("outside every checkout", str(ctx.exception))


class TargetRevParseTests(unittest.TestCase):
    """The target-side query: only "not a git repository" means no checkout."""

    def test_a_rev_parse_failure_other_than_not_a_repo_is_refused(self) -> None:
        for stderr in (DUBIOUS, "fatal: unable to read .git", ""):
            git = FakeTool([("--show-toplevel", 128, "", stderr)])
            with self.subTest(stderr=stderr), self.assertRaises(SigningConfigError):
                swgate_signing.checkout_roots(Path("."), git, timeout=5.0)

    def test_not_a_repo_is_still_no_roots(self) -> None:
        git = FakeTool([("--show-toplevel", 128, "", NOT_A_REPO)])
        self.assertEqual(swgate_signing.checkout_roots(Path("."), git, timeout=5.0), ())


class EnclosingCheckoutTests(unittest.TestCase):
    """The setting-side query: git asked from the setting's nearest existing ancestor."""

    def setUp(self) -> None:
        tmp = TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.repo = Path(tmp.name).resolve() / "unrelated"
        self.repo.mkdir()
        self.path = self.repo / "absent" / "deeper" / "signing.toml"

    def enclosing(self, git: FakeTool) -> tuple[Path, ...]:
        """The repository enclosing the setting path, through *git*."""
        return swgate_signing.enclosing_checkout(self.path, git, timeout=5.0)

    def test_a_repository_enclosing_the_setting_is_a_root(self) -> None:
        git = FakeTool([("--show-toplevel", 0, f"{self.repo}\n", "")])
        self.assertEqual(self.enclosing(git), (self.repo,))
        self.assertEqual(
            git.calls, [["git", "-C", str(self.repo), "rev-parse", "--show-toplevel"]]
        )

    def test_outside_any_repository_is_no_roots(self) -> None:
        git = FakeTool([("--show-toplevel", 128, "", NOT_A_REPO)])
        self.assertEqual(self.enclosing(git), ())

    def test_any_other_failure_is_refused(self) -> None:
        git = FakeTool([("--show-toplevel", 128, "", DUBIOUS)])
        with self.assertRaises(SigningConfigError):
            self.enclosing(git)
        for exc in (FileNotFoundError("git"), subprocess.TimeoutExpired("git", 5.0)):
            git = FakeTool()
            git.raises = exc
            with self.subTest(exc=type(exc).__name__):
                with self.assertRaises(SigningConfigError):
                    self.enclosing(git)


class UnrelatedRepositoryCliTests(test_signing._CliCase):
    """main(): a setting inside a repository other than the target's is exit 2."""

    def test_setting_inside_an_unrelated_repository_exits_two(self) -> None:
        other = self.top.parent / "dotfiles"
        config = write(other / "signing.toml", f'identity = "{IDENTITY}"\n')
        self.git = FakeTool(
            [
                (f"-C {other} ", 0, f"{other}\n", ""),
                ("--show-toplevel", 0, f"{self.top}\n", ""),
            ]
        )
        code, out, err = self.main(["--sign", "--signing-config", str(config)])
        self.assertEqual(code, 2, out + err)
        self.assertIn("outside every checkout", err)
        self.assertEqual(self.codesign.calls, [])

    def test_git_discovery_variables_are_dropped_from_its_environment(self) -> None:
        environ = {
            "PATH": "/usr/bin",
            "GIT_DIR": ".git",
            "GIT_WORK_TREE": "w",
            "GIT_CEILING_DIRECTORIES": "/",
            "GIT_COMMON_DIR": "c",
        }
        self.assertEqual(
            swift_gate.git_environment(environ), {"PATH": "/usr/bin", "LC_ALL": "C"}
        )

    def test_git_runs_in_the_c_locale_whatever_the_callers(self) -> None:
        # "not a git repository" is matched in git's stderr, which a translated locale
        # rewords: a German or French session would turn "no checkout" into exit 2.
        environ = {"LANG": "de_DE.UTF-8", "LC_ALL": "fr_FR.UTF-8"}
        env = swift_gate.git_environment(environ)
        self.assertEqual(env["LC_ALL"], "C")
        self.assertEqual(env["LANG"], "de_DE.UTF-8")  # LC_ALL outranks it; kept as is

    def test_a_git_failure_message_carries_no_home_path(self) -> None:
        # TimeoutExpired's text quotes the whole argv, `-C <absolute dir>` included.
        home = Path.home()
        argv = ["git", "-C", str(home / "project"), "rev-parse", "--show-toplevel"]
        for exc in (
            subprocess.TimeoutExpired(argv, 5.0),
            FileNotFoundError(2, "No such file", str(home / "bin" / "git")),
        ):
            git = FakeTool()
            git.raises = exc
            with self.subTest(exc=type(exc).__name__):
                with self.assertRaises(SigningConfigError) as ctx:
                    swgate_signing.checkout_roots(home / "project", git, timeout=5.0)
                self.assertNotIn(str(home), str(ctx.exception))
                self.assertIn("~/", str(ctx.exception))


class ReadResolvedTests(unittest.TestCase):
    """The file read is the path the guard checked, not the one as given (TOCTOU)."""

    def test_the_resolved_path_is_read(self) -> None:
        with TemporaryDirectory() as tmp:
            base = Path(tmp).resolve()
            real = write(base / "real" / "signing.toml", f'identity = "{IDENTITY}"\n')
            (base / "link").symlink_to(base / "real")
            reads: list[Path] = []

            def read_text(path: Path) -> str:
                reads.append(path)
                return path.read_text(encoding="utf-8")

            setting = swgate_signing.read_signing_identity(
                base / "link" / "signing.toml",
                checkout_roots=(base / "checkout",),
                read_text=read_text,
            )
        self.assertEqual(setting, Configured(IDENTITY))
        self.assertEqual(reads, [real])


class RedactEchoTests(unittest.TestCase):
    """codesign's own echo carries every matching certificate: scrub them all."""

    def test_an_ambiguity_error_loses_every_name_and_team_id(self) -> None:
        scrubbed = swgate_signing.redact(AMBIGUOUS, "Apple Development")
        for secret in (TEAM_ID, OTHER_ID, "Example Person", "Other Person"):
            self.assertNotIn(secret, scrubbed)
        self.assertIn(": …", scrubbed)
        self.assertIn("ambiguous", scrubbed)

    def test_a_bare_parenthesized_team_id_is_scrubbed(self) -> None:
        scrubbed = swgate_signing.redact(f"team ({OTHER_ID}) only", "-")
        self.assertEqual(scrubbed, "team (…) only")

    def test_an_identity_rendering_would_not_shorten_is_left_alone(self) -> None:
        text = "codesign --verify --strict: a-b"
        self.assertEqual(swgate_signing.redact(text, "-"), text)

    def test_a_short_parenthesized_token_is_not_a_team_id(self) -> None:
        self.assertEqual(swgate_signing.redact("ABOUT AB", "Example (AB)"), "ABOUT AB")

    def test_a_name_with_a_parenthesis_colon_or_quote_is_scrubbed(self) -> None:
        # A common name is free text: a parenthesized company, a colon or a quote inside
        # it must not stop the scrub short and leave the name in the log.
        for name in ("Jane (Acme) Doe", "Jane: Doe", 'Jane "JD" Doe'):
            text = f"Apple Development: {name} ({TEAM_ID}): ambiguous"
            with self.subTest(name=name):
                scrubbed = swgate_signing.redact(text, "-")
                self.assertEqual(scrubbed, "Apple Development: …: ambiguous")


class SingleWordIdentityTests(unittest.TestCase):
    """A one-word identity (a SHA-1, a bare team ID) is never printed: a placeholder is."""

    def test_a_single_word_renders_as_the_placeholder(self) -> None:
        for identity in (SHA1, TEAM_ID, "-"):
            with self.subTest(identity=identity):
                self.assertEqual(
                    swgate_signing.render_identity(identity), "<identity>…"
                )
        self.assertEqual(swgate_signing.render_identity(IDENTITY), "Apple…")

    def test_redact_scrubs_a_single_word_identity(self) -> None:
        scrubbed = swgate_signing.redact(f"error: {SHA1}: not found", SHA1)
        self.assertNotIn(SHA1, scrubbed)
        self.assertIn("<identity>…", scrubbed)

    def test_redact_scrubs_a_bare_team_id_identity(self) -> None:
        # Ten characters: no longer than the placeholder, so only the team-ID rule hides it.
        scrubbed = swgate_signing.redact(f"error: {TEAM_ID}: not found", TEAM_ID)
        self.assertEqual(scrubbed, "error: …: not found")


class SingleWordStageTests(test_signing._SignCase):
    """The success line with a SHA-1 identity names the placeholder, never the hash."""

    def test_the_success_line_carries_no_single_word_identity(self) -> None:
        result = self.gate(self.runner(), Configured(SHA1))
        self.assertEqual(result.returncode, 0, result.detail)
        self.assertNotIn(SHA1, result.detail)
        self.assertIn("with <identity>…", result.detail)


class _HomeCase(unittest.TestCase):
    """A temp dir standing in for the running user's home."""

    def setUp(self) -> None:
        tmp = TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.home = Path(tmp.name).resolve() / "home"
        self.home.mkdir()
        patcher = mock.patch.object(Path, "home", return_value=self.home)
        patcher.start()
        self.addCleanup(patcher.stop)

    def assert_home_free(self, text: str) -> None:
        """*text* names the home only as ``~``."""
        self.assertNotIn(str(self.home), text)
        self.assertIn("~/", text)


class RenderPathTests(unittest.TestCase):
    """render_path: a path under the home as ``~/…``, any other as given."""

    def test_render_path(self) -> None:
        home = Path("/h")
        self.assertEqual(swgate_signing.render_path(Path("/h/a/b"), home), "~/a/b")
        self.assertEqual(swgate_signing.render_path(Path("/h"), home), "~")
        self.assertEqual(swgate_signing.render_path(Path("/x/a"), home), "/x/a")


class HomePathMessageTests(_HomeCase):
    """No diagnostic carries the absolute home path."""

    def test_the_refusal_names_the_path_and_root_under_home_as_tilde(self) -> None:
        checkout = self.home / "workspace"
        with self.assertRaises(SigningConfigError) as ctx:
            swgate_signing.read_signing_identity(
                checkout / "signing.toml", checkout_roots=(checkout,)
            )
        self.assert_home_free(str(ctx.exception))
        self.assertIn(
            "~/workspace/signing.toml is inside ~/workspace", str(ctx.exception)
        )

    def test_malformed_setting_messages_name_the_path_as_tilde(self) -> None:
        path = self.home / ".config" / "swift_gate" / "signing.toml"
        for body in ("not toml [", "identity = 5\n", None):
            if body is None:
                path.unlink()
                path.mkdir()  # unreadable: a directory where the file should be
            else:
                write(path, body)
            with self.subTest(body=body), self.assertRaises(SigningConfigError) as ctx:
                swgate_signing.read_signing_identity(path, checkout_roots=())
            self.assert_home_free(str(ctx.exception))


class HomePathStageTests(test_signing._SignCase):
    """The stage's messages name a home path as ``~``, codesign's output included."""

    def test_not_configured_names_the_default_as_tilde(self) -> None:
        home = self.root.parent.parent / "home"
        path = home / ".config" / "swift_gate" / "signing.toml"
        with mock.patch.object(Path, "home", return_value=home):
            result = self.gate(self.runner(), NotConfigured(path))
        self.assertIn(
            "signing: not configured (~/.config/swift_gate/signing.toml absent)",
            result.detail,
        )
        self.assertNotIn(str(home), result.detail)

    def test_codesign_output_names_a_home_path_as_tilde(self) -> None:
        home = self.root.parent.parent / "home"
        keychain = home / "Library" / "Keychains" / "login.keychain-db"
        self.codesign = FakeTool(
            [("--force", 1, "", AMBIGUOUS.replace("<keychain>", str(keychain)))]
        )
        with mock.patch.object(Path, "home", return_value=home):
            result = self.gate(self.runner(), Configured("Apple Development"))
        self.assertEqual(result.returncode, 1)
        self.assertNotIn(str(home), result.detail)
        self.assertIn("~/Library/Keychains", result.detail)
        for secret in (TEAM_ID, OTHER_ID, "Example Person", "Other Person"):
            self.assertNotIn(secret, result.detail)


IMPLICIT = {"dependencies": [], "name": "Tool", "settings": [], "type": "executable"}
COVERED = {"dependencies": [], "name": "Hello", "settings": [], "type": "executable"}
REGULAR = {"dependencies": [], "name": "Lib", "settings": [], "type": "regular"}
HELLO = {
    "name": "hello",
    "settings": [],
    "targets": ["Hello"],
    "type": {"executable": None},
}


def executables(products: Sequence[object], targets: Sequence[object]) -> object:
    """The executables parsed from a dump with *products* and *targets*."""
    dump = dump_package(products=list(products), targets=list(targets))
    return swgate_manifest.parse_dump_package(json.dumps(dump)).executables


class ImplicitExecutableTests(unittest.TestCase):
    """An executable target no declared product covers is an implicit product."""

    def test_uncovered_executable_targets_join_the_declared_products(self) -> None:
        self.assertEqual(
            executables([HELLO, LIBRARY], [COVERED, IMPLICIT, REGULAR]),
            ("hello", "Tool"),
        )

    def test_only_an_executable_target_is_nothing_but_its_implicit_product(
        self,
    ) -> None:
        self.assertEqual(executables([], [IMPLICIT, REGULAR]), ("Tool",))

    def test_a_name_declared_and_implicit_is_listed_once(self) -> None:
        tool = {**HELLO, "name": "Tool", "targets": ["Other"]}
        self.assertEqual(executables([tool], [IMPLICIT]), ("Tool",))


class ImplicitExecutableStageTests(test_signing._SignCase):
    """The stage signs an executable target that declares no product."""

    def test_an_executable_target_with_no_product_is_signed(self) -> None:
        write(self.bin / "Tool", "binary")
        runner = self.runner()
        runner.dump = dump_package(products=[LIBRARY], targets=[IMPLICIT, REGULAR])
        result = self.gate(runner, Configured(IDENTITY))
        self.assertEqual(result.returncode, 0, result.detail)
        self.assertIn("signed and verified Tool", result.detail)
        self.assertEqual(Path(self.codesign.calls[0][-1]).name, "Tool")


class SigningConfigHelpTests(unittest.TestCase):
    """--signing-config's default is shown symbolically and expanded when parsed."""

    def test_help_shows_the_tilde_default(self) -> None:
        out = io.StringIO()
        with redirect_stdout(out), redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):
                swift_gate.build_parser().parse_args(["--help"])
        self.assertIn("~/.config/swift_gate/signing.toml", out.getvalue())
        self.assertNotIn(str(Path.home()), out.getvalue())


if __name__ == "__main__":
    unittest.main()
