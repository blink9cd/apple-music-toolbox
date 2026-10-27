# apple-music-toolbox

Tools that work against Apple Music on macOS, through Music.app's own scripting
dictionary: what was added most recently, how many of an album's tracks are favorited,
making Music.app reread the tags another tool changed, and finding where a library folder and
Music.app disagree. One more, `phone_audit`, reads a Finder-synced iPhone over USB instead,
with Homebrew's libimobiledevice, to find tracks the phone lists with no file behind them.
Python, no server, no build step -- each tool is run by hand.

## What this is

One folder per tool or shared library, each carrying its own code, companion doc and tests:

| Folder | What it is |
| --- | --- |
| `recently_added/` | The library that asks Music.app for its most recently added albums, by its own "date added": the AppleScript query, the `AlbumRef` type and the subprocess seam. `album_stats` imports it. No CLI, never run directly. |
| `album_stats/` | `album_stats.py` reports one album's track count, favorited-track count and year tag, asked of Music.app. A CLI. |
| `tag_refresh/` | `tag_refresh.py` makes Music.app reread the tags of MP3s whose tags changed on disk: every file track of the library in batches (`--whole-library`), or only the MP3s named by `--track`, `--album` or a list file (`--tracks-from`), such as the one lyricsmith's `album` and `sweep` write with `--changed-list`. Every call to Music.app is bounded, it never launches Music.app itself (a call made after Music quits mid-run relaunches it), and `--dry-run` refreshes nothing. macOS only. A CLI; see `tag_refresh/tag_refresh.md`. |
| `library_audit/` | `library_audit.py` compares a library folder's audio files with Music.app's file tracks, read-only: files with no track, tracks whose file is gone, track-number gaps, and album folders whose files and tracks differ in count. It reads Music.app through `tag_refresh/src/`'s calls and never writes to it. macOS only. A CLI; see `library_audit/library_audit.md`. |
| `phone_audit/` | `phone_audit.py` finds the tracks a Finder-synced iPhone lists with no file behind them, and the ones whose file is not the size the phone's database expects, read-only. It reads the phone over USB through Homebrew's `afcclient`, allowlisted to reads, copies the music database twice and compares the copies, and never uses Music.app. Proven on macOS. A CLI; see `phone_audit/phone_audit.md`. |

Each folder's `<name>.md` records why it works the way it does -- the option reference, the exit
codes, and the field evidence behind the choices. `recently_added/recently_added.md` is the one
to read first: why Music.app's own "date added" is trusted over a library folder's filesystem
timestamps is the reasoning the whole project turns on.

