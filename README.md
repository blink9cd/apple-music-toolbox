# apple-music-toolbox

Tools that work against Apple Music on macOS, through Music.app's own scripting
dictionary: what was added most recently, how many of an album's tracks are favorited,
making Music.app reread the tags another tool changed, and finding where a library folder and
Music.app disagree. One more, `phone_audit`, reads a Finder-synced iPhone over USB instead,
with Homebrew's libimobiledevice, to find tracks the phone lists with no file behind them.
Those are Python, with no server and no build step: each is run by hand. The last,
`scrobbler`, is a Swift background app that records what Music.app plays for a listensmith
store on the same Mac, with a Python command line that builds, signs, and installs it.

The scrobbler and `play_count_baseline` pair with listensmith, a listen store that is not
yet published. The record contract they write ships here, as the copy under
`scrobbler/contract/` with its schemas, so any store that implements that contract works
with them. The other tools need no store.

## What this is

One folder per tool or shared library, each carrying its own code, companion doc, and tests:

| Folder | What it is |
| --- | --- |
| `recently_added/` | The library that asks Music.app for its most recently added albums, by its own "date added": the AppleScript query, the `AlbumRef` type, and the subprocess seam. `album_stats` imports it. No CLI, never run directly. |
| `album_stats/` | `album_stats.py` reports one album's track count, favorited-track count and year tag, asked of Music.app. A CLI. |
| `tag_refresh/` | `tag_refresh.py` makes Music.app reread the tags of MP3s whose tags changed on disk: every file track of the library in batches (`--whole-library`), or only the MP3s named by `--track`, `--album`, or a list file (`--tracks-from`), such as the one lyricsmith's `album` and `sweep` write with `--changed-list`. Every call to Music.app is bounded, it never launches Music.app itself (a call made after Music quits mid-run relaunches it), and `--dry-run` refreshes nothing. macOS only. A CLI; see `tag_refresh/tag_refresh.md`. |
| `library_audit/` | `library_audit.py` compares a library folder's audio files with Music.app's file tracks, read-only: files with no track, tracks whose file is gone, track-number gaps, and album folders whose files and tracks differ in count. It reads Music.app through `tag_refresh/src/`'s calls and never writes to it. macOS only. A CLI; see `library_audit/library_audit.md`. |
| `play_count_baseline/` | `play_count_baseline.py` writes Music.app's lifetime play count for every track as one listensmith baseline JSON file, checked against the contract copy under `scrobbler/contract/` before it is written and again after, read-only. It reads Music.app through `tag_refresh/src/`'s calls, never launches it, and never writes to it. macOS only. A CLI; see `play_count_baseline/play_count_baseline.md`. |
| `scrobbler/` | listensmith's Music.app adapter: a SwiftPM package under `scrobbler/app/` that watches what Music.app plays, queues each play as a listensmith record, and sends the queue to the listensmith store and relay on `127.0.0.1`, plus `scrobbler.py`, which builds, signs, installs, uninstalls, and reports on it through a LaunchAgent. It never controls playback, never launches Music.app, and sends nothing beyond the loopback address. `scrobbler/contract/` is a checked copy of the listensmith contract it writes to. macOS 14 or newer. See `scrobbler/scrobbler.md`. |
| `phone_audit/` | `phone_audit.py` finds the tracks a Finder-synced iPhone lists with no file behind them, and the ones whose file is not the size the phone's database expects, read-only. It reads the phone over USB through Homebrew's `afcclient`, allowlisted to reads, copies the music database twice, compares the copies, and never uses Music.app. Proven on macOS. A CLI; see `phone_audit/phone_audit.md`. |

Each folder's `<name>.md` records why it works the way it does: the option reference, the exit
codes, and the field evidence behind the choices. `recently_added/recently_added.md`, for one,
records why Music.app's own "date added" is trusted over a library folder's filesystem
timestamps when deciding what was added most recently.

