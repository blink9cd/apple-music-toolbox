"""baseline_schema: a document checked against the scrobbler's copy of the contract.

Reads only the copy under ``scrobbler/contract/``: its baseline samples are the
reference, so a check that passed an invalid sample, or failed the valid one, fails
here. The missing-extra path is reached by making the ``jsonschema`` and
``referencing`` imports fail, every other import untouched.
"""

from __future__ import annotations

import builtins
import hashlib
import json
import sys
import unittest
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from types import ModuleType
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import baseline_schema as bs  # noqa: E402 - import follows the sys.path bootstrap above

#: The scrobbler's checked copy of the contract, found independently of the module.
_COPY_DIR = Path(__file__).resolve().parents[2] / "scrobbler" / "contract"
_SAMPLES = _COPY_DIR / "samples"
#: The schemas a baseline check reads, as the manifest names them.
_BASELINE_SCHEMAS = ("schemas/baseline.schema.json", "schemas/common.schema.json")
#: The packages the contract extra provides.
_CONTRACT_PACKAGES = ("jsonschema", "referencing")


def _samples(kind: str) -> list[Path]:
    """The copy's baseline samples of one kind, ``valid`` or ``invalid``."""
    return sorted((_SAMPLES / kind).glob("baseline-*.json"))


def _read(path: Path) -> object:
    """One UTF-8 JSON file, parsed."""
    return json.loads(path.read_text(encoding="utf-8"))


def _manifest() -> dict[str, str]:
    """The copy's manifest, path to SHA-256."""
    lines = (_COPY_DIR / "MANIFEST.sha256").read_text(encoding="utf-8").splitlines()
    return {path: digest for digest, path in (line.split("  ", 1) for line in lines)}


ImportFunction = Callable[..., ModuleType]


def _failing_contract_import(real: ImportFunction) -> ImportFunction:
    """An ``__import__`` that refuses the contract's packages and delegates the rest."""

    def importer(
        name: str,
        globals_: Mapping[str, object] | None = None,
        locals_: Mapping[str, object] | None = None,
        fromlist: Sequence[str] = (),
        level: int = 0,
    ) -> ModuleType:
        if name.partition(".")[0] in _CONTRACT_PACKAGES:
            raise ImportError(f"No module named {name!r}")
        return real(name, globals_, locals_, fromlist, level)

    return importer


class FindingsTest(unittest.TestCase):
    """`findings` agrees with the contract copy's own baseline samples."""

    def test_there_are_samples_of_both_kinds(self) -> None:
        # Non-vacuous: an emptied samples folder would pass both loops below.
        self.assertTrue(_samples("valid"))
        self.assertTrue(_samples("invalid"))

    def test_the_valid_baseline_samples_pass(self) -> None:
        for path in _samples("valid"):
            with self.subTest(sample=path.name):
                self.assertEqual(bs.findings(_read(path)), [])

    def test_the_invalid_baseline_samples_fail(self) -> None:
        for path in _samples("invalid"):
            with self.subTest(sample=path.name):
                self.assertNotEqual(bs.findings(_read(path)), [])

    def test_the_findings_are_sorted_messages(self) -> None:
        document = _read(_samples("valid")[0])
        assert isinstance(document, dict)
        del document["submission_client"]
        document["baseline_type"] = "listens"
        found = bs.findings(document)
        self.assertEqual(len(found), 2)
        self.assertEqual(found, sorted(found))

    def test_a_non_object_document_is_one_finding(self) -> None:
        self.assertEqual(len(bs.findings([])), 1)

    def test_the_schema_folder_is_the_copy_s(self) -> None:
        self.assertEqual(bs.SCHEMA_DIR, _COPY_DIR / "schemas")

    def test_the_manifest_lists_the_schemas_read_at_their_digests(self) -> None:
        manifest = _manifest()
        for name in _BASELINE_SCHEMAS:
            with self.subTest(schema=name):
                digest = hashlib.sha256((_COPY_DIR / name).read_bytes()).hexdigest()
                self.assertEqual(manifest.get(name), digest)


class LocatedFindingsTest(unittest.TestCase):
    """`located_findings` names where and which rule, and never the failing value."""

    def test_a_valid_sample_has_none(self) -> None:
        self.assertEqual(bs.located_findings(_read(_samples("valid")[0])), [])

    def test_each_finding_is_a_path_and_a_rule_never_the_value(self) -> None:
        document = _read(_samples("valid")[0])
        assert isinstance(document, dict)
        tracks = document["tracks"]
        assert isinstance(tracks, list)
        tracks[0]["track_name"] = ""
        tracks[0]["ls_year"] = "Invented Value"
        found = bs.located_findings(document)
        self.assertEqual(
            found,
            [
                "$.tracks[0].ls_year: fails the schema's 'type' rule",
                "$.tracks[0].track_name: fails the schema's 'minLength' rule",
            ],
        )
        self.assertNotIn("Invented Value", "".join(found))

    def test_it_agrees_with_findings_on_every_invalid_sample(self) -> None:
        for path in _samples("invalid"):
            with self.subTest(sample=path.name):
                document = _read(path)
                self.assertEqual(
                    len(bs.located_findings(document)), len(bs.findings(document))
                )


class ContractMissingTest(unittest.TestCase):
    """Without the contract extra, each check raises `ContractMissing`, naming it."""

    def test_require_contract_passes_with_the_extra_installed(self) -> None:
        bs.require_contract()  # raises on failure; returning at all is the pass

    def test_require_contract_raises_without_it(self) -> None:
        importer = _failing_contract_import(builtins.__import__)
        with (
            mock.patch("builtins.__import__", side_effect=importer),
            self.assertRaises(bs.ContractMissing),
        ):
            bs.require_contract()

    def test_located_findings_raises_without_it(self) -> None:
        importer = _failing_contract_import(builtins.__import__)
        with (
            mock.patch("builtins.__import__", side_effect=importer),
            self.assertRaises(bs.ContractMissing),
        ):
            bs.located_findings({})

    def test_a_failed_import_raises_contract_missing(self) -> None:
        importer = _failing_contract_import(builtins.__import__)
        with (
            mock.patch("builtins.__import__", side_effect=importer),
            self.assertRaises(bs.ContractMissing) as raised,
        ):
            bs.findings({})
        self.assertIn("pip install '.[contract]'", str(raised.exception))
        self.assertIsInstance(raised.exception.__cause__, ImportError)

    def test_other_imports_still_pass_through_the_fake(self) -> None:
        importer = _failing_contract_import(builtins.__import__)
        self.assertIs(importer("json"), json)


if __name__ == "__main__":
    unittest.main()
