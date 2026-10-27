"""Collecting the MP3s to refresh: the three explicit sources, the list contract, the union.

Every tree here is made under a temporary directory, and every file name is invented.
The property tests feed the list parser arbitrary bytes: a list file is written by
another tool, or typed, so the parser must never raise and never hand back a path the
contract refuses.
"""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

_HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(_HERE), str(_HERE.parent / "src")]

import refresh_core as rc  # noqa: E402 - import follows the sys.path bootstrap above
import refresh_fixtures as rf  # noqa: E402 - import follows the sys.path bootstrap above

settings.register_profile(
    "fuzz_gate_deterministic",
    derandomize=True,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow],
)
settings.load_profile("fuzz_gate_deterministic")

# os.geteuid exists only off Windows, so it is looked up; root reads a folder whose
# permissions refuse it, so the unreadable-folder test skips under it.
_GETEUID = getattr(os, "geteuid", None)
_IS_ROOT = _GETEUID is not None and _GETEUID() == 0
#: The label a list read from standard input is given in its problems.
_STDIN_LABEL = "-"
#: The parent-folder path component.
_PARENT = ".."


def _paths(collected: rc.Collected) -> list[Path]:
    """Return the collected MP3s' paths, in order."""
    return [mp3.path for mp3 in collected.mp3s]


class ParseListTest(unittest.TestCase):
    """parse_list: the list file contract, line by line, from bytes."""

    def test_absolute_paths_are_read_in_order(self) -> None:
        parsed = rc.parse_list(rf.list_bytes("/a/one.mp3", "/b/two.mp3"), "list.txt")
        self.assertEqual(
            parsed.paths, ((1, Path("/a/one.mp3")), (2, Path("/b/two.mp3")))
        )
        self.assertEqual(parsed.problems, ())

    def test_blank_lines_are_skipped_silently(self) -> None:
        parsed = rc.parse_list(rf.list_bytes("", "/a/one.mp3", "   "), "list.txt")
        self.assertEqual(parsed.paths, ((2, Path("/a/one.mp3")),))
        self.assertEqual(parsed.problems, ())

    def test_a_relative_path_is_reported_by_line_and_skipped(self) -> None:
        parsed = rc.parse_list(rf.list_bytes("/a/one.mp3", "b/two.mp3"), "list.txt")
        self.assertEqual(parsed.paths, ((1, Path("/a/one.mp3")),))
        self.assertEqual(
            parsed.problems,
            (rc.Problem("list.txt", 2, "b/two.mp3", rc.REASON_RELATIVE),),
        )

    def test_an_undecodable_line_is_reported_without_its_bytes(self) -> None:
        data = b"/a/caf\xe9.mp3\n/a/one.mp3\n"
        parsed = rc.parse_list(data, "list.txt")
        self.assertEqual(parsed.paths, ((2, Path("/a/one.mp3")),))
        self.assertEqual(
            parsed.problems, (rc.Problem("list.txt", 1, "", rc.REASON_NOT_UTF8),)
        )

    def test_an_unterminated_last_line_is_reported_not_read(self) -> None:
        # A writer stopped mid-line leaves exactly this, so it is never taken as a path.
        parsed = rc.parse_list(b"/a/one.mp3\n/a/tw", "list.txt")
        self.assertEqual(parsed.paths, ((1, Path("/a/one.mp3")),))
        self.assertEqual(
            parsed.problems,
            (rc.Problem("list.txt", 2, "/a/tw", rc.REASON_UNTERMINATED),),
        )

    def test_a_line_holding_a_nul_is_reported(self) -> None:
        parsed = rc.parse_list(b"/a/o\x00ne.mp3\n", "list.txt")
        self.assertEqual(parsed.paths, ())
        self.assertEqual(
            parsed.problems, (rc.Problem("list.txt", 1, "", rc.REASON_NUL),)
        )

    def test_standard_input_and_a_file_share_one_parser(self) -> None:
        data = rf.list_bytes("/a/one.mp3", "rel.mp3")
        from_file = rc.parse_list(data, "list.txt")
        from_stdin = rc.parse_list(data, _STDIN_LABEL)
        self.assertEqual(from_file.paths, from_stdin.paths)
        self.assertEqual(
            [problem.line for problem in from_file.problems],
            [problem.line for problem in from_stdin.problems],
        )
        self.assertEqual(from_stdin.problems[0].source, _STDIN_LABEL)

    def test_a_dot_dot_line_is_normalized_lexically(self) -> None:
        # Album names come from path components, so a ``..`` must never reach them.
        parsed = rc.parse_list(rf.list_bytes("/a/b/../c.mp3", "/a/./d.mp3"), "l")
        self.assertEqual(parsed.paths, ((1, Path("/a/c.mp3")), (2, Path("/a/d.mp3"))))

    def test_a_crlf_line_is_reported_for_its_carriage_return(self) -> None:
        parsed = rc.parse_list(b"/a/one.mp3\r\nrel.mp3\r\n/a/two.mp3\n", "list.txt")
        self.assertEqual(parsed.paths, ((3, Path("/a/two.mp3")),))
        self.assertEqual(
            parsed.problems,
            (
                rc.Problem("list.txt", 1, "/a/one.mp3", rc.REASON_CRLF),
                rc.Problem("list.txt", 2, "rel.mp3", rc.REASON_CRLF),
            ),
        )

    def test_empty_bytes_hold_nothing(self) -> None:
        self.assertEqual(rc.parse_list(b"", "list.txt"), rc.ParsedList((), ()))

    @given(st.binary())
    def test_fuzz_parse_list(self, data: bytes) -> None:
        parsed = rc.parse_list(data, "list.txt")
        line_count = data.count(b"\n") + 1
        for line, path in parsed.paths:
            self.assertTrue(rc.is_list_path(path), path)
            self.assertTrue(1 <= line <= line_count)
        for problem in parsed.problems:
            self.assertIsNotNone(problem.line)
            assert problem.line is not None  # narrowed for the type checker
            self.assertTrue(1 <= problem.line <= line_count)

    @given(
        st.lists(
            st.text(
                alphabet=st.characters(codec="utf-8", blacklist_characters="\n\r\x00"),
                min_size=1,
            ).filter(lambda name: name.strip() != "" and "/" not in name)
        )
    )
    def test_any_absolute_paths_round_trip(self, names: list[str]) -> None:
        # Compared as paths, so ``/.`` reads back as ``/`` (pathlib and normpath agree
        # on it); ``/..`` is no round trip at all, since a list line is normalized
        # lexically, so it is left out here and pinned on its own above.
        lines = [f"/{name}" for name in names if name != _PARENT]
        parsed = rc.parse_list(rf.list_bytes(*lines), "list.txt")
        self.assertEqual([path for _, path in parsed.paths], [Path(n) for n in lines])
        self.assertEqual(parsed.problems, ())


