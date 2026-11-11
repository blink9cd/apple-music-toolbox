"""The scrobbler's checked copy of the listensmith contract: complete, current and usable.

The copy under ``contract/`` lets the scrobbler, and the exported toolbox it ships in,
validate records with no listensmith checkout beside it. Its manifest names every copied
file with its SHA-256. Every test reads only the copy and the records the Swift package
writes beside it, never a file outside this checkout.

The copy is replaced whole from the contract's own files, never edited here; after
replacing it, inside ``contract/`` run ``shasum -a 256 <paths> | LC_ALL=C sort -k2 > MANIFEST.sha256``. ``LC_ALL=C`` matters:
the manifest test demands code-point order, and a UTF-8 locale's sort skips punctuation.

The records the Swift package builds are checked here too: its golden test writes them
to ``contract_built/``, and each must pass the copied schema its listen_type names.
"""

from __future__ import annotations

import ast
import functools
import hashlib
import json
import sys
import unittest
from pathlib import Path, PurePath
from types import ModuleType

from jsonschema import Draft202012Validator
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012, Schema

_HERE = Path(__file__).resolve().parent
COPY_DIR = _HERE.parent / "contract"
MANIFEST = COPY_DIR / "MANIFEST.sha256"
SCHEMA_DIR = COPY_DIR / "schemas"
SAMPLES_DIR = COPY_DIR / "samples"
DEFAULTS_FILE = COPY_DIR / "defaults.json"
#: The records the Swift package builds and writes, which this copy must accept.
BUILT_DIR = _HERE.parent / "contract_built"
#: Every schema's $id is this base plus its file name.
BASE_URI = "https://listensmith.invalid/contract/1/"
#: Which copied schema file governs each listen_type.
SCHEMA_BY_LISTEN_TYPE = {
    "single": "listen.schema.json",
    "import": "listen.schema.json",
    "playing_now": "now_playing.schema.json",
}
BASELINE_SCHEMA = "baseline.schema.json"
#: Sample files whose names start with this are play-count baselines, not listens.
BASELINE_PREFIX = "baseline-"
#: The store's port, which the scrobbler's Swift default is pinned against too.
STORE_PORT = 47831


def sha256_of(path: Path) -> str:
    """The hex SHA-256 of one file's bytes."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_manifest() -> list[tuple[str, str]]:
    """The manifest's (path, hash) pairs, in file order.

    Each line is ``shasum -a 256``'s output: the hash, two spaces, the path.
    """
    pairs = []
    for line in MANIFEST.read_text(encoding="utf-8").splitlines():
        digest, _, path = line.partition("  ")
        pairs.append((path, digest))
    return pairs


def copied_files() -> list[str]:
    """Every file in the copy, relative to it, except the manifest itself."""
    return sorted(
        path.relative_to(COPY_DIR).as_posix()
        for path in COPY_DIR.rglob("*")
        if path.is_file() and path != MANIFEST
    )


def read_json(path: Path) -> object:
    """Parse one UTF-8 JSON file."""
    return json.loads(path.read_text(encoding="utf-8"))


@functools.cache
def load_copy_registry() -> Registry[Schema]:
    """A registry of every copied schema keyed by its $id, with no retriever.

    With no retriever a $ref outside the copy fails rather than reaching the network.
    Built once and cached: a Registry is immutable, and callers validate many records.
    """
    resources = []
    for path in sorted(SCHEMA_DIR.glob("*.schema.json")):
        schema = read_json(path)
        assert isinstance(schema, dict)  # every schema file is a JSON object
        resource: Resource[Schema] = Resource.from_contents(
            schema, default_specification=DRAFT202012
        )
        resources.append((str(schema["$id"]), resource))
    return Registry().with_resources(resources)


def schema_errors(record: object, schema_name: str) -> list[str]:
    """Every message the named copied schema raises against *record*; empty is valid."""
    registry = load_copy_registry()
    schema = registry.contents(BASE_URI + schema_name)
    validator = Draft202012Validator(schema, registry=registry)
    return sorted(str(error.message) for error in validator.iter_errors(record))


def validate(record: object) -> list[str]:
    """Every way a listen submission fails the copied schema; empty means valid.

    The schema is the one the record's listen_type names; a record naming no known
    listen_type is one error, since no schema can judge it.
    """
    listen_type = record.get("listen_type") if isinstance(record, dict) else None
    schema_name = SCHEMA_BY_LISTEN_TYPE.get(str(listen_type))
    if schema_name is None:
        known = ", ".join(sorted(SCHEMA_BY_LISTEN_TYPE))
        return [f"listen_type must be one of: {known}"]
    return schema_errors(record, schema_name)


def validate_sample(path: Path) -> list[str]:
    """Validate one sample file as a baseline or a listen, by its file name."""
    record = read_json(path)
    if path.name.startswith(BASELINE_PREFIX):
        return schema_errors(record, BASELINE_SCHEMA)
    return validate(record)


class ManifestTest(unittest.TestCase):
    """The manifest names exactly the copied files, each with its current hash."""

    def test_manifest_lists_every_copied_file_with_its_hash(self) -> None:
        pairs = read_manifest()
        paths = [path for path, _ in pairs]
        self.assertEqual(paths, sorted(paths), "manifest lines are not sorted by path")
        self.assertEqual(paths, copied_files())
        for path, digest in pairs:
            with self.subTest(path=path):
                self.assertEqual(sha256_of(COPY_DIR / path), digest)


#: Calls that run code read from a file. Not one of them may appear in this suite.
_EXECUTING_CALLS = frozenset(
    {"exec", "exec_module", "run_path", "spec_from_file_location", "import_module"}
)


def _attribute_and_name_uses(tree: ast.AST) -> set[str]:
    """Every attribute and bare name this module's source mentions."""
    return {
        node.attr if isinstance(node, ast.Attribute) else node.id
        for node in ast.walk(tree)
        if isinstance(node, (ast.Attribute, ast.Name))
    }


