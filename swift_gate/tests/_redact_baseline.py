"""A frozen copy of an earlier signing redaction: the baseline the live one may only exceed.

Test support, never a suite: the differential property test runs this and the live
``swgate_signing.redact`` over the same generated lines and asserts that the live one
never keeps a name this one removed. Copied verbatim from ``src/swgate_signing.py`` as it
landed in that earlier release (the home-path rendering left out, since no test here
passes a home), so it must NOT be edited to track the live module: its whole value is
that it stays the old behavior.
"""

from __future__ import annotations

import re
from typing import Final

_ELLIPSIS = "…"
_PLACEHOLDER = "<identity>"  # shown for a one-word identity, which has no safe prefix
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
_LIST_CLOSER = '"'
_QUOTED_AT_START = re.compile(rf"{_PREFIX_CHAIN.pattern}\"")
# The first "<word run>: " on a line, as the plain pattern
# "[0-9A-Za-z][0-9A-Za-z ]*: " finds it, but tried once per run of word characters and
# spaces rather than once per character, so a long run costs one scan, not one per start.
_UNLISTED_TYPE = re.compile(
    r"(?<![0-9A-Za-z ]) *+(?P<start>[0-9A-Za-z])[0-9A-Za-z ]*+: "
)


def render_identity(identity: str) -> str:
    """The identity as shown anywhere: its first word, or a placeholder, plus an ellipsis."""
    words = identity.split()
    return f"{words[0] if len(words) > 1 else _PLACEHOLDER}{_ELLIPSIS}"


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
    if not line.startswith(_LIST_CLOSER, match.end()):
        return False
    if line.endswith(_LIST_OPENERS, 0, start):
        return True
    return start <= chain_end + 1 and bool(_QUOTED_AT_START.fullmatch(line, 0, start))


def _last_team_id(line: str) -> re.Match[str] | None:
    """The last spaced team ID on *line*, or None when it holds none."""
    found = list(_SPACED_TEAM_ID.finditer(line))
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


def _scrub_unlisted(line: str, *, wipe_to: int | None = None) -> str:
    """*line* with everything from its first ``<word run>: `` to its last team ID gone.

    The same as substituting a plain greedy pattern (a word run, a colon and a space,
    then any text up to the line's LAST spaced team ID) with ``…: …``, in linear time.
    It fires only while a raw team ID is left after the anchor, so a line whose names
    were all kept to their labels is untouched, and a residual ID takes every label
    before it too: the unknown type goes with its name, and so does anything the name
    could have been. *wipe_to*, when given, is where the wipe ends instead of that raw
    ID's end: the end of the last team ID codesign printed, so a label kept after the
    residual ID cannot shield the text between them.
    """
    last = _last_team_id(line)
    anchor = _UNLISTED_TYPE.search(line)
    if last is None or anchor is None or last.start() <= anchor.end():
        return line
    end = last.end() if wipe_to is None else wipe_to
    return f"{line[: anchor.start('start')]}{_ELLIPSIS}: {_ELLIPSIS}{line[end:]}"


def _scrub_line(line: str) -> str:
    """One line with its recognized common names labeled and every other name redacted.

    The label pass changes only the text up to the line's last team ID, so that ID's end
    sits the same distance from the end of its output as from the end of *line*: the
    unlisted pass wipes through it there, whichever IDs the label pass consumed.
    """
    last = _last_team_id(line)
    if last is None:
        return line
    kept = _keep_known_labels(line, last)
    return _scrub_unlisted(kept, wipe_to=len(kept) - (len(line) - last.end()))


def _scrub_common_names(text: str) -> str:
    """*text* with recognized common names kept to their type and all others redacted."""
    return "\n".join(_scrub_line(line) for line in text.split("\n"))


def redact(text: str, identity: str) -> str:
    """*text* with every common name, team ID and the identity scrubbed.

    A common name whose type is one of :data:`CERTIFICATE_TYPES` keeps only that type
    (``Apple Development: …``) where a common name is known to start: at the line's start,
    after one-token diagnostic prefixes (``codesign: Apple Development: …``), or as an item
    of codesign's own ``(matches "…" and "…"`` list. Anywhere else the type may sit inside
    a name, so it is not trusted. Then, on any line still holding a raw team ID, everything
    from the first ``<word run>: `` through the last such ID becomes ``…: …``, kept labels
    included: an unrecognized type cannot be told from part of the name, and the name may
    run across a label. Over-redacting there is the ruling's price for never leaking one.
    Any parenthesized team ID left becomes ``(…)``, whatever the identity, because codesign
    echoes every certificate an ambiguous identity matched. The identity itself is
    replaced by its rendering only when that shortens it, so the ad-hoc ``-`` leaves
    codesign's own flags intact.
    """
    scrubbed = _ANY_TEAM_ID.sub(f"({_ELLIPSIS})", _scrub_common_names(text))
    shown = render_identity(identity)
    if len(shown) < len(identity):
        scrubbed = scrubbed.replace(identity, shown)
    own = _OWN_TEAM_ID.search(identity)
    if own is not None:
        scrubbed = scrubbed.replace(own.group(1) or own.group(2), _ELLIPSIS)
    return scrubbed