class IsListPathTest(unittest.TestCase):
    """is_list_path: the shape every path parse_list returns must have."""

    def test_an_absolute_path_passes(self) -> None:
        self.assertTrue(rc.is_list_path(Path("/a/one.mp3")))

    def test_a_relative_path_fails(self) -> None:
        self.assertFalse(rc.is_list_path(Path("a/one.mp3")))

    def test_a_path_holding_a_linefeed_fails(self) -> None:
        self.assertFalse(rc.is_list_path(Path("/a/o\nne.mp3")))

    def test_a_path_holding_a_nul_fails(self) -> None:
        self.assertFalse(rc.is_list_path(Path("/a/o\x00ne.mp3")))


class CollectTracksTest(rf.TreeCase):
    """collect_mp3s over --track paths."""

    def test_a_track_is_collected_with_its_device_and_inode(self) -> None:
        track = self.touch("Artist/Album/01.mp3")
        collected = rc.collect_mp3s(tracks=[track])
        info = os.stat(track)
        self.assertEqual(collected.mp3s, (rc.Mp3(track, (info.st_dev, info.st_ino)),))
        self.assertEqual(collected.problems, ())

    def test_the_suffix_is_matched_without_case(self) -> None:
        track = self.touch("Album/01.MP3")
        self.assertEqual(_paths(rc.collect_mp3s(tracks=[track])), [track])

    def test_a_relative_track_is_made_absolute(self) -> None:
        # Against the working directory, which this test moves into its own tree.
        track = self.touch("Album/01.mp3")
        self.addCleanup(os.chdir, Path.cwd())
        os.chdir(self.root)
        self.assertEqual(
            _paths(rc.collect_mp3s(tracks=[Path("Album/01.mp3")])), [track]
        )

    def test_a_dot_dot_track_joins_its_real_folder(self) -> None:
        # From inside ``Album/Disc 1``, ``../00.mp3`` is ``Album/00.mp3``: one group,
        # named for ``Album``, never a ``Disc 1/..`` folder of its own.
        album = self.root / "Artist/Album"
        self.touch("Artist/Album/00.mp3")
        self.touch("Artist/Album/01.mp3", b"ID3 another")
        (album / "Disc 1").mkdir()
        self.addCleanup(os.chdir, Path.cwd())
        os.chdir(album / "Disc 1")
        collected = rc.collect_mp3s(tracks=[Path(_PARENT, "00.mp3")], albums=[album])
        groups = rc.group_albums(collected.mp3s, tag_reader=None)
        self.assertEqual([group.folder for group in groups], [album])
        self.assertEqual(groups[0].names, ("Album", "Artist"))

    def test_a_missing_track_is_reported(self) -> None:
        missing = self.root / "gone.mp3"
        collected = rc.collect_mp3s(tracks=[missing])
        self.assertEqual(collected.mp3s, ())
        self.assertEqual(
            collected.problems,
            (rc.Problem(rc.SOURCE_TRACK, None, str(missing), rc.REASON_NOT_A_FILE),),
        )

    def test_a_track_os_stat_refuses_is_not_a_file(self) -> None:
        bad = self.root / "o\x00ne.mp3"
        collected = rc.collect_mp3s(tracks=[bad])
        self.assertEqual(collected.problems[0].reason, rc.REASON_NOT_A_FILE)

    def test_a_folder_named_as_a_track_is_not_a_file(self) -> None:
        folder = self.root / "folder.mp3"
        folder.mkdir()
        collected = rc.collect_mp3s(tracks=[folder])
        self.assertEqual(collected.problems[0].reason, rc.REASON_NOT_A_FILE)

    def test_a_track_that_is_not_an_mp3_is_reported(self) -> None:
        cover = self.touch("Album/cover.jpg")
        collected = rc.collect_mp3s(tracks=[cover])
        self.assertEqual(collected.mp3s, ())
        self.assertEqual(
            collected.problems,
            (rc.Problem(rc.SOURCE_TRACK, None, str(cover), rc.REASON_NOT_MP3),),
        )