Five small libraries sit beside them, vendored whole with their own tests and docs:
`stdio_utf8` (UTF-8 on each tool's own output streams), `help_formatter` (live defaults in
`--help`), `html_page` (the HTML pages' shared frame, and the escape every report shows a
name through), `bounded_run` (a captured subprocess timeout that still holds when the child spawns
children of its own) and `live_pid_guard` (the cleanup `bounded_run`'s live tests owe).

A module reaches its siblings at one fixed place on `sys.path`: directly under the project
root, derived from the module's own `__file__`. See `stdio_utf8/stdio_utf8.md`, "How this
project's tools import it", for why that is one fixed candidate rather than a search up the
ancestors. The core tools import no third-party package, so `dependencies = []` in
`pyproject.toml` is not aspirational. `tag_refresh` and `library_audit` run without
third-party packages, and use `mutagen` from the `refresh_tags` extra when it is installed:
`tag_refresh` to ask Music.app for each named MP3's album tag too, and `library_audit` to
read the tags its track-number and album checks compare.

Another Apple Music tool lands here as a **sibling folder**, with nothing reshuffled: no
existing file moves, no existing path changes, and no existing doc citation goes stale.

## Requirements

Python 3.12 or newer for every tool. Beyond it, each needs:

- **`album_stats`** (and the `recently_added` library it imports): macOS and Music.app. Their
  calls go through `osascript` against Music.app's AppleScript dictionary, which exists on no
  other platform.
- **`tag_refresh`**: macOS, Music.app already running, since it never launches it itself, and
  the terminal's permission to control Music.app. `mutagen`, from the optional `refresh_tags`
  extra, adds the album-tag lookup; it runs without it.
- **`library_audit`**: macOS, Music.app already running (it never launches it, and only ever
  reads from it) and the terminal's permission to control Music.app, through `osascript` as
  above. Its tag checks need `mutagen`, from the `refresh_tags` extra, and are skipped without
  it. `--decode` runs `/usr/bin/afconvert`, which ships with macOS.
- **`phone_audit`**: Homebrew's libimobiledevice (`brew install libimobiledevice`), whose
  `afcclient` is its only way to the phone, and the iPhone connected by USB, trusted by this
  Mac and unlocked, with Music closed on it. It never uses Music.app or `osascript`. It has been proven on macOS only,
  though it makes no platform check of its own.

The core tools need the standard library only. The optional `refresh_tags` extra adds `mutagen`
for `tag_refresh` and `library_audit`, and the tests need the `test` extra; each package is
pinned to an exact version under `[project.optional-dependencies]` in `pyproject.toml`. Install
from this repository's root:

```bash
pip install ".[refresh_tags]"   # optional, for tag_refresh and library_audit
pip install ".[test]"           # to run the tests
```

The `test` extra repeats the `refresh_tags` pin, because the `tag_refresh` and `library_audit`
suites import that package. Either step installs the pinned packages and this project's
metadata, and no code: nothing here is imported from an installed location. Each tool is run directly, as below, and
puts its own sibling folders on the import path.

## Running the tools

Run from this repository's root:

```bash
python album_stats/album_stats.py --artist "<artist>" --album "<album>"
python tag_refresh/tag_refresh.py --album "<album folder>" --dry-run
python library_audit/library_audit.py --library "<library folder>"
python phone_audit/phone_audit.py --format json
```

Every CLI states its options, defaults, prerequisites and exit codes in `--help`. Each tool
folder that turns an input into an output ships a `samples/` directory whose README carries a
command you can run by hand and what its result should look like.

## Running the tests

Each folder has one test file at its top that runs its whole suite:

```bash
for suite in */test_*.py; do python "$suite"; done
```

The loop does reach `album_stats/tests/test_live_literal.py`, which compiles and runs real
AppleScript through `/usr/bin/osascript` (it skips itself off macOS).

Several test classes reach the real Music.app. To run everything else on a host without it,
set:

```bash
export APPLE_MUSIC_TOOLBOX_OFFLINE=1
```

One switch covers every live boundary in the project, deliberately rather than one variable
per folder. It skips those classes; it does not fake them, so a run with it set proves less
than a run without it.

`tag_refresh/tests/test_live_lookup.py`, which the loop above also reaches, is opt-in: it
makes one read-only lookup against the real Music.app, which must already be running, and
refreshes nothing. It skips unless `TAG_REFRESH_LIVE_ALBUM` names an album folder whose
folder name is the album's name in Music.app, and it skips off macOS and under
`APPLE_MUSIC_TOOLBOX_OFFLINE` too:

```bash
TAG_REFRESH_LIVE_ALBUM="<album folder>" python tag_refresh/test_tag_refresh.py
```

`phone_audit/tests/test_phone_live.py`, which the loop also reaches, is opt-in the same way:
it runs `phone_audit` once against the real phone, reading only, through the same seam as every
run, and checks only the report's shape. The phone must be connected by USB, trusted and
unlocked. It skips unless `PHONE_AUDIT_LIVE` is `1`, and it skips off macOS and under
`APPLE_MUSIC_TOOLBOX_OFFLINE` too:

```bash
PHONE_AUDIT_LIVE=1 python phone_audit/test_phone_audit.py
```

`library_audit/tests/test_audit_live.py`, which the loop also reaches, is opt-in the same way:
it makes the audit's two calls against the real Music.app, which must already be running,
reading only: the track count, then a listing of at most the first 50 tracks, checked only for
its shape through the audit's own row parser. It skips unless `LIBRARY_AUDIT_LIVE` is `1`, and
it skips off macOS and under `APPLE_MUSIC_TOOLBOX_OFFLINE` too:

```bash
LIBRARY_AUDIT_LIVE=1 python library_audit/test_library_audit.py
```

## License

GNU Affero General Public License v3.0 or later; see `LICENSE`.
