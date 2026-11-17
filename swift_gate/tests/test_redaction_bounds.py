"""Grouped suite: the widened redaction's bounds, its runtime and its only-over-redact rule.

Split from ``test_redaction_shapes`` at the file-length bar: each pass's linear-time
budget, the widened unlisted pass pinned to the greedy pattern it stands for, and the
differential property test that holds the invariant the earlier release set: no input is
redacted less than that release redacted it. Every name, type, team ID and path here is
an obvious fake.
"""

from __future__ import annotations

import re
import time
import unittest

# Test support, not suites: the sys.path bootstrap, and the earlier redaction as it landed.
import _fixtures  # noqa: F401 - imported for its sys.path inserts, which the next lines need
import _redact_baseline
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

import swgate_redact
import swgate_signing
from test_redaction_shapes import (
    KEYCHAIN,
    OTHER_ID,
    SHA1,
    TEAM_ID,
    THIRD_ID,
    mojibake,
    redact,
)

# The deterministic profile fuzz_gate's convention registers (fuzz_gate.md, "Determinism"),
# the same one test_coverage loads: derandomized so the run is reproducible, with no
# per-example deadline and no too_slow check, so machine load cannot fail a property that
# holds. Loaded at import, before the @given below is decorated, because a property
# snapshots its settings then.
settings.register_profile(
    "deterministic",
    derandomize=True,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow],
)
settings.load_profile("deterministic")

# Generous for a loaded machine, yet a small fraction of a quadratic pass's runtime on
# these lines, as test_redaction's budget is.
LINEAR_BUDGET_SECONDS = 2.0


class LinearTimeTests(unittest.TestCase):
    """Every new pass stays linear on a long adversarial line."""

    def test_long_adversarial_lines_redact_in_linear_time(self) -> None:
        for text in (
            ":" * 200_000 + f" ({TEAM_ID})",
            f'(matches "{"x" * 200_000}',
            ' and "' * 50_000,
            '(matches "' * 30_000,
            "a:" * 100_000 + ": this identity cannot be used for signing code",
            f"({TEAM_ID})" * 20_000 + ":",
            "Fake Type: Test " * 20_000,
            '(matches "' + '"x' * 100_000,
            '(matches "x" in ' * 30_000,
            ' and "' + '" in k' * 50_000,
            '(matches "' + '")' * 100_000,
            '(matches "' + '"x' * 200_000,
            (' and "' + '"' * 3) * 50_000,
            ' and "' + '" Smith' * 50_000,
        ):
            with self.subTest(length=len(text), head=text[:12]):
                began = time.perf_counter()
                redact(text, "Fake Type: Test")
                self.assertLess(time.perf_counter() - began, LINEAR_BUDGET_SECONDS)

    def test_a_short_identity_s_echo_scan_is_linear(self) -> None:
        for text in (
            "Bob: " * 60_000,
            '"Bob"' * 60_000,
            " Bob" * 75_000,
            "Bo" * 150_000,
        ):
            with self.subTest(length=len(text), head=text[:12]):
                began = time.perf_counter()
                redact(text, "Bob")
                self.assertLess(time.perf_counter() - began, LINEAR_BUDGET_SECONDS)


class WideUnlistedReferenceTests(unittest.TestCase):
    """The widened unlisted pass, pinned to the plain greedy pattern it stands for."""

    def test_the_wide_pass_matches_its_greedy_reference(self) -> None:
        # Linear as written; this pins it, on lines short enough for the reference's
        # backtracking to be harmless, to: after the last quote before the line's first
        # colon and any blanks, through that colon, then at least one character, through
        # the line's last team ID, spaced or not.
        reference = re.compile(
            r'^(?P<keep>(?:[^:\n]*")?[ \t]*)[^":\n]*:.+\([A-Z0-9]{10}\)'
        )
        for line in (
            "plain",
            f"Foo: ({TEAM_ID})",
            f"Foo:x ({TEAM_ID})",
            f"Foo:({TEAM_ID})",
            f"  a b: c ({TEAM_ID}) d ({OTHER_ID}) tail",
            f'"q: x" Bar: y ({TEAM_ID})',
            f'say "\tFoo-Type: y({TEAM_ID})" after',
            f"x({TEAM_ID}) Foo: y ({OTHER_ID})({TEAM_ID})",
            f"Foo: x ({TEAM_ID}) Bar: ",
            "Foo: bar: baz",
            f"({TEAM_ID}) no colon",
        ):
            with self.subTest(line=line):
                expected = reference.sub(lambda m: f"{m['keep']}…: …", line)
                self.assertEqual(swgate_redact._scrub_unlisted(line), expected)