Small libraries sit beside them, vendored whole with their own tests and docs:
`stdio_utf8` (UTF-8 on each tool's own output streams), `help_formatter` (live defaults in
`--help`), `html_page` (the HTML pages' shared frame, and the escape every report shows a
name through), `bounded_run` (a captured subprocess timeout that still holds when the child spawns
children of its own) and `live_pid_guard` (the cleanup `bounded_run`'s live tests owe). The
scrobbler brings its own: `launchd_agent` (its LaunchAgent, installed and read back), with
`atomic_write`, `bounded_run`, and `os_schedule_gen`, which that library imports; `swift_gate`, the Swift
gate whose signing reader and redaction the scrobbler's build reuses, with `pyproject_config`
and `venv_prune`, which it imports; and `tool_subdirs`, the folder conventions some of those
suites import.

A module reaches its siblings at one fixed place on `sys.path`: directly under the project
root, derived from the module's own `__file__`. See `stdio_utf8/stdio_utf8.md`, "How this
project's tools import it", for why that is one fixed candidate rather than a search up the
ancestors. `launchd_agent`, which also ships in a layout with a `utilities/` folder, looks
in its own folder and the one above it, here the root, and never higher. The core tools
import no third-party package, so `dependencies = []` in `pyproject.toml` is not
aspirational. `tag_refresh` and `library_audit` run without
third-party packages, and use `mutagen` from the `refresh_tags` extra when it is installed:
`tag_refresh` to ask Music.app for each named MP3's album tag too, and `library_audit` to
read the tags its track-number and album checks compare. `play_count_baseline` is the one
tool that needs a third-party package to run at all: `jsonschema`, from the optional
`contract` extra, without which it exits 2 before reading anything.

Another Apple Music tool lands here as a sibling folder, with nothing reshuffled: no
existing file moves, no existing path changes, and no existing doc citation goes stale.

## Requirements

Python 3.12 or newer for every tool (see Install below). Beyond it, each needs:

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
- **`play_count_baseline`**: macOS; Music.app already running (it never launches it, and
  only ever reads from it); the terminal's permission to control Music.app, through
  `osascript` as above; and the `contract` extra, which holds `jsonschema`.
- **`scrobbler`**: macOS 14 or newer, Music.app, and the Swift toolchain (Xcode or the
  Command Line Tools, Swift 6 or newer) to build the app. Installing it also needs a
  code-signing identity, named in a signing setting outside this checkout, and a
  listensmith store and relay running on this Mac to receive what it sends; the build and
  its tests need neither. `scrobbler/scrobbler.md` has the signing setting and every step.
- **`phone_audit`**: Homebrew's libimobiledevice (`brew install libimobiledevice`), whose
  `afcclient` is its only way to the phone, and the iPhone connected by USB, trusted by this
  Mac, and unlocked, with Music closed on it. It never uses Music.app or `osascript`. It has
  been proven on macOS only, though it makes no platform check of its own.

## Install

Needs Python 3.12 or newer. Install into a virtual
environment, because Homebrew and Debian Python refuse a
system-wide `pip install`:

```bash
python3 -m venv .venv
# shellcheck source=/dev/null # the activate script exists only once the line above has run
source .venv/bin/activate
pip install '.[refresh_tags]'
```

The commands below assume the venv is active, so `python`
is the venv's interpreter.

The `refresh_tags` extra is optional: it adds `mutagen` for `tag_refresh` and `library_audit`,
and every other tool needs the standard library only. To run the tests, install the `test`
extra into the same venv as well:

```bash
pip install '.[test]'
```

The `contract` extra holds `jsonschema` and the packages it needs, which validate against
the scrobbler's contract copy: the scrobbler's tests check that copy and the records its Swift
tests build with them, and `play_count_baseline` imports them at runtime, to check every
baseline it writes. `pip install '.[contract]'` installs just that set.

Each package is pinned to an exact version under `[project.optional-dependencies]` in
`pyproject.toml`. The `test` extra repeats the `refresh_tags` pin, because the `tag_refresh` and
`library_audit` suites import that package, and the `contract` set, for the same
reason. Either step installs the pinned packages and this
project's metadata, and no code: nothing here is imported from an installed location. Each tool
is run directly, as below, and puts its own sibling folders on the import path.

## Running the tools

Run from this repository's root:

```bash
python scrobbler/scrobbler.py status
python album_stats/album_stats.py --artist "<artist>" --album "<album>"
python tag_refresh/tag_refresh.py --album "<album folder>" --dry-run
python library_audit/library_audit.py --library "<library folder>"
python play_count_baseline/play_count_baseline.py --output "<new file outside any checkout>"
python phone_audit/phone_audit.py --format json
```

Every CLI states its options, defaults, prerequisites, and exit codes in `--help`. Each tool
folder that turns an input into an output ships a `samples/` directory whose README carries a
command you can run by hand and what its result should look like.

## Running the tests

Several test classes reach the real Music.app. To run everything else on a host without it,
set this first:

```bash
export APPLE_MUSIC_TOOLBOX_OFFLINE=1
```

One switch covers every live boundary in the project, deliberately rather than one variable
per folder. It skips those classes; it does not fake them, so a run with it set proves less
than a run without it.

Each folder has one test file at its top that runs its whole suite:

```bash
for suite in */test_*.py; do python "$suite"; done
```

The scrobbler's Swift package has tests of its own, which the loop does not run:

```bash
swift test --package-path scrobbler/app --scratch-path "$(mktemp -d)"
```

The outside `--scratch-path` keeps SwiftPM's `.build` out of the clone.

They cover its core with fakes for Music.app, the scheduler and the transport, and reach no
real host. The golden records they compare byte for byte are committed under
`scrobbler/contract_built/` and `scrobbler/status_built/`, and the loop's scrobbler suites
check the same files from the Python side, so the two halves can run in either order.

The loop does reach `album_stats/tests/test_live_literal.py`, which compiles and runs real
AppleScript through `/usr/bin/osascript` (it skips itself off macOS). It sends nothing to
Music.app, so the switch above does not skip it.

`album_stats/tests/test_live_star_rating.py`, which the loop also reaches, needs no opt-in: it
sends one read-only star-rating query to the real Music.app, but only when Music.app is already
running. It first asks `application "Music" is running`, which names Music outside any `tell`
block and so never launches it, and skips when the answer is anything but `true`. It skips off
macOS and under `APPLE_MUSIC_TOOLBOX_OFFLINE` too.

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
run, and checks only the report's shape. The phone must be connected by USB, trusted, and
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

`play_count_baseline/tests/test_baseline_live.py`, which the loop also reaches, is opt-in the
same way: it runs the whole tool once against the real Music.app, which must already be
running, reading only, into a temporary folder outside every checkout, and checks only that it
exits 0 and that the file validates. It skips unless `PLAY_COUNT_BASELINE_LIVE` is `1`, and it
skips off macOS and under `APPLE_MUSIC_TOOLBOX_OFFLINE` too:

```bash
PLAY_COUNT_BASELINE_LIVE=1 python play_count_baseline/test_play_count_baseline.py
```

Three more switches are opt-in, and the offline switch above does not cover them:

- `SCROBBLER_LIVE=1` turns on the scrobbler's live smoke test, which drives the real
  Music.app through the app's live layer, reading only. `scrobbler/scrobbler.md`, *The live
  smoke test*, has the command and the two runs it needs.
- `SCROBBLER_REGOLD=1` is not a live test: it makes the Swift tests rewrite the golden files
  they compare against, after a deliberate change to a record. Leave it unset otherwise.
- `LAUNCHD_AGENT_LIVE=1` turns on `launchd_agent`'s live test, which installs a throwaway
  agent in the real launchd, reads it loaded, and removes it. `launchd_agent/launchd_agent.md`
  has the command.

To type-check, run mypy over one top-level folder at a time, never over the repository root:
`_fixtures.py` and `test_cli.py` are each shipped by more than one folder, so a run over the
root refuses them as duplicate modules.

## License

GNU Affero General Public License v3.0 or later; see `LICENSE`.