class CollectAlbumsTest(rf.TreeCase):
    """collect_mp3s over --album folders."""

    def test_a_multi_disc_album_is_walked_in_order(self) -> None:
        album = self.root / "Album"
        second = self.touch("Album/Disc 2/01.mp3")
        first = self.touch("Album/Disc 1/01.mp3")
        loose = self.touch("Album/00 intro.mp3")
        self.assertEqual(
            _paths(rc.collect_mp3s(albums=[album])), [loose, first, second]
        )

    def test_hidden_folders_and_files_and_other_files_are_skipped(self) -> None:
        album = self.root / "Album"
        kept = self.touch("Album/01.mp3")
        self.touch("Album/.trash/02.mp3")
        self.touch("Album/._01.mp3")
        self.touch("Album/cover.jpg")
        self.touch("Album/notes.mp3.txt")
        self.assertEqual(_paths(rc.collect_mp3s(albums=[album])), [kept])

    def test_a_dot_dot_album_names_its_real_folders(self) -> None:
        album = self.root / "Artist/Album"
        disc = self.touch("Artist/Album/Disc 1/01.mp3")
        self.addCleanup(os.chdir, Path.cwd())
        os.chdir(disc.parent)
        collected = rc.collect_mp3s(albums=[Path(_PARENT)])
        self.assertEqual(_paths(collected), [disc])
        (group,) = rc.group_albums(collected.mp3s, tag_reader=None)
        self.assertEqual(group.names, ("Disc 1", "Album"))
        self.assertEqual(group.folder.parent, album)

    def test_a_linked_subfolder_is_walked(self) -> None:
        album = self.root / "Album"
        kept = self.touch("Album/01.mp3")
        self.touch("Elsewhere/01.mp3", b"ID3 another")
        (album / "Bonus").symlink_to(self.root / "Elsewhere")
        collected = rc.collect_mp3s(albums=[album])
        self.assertEqual(_paths(collected), [kept, album / "Bonus" / "01.mp3"])
        self.assertEqual(collected.problems, ())

    def test_a_link_loop_is_walked_once_and_reported(self) -> None:
        album = self.root / "Album"
        kept = self.touch("Album/Disc 1/01.mp3")
        back = album / "Disc 1" / "back"
        back.symlink_to(album)
        collected = rc.collect_mp3s(albums=[album])
        self.assertEqual(_paths(collected), [kept])
        self.assertEqual(
            collected.problems,
            (rc.Problem(rc.SOURCE_ALBUM, None, str(back), rc.REASON_ALREADY_WALKED),),
        )

    def test_a_subfolder_that_cannot_be_stated_is_reported_not_walked(self) -> None:
        album = self.root / "Album"
        kept = self.touch("Album/01.mp3")
        self.touch("Album/Disc 2/01.mp3", b"ID3 another")
        locked = str(album / "Disc 2")

        def _stat(path: str) -> os.stat_result:
            if path == locked:
                raise PermissionError(path)
            return os.stat(path)

        collected = rc.collect_mp3s(albums=[album], stat=_stat)
        self.assertEqual(_paths(collected), [kept])
        self.assertEqual(
            collected.problems,
            (rc.Problem(rc.SOURCE_ALBUM, None, locked, rc.REASON_UNREADABLE),),
        )

    def test_an_album_holding_no_mp3_is_reported(self) -> None:
        album = self.root / "Album"
        self.touch("Album/cover.jpg")
        self.touch("Album/.trash/01.mp3")
        collected = rc.collect_mp3s(albums=[album])
        self.assertEqual(collected.mp3s, ())
        self.assertEqual(
            collected.problems,
            (rc.Problem(rc.SOURCE_ALBUM, None, str(album), rc.REASON_NO_MP3),),
        )

    def test_a_file_named_as_an_album_is_not_a_folder(self) -> None:
        track = self.touch("01.mp3")
        collected = rc.collect_mp3s(albums=[track])
        self.assertEqual(
            collected.problems,
            (rc.Problem(rc.SOURCE_ALBUM, None, str(track), rc.REASON_NOT_A_FOLDER),),
        )

    def test_a_missing_album_folder_is_reported(self) -> None:
        missing = self.root / "Nothing"
        collected = rc.collect_mp3s(albums=[missing])
        self.assertEqual(
            collected.problems,
            (rc.Problem(rc.SOURCE_ALBUM, None, str(missing), rc.REASON_NOT_A_FOLDER),),
        )

    @unittest.skipIf(_IS_ROOT, "root reads a folder its permissions refuse")
    def test_an_unreadable_subfolder_is_reported_and_the_rest_kept(self) -> None:
        album = self.root / "Album"
        kept = self.touch("Album/01.mp3")
        locked = album / "Disc 2"
        locked.mkdir()
        locked.chmod(0)
        self.addCleanup(locked.chmod, 0o755)
        collected = rc.collect_mp3s(albums=[album])
        self.assertEqual(_paths(collected), [kept])
        self.assertEqual(len(collected.problems), 1)
        self.assertEqual(collected.problems[0].source, rc.SOURCE_ALBUM)
        self.assertEqual(collected.problems[0].reason, rc.REASON_UNREADABLE)

    def test_a_file_that_vanishes_before_its_stat_is_reported(self) -> None:
        album = self.root / "Album"
        kept = self.touch("Album/01.mp3")
        gone = self.touch("Album/02.mp3")

        def _stat(path: str) -> os.stat_result:
            if path == str(gone):
                raise FileNotFoundError(path)
            return os.stat(path)

        collected = rc.collect_mp3s(albums=[album], stat=_stat)
        self.assertEqual(_paths(collected), [kept])
        self.assertEqual(
            collected.problems,
            (rc.Problem(rc.SOURCE_ALBUM, None, str(gone), rc.REASON_NOT_A_FILE),),
        )


