"""scrob_agent: after the swap, a copy of the app left under an earlier name is removed.

Split from test_scrob_agent.py, whose `AgentCase` kit (every tool and launchd a fake, the
swap logged) these tests share. The case-only rename is reproduced on a real temporary
folder where its volume ignores case, and through an injected identity seam everywhere.
"""

from __future__ import annotations

import plistlib
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))

import _scrob_fixtures as fx  # noqa: E402 - import follows the sys.path bootstrap above
import scrob_agent  # noqa: E402 - on sys.path once _scrob_fixtures is imported
from test_scrob_agent import AgentCase  # noqa: E402 - on sys.path, as above

if sys.platform == "win32":
    # POSIX only, as the scrobbler is.
    raise unittest.SkipTest("the scrobbler runs on macOS only")  # pragma: only-on win32


class OldNameSweepTest(AgentCase):
    """After the swap, a copy of the app left under an earlier name is removed."""

    def put_app(self, name: str, bundle_id: str | None) -> Path:
        """An app folder `name` in the data folder; with an Info.plist when `bundle_id`."""
        contents = self.kit.paths.data_dir / name / "Contents"
        contents.mkdir(parents=True)
        if bundle_id is not None:
            plist = {"CFBundleIdentifier": bundle_id}
            (contents / "Info.plist").write_bytes(plistlib.dumps(plist))
        return contents.parent

    def test_a_copy_under_an_earlier_name_is_removed(self) -> None:
        old = self.put_app("an earlier name.app", self.kit.layout.bundle_id)
        self.app_starts()
        self.assertEqual(self.install(), 0)
        self.assertFalse(old.exists())
        self.assertEqual(self.executable().read_bytes(), fx.BUILT_BYTES)

    def test_another_apps_bundle_is_kept(self) -> None:
        other = self.put_app("Another.app", "invalid.example.another")
        self.app_starts()
        self.assertEqual(self.install(), 0)
        self.assertTrue(other.is_dir())

    def test_an_app_folder_without_a_readable_plist_is_kept(self) -> None:
        bare = self.put_app("Bare.app", None)
        broken = self.put_app("Broken.app", None)
        (broken / "Contents" / "Info.plist").write_bytes(b"not a plist")
        self.app_starts()
        self.assertEqual(self.install(), 0)
        self.assertTrue(bare.is_dir())
        self.assertTrue(broken.is_dir())

    def test_a_symlinked_app_folder_is_never_followed(self) -> None:
        target = Path(self.kit.host.home) / "elsewhere.app"
        (target / "Contents").mkdir(parents=True)
        plist = {"CFBundleIdentifier": self.kit.layout.bundle_id}
        (target / "Contents" / "Info.plist").write_bytes(plistlib.dumps(plist))
        self.kit.paths.data_dir.mkdir(parents=True, exist_ok=True)
        link = self.kit.paths.data_dir / "linked.app"
        link.symlink_to(target)
        self.app_starts()
        self.assertEqual(self.install(), 0)
        self.assertTrue(link.is_symlink())
        self.assertTrue(target.is_dir())

    @unittest.skipUnless(fx.CASE_INSENSITIVE_TMP, fx.CASE_SENSITIVE_REASON)
    def test_an_earlier_name_differing_only_in_case_is_upgraded_not_removed(
        self,
    ) -> None:
        # The regression: on a case-insensitive volume the swap exchanged into the old
        # entry, which kept its old spelling; the sweep compared spellings, judged the
        # new app an earlier copy and removed it, and install exited 1.
        final = self.kit.paths.app_bundle
        # Only the stem's case differs, as in the real rename; `.app` stays as globbed.
        old_name = final.stem.swapcase() + final.suffix
        self.put_app(old_name, self.kit.layout.bundle_id)
        self.app_starts()
        self.assertEqual(self.install(), 0)
        self.assertEqual(self.executable().read_bytes(), fx.BUILT_BYTES)
        data = self.kit.paths.data_dir.iterdir()
        apps = [p.name for p in data if p.suffix.casefold() == final.suffix]
        self.assertEqual(apps, [final.name])

    def test_the_installed_bundle_is_known_by_identity_not_spelling(self) -> None:
        # Runs on any volume: the identity seam says a folder spelled otherwise IS the
        # installed bundle, as a case-insensitive volume would.
        self.kit.paths.app_bundle.mkdir(parents=True)
        other = self.put_app("spelled otherwise.app", self.kit.layout.bundle_id)
        stranger = self.put_app("a stranger.app", self.kit.layout.bundle_id)

        def same(first: Path, second: Path) -> bool:
            return first == other and second == self.kit.paths.app_bundle

        scrob_agent.remove_earlier_copies(
            self.kit.host, self.kit.layout, self.kit.paths, same_entry=same
        )
        self.assertTrue(other.is_dir())
        self.assertFalse(stranger.exists())

    def test_an_earlier_copy_that_cannot_be_removed_is_its_own_warning(self) -> None:
        old = self.put_app("an earlier name.app", self.kit.layout.bundle_id)
        self.app_starts()
        real_rmtree = scrob_agent.shutil.rmtree

        def refuse_the_old_copy(path: Path, ignore_errors: bool = False) -> None:
            if Path(path) == old:
                raise PermissionError("invented")
            real_rmtree(path, ignore_errors=ignore_errors)

        with mock.patch.object(scrob_agent.shutil, "rmtree", refuse_the_old_copy):
            self.assertEqual(self.install(), 0)
        self.assertTrue(old.is_dir())
        said = self.kit.err.getvalue()
        self.assertIn("could not remove an earlier copy", said)
        self.assertIn("an earlier name.app", said)
