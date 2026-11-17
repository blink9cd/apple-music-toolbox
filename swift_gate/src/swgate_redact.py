"""How the ``--sign`` stage shows an identity and codesign's output: never a name in full.

Private to ``swift_gate``; :mod:`swgate_signing` re-exports :func:`render_identity` and
:data:`CERTIFICATE_TYPES` and wraps :func:`redact_text` with the home-path rendering.

Two rules govern every pass here:

* **A change may only over-redact.** No input may come out holding a name an earlier
  release removed; a differential property test against a frozen copy of the earlier
  redaction holds that.
* **Every pass is linear** in the line's length, since codesign's output is not ours.

No Apple-issued common name has the unusual shapes handled here. They reach codesign's
output through the identity as configured, which codesign echoes verbatim at the start of
every ``findIdentity`` message, as Mac Roman mojibake of its UTF-8 bytes when it is not
ASCII, or through a self-made certificate's common name. So the identity is masked before
any other pass, and the passes after it are widened toward over-redaction.

Entry point assumptions
-----------------------
Pure: strings in, strings out. Reads nothing and runs nothing.
"""

from __future__ import annotations

import re
from typing import Final

__all__ = ["CERTIFICATE_TYPES", "redact_text", "render_identity"]

_ELLIPSIS = "…"
_PLACEHOLDER = "<identity>"  # shown for a one-word identity, which has no safe prefix
_AD_HOC = "-"  # codesign's ad-hoc identity: never masked, so its own flags stay intact
# An Apple team ID: ten upper-case letters or digits, parenthesized after a common name.
_TEAM_ID = r"[A-Z0-9]{10}"
_ANY_TEAM_ID = re.compile(rf"\({_TEAM_ID}\)")
# The configured identity's own team ID: the whole identity, or its trailing "(ID)".
_OWN_TEAM_ID = re.compile(rf"^({_TEAM_ID})$|\(({_TEAM_ID})\)\s*$")
# The certificate types whose label a redacted common name keeps, a deliberately closed
# list. Only these: a type is recognized by name, never by shape, because any word
# run before a colon (a "codesign:" diagnostic prefix) is otherwise taken for the type.
CERTIFICATE_TYPES: Final = (
    "Apple Development",
    "Apple Distribution",
    "Developer ID Application",
    "Developer ID Installer",
    "Mac App Distribution",
    "Mac Installer Distribution",
    "Mac Developer",
    "iPhone Developer",
    "iPhone Distribution",
    "3rd Party Mac Developer Application",
    "3rd Party Mac Developer Installer",
)
# Longest first, so no type can match as the prefix of a longer one.
_KNOWN_KIND = "|".join(
    re.escape(kind) for kind in sorted(CERTIFICATE_TYPES, key=len, reverse=True)
)
# A certificate common name, "<Type>: <Name> (<ID>)", as codesign echoes it. The name is
# free text (a parenthesized company, a colon, a quote), so it runs lazily to the nearest
# parenthesized team ID on the line rather than stopping at the first such character.
# Where a match may START is not this pattern's to say: see _begins_common_name.
_KNOWN_COMMON_NAME = re.compile(rf"(?P<kind>{_KNOWN_KIND}): [^\n]+? \({_TEAM_ID}\)")
# A whole identity that is such a common name, which the passes handle unmasked.
_KNOWN_IDENTITY = re.compile(rf"(?:{_KNOWN_KIND}): [^\n]+ \({_TEAM_ID}\)")
# A team ID as it ends a common name, after a space. Two can never overlap.
_SPACED_TEAM_ID = re.compile(rf" \({_TEAM_ID}\)")
# What may sit before a recognized type on its line, for its label to be kept. A list of
# the places a common name is known to start, not of the places it cannot: a type can sit
# inside any free-text name, after any character, and keeping its label there would print
# the name to its left. A refused type keeps its raw team ID, which the unlisted pass
# then takes with everything before it, so the narrowness can only over-redact.
#
# * Line start, or a chain of one-token diagnostic prefixes (``codesign: error: ``).
_PREFIX_CHAIN = re.compile(r"[ \t]*(?:[\w./-]+: )*")
# * A quoted name, closed by a quote: an item of codesign's own ambiguity list,
#   ``(matches "A" and "B"``, or one quoted where the chain above would allow it bare.
_LIST_OPENERS = ('(matches "', '" and "')
_QUOTE = '"'
_QUOTED_AT_START = re.compile(rf"{_PREFIX_CHAIN.pattern}\"")
_BLANKS = " \t"
# An item of codesign's ambiguity list, in either of its two formats,
# ``(matches "A" and "B" in K)`` or ``(matches "A" in K and "B" in K)``, team ID or not,
# opens after one of these and ends at the LAST quote before the next opener, or before
# the line's end when none follows. Never at the first quote or closer after it: a common
# name may hold a quote, ``" in `` or ``")``, and the text after the item is kept as the
# keychain path. Only a keychain path holding a quote is absorbed: over-redaction. What
# that quote leaves before the next opener must be nothing or one of codesign's own tails
# (`` in <keychain>`` or ``)``); anything else is no format of codesign's, and the item
# runs on to the next opener or the line's end.
_ITEM_OPENERS = ('(matches "', ' and "')
_ITEM_TAILS = (" in ", ")")
# What a list item or a refusal's prefix may still hold and be kept: a recognized type's
# label, which the label pass left there, after a diagnostic chain for the prefix.
_KEPT_LABEL = re.compile(rf"(?:{_KNOWN_KIND}): {_ELLIPSIS}")
_KEPT_PREFIX = re.compile(rf"{_PREFIX_CHAIN.pattern}{_KEPT_LABEL.pattern}")
# codesign's "%s: this identity cannot be used for signing code": the common name it
# prints there is not quoted, so it is taken whole, up to the message.
_CANNOT_SIGN = ": this identity cannot be used for signing code"
# The identity's stand-in while the passes run. Its shape is what the proof that masking
# only over-redacts rests on: it starts with a word character, so a word run reaching it
# runs on into it; it has a colon, so it anchors the unlisted pass at its start as any
# colon in the identity would have; a space breaks it as a diagnostic chain, so it can
# never make a label pass newly accept a type after it; and it carries one fake team ID
# per team ID the identity holds, spaced the same way, so it ends a wipe where the
# identity would have. It holds no quote and no recognized type.
_MASK_WORD = "Zxmaskedidentityxz"
_MASK_HEAD = f"{_MASK_WORD} {_MASK_WORD}: "
_MASK_TEAM_ID = "ZZZZZZZZZZ"


