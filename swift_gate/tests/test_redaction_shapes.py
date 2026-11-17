"""Grouped suite: the common-name shapes an earlier redaction let through.

None of these shapes is an Apple-issued common name. They reach codesign's output through
the identity as configured, which codesign echoes verbatim at the start of every
``findIdentity`` message (as Mac Roman mojibake of its UTF-8 bytes when it is not ASCII),
or through a self-made certificate's common name. So the identity is replaced before any
other pass, and the unlisted pass is widened only toward over-redaction; the pass bounds
and the differential property test against that earlier redaction are in
``test_redaction_bounds``. Every name, type, team ID and path here is an obvious fake.
"""

from __future__ import annotations

import unittest

# Test support, not a suite: the sys.path bootstrap.
import _fixtures  # noqa: F401 - imported for its sys.path inserts, which the next lines need

import swgate_redact
import swgate_signing

TEAM_ID = "ABCDE12345"
OTHER_ID = "FGHIJ67890"
THIRD_ID = "KLMNO13579"
SHA1 = "0123456789ABCDEF0123456789ABCDEF01234567"
KEYCHAIN = "/fake/keychains/test.keychain-db"
# Every name fragment the example inputs carry; none may survive a redaction.
NAMES = ("Test", "Person", "Bob", "Jane", "Ünal", "Jörg")


def mojibake(text: str) -> str:
    """*text* as codesign echoes a non-ASCII identity: its UTF-8 bytes read as Mac Roman."""
    return text.encode("utf-8").decode("mac_roman")


def redact(text: str, identity: str = "-") -> str:
    """*text* redacted for *identity*, the ad-hoc one by default."""
    return swgate_signing.redact(text, identity)


def mask_for(identity: str) -> str | None:
    """The stand-in the redaction masks *identity* with, or None when it masks nothing."""
    return swgate_redact._identity_mask(identity)


def _messages(identity: str, other: str) -> tuple[str, ...]:
    """Each findIdentity message codesign writes for *identity*, *other* a near match."""
    return (
        f'{identity}: ambiguous (matches "{identity}" and "{other}" in {KEYCHAIN})',
        f'{identity}: ambiguous (matches "{identity}" in {KEYCHAIN} and "{other}" '
        f"in {KEYCHAIN})",
        f"{identity}: this identity cannot be used for signing code",
        f"{identity}: no identity found",
    )


class _ShapeCase(unittest.TestCase):
    """An assertion that no fake name, nor its mojibake, survives a redaction."""

    def assert_no_name(self, scrubbed: str, *extra: str) -> None:
        """No name fragment, in either spelling, and no team ID is left in *scrubbed*."""
        for fragment in (*NAMES, *extra):
            self.assertNotIn(fragment, scrubbed)
            self.assertNotIn(mojibake(fragment), scrubbed)
        for team in (TEAM_ID, OTHER_ID, THIRD_ID):
            self.assertNotIn(team, scrubbed)


