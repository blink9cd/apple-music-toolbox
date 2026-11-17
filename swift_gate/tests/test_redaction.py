"""Grouped suite: where a recognized certificate type may anchor, and the home's reach.

Regression tests from the redaction's review: a listed type inside an unlisted common
name must not anchor the label-keeping pass (it leaked the name fragment to its left), a
raw team ID left after that pass takes every name fragment and label before it (a later
finding: a pass confined to the gaps between kept labels leaked the names' tails), both
passes stay linear on a long line, the injected home must reach every swift_gate message,
a symlinked home is still shown as ``~``, and an unrunnable ``codesign`` is reported
without its exception text. Every name, team ID and home is an obvious fake.
"""

from __future__ import annotations

import dataclasses
import io
import re
import time
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

import _redact_baseline
from _fixtures import write

# The base cases are reached through the module, so discovery does not collect them here a
# second time; the fakes' names are shared, not restated.
import test_signing
from test_signing import IDENTITY, TEAM_ID, FakeTool

import swgate_signing
import swift_gate
from swgate_model import Configured, NotConfigured, SigningConfigError

OTHER_ID = "FGHIJ67890"
# Generous for a loaded machine (a linear pass on these ~300 KB lines takes milliseconds),
# yet a small fraction of a quadratic pass's tens of seconds, so it cannot flake either way.
LINEAR_BUDGET_SECONDS = 2.0
# Every name fragment the leaking inputs below carry; none may survive a redaction.
FRAGMENTS = ("Foo", "Bar", "Acme", "Bob", "Jane", "Pro", "Custom")


def redact(text: str) -> str:
    """*text* redacted for the ad-hoc identity, which redacts nothing of its own."""
    return swgate_signing.redact(text, "-")


class AnchorLeakTests(unittest.TestCase):
    """A listed type inside an unlisted common name is not where a common name starts."""

    def test_a_type_after_a_word_and_a_space_does_not_anchor(self) -> None:
        for text in (
            f"Foo: Bar Mac Developer: Jane ({TEAM_ID})",
            f"Acme Corp: Bob Apple Distribution: Jane ({TEAM_ID})",
            f"Pro Mac Developer: Jane ({TEAM_ID})",
        ):
            with self.subTest(text=text):
                self.assertEqual(redact(text), "…: …")

    def test_a_type_after_punctuation_inside_a_name_does_not_anchor(self) -> None:
        for text, expected in (
            (f"Custom: Bob-Mac Developer: Jane ({TEAM_ID})", "…: …"),
            (f"Custom: Bob, Mac Developer: Jane ({TEAM_ID})", "…: …"),
            (f"Custom: Bob/Apple Development: Jane ({TEAM_ID})", "…: …"),
            (f"Custom: (Mac Developer: Jane ({TEAM_ID}))", "…: …)"),
            (f'Custom: Bob "Mac Developer: Jane ({TEAM_ID})"', '…: …"'),
            (f'Custom: Bob "Mac Developer: Jane ({TEAM_ID})', "…: …"),
            (f"Custom Type: Bob: Mac Developer: Jane ({TEAM_ID})", "…: …"),
        ):
            with self.subTest(text=text):
                scrubbed = redact(text)
                self.assertEqual(scrubbed, expected)
                for fragment in FRAGMENTS:
                    self.assertNotIn(fragment, scrubbed)

    def test_a_diagnostic_prefix_still_keeps_the_label(self) -> None:
        for text, expected in (
            (
                f"codesign: Apple Development: Example Person ({TEAM_ID})",
                "codesign: Apple Development: …",
            ),
            (
                f"error: Mac Developer: Example Person ({TEAM_ID})",
                "error: Mac Developer: …",
            ),
            (
                f"  codesign: error: Mac Developer: Example Person ({TEAM_ID})",
                "  codesign: error: Mac Developer: …",
            ),
        ):
            with self.subTest(text=text):
                self.assertEqual(redact(text), expected)

    def test_each_certificate_codesign_echoes_keeps_its_label(self) -> None:
        text = (
            f'codesign: ambiguous (matches "Apple Development: X ({TEAM_ID})" and '
            f'"Apple Distribution: Y ({OTHER_ID})" in <keychain>)'
        )
        self.assertEqual(
            redact(text),
            'codesign: ambiguous (matches "Apple Development: …" and '
            '"Apple Distribution: …" in <keychain>)',
        )

    def test_a_quoted_type_outside_codesign_s_list_does_not_anchor(self) -> None:
        # Only codesign's own "(matches "A" and "B"" list opens a quoted common name: a
        # quote anywhere else may sit inside a name, so the label is not kept there.
        scrubbed = redact(f'note "Mac Developer: Jane ({TEAM_ID})"')
        self.assertNotIn("Jane", scrubbed)
        self.assertNotIn("Mac Developer", scrubbed)


