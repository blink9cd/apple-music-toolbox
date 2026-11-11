"""Parse ``swift package dump-package`` into ``PackageFacts``; check SWG001 and SWG002.

Private to ``swift_gate``. The keys read here were verified live against SwiftPM 6.4
(``swift_gate.md`` -> *The floor and the language mode* records them):

* ``platforms[]``: ``{"platformName": "macos", "version": "14.0", "options": []}``;
* ``toolsVersion._version``: ``"6.0.0"``;
* ``swiftLanguageVersions``: ``null`` (the tools version's default) or ``["6", ...]``,
  which is what a manifest's ``swiftLanguageModes:`` argument dumps as;
* ``targets[].settings[]``: ``{"tool": "swift", "kind": {"swiftLanguageMode":
  {"_0": "5"}}}`` for a target's ``.swiftLanguageMode(.v5)``;
* ``products[]``: ``{"name": "hello", "type": {"executable": null}, ...}`` for an
  ``.executable`` product, and ``{"library": ["automatic"]}`` as the type of a library.
  Only declared products appear, so ``[]`` for a package declaring none;
* ``targets[].type``: ``"executable"`` for an ``.executableTarget``. One that no declared
  executable product's ``targets`` names gets an implicit product of its own name, which
  SwiftPM builds (measured: a ``Tool`` target with no product built ``Tool``, and a
  ``Hello`` target behind a ``hello`` product built only ``hello``).

Anything of the wrong shape is a :class:`~swgate_model.ParseError` (exit 2), because a
gate that read a drifted dump as "no platforms" would report a false SWG001, and one that
read it as "no settings" would pass a mode it never saw.

Entry point assumptions
-----------------------
Pure: text in, records and findings out.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, field

from swgate_model import ConfigError, Finding, ParseError

_REQUIRED_MODE = "6"
_MIN_TOOLS = (6,)  # a tools version below 6.0 predates language mode 6
# The setting key a target's language mode dumps under. The deprecated spelling is read too,
# so a manifest using the older name cannot slip a mode past the check.
_MODE_KEYS = ("swiftLanguageMode", "swiftLanguageVersion")
# The products[].type key of an .executable product, and the targets[].type value of an
# .executableTarget: the same word in both places.
_EXECUTABLE_KIND = "executable"


@dataclass(frozen=True)
class PackageFacts:
    """The manifest facts this gate checks, read from one dump."""

    name: str
    macos: str | None
    tools_version: str
    language_modes: tuple[str, ...]
    target_modes: dict[str, str] = field(default_factory=dict)
    executables: tuple[str, ...] = ()  # the executable products, which --sign signs


def _as_dict(value: object, what: str) -> dict[str, object]:
    """*value* as a JSON object, else a ParseError naming *what*."""
    if not isinstance(value, dict):
        raise ParseError(f"dump-package {what} is not an object")
    return value


def _as_list(value: object, what: str) -> list[object]:
    """*value* as a JSON array, else a ParseError naming *what*."""
    if not isinstance(value, list):
        raise ParseError(f"dump-package {what} is not an array")
    return value


def _as_str(value: object, what: str) -> str:
    """*value* as a JSON string, else a ParseError naming *what*."""
    if not isinstance(value, str):
        raise ParseError(f"dump-package {what} is not a string")
    return value


def parse_dump_package(text: str) -> PackageFacts:  # fuzz-target
    """The :class:`PackageFacts` in a dump-package JSON document."""
    try:
        data = json.loads(text)
    except ValueError as exc:
        raise ParseError(f"dump-package output is not JSON: {exc}") from exc
    try:
        return _facts_from(_as_dict(data, "output"))
    except KeyError as exc:
        raise ParseError(f"dump-package output lacks the key {exc}") from exc


def _facts_from(data: Mapping[str, object]) -> PackageFacts:
    """Build the facts from a decoded dump; KeyError on a missing key."""
    tools = _as_dict(data["toolsVersion"], "toolsVersion")
    modes = data.get("swiftLanguageVersions")
    return PackageFacts(
        name=_as_str(data["name"], "name"),
        macos=_macos_version(_as_list(data["platforms"], "platforms")),
        tools_version=_as_str(tools["_version"], "toolsVersion._version"),
        language_modes=tuple(
            _as_str(mode, "swiftLanguageVersions[]")
            for mode in (
                [] if modes is None else _as_list(modes, "swiftLanguageVersions")
            )
        ),
        target_modes=_target_modes(_as_list(data["targets"], "targets")),
        executables=_executables(
            _as_list(data["products"], "products"),
            _as_list(data["targets"], "targets"),
        ),
    )


def _executables(products: list[object], targets: list[object]) -> tuple[str, ...]:
    """Every executable SwiftPM builds: the declared products, then the implicit ones.

    SwiftPM gives each executable target that no declared executable product covers an
    implicit product named after the target, so those are signed too. Deduplicated,
    keeping declaration order.
    """
    names, covered = _declared_executables(products)
    for entry in targets:
        target = _as_dict(entry, "targets[]")
        name = _as_str(target["name"], "targets[].name")
        if target["type"] == _EXECUTABLE_KIND and name not in covered:
            names.append(name)
    return tuple(dict.fromkeys(names))


def _declared_executables(products: list[object]) -> tuple[list[str], set[str]]:
    """The executable products' names, and the targets those products cover."""
    names: list[str] = []
    covered: set[str] = set()
    for entry in products:
        product = _as_dict(entry, "products[]")
        kind = _as_dict(product["type"], "products[].type")
        if _EXECUTABLE_KIND in kind:
            names.append(_as_str(product["name"], "products[].name"))
            members = _as_list(product["targets"], "products[].targets")
            covered.update(_as_str(each, "products[].targets[]") for each in members)
    return names, covered


