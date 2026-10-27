"""Every environment variable this project reads by name is declared to the gate cache.

`APPLE_MUSIC_TOOLBOX_OFFLINE` skips every live boundary test, so it changes a gate verdict
without changing one file. The workspace gate's verdict cache folds in only the variables
that `[tool.gate_cache] env` in this project's pyproject.toml declares. An undeclared one
lets a verdict recorded with it unset be replayed into a run with it set, and the
reverse -- an online sweep replaying an offline PASS never runs the live tests at all.

So this test fails on a read nothing declares, or one whose name it cannot resolve, which stops a new switch landing without
its declaration, and on a declaration nothing reads, which stops a renamed switch leaving
a stale name behind. It sits under tag_refresh only because a test must live under one
tool; it scans every tool folder in this project, and skips the vendored shared
libraries for the reason recorded beside `_VENDORED`.

One narrow class is held apart: a CREDENTIAL. Folding a token's value into a persisted
cache key would write a secret's fingerprint to disk, and a credential never changes which
tests run, since every suite that could reach one clears it first. So `_CREDENTIAL_READS`
names each such variable with its reason. The read stays visible to this scan rather than
hidden from it: an exempted name must still be read somewhere OUTSIDE the tests, so a
stale exemption fails just as a stale declaration does, and a test's own read cannot keep
one alive. An exempted name may never be declared as well.

A second narrow class is held apart for the same two checks: a variable every suite that
could read it REDIRECTS (a config directory pointed under a temporary HOME), so its value
never reaches a verdict, while declaring it would only split the cache by machine layout.
"""

from __future__ import annotations

import ast
import tomllib
import unittest
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
# How a read is spelled here, compared as unparsed source so `os.getenv` and a bare
# `getenv` imported from os are both seen.
_GETTERS = frozenset({"os.environ.get", "os.getenv", "environ.get", "getenv"})
_MAPPINGS = frozenset({"os.environ", "environ"})
# A switch the scan must find, so a scanner that silently stopped matching cannot pass
# by finding nothing on either side.
_KNOWN_SWITCH = "APPLE_MUSIC_TOOLBOX_OFFLINE"

# The vendored shared libraries, skipped by the scan below. Their environment use is
# test-fixture plumbing -- a pid-file path a test exports for one child and reads back --
# not a switch that changes which tests run, so declaring it would say something untrue.
# Two of those reads name a variable no static scan can resolve (a function parameter,
# and a constant read through its module), which is exactly the shape this scan refuses
# in this project's OWN code. Excluded by name rather than by listing the tool folders,
# so a tool folder added later is scanned by default -- the safe direction.
_VENDORED = frozenset(
    {"stdio_utf8", "help_formatter", "html_page", "bounded_run", "live_pid_guard"}
)
# Credentials the project reads but must never declare, each with its reason. A mapping,
# not a list, so an entry cannot be added without saying why.
_CREDENTIAL_READS: dict[str, str] = {}
# Variables the code reads but every suite that could reach the read redirects, each with
# its reason; held to the same two checks as the credentials above.
_REDIRECTED_READS: dict[str, str] = {}
_EXEMPT_READS = {**_CREDENTIAL_READS, **_REDIRECTED_READS}


def _read_key(node: ast.AST) -> ast.AST | None:
    """The key expression *node* reads the environment with, else None."""
    if isinstance(node, ast.Call) and node.args and ast.unparse(node.func) in _GETTERS:
        return node.args[0]
    if (
        isinstance(node, ast.Subscript)
        and isinstance(node.ctx, ast.Load)
        and ast.unparse(node.value) in _MAPPINGS
    ):
        return node.slice
    if (
        isinstance(node, ast.Compare)
        and isinstance(node.ops[0], (ast.In, ast.NotIn))
        and ast.unparse(node.comparators[0]) in _MAPPINGS
    ):
        return node.left
    return None


def _string_constants(tree: ast.Module) -> dict[str, str]:
    """Module-level ``NAME = "literal"`` bindings, plain or annotated.

    The ``USERNAME_ENV = "..."`` style reads a variable through a named constant, and a
    scan that saw only literals would miss every such read.
    """
    found: dict[str, str] = {}
    for node in tree.body:
        if isinstance(node, ast.Assign):
            targets, value = node.targets, node.value
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            targets, value = [node.target], node.value
        else:
            continue
        if isinstance(value, ast.Constant) and isinstance(value.value, str):
            found.update(
                (t.id, value.value) for t in targets if isinstance(t, ast.Name)
            )
    return found