class SecondPassTests(unittest.TestCase):
    """The unlisted-type pass, over the whole line once the kept labels are in."""

    def test_an_unlisted_name_after_a_kept_label_takes_the_label_too(self) -> None:
        # The unlisted pass runs over the whole line, so a raw team ID left anywhere on it
        # wipes everything from the first "<word run>: " through it, kept labels included.
        # The over-redaction is the price of never leaking a name.
        text = (
            'codesign: ambiguous (matches "Apple Development: J (AAAAAAAAAA)" and '
            '"Foo Type: Bob (BBBBBBBBBB)")'
        )
        self.assertEqual(redact(text), '…: …")')

    def test_an_unlisted_name_before_a_kept_label_is_redacted_whole(self) -> None:
        text = f"Foo Type: Bob ({OTHER_ID})\nApple Development: J ({TEAM_ID})"
        self.assertEqual(redact(text), "…: …\nApple Development: …")

    def test_a_type_after_free_text_mid_line_is_over_redacted(self) -> None:
        # "then " is not a place a common name is known to start, so the label goes too:
        # the narrowness over-redacts, as the ruling allows, rather than guess.
        text = f"Foo Type: Bob ({OTHER_ID}) then Apple Development: J ({TEAM_ID})"
        self.assertEqual(redact(text), "…: …")

    def test_a_quoted_name_where_a_bare_one_may_start_keeps_its_label(self) -> None:
        text = f'codesign: "Apple Development: J ({TEAM_ID})": ambiguous'
        self.assertEqual(redact(text), 'codesign: "Apple Development: …": ambiguous')

    def test_a_name_holding_an_ellipsis_is_still_redacted_whole(self) -> None:
        # The kept label's "…" must not be told apart by its character: a real name may
        # carry one, and it would then stop the scrub short and leave the name.
        scrubbed = redact(f"Foo Type: Bob… Smith ({TEAM_ID})")
        self.assertEqual(scrubbed, "…: …")


