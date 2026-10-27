"""phone_db: the database copied twice and compared, checked, read, and cleaned up.

Every copy goes through a copier built here from invented bytes, so nothing reaches a
phone; the database is built from SQL text by `phone_fixtures`.
"""

from __future__ import annotations

import contextlib
import sqlite3
import stat
import sys
import unittest
from collections.abc import Callable, Mapping
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

_HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(_HERE), str(_HERE.parent / "src")]

import phone_fixtures as pf  # noqa: E402 - import follows the sys.path bootstrap above
import phone_db as pd  # noqa: E402 - import follows the sys.path bootstrap above

_DB = pd.DB_REMOTE


class _Copier:
    """Copies from invented remote files, each bytes or a list served one per copy.

    A None in such a list leaves that copy absent, as a file the phone lacked then.

    *during* runs on each copy's local path before it is written, so a test can look
    at the scratch folder while it exists.
    """

    def __init__(
        self,
        files: Mapping[str, bytes | list[bytes | None]],
        during: Callable[[Path], None] | None = None,
    ) -> None:
        self.files = files
        self.during = during
        self.copied: list[tuple[str, Path]] = []

    def __call__(self, remote: str, local: Path) -> bool:
        if self.during is not None:
            self.during(local)
        self.copied.append((remote, local))
        data = self.files.get(remote)
        if isinstance(data, list):
            served = sum(r == remote for r, _ in self.copied)
            data = data[served - 1]
        if data is None:
            return False
        local.write_bytes(data)
        return True


def _db(*rows: pf.Row) -> bytes:
    """A database holding *rows*."""
    return pf.database_bytes(pf.fixture_sql(rows))


class _Scratch(unittest.TestCase):
    """A parent folder for the tool's scratch, checked empty after each run."""

    def setUp(self) -> None:
        super().setUp()
        holder = TemporaryDirectory()
        self.addCleanup(holder.cleanup)
        self.parent = Path(holder.name)

    def load(self, copier: _Copier) -> pd.PhoneRows:
        """Load the rows through *copier*, then confirm the scratch is gone."""
        try:
            return pd.load_rows(
                copier, progress=lambda _line: None, temp_parent=self.parent
            )
        finally:
            self.assertEqual(list(self.parent.iterdir()), [])


class RemotePathTest(unittest.TestCase):
    """The phone paths are relative to the AFC root, the device's /var/mobile/Media."""

    def test_the_database_path_starts_at_itunes_control(self) -> None:
        self.assertEqual(pd.DB_REMOTE, "/iTunes_Control/iTunes/MediaLibrary.sqlitedb")
        self.assertEqual(pd.DB_REMOTE, pf.DB_REMOTE)