class IdentityFirstTests(_ShapeCase):
    """The identity is replaced before the passes that would otherwise break it up."""

    def test_an_identity_with_a_team_id_no_longer_leaks_its_name(self) -> None:
        identity = f"Foo:Bob ({TEAM_ID})"
        scrubbed = redact(f"{identity}: no identity found", identity)
        self.assert_no_name(scrubbed)
        self.assertTrue(scrubbed.endswith(": no identity found"), scrubbed)

    def test_the_mojibake_spelling_is_replaced_too(self) -> None:
        identity = f"Ünlisted Type: Jörg Ünal ({TEAM_ID})"
        for spelling in (identity, mojibake(identity)):
            with self.subTest(spelling=spelling):
                scrubbed = redact(f"{spelling}: no identity found", identity)
                self.assert_no_name(scrubbed, "nlisted")

    def test_a_mojibake_identity_without_a_team_id_shows_its_rendering(self) -> None:
        identity = "Fake Type: Jörg Ünal"
        scrubbed = redact(f"{mojibake(identity)}: no identity found", identity)
        self.assertEqual(scrubbed, "Fake…: no identity found")

    def test_a_self_made_identity_echoed_as_configured_is_shown_rendered(self) -> None:
        scrubbed = redact(
            "Fake Type: Test Person: no identity found", "Fake Type: Test Person"
        )
        self.assertEqual(scrubbed, "Fake…: no identity found")

    def test_a_known_type_identity_keeps_its_earlier_rendering(self) -> None:
        identity = f"Apple Development: Test Person ({TEAM_ID})"
        scrubbed = redact(f"{identity}: no identity found", identity)
        self.assertEqual(scrubbed, "Apple Development: …: no identity found")

    def test_the_ad_hoc_identity_leaves_codesign_s_flags_intact(self) -> None:
        text = "--force --sign - --timestamp=none: replacing existing signature"
        self.assertEqual(redact(text, "-"), text)

    def test_an_unknown_type_one_id_identity_is_masked_in_every_message(self) -> None:
        # Only a KNOWN type's one-ID common name is left to the passes: an unknown type
        # holding a quote would otherwise keep the text between its quotes.
        for identity, other in (
            (f'Fake "Jane": Bob ({TEAM_ID})', f'Fake "Jane": Bobby ({OTHER_ID})'),
            (f"Foo:Bob ({TEAM_ID})", f"Foo:Bobby ({OTHER_ID})"),
        ):
            for text in _messages(identity, other):
                with self.subTest(text=text):
                    scrubbed = redact(text, identity)
                    self.assert_no_name(scrubbed)
                    self.assertTrue(scrubbed.endswith(text[-12:]), scrubbed)

    def test_the_mask_is_withheld_only_for_what_the_passes_handle(self) -> None:
        masked = (
            f'Fake "Jane": Bob ({TEAM_ID})',
            f"Foo:Bob ({TEAM_ID})",
            "Fake Type: Bob Jones",
            f"Apple Development: Bob ({TEAM_ID}) Jane ({OTHER_ID})",
            f"Apple Development Bob ({TEAM_ID})",
            SHA1,
        )
        for identity in masked:
            with self.subTest(identity=identity):
                self.assertIsNotNone(mask_for(identity))
        for identity in (
            "Apple Development",
            "Developer ID Application",
            f"Apple Development: Bob Jones ({TEAM_ID})",
            f"Mac Developer: Bob ({TEAM_ID})",
        ):
            with self.subTest(identity=identity):
                self.assertIsNone(mask_for(identity))

    def test_the_rendering_stops_at_a_colon_inside_the_first_word(self) -> None:
        self.assertEqual(swgate_signing.render_identity(f"Foo:Bob ({TEAM_ID})"), "Foo…")
        self.assertEqual(
            swgate_signing.render_identity(f":Bob ({TEAM_ID})"), "<identity>…"
        )