class NameTailTests(unittest.TestCase):
    """A raw team ID left after the label pass takes every name fragment before it."""

    def test_no_name_fragment_survives_a_residual_team_id(self) -> None:
        for text in (
            "Apple Development: J (AAAAAAAAAA) Carl (BBBBBBBBBB)",
            "Apple Development: J (AAAAAAAAAA)Bob Carl (BBBBBBBBBB)",
            'codesign: "Apple Development: J (AAAAAAAAAA)" Bob (BBBBBBBBBB)',
            'Foo: "Apple Development: J (AAAAAAAAAA)" Bob (BBBBBBBBBB)',
            'Foo Type: Bob (matches "Apple Development: J (AAAAAAAAAA)" Carl (BBBBBBBBBB)',
            'Foo Type: Bob " and "Apple Development: J (AAAAAAAAAA)" Carl (BBBBBBBBBB)',
            "Foo Type: Bob Apple Development: J (AAAAAAAAAA) Carl (BBBBBBBBBB)",
        ):
            with self.subTest(text=text):
                scrubbed = redact(text)
                self.assertEqual(scrubbed, "…: …")
                for fragment in ("J", "Bob", "Carl", "Foo", "AAAAAAAAAA", "BBBBBBBBBB"):
                    self.assertNotIn(fragment, scrubbed)

    def test_a_kept_label_after_a_residual_id_shields_nothing(self) -> None:
        # The wipe must run to the line's last team ID as codesign printed it, not to the
        # last one the label pass left raw: a kept label after a residual ID otherwise
        # shields the name text between them.
        for text in (
            'Foo: Bob (AAAAAAAAAA) Carl" and "Apple Development: J (BBBBBBBBBB)"',
            'codesign: Foo: Bob (AAAAAAAAAA) Carl (matches "Apple Development: J '
            '(BBBBBBBBBB)"',
        ):
            with self.subTest(text=text):
                scrubbed = redact(text)
                self.assertEqual(scrubbed, '…: …"')
                for fragment in ("J", "Bob", "Carl", "Foo", "AAAAAAAAAA", "BBBBBBBBBB"):
                    self.assertNotIn(fragment, scrubbed)

    def test_a_line_whose_ids_were_all_consumed_keeps_its_labels(self) -> None:
        text = f"codesign: Apple Development: J ({TEAM_ID})\nnext: plain"
        self.assertEqual(redact(text), "codesign: Apple Development: …\nnext: plain")

    def test_the_baseline_unlisted_pass_matches_its_greedy_reference(self) -> None:
        # The pass was written for linear time; this pins it to the plain greedy pattern
        # it stands for, on lines short enough for that pattern's backtracking to be
        # harmless. A later change widened the live pass (test_redaction_shapes pins that
        # one), so this now holds the frozen copy the differential test compares against.
        reference = re.compile(r"[0-9A-Za-z][0-9A-Za-z ]*: [^\n]+ \([A-Z0-9]{10}\)")
        for line in (
            "plain",
            f"Foo: ({TEAM_ID})",
            f"Foo: x ({TEAM_ID})",
            f"  a b: c ({TEAM_ID}) d ({OTHER_ID}) tail",
            f"   : x ({TEAM_ID}) Foo: y ({OTHER_ID})",
            f'"q: x" Bar: y ({TEAM_ID})',
            f"Foo: x ({TEAM_ID}) Bar: ",
            f"x({TEAM_ID}) Foo: y ({OTHER_ID})({TEAM_ID})",
            f"Foo:x ({TEAM_ID}) bar: y ({OTHER_ID})",
            "Foo: bar: baz",
        ):
            with self.subTest(line=line):
                self.assertEqual(
                    _redact_baseline._scrub_unlisted(line), reference.sub("…: …", line)
                )

    def test_an_adversarial_long_line_redacts_in_linear_time(self) -> None:
        # A listed type repeated thousands of times, with and without a team ID to end the
        # line: a pattern that rescans the line per type is quadratic here.
        run = "Bob Mac Developer: " * 16000
        for text in (f"{run}X ({TEAM_ID})", run, f"{run}X ({TEAM_ID}) {run}"):
            with self.subTest(length=len(text)):
                began = time.perf_counter()
                scrubbed = redact(text)
                self.assertLess(time.perf_counter() - began, LINEAR_BUDGET_SECONDS)
                self.assertNotIn(TEAM_ID, scrubbed)

    def test_many_names_on_one_long_line_redact_in_linear_time(self) -> None:
        text = f"a: {'a: ' * 40000}" + f"Mac Developer: X ({TEAM_ID}) " * 8000
        began = time.perf_counter()
        scrubbed = redact(text)
        self.assertLess(time.perf_counter() - began, LINEAR_BUDGET_SECONDS)
        self.assertNotIn("X", scrubbed)


class _LinkedHomeCase(unittest.TestCase):
    """A real home dir and a symlink standing in for it, as ``Path.home()`` may report."""

    def setUp(self) -> None:
        tmp = TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        base = Path(tmp.name).resolve()
        self.real = base / "real-home"
        self.real.mkdir()
        self.link = base / "home-link"
        self.link.symlink_to(self.real, target_is_directory=True)


class LinkedHomeTests(_LinkedHomeCase):
    """A resolved path under a symlinked home is shown from ``~``, not absolute."""

    def test_render_path_matches_the_resolved_home(self) -> None:
        target = (self.link / "project").resolve()
        self.assertEqual(swgate_signing.render_path(target, self.link), "~/project")
        self.assertEqual(swgate_signing.render_path(self.real, self.link), "~")

    def test_redact_tildes_the_resolved_home_in_text(self) -> None:
        text = f"in {self.real}/Library/k and {self.link}/Library/k"
        scrubbed = swgate_signing.redact(text, "-", home=self.link)
        self.assertEqual(scrubbed, "in ~/Library/k and ~/Library/k")