class CollectListsTest(rf.TreeCase):
    """collect_mp3s over list sources: the parse, then each path checked on disk."""

    def test_a_listed_path_that_is_not_a_file_is_reported_by_line(self) -> None:
        kept = self.touch("Album/01.mp3")
        missing = self.root / "Album/02.mp3"
        source = rc.ListSource("list.txt", rf.list_bytes(str(kept), "", str(missing)))
        collected = rc.collect_mp3s(lists=[source])
        self.assertEqual(_paths(collected), [kept])
        self.assertEqual(
            collected.problems,
            (rc.Problem("list.txt", 3, str(missing), rc.REASON_NOT_A_FILE),),
        )

    def test_a_listed_file_that_is_not_an_mp3_is_reported_by_line(self) -> None:
        cover = self.touch("Album/cover.jpg")
        source = rc.ListSource(_STDIN_LABEL, rf.list_bytes(str(cover)))
        collected = rc.collect_mp3s(lists=[source])
        self.assertEqual(
            collected.problems,
            (rc.Problem(_STDIN_LABEL, 1, str(cover), rc.REASON_NOT_MP3),),
        )

    def test_parse_problems_come_through_with_the_disk_ones(self) -> None:
        source = rc.ListSource("list.txt", rf.list_bytes("relative.mp3"))
        collected = rc.collect_mp3s(lists=[source])
        self.assertEqual(collected.problems[0].reason, rc.REASON_RELATIVE)