def render_identity(identity: str) -> str:
    """The identity as shown anywhere: its first word, or a placeholder, plus an ellipsis.

    The first word stops at a colon inside it, so ``Foo:Bob (ID)`` shows as ``Foo…``.
    """
    words = identity.split()
    first = words[0].split(":", 1)[0] if words else ""
    return f"{first if len(words) > 1 and first else _PLACEHOLDER}{_ELLIPSIS}"


def _begins_common_name(line: str, match: re.Match[str], chain_end: int) -> bool:
    """Whether a recognized type *match* on *line* starts a common name, so may keep it.

    True only where a common name is known to start (:data:`_PREFIX_CHAIN`, or an item
    of codesign's own ambiguity list); anywhere else the type may sit inside a name.
    *chain_end* is where the line's longest prefix chain ends. A chain before the match
    is a prefix of that one, so a match starting further on (all but the first, since a
    team ID's parenthesis ends every chain) is refused without rescanning the line.
    """
    start = match.start()
    if start <= chain_end and _PREFIX_CHAIN.fullmatch(line, 0, start):
        return True
    if not line.startswith(_QUOTE, match.end()):
        return False
    if line.endswith(_LIST_OPENERS, 0, start):
        return True
    return start <= chain_end + 1 and bool(_QUOTED_AT_START.fullmatch(line, 0, start))


def _last(pattern: re.Pattern[str], line: str) -> re.Match[str] | None:
    """The last match of *pattern* on *line*, or None when it has none."""
    found = list(pattern.finditer(line))
    return found[-1] if found else None