class InjectedHomeTests(test_signing._SignCase):
    """The home a caller injects reaches the sign stage's and the setting's messages."""

    def setUp(self) -> None:
        super().setUp()
        self.home = self.root.parent.parent / "injected-home"
        # Path.home() is pointed elsewhere, so a message reading it would fail the pins.
        patcher = mock.patch.object(Path, "home", return_value=Path("/elsewhere-home"))
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_not_configured_uses_the_injected_home(self) -> None:
        path = self.home / ".config" / "swift_gate" / "signing.toml"
        opts = dataclasses.replace(self.opts, home=self.home)
        self.opts = opts
        result = self.gate(self.runner(), NotConfigured(path))
        self.assertIn("(~/.config/swift_gate/signing.toml absent)", result.detail)

    def test_codesign_output_uses_the_injected_home(self) -> None:
        keychain = self.home / "Library" / "login.keychain-db"
        self.codesign = FakeTool([("--force", 1, "", f"error: in {keychain}")])
        self.opts = dataclasses.replace(self.opts, home=self.home)
        result = self.gate(self.runner(), Configured(IDENTITY))
        self.assertIn("error: in ~/Library/login.keychain-db", result.detail)
        self.assertNotIn(str(self.home), result.detail)

    def test_the_setting_messages_use_the_injected_home(self) -> None:
        checkout = self.home / "workspace"
        with self.assertRaises(SigningConfigError) as ctx:
            swgate_signing.read_signing_identity(
                checkout / "signing.toml", checkout_roots=(checkout,), home=self.home
            )
        self.assertIn(
            "~/workspace/signing.toml is inside ~/workspace", str(ctx.exception)
        )
        path = write(self.home / "signing.toml", "not toml [")
        with self.assertRaises(SigningConfigError) as ctx:
            swgate_signing.read_signing_identity(
                path, checkout_roots=(), home=self.home
            )
        self.assertIn("the signing setting ~/signing.toml", str(ctx.exception))

    def test_the_git_messages_use_the_injected_home(self) -> None:
        broken = FakeTool([("--show-toplevel", 1, "", f"fatal: at {self.home}/x")])
        with self.assertRaises(SigningConfigError) as ctx:
            swgate_signing.checkout_roots(
                self.home / "workspace", broken, timeout=1.0, home=self.home
            )
        self.assertIn("in ~/workspace", str(ctx.exception))
        self.assertIn("fatal: at ~/x", str(ctx.exception))


class InjectedHomeCliTests(test_signing._CliCase):
    """main()'s *home* reaches the setting's refusal and the sign stage's message."""

    def setUp(self) -> None:
        super().setUp()
        self.home = self.config.parent
        patcher = mock.patch.object(Path, "home", return_value=Path("/elsewhere-home"))
        patcher.start()
        self.addCleanup(patcher.stop)

    def main_at_home(self, setting: Path) -> tuple[int, str, str]:
        """Run main with --sign, *setting* and the injected home, every seam faked."""
        out, err = io.StringIO(), io.StringIO()
        argv = ["--path", str(self.top), "--scratch-path", str(self.opts.scratch_base)]
        argv += ["--min-percent", "80", "--sign", "--signing-config", str(setting)]
        with (
            mock.patch.object(swift_gate, "_run_swift", self.runner()),
            mock.patch.object(swift_gate, "_run_codesign", self.codesign),
            mock.patch.object(swift_gate, "_run_git", self.git),
            mock.patch.object(swift_gate, "locate_swift", return_value="swift"),
            redirect_stdout(out),
            redirect_stderr(err),
        ):
            code = swift_gate.main(argv, home=self.home)
        return code, out.getvalue(), err.getvalue()

    def test_an_absent_setting_is_shown_from_the_injected_home(self) -> None:
        code, out, _ = self.main_at_home(self.config)
        self.assertEqual(code, 0, out)
        self.assertIn("signing: not configured (~/signing.toml absent)", out)

    def test_a_refused_setting_is_shown_from_the_injected_home(self) -> None:
        inside = self.home / "workspace" / "signing.toml"
        with mock.patch.object(
            swift_gate, "checkout_roots", return_value=(inside.parent,)
        ):
            code, _, err = self.main_at_home(inside)
        self.assertEqual(code, 2)
        self.assertIn("~/workspace/signing.toml is inside ~/workspace", err)


class CodesignLaunchTests(test_signing._SignCase):
    """An unrunnable codesign is named by class and reason, never its exception text."""

    def test_the_exception_text_and_its_path_are_not_printed(self) -> None:
        where = self.root.parent.parent / "bin" / "codesign"
        self.codesign.raises = FileNotFoundError(
            2, "No such file or directory", str(where)
        )
        result = self.gate(self.runner(), Configured(IDENTITY))
        self.assertEqual(result.returncode, 2)
        self.assertIn(
            "could not run codesign: FileNotFoundError: No such file or directory",
            result.detail,
        )
        self.assertNotIn(str(where), result.detail)
        self.assertNotIn(TEAM_ID, result.detail)