def _names_read(source: str) -> tuple[set[str], list[str]]:
    """Every name *source* reads from the environment, and each read it cannot name.

    A key resolves when it is a string literal or a module-level constant bound to one.
    Anything else comes back as ``"<line>: <read>"`` so the test FAILS on it: skipping a
    read the scan cannot name would reopen the gap it exists to close.
    """
    tree = ast.parse(source)
    constants = _string_constants(tree)
    names: set[str] = set()
    unresolved: list[str] = []
    for node in ast.walk(tree):
        key = _read_key(node)
        if key is None:
            continue
        if isinstance(key, ast.Constant) and isinstance(key.value, str):
            names.add(key.value)
        elif isinstance(key, ast.Name) and key.id in constants:
            names.add(constants[key.id])
        else:
            unresolved.append(f"{getattr(node, 'lineno', 0)}: {ast.unparse(node)}")
    return names, unresolved


def _is_test_file(relative: Path) -> bool:
    """True for a suite or a fixture: a ``test_*`` file, or anything under ``tests/``."""
    return relative.name.startswith("test_") or "tests" in relative.parts[:-1]


def _project_reads(*, tests: bool = True) -> tuple[set[str], list[str]]:
    """Every environment read in this project's own tools, caches and vendored skipped.

    With *tests* False, test files are left out, which is how an exemption is shown to
    be held up by a read the shipped code makes rather than by a test of it.
    """
    names: set[str] = set()
    unresolved: list[str] = []
    for path in sorted(_PROJECT_ROOT.rglob("*.py")):
        relative = path.relative_to(_PROJECT_ROOT)
        if relative.parts[0] in _VENDORED or any(
            part.startswith(".") or part == "__pycache__" for part in relative.parts
        ):
            continue
        if not tests and _is_test_file(relative):
            continue
        found, unnamed = _names_read(path.read_text(encoding="utf-8"))
        names |= found
        unresolved += [f"{relative.as_posix()}:{entry}" for entry in unnamed]
    return names, unresolved


def _declared() -> set[str]:
    """The names this project's pyproject.toml declares under [tool.gate_cache] env."""
    text = (_PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    return set(tomllib.loads(text)["tool"]["gate_cache"]["env"])


class TestEnvDeclared(unittest.TestCase):
    """The declaration and the reads are the same set, in both directions."""

    def test_the_scanner_sees_each_read_form_and_no_write(self) -> None:
        source = (
            'NAMED_ENV = "E"\n'
            'os.environ.get("A")\n'
            'os.getenv("B")\n'
            'os.environ["C"]\n'
            'if "D" in os.environ: pass\n'
            "os.environ.get(NAMED_ENV)\n"
            'os.environ["W"] = "1"\n'
            'patch.dict(os.environ, {"P": "1"})\n'
            'os.environ.pop("Q", None)\n'
        )
        self.assertEqual(_names_read(source), ({"A", "B", "C", "D", "E"}, []))

    def test_a_read_the_scanner_cannot_name_is_reported(self) -> None:
        """Skipping it would reopen the gap: the name could be a switch nobody declared."""
        _, unresolved = _names_read("def f(name):\n    return os.environ.get(name)\n")
        self.assertEqual(unresolved, ["2: os.environ.get(name)"])

    def test_a_test_file_is_a_suite_or_anything_under_tests(self) -> None:
        cases = {
            "tag_refresh/tests/cli_fixtures.py": True,
            "tag_refresh/tests/test_env_declared.py": True,
            "album_stats/test_album_stats.py": True,
            "tag_refresh/src/refresh_core.py": False,
            "album_stats/album_stats.py": False,
            "tests.py": False,
        }
        for relative, expected in cases.items():
            with self.subTest(relative=relative):
                self.assertIs(_is_test_file(Path(relative)), expected)

    def test_every_environment_read_is_declared_and_nothing_else(self) -> None:
        read, unresolved = _project_reads()
        self.assertEqual(
            unresolved,
            [],
            "an environment read whose name this scan cannot resolve: spell the name "
            "as a string literal or a module-level constant so it can be checked",
        )
        self.assertIn(
            _KNOWN_SWITCH, read, "the scan found no switch; it is not looking"
        )
        shipped, _ = _project_reads(tests=False)
        for name in sorted(_EXEMPT_READS):
            with self.subTest(exempt=name):
                self.assertIn(
                    name,
                    shipped,
                    "an exemption no shipped code reads: remove it",
                )
                self.assertNotIn(
                    name,
                    _declared(),
                    "an exempted variable must never be folded into the cache key",
                )
        self.assertEqual(
            sorted(read - _EXEMPT_READS.keys()),
            sorted(_declared()),
            "[tool.gate_cache] env in this project's pyproject.toml must list exactly "
            "the variables its code reads by name, or the gate cache replays a verdict "
            "across a change in one of them",
        )