def _keep_known_labels(line: str, last: re.Match[str]) -> str:
    """*line* with each recognized common name that starts a name kept to its type.

    *last* is the line's last spaced team ID. A refused match is left as it is, raw team
    ID and all, for :func:`_scrub_unlisted`. Only the text up to *last* is searched, since
    no common name ends past it, so a type repeated after it is not rescanned to the
    line's end each time; the text after it is returned unchanged.
    """
    # The pattern matches the empty string, so its first match is always at the start.
    chain_end = next(_PREFIX_CHAIN.finditer(line)).end()

    def label(match: re.Match[str]) -> str:
        if not _begins_common_name(line, match, chain_end):
            return match[0]
        return f"{match['kind']}: {_ELLIPSIS}"

    return _KNOWN_COMMON_NAME.sub(label, line[: last.end()]) + line[last.end() :]


def _unlisted_anchor(line: str) -> tuple[int, int] | None:
    """Where the unlisted pass's wipe starts on *line*, and where its anchor ends.

    The anchor is the line's first colon, whatever follows it (a space, a tab, a name),
    and the wipe starts after the last quote before it and any blanks: so a type of any
    spelling goes with its name. The earlier anchor, the first ``<word run>: ``, can only
    start at or after this one and end at or after it, so this one only over-redacts.
    None when the line has no colon.
    """
    colon = line.find(":")
    if colon < 0:
        return None
    start = line.rfind(_QUOTE, 0, colon) + 1
    while start < colon and line[start] in _BLANKS:
        start += 1
    return start, colon + 1


def _scrub_unlisted(line: str, *, wipe_to: int | None = None) -> str:
    """*line* with everything from its first colon's type to its last team ID gone.

    The same as substituting a plain greedy pattern (the text after the last quote
    before the first colon, past any blanks, through that colon and at least one more
    character, then any text up to the line's LAST team ID, spaced or not) with
    ``…: …``, in linear time. It fires only while a raw team ID is left after the
    anchor, so a line whose names were all kept to their labels is untouched, and a
    residual ID takes every label before it too. *wipe_to*, when given, is where the
    wipe ends instead of that raw ID's end: the end of the last team ID codesign
    printed, so a label kept after the residual ID cannot shield the text between them.
    """
    last = _last(_ANY_TEAM_ID, line)
    anchor = _unlisted_anchor(line)
    if last is None or anchor is None or last.start() <= anchor[1]:
        return line
    end = last.end() if wipe_to is None else wipe_to
    return f"{line[: anchor[0]]}{_ELLIPSIS}: {_ELLIPSIS}{line[end:]}"


def _scrub_names(line: str) -> str:
    """One line with its recognized common names labeled and every other name redacted.

    The label pass changes only the text up to the line's last spaced team ID, which is
    at or before its last team ID of any spacing, so that ID's end sits the same distance
    from the end of its output as from the end of *line*: the unlisted pass wipes through
    it there, whichever IDs the label pass consumed.
    """
    last = _last(_ANY_TEAM_ID, line)
    if last is None:
        return line
    spaced = _last(_SPACED_TEAM_ID, line)
    kept = line if spaced is None else _keep_known_labels(line, spaced)
    return _scrub_unlisted(kept, wipe_to=len(kept) - (len(line) - last.end()))


def _is_kept(text: str, pattern: re.Pattern[str], mask: str | None) -> bool:
    """Whether *text* may stay: a kept label (*pattern*), or the identity's mask whole."""
    return text == mask or bool(pattern.fullmatch(text))


class _NextFinder:
    """The next place *needle* occurs on a line, at or after a position that only grows.

    Each lookup reuses the last one while it is still ahead of the position, so all the
    lookups on one line together scan it once: the list-item pass stays linear.
    """

    def __init__(self, line: str, needle: str) -> None:
        # Searched from nowhere yet. Past the line's end means "none left": once a search
        # finds nothing, no later one can, so it is never repeated.
        self._line, self._needle, self._found = line, needle, -1

    def at_or_after(self, start: int) -> int:
        """Where *needle* next occurs at or after *start*, or -1 when it does not."""
        if self._found < start <= len(self._line):
            found = self._line.find(self._needle, start)
            self._found = len(self._line) + 1 if found < 0 else found
        return self._found if start <= self._found <= len(self._line) else -1