class LoadTest(_Scratch):
    """Two copies, compared, then read."""

    def test_rows_in_a_sync_folder_are_read_and_the_rest_tallied(self) -> None:
        database = _db(
            pf.Row(
                1,
                pf.base("F00"),
                "AAAA.mp3",
                100,
                "One",
                1,
                2,
                "Invented Album",
                "The Placeholder Band",
            ),
            pf.Row(2, "iTunes_Control/Purchases", "BBBB.mp3", 5),
            pf.Row(3, None, "CCCC.mp3", 5),
        )
        rows = self.load(_Copier({_DB: database}))
        self.assertEqual(
            rows.rows,
            (
                pd.PhoneRow(
                    1,
                    "F00",
                    "AAAA.mp3",
                    100,
                    "One",
                    1,
                    2,
                    "Invented Album",
                    "The Placeholder Band",
                ),
            ),
        )
        self.assertEqual(rows.outside_sync, 2)

    def test_each_file_is_copied_twice_into_its_own_private_folder(self) -> None:
        modes: list[int] = []
        copier = _Copier(
            {_DB: _db()},
            during=lambda local: modes.extend(
                stat.S_IMODE(p.stat().st_mode)
                for p in (local.parent, local.parent.parent)
            ),
        )
        self.load(copier)
        remotes = [r for r, _ in copier.copied]
        self.assertEqual(remotes, [_DB, _DB + "-wal", _DB + "-shm"] * 2)
        locals_ = [p for _, p in copier.copied]
        self.assertEqual({p.parent.name for p in locals_[:3]}, {"1"})
        self.assertEqual({p.parent.name for p in locals_[3:]}, {"2"})
        self.assertEqual(
            [p.name for p in locals_[:3]], [Path(r).name for r in remotes[:3]]
        )
        self.assertEqual(set(modes), {0o700})

    def test_rows_held_only_in_the_wal_are_read(self) -> None:
        # The -wal must sit beside the copy under the same base name, or SQLite reads
        # the main file alone and these rows vanish.
        with TemporaryDirectory() as scratch:
            path = Path(scratch) / "MediaLibrary.sqlitedb"
            with contextlib.closing(sqlite3.connect(path)) as writer:
                writer.execute("PRAGMA journal_mode=WAL")
                writer.execute("PRAGMA wal_autocheckpoint=0")
                writer.executescript(pf.SCHEMA)
                writer.commit()
                writer.executescript(
                    pf.fixture_sql([pf.Row(7, pf.base("F03"), "WALL.mp3", 9)]).replace(
                        pf.SCHEMA, ""
                    )
                )
                writer.commit()
                files = {
                    _DB + suffix: Path(f"{path}{suffix}").read_bytes()
                    for suffix in ("", "-wal", "-shm")
                }
        self.assertGreater(len(files[_DB + "-wal"]), 0)
        rows = self.load(_Copier(files))
        self.assertEqual([r.item_pid for r in rows.rows], [7])


class RefusalTest(_Scratch):
    """Every way the copy cannot be trusted, each refused with the scratch removed."""

    def assert_refused(self, copier: _Copier, words: str) -> None:
        with self.assertRaises(pd.DatabaseRefused) as caught:
            self.load(copier)
        self.assertIn(words, str(caught.exception))

    def test_a_phone_with_no_database(self) -> None:
        self.assert_refused(_Copier({}), "no music database")

    def test_a_database_that_changed_between_the_copies(self) -> None:
        changed: list[bytes | None] = [_db(), _db(pf.Row(1, pf.base("F00"), "A", 1))]
        self.assert_refused(_Copier({_DB: changed}), "changed while it was copied")

    def test_a_wal_present_in_one_copy_only(self) -> None:
        copier = _Copier({_DB: _db(), _DB + "-wal": [b"x", None]})
        self.assert_refused(copier, "changed while it was copied")

    def test_a_file_that_is_not_a_database(self) -> None:
        self.assert_refused(_Copier({_DB: b"not a database" * 100}), "cannot be read")

    def test_a_database_without_the_expected_tables(self) -> None:
        self.assert_refused(
            _Copier({_DB: pf.database_bytes("CREATE TABLE other (x);")}),
            "expected tables",
        )

    def test_a_failed_cleanup_does_not_hide_the_original_error(self) -> None:
        # A copy folder that cannot be emptied makes rmtree fail; the error the caller
        # sees must still be the one that ended the load.
        locked: list[Path] = []

        def unlock() -> None:
            for folder in locked:
                folder.chmod(0o700)

        self.addCleanup(unlock)

        def lock_then_fail(_remote: str, local: Path) -> bool:
            local.write_bytes(b"copied")
            local.parent.chmod(0o500)
            locked.append(local.parent)
            raise RuntimeError("the original error")

        with self.assertRaisesRegex(RuntimeError, "the original error"):
            pd.load_rows(
                lock_then_fail, progress=lambda _line: None, temp_parent=self.parent
            )

    def test_a_copier_failure_still_removes_the_scratch(self) -> None:
        def broken(_remote: str, _local: Path) -> bool:
            raise OSError("copy broke")

        with self.assertRaises(OSError):
            pd.load_rows(broken, progress=lambda _line: None, temp_parent=self.parent)
        self.assertEqual(list(self.parent.iterdir()), [])