def _macos_version(platforms: list[object]) -> str | None:
    """The version of the ``macos`` platform entry, or None when there is none."""
    for entry in platforms:
        platform = _as_dict(entry, "platforms[]")
        if platform["platformName"] == "macos":
            return _as_str(platform["version"], "platforms[].version")
    return None


def _target_modes(targets: list[object]) -> dict[str, str]:
    """Each target's explicit language-mode setting, keyed by target name."""
    modes: dict[str, str] = {}
    for entry in targets:
        target = _as_dict(entry, "targets[]")
        name = _as_str(target["name"], "targets[].name")
        for setting in _as_list(target["settings"], "targets[].settings"):
            kind = _as_dict(_as_dict(setting, "settings[]")["kind"], "settings[].kind")
            for key in _MODE_KEYS:
                if key in kind:
                    mode = _as_dict(kind[key], f"settings[].kind.{key}")["_0"]
                    modes[name] = _as_str(mode, f"settings[].kind.{key}._0")
    return modes


def version_tuple(text: str) -> tuple[int, ...]:
    """``"14"`` and ``"14.0.0"`` both as ``(14,)``: trailing zero parts dropped.

    Raises ValueError on a non-numeric part.
    """
    parts = [int(part) for part in text.strip().split(".")]
    while len(parts) > 1 and parts[-1] == 0:
        parts.pop()
    return tuple(parts)


def check_manifest(facts: PackageFacts, floor: str, shown: str) -> tuple[Finding, ...]:
    """SWG001 for a macOS platform off the floor; SWG002 for tools or mode below 6."""
    try:
        wanted = version_tuple(floor)
    except ValueError as exc:
        raise ConfigError(f"macos_floor {floor!r} is not a version") from exc
    return (
        *_floor_findings(facts, floor, wanted, shown),
        *_mode_findings(facts, shown),
    )


def _floor_findings(
    facts: PackageFacts, floor: str, wanted: tuple[int, ...], shown: str
) -> tuple[Finding, ...]:
    """SWG001 unless the package declares exactly the floor."""
    if facts.macos is None:
        problem = "declares no macOS platform"
    elif _parsed(facts.macos, "macOS platform version") != wanted:
        problem = f"declares macOS {facts.macos}"
    else:
        return ()
    return (Finding("SWG001", shown, 0, f'{problem}; the floor is .macOS("{floor}")'),)


def _mode_findings(facts: PackageFacts, shown: str) -> tuple[Finding, ...]:
    """SWG002 for a tools version below 6.0, or any language mode other than 6."""
    findings: list[Finding] = []
    if _parsed(facts.tools_version, "tools version") < _MIN_TOOLS:
        findings.append(
            Finding("SWG002", shown, 1, f"tools version {facts.tools_version} < 6.0")
        )
    for mode in facts.language_modes:
        if mode != _REQUIRED_MODE:
            findings.append(
                Finding("SWG002", shown, 0, f"package language mode {mode}, not 6")
            )
    for target, mode in sorted(facts.target_modes.items()):
        if mode != _REQUIRED_MODE:
            findings.append(
                Finding(
                    "SWG002", shown, 0, f"target {target} language mode {mode}, not 6"
                )
            )
    return tuple(findings)


def _parsed(text: str, what: str) -> tuple[int, ...]:
    """:func:`version_tuple`, with a malformed dump value as a ParseError."""
    try:
        return version_tuple(text)
    except ValueError as exc:
        raise ParseError(f"dump-package {what} {text!r} is not a version") from exc
