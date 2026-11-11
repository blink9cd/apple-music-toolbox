"""audit_groups: which album group a file and a Music.app track count toward.

A group is the album artist (else artist), album and disc, both sides normalized the
same way, or the folder when a file's tags cannot be read. The pure half
takes invented values; the folder attribution of a gone track takes a fake ``stat``
where a test needs a path to report a device and inode of its choosing, and a real
temporary tree otherwise. Nothing reads a real library.
"""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(_HERE), str(_HERE.parent / "src")]

import audit_fixtures as af  # noqa: E402 - import follows the sys.path bootstrap above
import audit_groups as ag  # noqa: E402 - import follows the sys.path bootstrap above
import audit_rows as ar  # noqa: E402 - import follows the sys.path bootstrap above
import audit_tags as at  # noqa: E402 - import follows the sys.path bootstrap above
import audit_walk as aw  # noqa: E402 - import follows the sys.path bootstrap above


def _row(
    path: str = "", *, album: str = af.ALBUM, disc: int = 1, number: int = 1
) -> ar.TrackRow:
    """An invented listing row of *album*'s *disc*, its file at *path*."""
    return ar.TrackRow(af.pid(number), "local only", disc, number, path, album, af.BAND)


class NormalizedTest(unittest.TestCase):
    """Both sides' names compared the same way."""

    def test_case_ends_and_line_breaks_are_ignored(self) -> None:
        self.assertEqual(ag.normalized("  Invented\tALBUM \r\n"), "invented album")

    def test_composed_and_decomposed_accents_are_one_name(self) -> None:
        self.assertEqual(ag.normalized("Café"), ag.normalized("Café"))

    def test_casefold_reaches_past_lowercase(self) -> None:
        self.assertEqual(ag.normalized("STRASSE"), ag.normalized("straße"))


class GroupTest(unittest.TestCase):
    """What a group is equal by, how it is shown, and its order."""

    def test_a_file_and_a_track_of_one_album_are_one_group(self) -> None:
        self.assertEqual(
            ag.tag_group("the placeholder band", "INVENTED ALBUM", 1),
            ag.row_group(_row()),
        )

    def test_music_s_disc_zero_is_disc_one(self) -> None:
        self.assertEqual(ag.row_group(_row(disc=0)), ag.tag_group(af.BAND, af.ALBUM, 1))

    def test_a_row_s_disc_past_four_digits_is_disc_one(self) -> None:
        # Regression: row_tags read such a disc as disc 1 while row_group once
        # kept it raw, so the two sides of one album made a false count difference.
        past = _row(disc=at.LARGEST_NUMBER + 1)
        self.assertEqual(ag.row_group(past), ag.tag_group(af.BAND, af.ALBUM, 1))
        self.assertEqual(
            ag.row_group(_row(disc=at.LARGEST_NUMBER)),
            ag.tag_group(af.BAND, af.ALBUM, at.LARGEST_NUMBER),
        )

    def test_a_file_and_a_track_whose_discs_run_past_four_digits_are_one_group(
        self,
    ) -> None:
        # A file's disc tag past four digits reads as disc 1 (audit_tags), so a gone
        # track listing the same disc must count toward that same group.
        read = at.file_tags_from({"TPOS": af.Frame(str(at.LARGEST_NUMBER + 1))})
        assert read is not None
        filed = at.FileTags(af.BAND, af.ALBUM, read.disc, 1, None)
        self.assertEqual(
            ag.tags_group(filed), ag.row_group(_row(disc=at.LARGEST_NUMBER + 1))
        )

    def test_another_disc_or_album_is_another_group(self) -> None:
        self.assertNotEqual(ag.row_group(_row(disc=2)), ag.row_group(_row()))
        self.assertNotEqual(ag.row_group(_row(album="Other")), ag.row_group(_row()))

    def test_a_folder_group_is_never_a_tag_group(self) -> None:
        self.assertNotEqual(ag.folder_group(Path("/L")), ag.tag_group("", "", 1))

    def test_labels(self) -> None:
        self.assertEqual(
            ag.group_label(ag.tag_group(af.BAND, af.ALBUM, 2)),
            f"{af.BAND} / {af.ALBUM}, disc 2",
        )
        self.assertEqual(
            ag.group_label(ag.folder_group(Path("/L/A"))), "/L/A (by folder)"
        )

    def test_order_puts_tag_groups_first(self) -> None:
        groups = [
            ag.folder_group(Path("/L/A")),
            ag.tag_group("b", "x", 1),
            ag.tag_group("a", "y", 2),
            ag.tag_group("a", "y", 1),
        ]
        self.assertEqual(
            sorted(groups, key=ag.group_order),
            [groups[3], groups[2], groups[1], groups[0]],
        )