# The generated lines: name tokens, which the property tracks, among the structure
# codesign's messages and the unusual shapes are built of. No structural token contains a
# "Q", so a name token can only appear where a name was put.
_NAME_TOKENS = ("Qaa", "Qab", "Qac", "Qad", "Qñe", "Qüf")
_STRUCTURE = (
    ": ", ":", ":\t", " ", "\t", "\n", '"', "(", ")", "…",
    '(matches "', '" and "', f'" in {KEYCHAIN} and "', f'" in {KEYCHAIN})',
    "codesign: ", "error: ", ": ambiguous ", ": no identity found",
    ": this identity cannot be used for signing code",
    "Apple Development", "Mac Developer", "Developer ID Application",
    "Fake-Type", "Ünlisted Type", "Foo_Type", "Fake Type",
    f" ({TEAM_ID})", f"({OTHER_ID})", f" ({THIRD_ID})", TEAM_ID,
)  # fmt: skip
_IDENTITIES = (
    "-",
    TEAM_ID,
    SHA1,
    "Apple Development",
    "Fake Type: Qia",
    "Fake Type Qia Qib",
    f"Apple Development: Qia Qib ({TEAM_ID})",
    f"Foo:Qia ({TEAM_ID})",
    f"Ünlisted Type: Qñc ({THIRD_ID})",
    f"Fake-Type: Qia({OTHER_ID})",
    f"Developer ID Application: Qia Qib ({TEAM_ID})",
    f"Fake Type: Qia ({TEAM_ID}) Qib ({OTHER_ID})",
    # Short one-word identities, masked only where codesign echoes them.
    "Qia",
    "Qñc",
    "Qia:",
    # The masking exemption's boundary: a known type's one-ID common name and a bare
    # known type are left to the passes; an unknown type with a quote is masked.
    f"Mac Developer: Qia ({TEAM_ID})",
    "Developer ID Application",
    f'Fake "Qib": Qia ({TEAM_ID})',
    f'Apple Development: Qia "Qib" ({OTHER_ID})',
)
_IDENTITY_NAMES = ("Qia", "Qib", "Qñc")
_TEAM_IDS = (TEAM_ID, OTHER_ID, THIRD_ID)
_TRACKED = (*_NAME_TOKENS, *_IDENTITY_NAMES, *_TEAM_IDS)
# A token that stands for the identity, in either spelling, wherever it is drawn.
_AS_TYPED, _AS_ECHOED = "\x00typed\x00", "\x00echoed\x00"
_TOKENS = st.sampled_from((*_STRUCTURE, *_NAME_TOKENS, _AS_TYPED, _AS_ECHOED))


@st.composite
def _case(draw: st.DrawFn) -> tuple[str, str]:
    """A generated line or two and the identity it was redacted for."""
    identity = draw(st.sampled_from(_IDENTITIES))
    tokens = draw(st.lists(_TOKENS, max_size=24))
    text = "".join(tokens).replace(_AS_TYPED, identity)
    return text.replace(_AS_ECHOED, mojibake(identity)), identity


def _kept(text: str) -> set[str]:
    """Which tracked fragments *text* still holds, in either spelling."""
    return {each for each in _TRACKED if each in text or mojibake(each) in text}


class DifferentialPropertyTests(unittest.TestCase):
    """The live redaction never keeps a fragment the earlier redaction removed."""

    # The loaded profile makes it deterministic; the cap bounds it, because this runs in
    # the inner-loop gate.
    @settings(max_examples=1500)
    @given(_case())
    def test_the_live_redaction_never_keeps_what_the_baseline_removed(
        self, case: tuple[str, str]
    ) -> None:
        text, identity = case
        before = _kept(_redact_baseline.redact(text, identity))
        after = _kept(swgate_signing.redact(text, identity))
        self.assertLessEqual(after - before, set(), (text, identity))

    def test_the_tracked_tokens_cannot_be_made_by_the_structure(self) -> None:
        # The property reads "absent" as "removed", which holds only if no structural
        # token, rendering or replacement can spell a tracked fragment by itself.
        joined = "".join(_STRUCTURE) + "…<identity>()"
        self.assertIsNone(re.search("Q", joined))


if __name__ == "__main__":
    unittest.main()