class UnionTest(rf.TreeCase):
    """The sources are united by device and inode, so each file appears once."""

    def test_one_file_named_by_every_source_appears_once(self) -> None:
        track = self.touch("Album/01.mp3")
        other = self.touch("Album/02.mp3")
        source = rc.ListSource("list.txt", rf.list_bytes(str(track)))
        collected = rc.collect_mp3s(
            tracks=[track], albums=[self.root / "Album"], lists=[source]
        )
        self.assertEqual(_paths(collected), [track, other])

    def test_a_hard_link_and_a_symlink_count_as_the_file_they_reach(self) -> None:
        track = self.touch("Album/01.mp3")
        hard = self.root / "hard.mp3"
        os.link(track, hard)
        soft = self.root / "soft.mp3"
        soft.symlink_to(track)
        collected = rc.collect_mp3s(tracks=[track, hard, soft])
        self.assertEqual(_paths(collected), [track])

    def test_every_path_naming_a_file_gives_its_album_names(self) -> None:
        # The first-named path is the one kept, but the names come from them all.
        album = self.root / "Artist/Album"
        track = self.touch("Artist/Album/01.mp3")
        link = self.root / "Picks/Mix/01.mp3"
        link.parent.mkdir(parents=True)
        os.link(track, link)
        collected = rc.collect_mp3s(tracks=[link], albums=[album])
        self.assertEqual(_paths(collected), [link])
        self.assertEqual(collected.mp3s[0].aliases, (track,))
        (group,) = rc.group_albums(collected.mp3s, tag_reader=None)
        self.assertEqual(group.names, ("Mix", "Picks", "Album", "Artist"))

    def test_no_source_collects_nothing(self) -> None:
        self.assertEqual(rc.collect_mp3s(), rc.Collected((), ()))

    def test_sources_holding_no_mp3_collect_nothing_and_say_why(self) -> None:
        album = self.root / "Empty"
        album.mkdir()
        collected = rc.collect_mp3s(
            albums=[album], lists=[rc.ListSource("list.txt", b"x\n")]
        )
        self.assertEqual(collected.mp3s, ())
        self.assertEqual(
            collected.problems,
            (
                rc.Problem(rc.SOURCE_ALBUM, None, str(album), rc.REASON_NO_MP3),
                rc.Problem("list.txt", 1, "x", rc.REASON_RELATIVE),
            ),
        )
