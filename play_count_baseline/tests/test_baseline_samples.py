"""The hand run in samples/README.md, run for real in a shell against the sample's fake osascript.

The README's command block runs in ``bash``, from the samples folder, as a separate
process. Its ``PATH`` is a mirror: a temporary folder holding only the few commands the
block and the fake need (``bash``, ``mktemp``, ``grep``, ``diff``) and a ``python`` that
starts this interpreter, so no real ``osascript`` is on it. The block's own line then puts
``fake_bin`` first, as a hand run does. ``TMPDIR`` points at the test's own temporary
folder, so the block's ``mktemp -d`` makes its output folder there, outside any checkout
(macOS's ``mktemp -d`` ignores ``TMPDIR`` unless given a template, so the block names one).

The baseline written must equal ``expected-baseline.json`` in every key but
``captured_at``, which is the run's own clock; what the run prints must equal the README's
blocks; and every block must appear in the README as written. The two tests that run the
tool itself skip off macOS, because the tool refuses every other platform before it reads
anything; the README's blocks, the wrong-folder guard, and the fake are checked everywhere.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

_HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(_HERE.parent), str(_HERE.parent / "src")]

import play_count_baseline  # noqa: E402, F401 - puts tag_refresh's src/ on sys.path
import bounded_run  # noqa: E402 - music_calls, imported above, put it on sys.path

_SAMPLES = _HERE.parent / "samples"
_README = _SAMPLES / "README.md"
_FAKE = _SAMPLES / "fake_bin" / "osascript"
_EXPECTED = _SAMPLES / "expected-baseline.json"
#: The one key whose value differs from run to run.
_VARYING = "captured_at"
#: What the guard says when the block is run from the wrong folder.
_WRONG_FOLDER = "run this from the samples folder"
#: The commands the block and the fake run by name, mirrored onto the test's PATH.
_MIRRORED = ("bash", "mktemp", "grep", "diff")
#: How long one run of the block may take: four invented tracks, three fake calls.
_RUN_TIMEOUT_S = 120

COMMAND = f"""\
test -x fake_bin/osascript || echo "{_WRONG_FOLDER}: fake_bin/osascript is not here" >&2
out="$(mktemp -d "${{TMPDIR:-/tmp}}/play_count_baseline.XXXXXX")/baseline.json"
test -x fake_bin/osascript && PATH="$PWD/fake_bin:$PATH" TZ=UTC python ../play_count_baseline.py --output "$out"
test -f "$out" && diff <(grep -v '"{_VARYING}"' expected-baseline.json) <(grep -v '"{_VARYING}"' "$out") && echo "matches expected-baseline.json but for {_VARYING}"
"""

STDOUT = f"matches expected-baseline.json but for {_VARYING}\n"

STDERR = """\
tracks 1-4 of 4
tracks read: 4
tracks written: 3
excluded, no name: 0
excluded, no artist: 1
missing release_name: 0
missing ls_album_artist: 2
missing ls_disc_number: 1
missing duration_ms: 0
missing last_played_at: 1
missing ls_genre: 1
missing ls_year: 1
missing ls_file_path: 1
"""


def _fenced(body: str, language: str) -> str:
    """*body* as the README fences it."""
    return f"```{language}\n{body}```\n"


def _mirror(folder: Path) -> Path:
    """A ``PATH`` folder holding only `_MIRRORED` and a ``python`` for this interpreter."""
    folder.mkdir()
    for name in _MIRRORED:
        found = shutil.which(name)
        assert found is not None, f"{name} is not on PATH"
        (folder / name).symlink_to(found)
    python = folder / "python"
    # A wrapper, not a link: a linked venv interpreter would not find its pyvenv.cfg,
    # and so would start without the contract extra this run needs.
    python.write_text(
        f'#!/bin/sh\nexec "{sys.executable}" "$@"\n', encoding="utf-8", newline="\n"
    )
    python.chmod(0o755)
    return folder


def _without_varying(document: dict[str, object]) -> dict[str, object]:
    """*document* less its `_VARYING` key."""
    return {key: value for key, value in document.items() if key != _VARYING}


class ScratchCase(unittest.TestCase):
    """A scratch folder holding the mirrored ``PATH`` and the block's ``TMPDIR``."""

    def setUp(self) -> None:
        """A scratch folder for the mirror and for the block's ``mktemp -d``."""
        super().setUp()
        holder = TemporaryDirectory()
        self.addCleanup(holder.cleanup)
        self.scratch = Path(holder.name).resolve()
        self.temp = self.scratch / "tmp"
        self.temp.mkdir()
        self.path = _mirror(self.scratch / "bin")

    def run_block(self, cwd: Path) -> bounded_run.subprocess.CompletedProcess[str]:
        """The README's block, in ``bash`` from *cwd*, on the mirrored ``PATH``."""
        return bounded_run.run_bounded(
            [str(self.path / "bash"), "-c", COMMAND],
            timeout=_RUN_TIMEOUT_S,
            cwd=str(cwd),
            env={"PATH": str(self.path), "TMPDIR": str(self.temp)},
        )

    def written_path(self) -> Path:
        """The one baseline the block wrote under the scratch ``TMPDIR``."""
        found = list(self.temp.rglob("baseline.json"))
        self.assertEqual(len(found), 1, found)
        return found[0]


