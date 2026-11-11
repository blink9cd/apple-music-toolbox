"""A baseline document checked against the scrobbler's copy of the listensmith contract.

The schemas are the copy under ``scrobbler/contract/schemas/``, found from this file,
so no listensmith checkout is needed. They are loaded into an offline registry with no
retriever: a ``$ref`` outside the copy fails instead of reaching the network.
``jsonschema`` comes from the toolbox's optional ``contract`` extra and is imported only
when a document is checked, or when `require_contract` asks up front, so its absence is
`ContractMissing`, naming the extra, rather than an import error at start-up.
`located_findings` is the form a run prints: where each failure is and which rule it
breaks, never the value, which may be a track's name or path.
"""

from __future__ import annotations

import functools
import json
from pathlib import Path
from collections.abc import Iterator
from typing import Protocol

#: The contract copy's schemas: two folders up is the toolbox's project root.
SCHEMA_DIR = Path(__file__).resolve().parents[2] / "scrobbler" / "contract" / "schemas"
#: The ``$id`` of the schema a baseline document is checked against.
_BASELINE_ID = "https://listensmith.invalid/contract/1/baseline.schema.json"


class ContractMissing(Exception):
    """The contract extra, which holds ``jsonschema``, is not installed."""


class _Failure(Protocol):
    """The part of a ``jsonschema`` validation error read here."""

    message: str
    json_path: str
    validator: object


class _Validator(Protocol):
    """The part of a ``jsonschema`` validator used here; the package ships no types."""

    def iter_errors(self, instance: object) -> Iterator[_Failure]:
        """Every way *instance* fails the schema."""


@functools.cache
def _schemas() -> tuple[tuple[str, dict[str, object]], ...]:
    """Every copied schema with its ``$id``, read once: the files do not change in a run."""
    loaded = []
    for path in sorted(SCHEMA_DIR.glob("*.schema.json")):
        schema = json.loads(path.read_text(encoding="utf-8"))
        loaded.append((str(schema["$id"]), schema))
    return tuple(loaded)


def _validator() -> _Validator:
    """A validator for the copied baseline schema, its ``$ref``s resolved offline.

    Raises `ContractMissing` when ``jsonschema`` or ``referencing`` cannot be imported.
    Typed by the `_Validator` protocol: the class exists only once the optional
    import succeeds, and ``jsonschema`` ships no type information.
    """
    # Imported here, each call, so the tool runs, and says what is missing, without them.
    try:
        from jsonschema import Draft202012Validator
        from referencing import Registry, Resource
        from referencing.jsonschema import DRAFT202012
    except ImportError as missing:
        raise ContractMissing(
            "checking the baseline needs the toolbox's contract extra: "
            "pip install '.[contract]'"
        ) from missing
    registry = Registry().with_resources(
        (schema_id, Resource.from_contents(schema, default_specification=DRAFT202012))
        for schema_id, schema in _schemas()
    )
    return Draft202012Validator(registry.contents(_BASELINE_ID), registry=registry)


def require_contract() -> None:
    """Raise `ContractMissing` now, before any work, when the extra is not installed."""
    _validator()


def findings(document: object) -> list[str]:
    """Every way *document* fails the copied baseline schema, sorted; empty is valid.

    Each is the validator's own message, which may quote the failing value. Raises
    `ContractMissing` when ``jsonschema`` or ``referencing`` cannot be imported.
    """
    return sorted(str(error.message) for error in _validator().iter_errors(document))


def located_findings(document: object) -> list[str]:
    """Every failure as its JSON path and the rule it breaks, sorted; never a value.

    For a run's stderr: a value in a baseline is a track's name or path, which a pasted
    summary must not carry, so the validator's message, which may quote it, is left
    out. Raises `ContractMissing` as `findings` does.
    """
    return sorted(
        f"{error.json_path}: fails the schema's {error.validator!r} rule"
        for error in _validator().iter_errors(document)
    )