class IntegrityTest(unittest.TestCase):
    """``PRAGMA integrity_check`` must answer exactly ``ok``."""

    def test_ok_alone_passes(self) -> None:
        self.assertIsNone(pd.integrity_problem([("ok",)]))

    def test_anything_else_is_a_problem(self) -> None:
        for answer in (
            [],
            [("ok",), ("ok",)],
            [("*** in database main ***",), ("Page 3 bad",)],
        ):
            with self.subTest(answer=answer):
                problem = pd.integrity_problem(answer)
                assert problem is not None
                self.assertIn("integrity check", problem)

    def test_a_multi_row_answer_names_the_first_line_that_is_not_ok(self) -> None:
        problem = pd.integrity_problem([("ok",), ("Page 3 bad",)])
        assert problem is not None
        self.assertTrue(problem.endswith(": Page 3 bad"), problem)

    def test_ok_repeated_names_the_row_count_never_ok(self) -> None:
        problem = pd.integrity_problem([("ok",), ("ok",)])
        assert problem is not None
        self.assertIn("returned 2 rows", problem)
        self.assertNotIn(": ok", problem)

    def test_the_problem_is_raised_from_a_read(self) -> None:
        with TemporaryDirectory() as scratch:
            path = Path(scratch) / "db"
            path.write_bytes(_db())
            invented = "integrity check: invented"
            with (
                mock.patch.object(pd, "integrity_problem", return_value=invented),
                self.assertRaises(pd.DatabaseRefused) as caught,
            ):
                pd.read_rows(path)
        self.assertIn(invented, str(caught.exception))


class RowsOfTest(unittest.TestCase):
    """Each record's values made safe to report; the folder from the base path's end."""

    def test_missing_names_are_empty_and_missing_numbers_zero(self) -> None:
        rows = pd.rows_of(
            [(1, pf.base("F01"), None, None, None, None, None, None, None)]
        )
        self.assertEqual(
            rows.rows, (pd.PhoneRow(1, "F01", "", None, "", 0, 0, "", ""),)
        )

    def test_a_size_that_is_not_a_positive_integer_is_unknown(self) -> None:
        for size in (0, -5, None, "12", 1.5):
            with self.subTest(size=size):
                rows = pd.rows_of([(1, pf.base("F01"), "A", size, "", 1, 1, "", "")])
                self.assertIsNone(rows.rows[0].size)

    def test_a_text_value_of_another_type_is_shown_as_text(self) -> None:
        rows = pd.rows_of([(1, pf.base("F01"), b"AB", 5, 42, "2", 3.0, "", "")])
        row = rows.rows[0]
        self.assertEqual(
            (row.name, row.title, row.disc, row.track), ("b'AB'", "42", 0, 0)
        )

    def test_only_a_last_component_of_f_and_two_digits_is_in_the_sync(self) -> None:
        cases = {
            pf.base("F00"): "F00",
            pf.base("F49") + "/": "F49",
            "F07": "F07",
            pf.base("F100"): None,
            pf.base("f00"): None,
            pf.base("F0"): None,
            "iTunes_Control/Music/F00/Sub": None,
            "": None,
            None: None,
            7: None,
        }
        for path, folder in cases.items():
            with self.subTest(path=path):
                rows = pd.rows_of([(1, path, "A", 5, "", 1, 1, "", "")])
                self.assertEqual(
                    [r.folder for r in rows.rows], [] if folder is None else [folder]
                )
                self.assertEqual(rows.outside_sync, 1 if folder is None else 0)

    def test_a_missing_name_table_row_keeps_the_row(self) -> None:
        with TemporaryDirectory() as scratch:
            path = Path(scratch) / "db"
            path.write_bytes(
                _db(pf.Row(1, pf.base("F00"), "A", 5, album=None, artist=None))
            )
            rows = pd.read_rows(path)
        self.assertEqual([(r.album, r.artist) for r in rows.rows], [("", "")])


if __name__ == "__main__":
    unittest.main()