class ShortIdentityTests(_ShapeCase):
    """Every configured identity but the ad-hoc ``-`` is masked.

    One no longer than its rendering shows as the placeholder, and only where codesign
    echoes it: before ``: `` at a line's start or after a blank, or as a whole quoted
    item, so the same letters inside another word or a path are left alone.
    """

    def test_a_short_identity_shows_the_placeholder_in_every_message(self) -> None:
        shown = "<identity>…"
        expected = (
            f'{shown}: ambiguous (matches "…" and "…" in {KEYCHAIN})',
            f'{shown}: ambiguous (matches "…" in {KEYCHAIN} and "…" in {KEYCHAIN})',
            f"{shown}: this identity cannot be used for signing code",
            f"{shown}: no identity found",
        )
        texts = (
            f'Bob: ambiguous (matches "Fake Type: Bob" and "Fake Type: Bobby" '
            f"in {KEYCHAIN})",
            f'Bob: ambiguous (matches "Fake Type: Bob" in {KEYCHAIN} and '
            f'"Fake Type: Bobby" in {KEYCHAIN})',
            "Bob: this identity cannot be used for signing code",
            "Bob: no identity found",
        )
        for text, wanted in zip(texts, expected, strict=True):
            with self.subTest(text=text):
                self.assertEqual(redact(text, "Bob"), wanted)

    def test_a_quoted_item_that_is_the_short_identity_shows_the_placeholder(
        self,
    ) -> None:
        text = f'Bob: ambiguous (matches "Bob" and "Bobby" in {KEYCHAIN})'
        self.assertEqual(
            redact(text, "Bob"),
            f'<identity>…: ambiguous (matches "<identity>…" and "…" in {KEYCHAIN})',
        )

    def test_a_short_identity_in_its_mojibake_spelling(self) -> None:
        scrubbed = redact(f"{mojibake('Jörg')}: no identity found", "Jörg")
        self.assertEqual(scrubbed, "<identity>…: no identity found")

    def test_a_bare_team_id_identity_shows_the_placeholder(self) -> None:
        scrubbed = redact(f"error: {TEAM_ID}: not found", TEAM_ID)
        self.assertEqual(scrubbed, "error: <identity>…: not found")

    def test_the_short_identity_is_left_inside_other_words_and_paths(self) -> None:
        for text in (
            "compiling /fake/Bob/Bobby.swift for Bobcat",
            "xBob: y",
            "/fake/Bob: y",
            "Bobby: no identity found",
            "Bob:no space",
            'say "Bob is here"',
        ):
            with self.subTest(text=text):
                self.assertEqual(redact(text, "Bob"), text)

    def test_the_ad_hoc_identity_is_never_masked(self) -> None:
        for text in ("-: no identity found", 'x (matches "-" and "-")'):
            with self.subTest(text=text):
                self.assertNotIn("<identity>", redact(text, "-"))
        self.assertIsNone(mask_for("-"))
        self.assertIsNotNone(mask_for("Bob"))
        self.assertIsNotNone(mask_for(TEAM_ID))