class FileGroupsTest(unittest.TestCase):
    """Each walked file's group: its tags', else its folder."""

    def test_read_tags_group_by_tags_and_unread_ones_by_folder(self) -> None:
        read, unread = Path("/L/A/01.mp3"), Path("/L/B/01.mp3")
        groups = ag.file_groups(
            [aw.AudioFile(read, (1, 1)), aw.AudioFile(unread, (1, 2))],
            {read: af.tagged(1)},
        )
        self.assertEqual(groups[read], ag.tag_group(af.BAND, af.ALBUM, 1))
        self.assertEqual(groups[unread], ag.folder_group(Path("/L/B")))

    def test_without_a_tag_reader_every_file_groups_by_folder(self) -> None:
        path = Path("/L/A/01.mp3")
        groups = ag.file_groups([aw.AudioFile(path, (1, 1))], None)
        self.assertEqual(groups[path], ag.folder_group(Path("/L/A")))


class CompilationGroupTest(unittest.TestCase):
    """A flagged compilation is one group, whatever artist each track names."""

    def test_flagged_tracks_of_one_album_share_one_group(self) -> None:
        one = ag.tag_group("First Placeholder", af.ALBUM, 1, compilation=True)
        two = ag.tag_group("Second Placeholder", af.ALBUM, 1, compilation=True)
        self.assertEqual(one, two)
        self.assertEqual(one.artist_key, ag.COMPILATION_KEY)
        self.assertEqual(ag.group_label(one), f"(compilation) / {af.ALBUM}, disc 1")

    def test_no_artist_name_reaches_the_compilation_key(self) -> None:
        for name in ("compilation", " Compilation ", "(compilation)", ""):
            with self.subTest(name=name):
                self.assertNotEqual(
                    ag.tag_group(name, af.ALBUM, 1),
                    ag.tag_group(name, af.ALBUM, 1, compilation=True),
                )

    def test_a_listed_flagged_track_groups_as_a_flagged_file_does(self) -> None:
        row = ar.TrackRow(af.pid(1), "local only", 1, 1, "", af.ALBUM, "Solo", True)
        self.assertEqual(
            ag.row_group(row),
            ag.tags_group(af.tagged(1, artist="Other", compilation=True)),
        )


class MusicGroupsByTagsTest(af.AuditCase):
    """With tags read: a matched track counts toward its file's group, a gone one by place."""

    def setUp(self) -> None:
        """A tagged album folder and a folder whose one file's tags could not be read."""
        super().setUp()
        (self.read,) = self.album("Band/Album", "01 a.mp3")
        (self.unread,) = self.album("Band/Unread", "01 x.mp3")
        self.files = [
            aw.AudioFile(path, (os.stat(path).st_dev, os.stat(path).st_ino))
            for path in (self.read, self.unread)
        ]
        self.groups = ag.file_groups(self.files, {self.read: af.tagged(1)})
        self.tagged = ag.tag_group(af.BAND, af.ALBUM, 1)
        self.folder = ag.folder_group(self.unread.parent)

    def groups_of(
        self,
        matched: dict[tuple[int, int], tuple[ar.TrackRow, ...]],
        gone: tuple[ar.TrackRow, ...],
        stat: ag.StatFn = os.stat,
    ) -> list[ag.Group]:
        """The Music side of *matched* and *gone* tracks, tags read."""
        return ag.music_groups(
            self.files,
            self.groups,
            matched,
            gone,
            library=self.library,
            by_folder=False,
            stat=stat,
        )

    def test_a_matched_track_counts_toward_its_file_s_group(self) -> None:
        # Music lists another album for the tagged file: still the file's group.
        matched = {
            self.files[0].key: (_row(str(self.read), album="Listed"),),
            self.files[1].key: (_row(str(self.unread)), _row(str(self.unread))),
        }
        self.assertEqual(
            self.groups_of(matched, ()), [self.tagged, self.folder, self.folder]
        )

    def test_a_gone_track_with_no_location_counts_toward_its_listed_album(
        self,
    ) -> None:
        self.assertEqual(
            self.groups_of({}, (_row(disc=2),)), [ag.row_group(_row(disc=2))]
        )

    def test_a_gone_track_inside_the_library_counts_toward_its_listed_album(
        self,
    ) -> None:
        gone = _row(str(self.library / "Moved" / "Away" / "02 b.mp3"), album="Other")
        self.assertEqual(self.groups_of({}, (gone,)), [ag.row_group(gone)])

    def test_a_gone_track_in_a_by_folder_group_s_folder_counts_toward_it(
        self,
    ) -> None:
        gone = _row(str(self.unread.parent / "02 y.mp3"), album="Other")
        self.assertEqual(self.groups_of({}, (gone,)), [self.folder])

    def test_a_folder_also_holding_tagged_files_does_not_take_a_gone_track(
        self,
    ) -> None:
        # One unreadable file beside the tagged one: the folder is mixed, so a gone
        # track there goes by its listed album, as the readable file does.
        (odd,) = self.album("Band/Album", "03 odd.mp3")
        info = os.stat(odd)
        self.files.append(aw.AudioFile(odd, (info.st_dev, info.st_ino)))
        self.groups = ag.file_groups(self.files, {self.read: af.tagged(1)})
        gone = _row(str(self.read.parent / "02 b.mp3"))
        self.assertEqual(self.groups_of({}, (gone,)), [ag.row_group(gone)])

    def test_a_gone_track_outside_the_library_is_not_counted(self) -> None:
        elsewhere = self.touch("elsewhere/x.mp3")
        gone = (
            _row(str(elsewhere.parent / "gone.mp3")),
            _row(str(self.root / "vanished" / "deep" / "gone.mp3")),
            _row("/\x00bad/x"),
        )
        self.assertEqual(self.groups_of({}, gone), [])

    def test_a_library_named_through_a_link_is_found_by_stat(self) -> None:
        # Music answers the resolved path; here the library is named by the real one
        # while the track names a symbolic link to it.
        alias = self.root / "alias"
        alias.symlink_to(self.library)
        gone = _row(str(alias / "Moved" / "02 b.mp3"))
        self.assertEqual(self.groups_of({}, (gone,)), [ag.row_group(gone)])

    def test_when_nothing_stats_the_path_text_decides(self) -> None:
        def _stat(path: str) -> os.stat_result:
            raise PermissionError(13, "Permission denied", path)

        inside = _row(f"{self.library}//Moved/./02 b.mp3")
        outside = _row(str(self.root / "elsewhere" / "02 b.mp3"))
        prefix = _row(f"{self.library}-other/02 b.mp3")
        self.assertEqual(
            self.groups_of({}, (inside, outside, prefix), _stat), [ag.row_group(inside)]
        )