def _first(finders: tuple[_NextFinder, ...], start: int) -> int:
    """The earliest place any of *finders* next occurs at or after *start*, or -1."""
    found = [at for at in (each.at_or_after(start) for each in finders) if at >= 0]
    return min(found) if found else -1


def _item_end(line: str, start: int, boundary: int) -> int:
    """Where the list item opened at *start* ends, the next opener being at *boundary*.

    At the last quote before *boundary* when only nothing or one of codesign's own tails
    follows it there, and otherwise at *boundary*: the item takes any quote it holds.
    """
    end = line.rfind(_QUOTE, start, boundary)
    if end < 0:
        return boundary
    tail = end + 1
    if tail == boundary or line.startswith(_ITEM_TAILS, tail, boundary):
        return end
    return boundary


def _scrub_list_items(line: str, mask: str | None) -> str:
    """*line* with every item of codesign's ``(matches "…"`` list that is a name as ``…``.

    Runs after the unlisted pass, on its output, so it can only take more: an item with
    no team ID (a self-made certificate's common name) is otherwise left whole. The scan
    resumes at the next opener, the item's boundary, which the item's span never
    reaches, so the backward quote searches cover disjoint spans: the pass is linear.
    """
    openers = tuple(_NextFinder(line, each) for each in _ITEM_OPENERS)
    parts: list[str] = []
    done = at = 0
    while (opened := _first(openers, at)) >= 0:
        start = line.index(_QUOTE, opened) + 1
        boundary = _first(openers, start)
        boundary = len(line) if boundary < 0 else boundary
        end = _item_end(line, start, boundary)
        if not _is_kept(line[start:end], _KEPT_LABEL, mask):
            parts.append(f"{line[done:start]}{_ELLIPSIS}")
            done = end
        at = boundary
    return "".join(parts) + line[done:]


def _scrub_refused_name(line: str, mask: str | None) -> str:
    """*line* with the common name before codesign's cannot-sign message as ``…``."""
    at = line.find(_CANNOT_SIGN)
    if at < 0:
        return line
    lead = len(line[:at]) - len(line[:at].lstrip(_BLANKS))
    name = line[lead:at]
    if not name or _is_kept(name, _KEPT_PREFIX, mask):
        return line
    return f"{line[:lead]}{_ELLIPSIS}{line[at:]}"


def _scrub_line(line: str, mask: str | None) -> str:
    """One line through every pass, in the order the only-over-redact proof needs."""
    return _scrub_refused_name(_scrub_list_items(_scrub_names(line), mask), mask)


def _spellings(identity: str) -> tuple[str, ...]:
    """*identity* as typed and as codesign echoes it: Mac Roman mojibake of its UTF-8."""
    return tuple(
        dict.fromkeys((identity, identity.encode("utf-8").decode("mac_roman")))
    )


def _holds_no_unhandled_name(identity: str) -> bool:
    """Whether the passes alone already remove any name *identity* holds, wherever it is.

    A bare recognized type holds no name. A ``<Type>: <Name> (<ID>)`` common name with one
    team ID is labeled where it starts a name and wiped elsewhere, as the earlier
    redaction did, and masking it would only lose its kept label.
    """
    if identity in CERTIFICATE_TYPES:
        return True
    one_id = len(_ANY_TEAM_ID.findall(identity)) == 1
    return one_id and bool(_KNOWN_IDENTITY.fullmatch(identity))


def _identity_mask(identity: str) -> str | None:
    """The stand-in *identity* is masked with before the passes, or None for no mask.

    Every configured identity is masked but two: the
    ad-hoc ``-``, so codesign's own flags stay intact, and one the passes already handle.
    """
    if identity == _AD_HOC or _holds_no_unhandled_name(identity):
        return None
    ids = [
        f"{_MASK_WORD}{' ' if identity[: found.start()].endswith(' ') else ''}"
        f"({_MASK_TEAM_ID})"
        for found in _ANY_TEAM_ID.finditer(identity)
    ]
    return _MASK_HEAD + ("".join(ids) if ids else _MASK_WORD)