class FormatStringTests(_ShapeCase):
    """Each findIdentity format string, with fake common names of every shape."""

    def test_ambiguous_with_both_items_in_one_keychain(self) -> None:
        identity = "Fake Type: Test"
        text = (
            f'{identity}: ambiguous (matches "Fake Type: Test Person" and '
            f'"Fake Type: Test Bob ({TEAM_ID})" in {KEYCHAIN})'
        )
        scrubbed = redact(text, identity)
        self.assert_no_name(scrubbed)
        self.assertTrue(scrubbed.endswith(f" in {KEYCHAIN})"), scrubbed)

    def test_ambiguous_with_each_item_in_its_own_keychain(self) -> None:
        identity = "Fake Type: Test"
        text = (
            f'{identity}: ambiguous (matches "Fake Type: Test Person" in {KEYCHAIN} '
            f'and "Fake Type: Test Jane" in {KEYCHAIN})'
        )
        scrubbed = redact(text, identity)
        self.assertEqual(
            scrubbed,
            f'Fake…: ambiguous (matches "…" in {KEYCHAIN} and "…" in {KEYCHAIN})',
        )

    def test_an_item_that_is_the_identity_shows_its_rendering(self) -> None:
        identity = "Fake Type: Test"
        text = (
            f'{identity}: ambiguous (matches "{identity}" and "{identity} Person" '
            f"in {KEYCHAIN})"
        )
        self.assertEqual(
            redact(text, identity),
            f'Fake…: ambiguous (matches "Fake…" and "…" in {KEYCHAIN})',
        )

    def test_a_quote_inside_an_item_does_not_end_it(self) -> None:
        # An item ends at codesign's own delimiters, not at the next quote, so a common
        # name holding a quote is taken whole even with no team ID on the line.
        identity = "Fake Type: Bob"
        keychain = "/fake/keychains/t.keychain-db"
        text = (
            f'{identity}: ambiguous (matches "Fake Type: Bob "Bobby" Smith" and '
            f'"Fake Type: Bob Jones" in {keychain})'
        )
        self.assertEqual(
            redact(text, identity),
            f'Fake…: ambiguous (matches "…" and "…" in {keychain})',
        )

    def test_a_quote_inside_an_item_of_the_per_keychain_format(self) -> None:
        identity = "Fake Type: Bob"
        text = (
            f'{identity}: ambiguous (matches "Fake Type: Bob "Bobby" Smith" in '
            f'{KEYCHAIN} and "Fake Type: Bob "Jo" Jones" in {KEYCHAIN})'
        )
        self.assertEqual(
            redact(text, identity),
            f'Fake…: ambiguous (matches "…" in {KEYCHAIN} and "…" in {KEYCHAIN})',
        )

    def test_an_item_with_no_closing_delimiter_runs_to_the_line_end(self) -> None:
        for text in ('x (matches "Bob "Bobby" Smith', 'x (matches "Bob" Smith tail'):
            with self.subTest(text=text):
                scrubbed = redact(text)
                self.assert_no_name(scrubbed, "Smith")
                self.assertTrue(scrubbed.startswith('x (matches "'), scrubbed)

    def test_cannot_be_used_with_no_name_before_it_is_left_alone(self) -> None:
        text = "  : this identity cannot be used for signing code"
        self.assertEqual(redact(text, SHA1), text)

    def test_ambiguous_known_types_leak_no_name(self) -> None:
        # The identity is a bare known type, which holds no name, so it is left to the
        # passes as the earlier redaction left it; the label pass then reads the line's
        # own leading type as a common name running to the first team ID, which
        # over-redacts.
        text = (
            f'Apple Development: ambiguous (matches "Apple Development: Test ({TEAM_ID})"'
            f' and "Apple Development: Jane ({OTHER_ID})" in {KEYCHAIN})'
        )
        scrubbed = redact(text, "Apple Development")
        self.assert_no_name(scrubbed)
        self.assertTrue(scrubbed.startswith("Apple…: "), scrubbed)
        self.assertTrue(scrubbed.endswith(f" in {KEYCHAIN})"), scrubbed)

    def test_cannot_be_used_redacts_the_unquoted_common_name(self) -> None:
        for name in (
            "Fake-Type: Test Person",
            f"Fake-Type: Test Person ({TEAM_ID})",
            f"Foo:Bob({TEAM_ID})",
            "Test Person",
        ):
            with self.subTest(name=name):
                scrubbed = redact(
                    f"{name}: this identity cannot be used for signing code", SHA1
                )
                self.assertEqual(
                    scrubbed, "…: this identity cannot be used for signing code"
                )

    def test_cannot_be_used_keeps_a_known_label_and_the_identity_rendering(
        self,
    ) -> None:
        suffix = ": this identity cannot be used for signing code"
        known = redact(f"Apple Development: Test Person ({TEAM_ID}){suffix}", SHA1)
        self.assertEqual(known, f"Apple Development: …{suffix}")
        echoed = redact(f"Fake Type: Test Person{suffix}", "Fake Type: Test Person")
        self.assertEqual(echoed, f"Fake…{suffix}")

    def test_no_identity_found(self) -> None:
        for identity in (f"Foo:Bob ({TEAM_ID})", "Fake Type:\tTest Person", SHA1):
            with self.subTest(identity=identity):
                scrubbed = redact(f"{identity}: no identity found", identity)
                self.assert_no_name(scrubbed)
                self.assertNotIn(SHA1, scrubbed)


