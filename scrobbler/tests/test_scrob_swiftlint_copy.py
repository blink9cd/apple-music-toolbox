"""The export's SwiftLint rule set holds exactly the rules this project is linted with.

Where this project is developed, its Swift package is linted with a shared rule set kept
outside the project, which the project's ``[tool.swift_lint] swiftlint_config`` names.
That rule set does not ship, so the export carries a copy of it at the exported
repository's root, where SwiftLint finds it unaided; the copy's source sits in the
project's export policy folder, which does not ship either. The copy's comments are its
own (they describe where it sits), but its rules must be the reference's, or a stranger's
lint judges the package by rules this checkout never applied. This test compares the
two with comments and blank lines dropped, line for line, indentation kept, since in
YAML the indentation is the structure.

In an exported checkout the public config names no rule set, the root copy is the rule
set, and the test skips, saying why; where the config names one, both files must exist.
"""

from __future__ import annotations

import tomllib
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
#: The configuration this project is gated with, which names the reference rule set.
_CONFIG = _PROJECT_ROOT / "pyproject.toml"
#: The copy the export ships at its root as ``.swiftlint.yml``.
_COPY = _PROJECT_ROOT / "export" / "vendored" / ".swiftlint.yml"
_COMMENT = "#"


def rule_lines(text: str) -> list[str]:
    """*text*'s YAML content lines: full-line comments and blank lines dropped.

    Only whole-line comments are dropped: the rule sets compared here carry no trailing
    comment, and a ``#`` after content could sit inside a quoted value.
    """
    return [
        line.rstrip()
        for line in text.splitlines()
        if line.strip() and not line.lstrip().startswith(_COMMENT)
    ]


def reference_rule_set(config: Path) -> Path | None:
    """The rule set *config*'s ``[tool.swift_lint]`` names, resolved; None when unnamed."""
    with config.open("rb") as handle:
        table = tomllib.load(handle).get("tool", {}).get("swift_lint", {})
    named = table.get("swiftlint_config")
    return (config.parent / named).resolve() if isinstance(named, str) else None


_REFERENCE = reference_rule_set(_CONFIG)
_NO_REFERENCE = (
    "this checkout's config names no SwiftLint rule set to compare against (an exported "
    "checkout, whose root .swiftlint.yml is the rule set)"
)


class RuleLinesTest(unittest.TestCase):
    def test_comments_and_blank_lines_are_dropped_and_indentation_kept(self) -> None:
        text = "# head\n\nrule:\n  # why\n  key: true   \n"
        self.assertEqual(rule_lines(text), ["rule:", "  key: true"])


class ReferenceRuleSetTest(unittest.TestCase):
    def test_a_named_rule_set_resolves_beside_the_config(self) -> None:
        with TemporaryDirectory() as tmp:
            config = Path(tmp).resolve() / "pyproject.toml"
            config.write_text(
                '[tool.swift_lint]\nswiftlint_config = "a/rules.yml"\n',
                encoding="utf-8",
                newline="\n",
            )
            self.assertEqual(
                reference_rule_set(config), Path(tmp).resolve() / "a" / "rules.yml"
            )

    def test_a_config_naming_none_gives_none(self) -> None:
        with TemporaryDirectory() as tmp:
            config = Path(tmp) / "pyproject.toml"
            config.write_text('[project]\nname = "x"\n', encoding="utf-8", newline="\n")
            self.assertIsNone(reference_rule_set(config))


@unittest.skipIf(_REFERENCE is None, _NO_REFERENCE)
class SwiftLintCopyTest(unittest.TestCase):
    def test_the_exported_rule_set_matches_the_reference(self) -> None:
        assert _REFERENCE is not None  # the class is skipped otherwise
        expected = rule_lines(_REFERENCE.read_text(encoding="utf-8"))
        # Non-vacuous: an emptied reference would match an emptied copy.
        self.assertTrue(expected, f"{_REFERENCE.name} holds no rule")
        self.assertEqual(
            rule_lines(_COPY.read_text(encoding="utf-8")),
            expected,
            f"{_COPY.name} under export/vendored/ must hold the rules of "
            f"{_REFERENCE.name}, comments aside",
        )


if __name__ == "__main__":
    unittest.main()