def _echoes(spelling: str) -> re.Pattern[str]:
    """Where codesign echoes a short identity *spelling*, and nowhere else.

    Before ``: `` at a line's start or after a blank, as every ``findIdentity`` message
    opens, or as a whole quoted string, as an item of its ambiguity list. Never inside a
    longer word or a path, which an identity this short could otherwise garble. A short
    identity equal to a diagnostic prefix word (``error`` in ``codesign: error: no
    identity found``) is masked there too, which only over-redacts. Linear: the spelling
    is a literal no longer than the placeholder's rendering.
    """
    word = re.escape(spelling)
    return re.compile(rf'(?:^|(?<=[ \t])){word}(?=: )|(?<="){word}(?=")', re.MULTILINE)


def _replace_spelling(text: str, spelling: str, mask: str, *, everywhere: bool) -> str:
    """*text* with *spelling* replaced by *mask*: everywhere, or only where it is echoed."""
    if everywhere:
        return text.replace(spelling, mask)
    return _echoes(spelling).sub(lambda _echo: mask, text)


def _mask_identity(text: str, identity: str, mask: str | None, shown: str) -> str:
    """*text* with every spelling of *identity* replaced by *mask*, when there is one.

    An identity its rendering *shown* shortens is replaced everywhere, as the earlier
    redaction replaced it. One no longer than that (a one-word identity of a few
    characters) is replaced only where codesign echoes it (:func:`_echoes`), and then
    shows as the placeholder rendering, the only rendering a one-word identity has.
    """
    if mask is None:
        return text
    everywhere = len(shown) < len(identity)
    for spelling in _spellings(identity):
        text = _replace_spelling(text, spelling, mask, everywhere=everywhere)
    return text


def redact_text(text: str, identity: str) -> str:
    """*text* with every common name, team ID and the identity scrubbed.

    First the identity, as typed and in codesign's mojibake spelling, is masked, so no
    later pass can break it up and leave its name behind: every identity but the ad-hoc
    ``-`` and those the passes already handle, everywhere when its rendering shortens it
    and otherwise only where codesign echoes it. Then, line by line: a common
    name whose type is one of :data:`CERTIFICATE_TYPES` keeps only that type
    (``Apple Development: …``) where a common name is known to start: at the line's
    start, after one-token diagnostic prefixes, or as an item of codesign's own
    ``(matches "…" and "…"`` list. On any line still holding a raw team ID, spaced or
    not, everything from the type before its first colon, of any spelling, through the
    last team ID becomes ``…: …``, kept labels included. Every item of codesign's list,
    running to the last quote before the next item rather than to the next quote, that
    is not a kept label becomes ``…``, team ID or not, and so does the common name
    before ``: this identity cannot be used for signing code``. The mask then shows as
    the identity's rendering (the placeholder, for a one-word identity), any
    parenthesized team ID left becomes ``(…)``, and an identity its rendering shortens,
    and its own team ID, are scrubbed wherever they survive. The ad-hoc ``-`` is never
    replaced, so codesign's own flags stay intact.
    """
    shown = render_identity(identity)
    mask = _identity_mask(identity)
    masked = _mask_identity(text, identity, mask, shown)
    scrubbed = "\n".join(_scrub_line(line, mask) for line in masked.split("\n"))
    if mask is not None:
        scrubbed = scrubbed.replace(mask, shown)
    scrubbed = _ANY_TEAM_ID.sub(f"({_ELLIPSIS})", scrubbed)
    if len(shown) < len(identity):
        for spelling in _spellings(identity):
            scrubbed = scrubbed.replace(spelling, shown)
    own = _OWN_TEAM_ID.search(identity)
    if own is not None:
        scrubbed = scrubbed.replace(own.group(1) or own.group(2), _ELLIPSIS)
    return scrubbed
