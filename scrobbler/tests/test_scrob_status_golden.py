"""scrob_status reads the status files the Swift app writes, from its golden copies.

The Swift package's status golden test writes ``status_built/`` through the app's real
status writer and fails when the writer's bytes drift from those files. This suite reads
the same files with the real reader, so a key renamed on either side fails a test.
"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import _scrob_fixtures as fx  # noqa: E402 - import follows the sys.path bootstrap above
import scrob_status  # noqa: E402 - on sys.path once _scrob_fixtures is imported

#: The status files the Swift golden test writes.
STATUS_BUILT_DIR = Path(__file__).resolve().parents[1] / "status_built"

#: Each golden file and the fields the reader must find in it; the values are the
#: invented ones the Swift test sets.
EXPECTED = {
    "status-every-field.json": scrob_status.AppStatus(
        version="9.8.7",
        started_at=1_795_000_000.5,
        heartbeat_at=1_795_000_600.25,
        queue_backlog=3,
        oldest_queued_at=1_794_999_000.0,
        refused_count=2,
        last_queued_at=1_795_000_500.75,
        last_sent_at=1_795_000_400.0,
        last_send_error="store unreachable",
        automation_denied=True,
    ),
    "status-optionals-null.json": scrob_status.AppStatus(
        version="9.8.7",
        started_at=1_795_100_000.0,
        heartbeat_at=1_795_100_030.0,
        queue_backlog=0,
        oldest_queued_at=None,
        refused_count=0,
        last_queued_at=None,
        last_sent_at=None,
        last_send_error=None,
        automation_denied=False,
    ),
}


class GoldenStatusTest(unittest.TestCase):
    """Each status file the app writes reads back as the values it was written with."""

    def test_the_folder_holds_exactly_the_expected_files(self) -> None:
        names = sorted(path.name for path in STATUS_BUILT_DIR.iterdir())
        self.assertEqual(names, sorted(EXPECTED))

    def test_each_golden_file_reads_as_its_values(self) -> None:
        for name, expected in EXPECTED.items():
            with self.subTest(name=name):
                parsed = scrob_status.read_app_status(STATUS_BUILT_DIR / name)
                self.assertEqual(parsed, expected)

    def test_the_status_fixture_writes_the_keys_the_app_writes(self) -> None:
        # The other status tests start from the fixture's hand-written file, so its keys
        # must be the app's, including the ones the reader does not use.
        kit = fx.make_kit(self)
        kit.write_status()
        fixture_keys = set(
            json.loads(kit.paths.status_file.read_text(encoding="utf-8"))
        )
        for name in EXPECTED:
            with self.subTest(name=name):
                text = (STATUS_BUILT_DIR / name).read_text(encoding="utf-8")
                self.assertEqual(set(json.loads(text)), fixture_keys)


if __name__ == "__main__":
    unittest.main()