class MusicGroupsByFolderTest(af.AuditCase):
    """Without tags: matched tracks count toward their file's folder, gone ones by stat."""

    def setUp(self) -> None:
        """One album folder of one walked file."""
        super().setUp()
        (self.kept,) = self.album("Band/Album", "01 a.mp3")
        info = os.stat(self.kept)
        self.files = [aw.AudioFile(self.kept, (info.st_dev, info.st_ino))]
        self.groups = ag.file_groups(self.files, None)
        self.folder = ag.folder_group(self.kept.parent)

    def groups_of(
        self, gone: tuple[ar.TrackRow, ...], stat: ag.StatFn = os.stat
    ) -> list[ag.Group]:
        """The Music side of *gone* tracks, the walked file matched once."""
        matched = {self.files[0].key: (_row(str(self.kept)),)}
        return ag.music_groups(
            self.files,
            self.groups,
            matched,
            gone,
            library=self.library,
            by_folder=True,
            stat=stat,
        )

    def test_a_gone_track_counts_toward_its_folder_found_by_stat(self) -> None:
        # Named by a path that differs as text: a symbolic link to the library.
        alias = self.root / "alias"
        alias.symlink_to(self.library)
        gone = _row(str(alias / "Band" / "Album" / "02 b.mp3"))
        self.assertEqual(self.groups_of((gone,)), [self.folder, self.folder])

    def test_an_unstattable_parent_falls_back_to_the_path_text(self) -> None:
        gone = _row(str(self.kept.parent / "02 b.mp3"))

        def _stat(path: str) -> os.stat_result:
            if path == str(self.kept.parent):
                raise PermissionError(13, "Permission denied", path)
            return os.stat(path)

        # The walked folder's own stat fails too, so only its text can match.
        self.assertEqual(self.groups_of((gone,), _stat), [self.folder, self.folder])

    def test_the_path_text_is_compared_normalized(self) -> None:
        gone = _row(f"{self.library}//Band/./Album/02 b.mp3")

        def _stat(path: str) -> os.stat_result:
            if "Album" in path and not path.endswith(".mp3"):
                raise FileNotFoundError(2, "No such file or directory", path)
            return os.stat(path)

        self.assertEqual(self.groups_of((gone,), _stat), [self.folder, self.folder])

    def test_a_gone_track_with_no_location_or_elsewhere_is_not_counted(self) -> None:
        elsewhere = self.touch("other/x.mp3")
        gone = (_row(""), _row(str(elsewhere.parent / "gone.mp3")), _row("/\x00bad/x"))
        self.assertEqual(self.groups_of(gone), [self.folder])


if __name__ == "__main__":
    unittest.main()