class AnywhereTest(ScratchCase):
    """What holds on every platform: the README's blocks, the guard, and the fake."""

    def test_every_block_appears_in_the_readme_as_written(self) -> None:
        text = _README.read_text(encoding="utf-8")
        for body, language in ((COMMAND, "bash"), (STDOUT, "text"), (STDERR, "text")):
            with self.subTest(block=body.splitlines()[0]):
                self.assertIn(_fenced(body, language), text)

    def test_from_another_folder_the_block_writes_nothing(self) -> None:
        # The guard must stop the running line before python, so with no fake here
        # the real osascript is never looked for.
        result = self.run_block(self.scratch)
        self.assertIn(_WRONG_FOLDER, result.stderr)
        self.assertNotIn("command not found", result.stderr)
        self.assertEqual(list(self.temp.rglob("baseline.json")), [])
        self.assertNotEqual(result.returncode, 0)

    def test_the_fake_refuses_a_script_it_does_not_know(self) -> None:
        result = bounded_run.run_bounded(
            [str(self.path / "bash"), str(_FAKE), "-e", "anything else"],
            timeout=_RUN_TIMEOUT_S,
            env={"PATH": str(self.path)},
        )
        self.assertEqual(result.returncode, 1)
        self.assertIn("not a script this sample answers", result.stderr)

    def test_the_fake_is_executable(self) -> None:
        self.assertTrue(os.access(_FAKE, os.X_OK))


# The tool refuses every platform but macOS before it reads anything (exit 2), so the
# block's run can write a baseline only there; the export's suite runs on other hosts too.
@unittest.skipUnless(sys.platform == "darwin", "the tool runs only on macOS")
class SamplesTest(ScratchCase):
    """What the README's block prints and writes, on macOS, where the tool runs."""

    def test_the_block_writes_the_expected_baseline_and_says_so(self) -> None:
        result = self.run_block(_SAMPLES)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, STDOUT)
        self.assertEqual(result.stderr, STDERR)
        expected = json.loads(_EXPECTED.read_text(encoding="utf-8"))
        written = json.loads(self.written_path().read_text(encoding="utf-8"))
        assert isinstance(written, dict)
        self.assertIn(_VARYING, written)
        self.assertEqual(_without_varying(written), _without_varying(expected))

    def test_the_expected_file_is_what_the_tool_writes_byte_for_byte_but_one_line(
        self,
    ) -> None:
        result = self.run_block(_SAMPLES)
        self.assertEqual(result.returncode, 0, result.stderr)
        expected = _EXPECTED.read_text(encoding="utf-8").splitlines()
        written = self.written_path().read_text(encoding="utf-8").splitlines()
        differing = [pair for pair in zip(expected, written) if pair[0] != pair[1]]
        self.assertEqual(len(expected), len(written))
        self.assertEqual(len(differing), 1)
        self.assertIn(f'"{_VARYING}"', differing[0][0])


if __name__ == "__main__":
    unittest.main()