def _parents_indexes(tree: ast.AST) -> list[object]:
    """The index of every ``<path>.parents[<index>]`` this module's source writes."""
    return [
        node.slice.value if isinstance(node.slice, ast.Constant) else node.slice
        for node in ast.walk(tree)
        if isinstance(node, ast.Subscript)
        and isinstance(node.value, ast.Attribute)
        and node.value.attr == "parents"
    ]


def _sibling_modules() -> dict[str, ModuleType]:
    """Every module in this folder, by name, imported as a runner imports it.

    By name off ``sys.path``, through the loader a runner uses, so no path is read and
    executed here; the folder goes first, as each suite's own bootstrap puts it.
    """
    sys.path.insert(0, str(_HERE))
    names = sorted(path.stem for path in _HERE.glob("*.py"))
    unittest.TestLoader().loadTestsFromNames(names)
    return {name: sys.modules[name] for name in names}


def _paths_outside(module: ModuleType, root: Path) -> list[str]:
    """Each module-level path global of *module* that resolves outside *root*."""
    return [
        f"{name} = {value}"
        for name, value in sorted(vars(module).items())
        if isinstance(value, PurePath)
        and not Path(value).resolve().is_relative_to(root)
    ]


class ContainmentTest(unittest.TestCase):
    """No suite here holds a module-level path outside the checkout, nor runs a file.

    A path that resolves above the project root names a folder outside the clone, where
    anyone could plant a file; a suite that imported a module from there would run it.
    The first test reads the resolved value of every module-level path global in this
    folder's modules, so such a climb fails however it is spelled; it does not see a
    path built inside a function. The other two read this file's own source: one for a
    ``.parents`` index past the project root, wherever it is written, and one for a call
    that executes code read from a file.
    """

    def setUp(self) -> None:
        self.tree = ast.parse(Path(__file__).read_text(encoding="utf-8"))

    def test_no_module_level_path_resolves_outside_the_project(self) -> None:
        # _HERE is tests/: its parents[1] is the project root, the clone's top.
        root = _HERE.parents[1].resolve()
        for name, module in _sibling_modules().items():
            with self.subTest(module=name):
                self.assertEqual(_paths_outside(module, root), [])

    def test_no_parents_index_climbs_above_the_project_root(self) -> None:
        # _HERE is tests/: its parents[0] is scrobbler/ and parents[1] the project root,
        # so any other index, or one computed at run time, can leave the checkout.
        indexes = _parents_indexes(self.tree)
        self.assertEqual([i for i in indexes if i not in (0, 1)], [])

    def test_no_file_read_is_executed(self) -> None:
        found = _attribute_and_name_uses(self.tree) & _EXECUTING_CALLS
        self.assertEqual(sorted(found), [])


class SamplesTest(unittest.TestCase):
    """The copy alone judges its own samples the way listensmith does."""

    def test_copy_validates_its_own_samples(self) -> None:
        valid = sorted((SAMPLES_DIR / "valid").glob("*.json"))
        invalid = sorted((SAMPLES_DIR / "invalid").glob("*.json"))
        self.assertTrue(valid and invalid, "the copy holds no samples")
        for path in valid:
            with self.subTest(valid=path.name):
                self.assertEqual(validate_sample(path), [])
        for path in invalid:
            with self.subTest(invalid=path.name):
                self.assertNotEqual(validate_sample(path), [])

    def test_a_record_with_no_known_listen_type_is_one_error(self) -> None:
        self.assertEqual(len(validate({"listen_type": "scrobble"})), 1)
        self.assertEqual(len(validate(["not", "an", "object"])), 1)


class BuiltRecordsTest(unittest.TestCase):
    """Every record the Swift package's golden test writes passes the copied schema."""

    def test_built_records_validate(self) -> None:
        built = sorted(BUILT_DIR.glob("*.json"))
        self.assertTrue(built, "the Swift package has written no golden records")
        for path in built:
            with self.subTest(built=path.name):
                self.assertEqual(validate(read_json(path)), [])


class DefaultsTest(unittest.TestCase):
    """The copied defaults hold the store port the scrobbler is built against."""

    def test_defaults_store_port(self) -> None:
        defaults = read_json(DEFAULTS_FILE)
        assert isinstance(defaults, dict)  # defaults.json is a JSON object
        self.assertEqual(defaults["store_port"], STORE_PORT)


if __name__ == "__main__":
    unittest.main()