class ItemDelimiterTests(_ShapeCase):
    """An item runs to the last quote before the next item, so no closer inside it ends it.

    Each name below holds one of codesign's own closers (``" in `` or ``")``), which ended
    the item early and kept the text after it as the keychain path.
    """

    IDENTITY = "Fake Type: Bob"
    K = "/fake/keychains/t.keychain-db"
    SHOWN_ONE = f'Fake…: ambiguous (matches "…" and "…" in {K})'
    SHOWN_EACH = f'Fake…: ambiguous (matches "…" in {K} and "…" in {K})'

    def check(self, items: tuple[str, str], *, per_keychain: bool) -> None:
        """Both *items* in one ambiguity list, in the format *per_keychain* names."""
        first, second = items
        tail = f" in {self.K}" if per_keychain else ""
        text = (
            f'{self.IDENTITY}: ambiguous (matches "{first}"{tail} and "{second}" '
            f"in {self.K})"
        )
        scrubbed = redact(text, self.IDENTITY)
        self.assertEqual(scrubbed, self.SHOWN_EACH if per_keychain else self.SHOWN_ONE)
        self.assert_no_name(scrubbed, "Smith", "Alice")

    def check_both_places(self, name: str) -> None:
        """*name* as the first and as the last item, in each of codesign's formats."""
        other = "Fake Type: Bobby Jones"
        for items in ((name, other), (other, name)):
            for per_keychain in (False, True):
                with self.subTest(items=items, per_keychain=per_keychain):
                    self.check(items, per_keychain=per_keychain)

    def test_a_name_holding_a_quoted_in_in_the_one_keychain_format(self) -> None:
        self.check(
            ('Fake Type: Bob "x" in Smith', "Fake Type: Bobby Jones"),
            per_keychain=False,
        )

    def test_a_name_holding_a_quoted_in_in_the_per_keychain_format(self) -> None:
        self.check(
            ('Fake Type: Bob "x" in Smith', "Fake Type: Bobby Jones"), per_keychain=True
        )

    def test_a_name_holding_a_quoted_in_as_the_last_item(self) -> None:
        self.check_both_places('Fake Type: Bob "x" in Smith')

    def test_a_name_holding_a_quote_and_parenthesis(self) -> None:
        self.check_both_places('Fake Type: Bob (Jane") Smith')

    def test_a_name_running_on_after_a_quoted_in(self) -> None:
        self.check_both_places('Bob "x" in Smith Jones Alice')

    def test_two_names_each_holding_a_quoted_in(self) -> None:
        self.check(('Bob "x" in Smith', 'Jane "y" in Jones'), per_keychain=True)


class UnlistedShapeTests(_ShapeCase):
    """The unusual shapes, each now redacted past its team ID."""

    def test_a_type_with_non_ascii_or_punctuation(self) -> None:
        for kind in (
            "Ünlisted Type",
            "Foo-Type",
            "Foo_Type",
            "Foo.Type!",
            "Foo (Beta)",
        ):
            with self.subTest(kind=kind):
                scrubbed = redact(f"{kind}: Test Person ({TEAM_ID})")
                self.assertEqual(scrubbed, "…: …")

    def test_no_space_after_the_colon_or_a_tab(self) -> None:
        for text in (
            f"Foo:Bob ({TEAM_ID})",
            f"Apple Development:\tTest Person ({TEAM_ID})",
            f"codesign: Fake Type:\tJane ({TEAM_ID})",
        ):
            with self.subTest(text=text):
                self.assert_no_name(redact(text))

    def test_no_space_before_the_team_id(self) -> None:
        for text in (
            f"Apple Development: TestPerson({TEAM_ID})",
            f"Fake Type: Jane({TEAM_ID})",
            f"error: Bob({TEAM_ID}) and Jane ({OTHER_ID})",
        ):
            with self.subTest(text=text):
                self.assert_no_name(redact(text))

    def test_a_bare_quoted_item_in_codesign_s_list(self) -> None:
        for text in (
            f'codesign: ambiguous (matches "Test Person ({TEAM_ID})" and "Jane")',
            f'error: ambiguous (matches "Test Person" in {KEYCHAIN} and "Bob" in k)',
            'x (matches "Jane"',
        ):
            with self.subTest(text=text):
                self.assert_no_name(redact(text))

    def test_a_wrapped_name_is_left_to_the_line_it_lands_on(self) -> None:
        # Shape 5 comes only from a self-made certificate: codesign never wraps on a
        # pipe. The continuation line holds a team ID and no colon, so only the ID goes.
        self.assertEqual(
            redact(f"Fake Type: Test\nPerson ({TEAM_ID})"),
            "Fake Type: Test\nPerson (…)",
        )


if __name__ == "__main__":
    unittest.main()
