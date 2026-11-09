# tag_refresh.py

Make Music.app reread the tags of MP3s whose tags changed on disk, so the lyrics, titles, and
album names it shows are the files' own again. macOS only.

## Why it exists

Music.app keeps its own copy of each track's tags and does not notice a tag rewritten by
another tool (`lyricsmith album`, say) until it is told to `refresh` the track. The script this
replaces refreshed every track of the library with one `osascript` call per track and no
timeout. Measured on a library of about 21,000 file tracks, 12 tracks refreshed in one call
took 0.32 s and in 12 separate calls 2.1 s, so the one-call-per-track form costs about an hour
a library.

This tool batches instead. `--whole-library` refreshes 500 tracks a call: tracks 101 to 600
took 4.04 s in one call on the same library, about 8 ms a track; a real whole-library run took about 4 minutes
20 seconds, about 12 ms a track. Explicit mode refreshes only the files you name, with two calls an album folder.
Every call is bounded, and a run that meets a timeout stops rather than queueing behind it.

The lyrics tools never call it: they write the paths they changed to a plain list file
(`--changed-list`), and this tool reads that list with `--tracks-from`, so they learn nothing
of Music.app.

## Prerequisites

- **macOS**, where Music.app and `osascript` exist. Anywhere else a run exits `2` with one
  line before it reads anything.
- **Music.app already running.** The tool asks `application "Music" is running`, which
  answers without launching it, before it says anything else to Music; when Music is not
  running it exits `2` and asks you to open it. The tool never launches Music itself, but
  if Music quits mid-run, the next call's `tell` block relaunches it.
- **The automation permission** for the terminal that runs it, to control Music (System
  Settings > Privacy & Security > Automation). The first run asks for it; refused, each call
  fails: in explicit mode each album folder reports the error, and under `--whole-library`
  the count fails, reported as `error: counting the file tracks: <reason>`.
- **Optional: the project's `refresh_tags` extra** (`pip install ".[refresh_tags]"` from the project
  root), for mutagen, so explicit mode can ask Music for each MP3's album tag too (see
  "The names asked for"). The tool runs without it.

## Usage

```text
tag_refresh.py --whole-library [--dry-run]
tag_refresh.py [--track <mp3> ...] [--album <dir> ...] [--tracks-from <file|->] [--dry-run]
               [--missing-list <file>]
```

| Option | Default | Description |
| --- | --- | --- |
| `--whole-library` | off | Refresh every file track Music.app holds, in batches. Refused with any other source. |
| `--track` | none | One MP3 to refresh; repeatable. |
| `--album` | none | Every MP3 under this folder, hidden folders skipped, so a multi-disc album's disc folders count; repeatable. |
| `--tracks-from` | none | A list file (the contract below); `-` reads standard input. Given once. |
| `--dry-run` | off | Do everything but refresh: count the batches, or look up and match the named files and report what would be refreshed. |
| `--missing-list` | none | Explicit mode only: after the run, write the MP3s reported `not in Music` to this file, one path a line (below). Left out, no file is written. |

Exactly one mode is required: `--whole-library`, or at least one of the three explicit
sources. Neither, or `--whole-library` with a source, is a usage error, exit `2`.
`--tracks-from` is given once, since a run reads one list: a second `--tracks-from` is a
usage error too, rather than a list dropped without a word.

## The two modes

**`--whole-library`** counts the library's file tracks in one call, then refreshes
`file tracks i thru j of library playlist 1` in one call per batch of 500, with a progress
line per batch on stderr. It looks nothing up. A track added to or removed from the library
during the run shifts the later indexes, so one track may be refreshed twice or missed once;
the next run catches it.

**Explicit mode** refreshes the MP3s that `--track`, `--album`, and `--tracks-from` name.
The sources combine, and each file counts once, however many times and by whichever paths it
is named: they are united by device and inode. The MP3s are grouped by their folder, and for
each album folder the tool makes two calls:

1. **Look up.** Every file track whose album is one of the folder's names (below), each
   answered as its `id`, persistent ID, and file path.
2. **Refresh by id.** Each matched track by direct `track id N`, refreshed only when its
   persistent ID is still the one the lookup answered; a track whose ID changed, or that is
   gone, is counted `stale` and never refreshed blind.

A row is matched to a named MP3 by the device and inode its path stats to, never by the path
text: Music answers the resolved path (an iCloud Drive library's real location, say), which is
rarely the path you typed. A named MP3 that no row matches is reported `not in Music`,
which is not an error: it may simply not be in the library.

## The list file contract

`--tracks-from` reads, and the lyrics tools' `--changed-list` writes, this format. This doc
owns it; theirs point here.

- UTF-8, one absolute MP3 path per line, each line ended by a linefeed (`\n`).
- Blank lines are skipped.
- A relative path, a path that is not a file or not an MP3, a line that is not UTF-8, a line
  holding a NUL, and a line ended by a carriage return (a list saved with CRLF endings) are
  each reported on stderr by line number and skipped, never fatal; the run exits `1`.
- **A last line with no linefeed is reported and not read**, as a line a writer stopped in the
  middle of. An editor that leaves off the final newline therefore loses the last path: end
  the file with a linefeed.
- A list file that cannot be read at all ends the run with exit `2` before Music is asked
  anything.
- A path holding a linefeed cannot be written in this format, so a writer reports such a
  track instead of writing it.

Each skipped input is one stderr line, naming where it came from:

```text
--tracks-from changed.txt, line 3: relative/01 a.mp3: not an absolute path
--tracks-from -, line 4: not UTF-8
--track: /path/to/cover.jpg: not an MP3
--album: /path/to/Empty Folder: holds no MP3
```

A folder that `--album` reaches a second time through a link is reported too, and is walked
once; it does not change the exit code.

## The missing list

`--missing-list FILE` writes every MP3 an explicit run reported `not in Music` to `FILE`, in
the list format above, in report order, so the list can be read back with `--tracks-from`
once the files are in Music, or handed to whatever repairs them. A dry run writes it too; a
run with nothing missing writes an empty file; a run stopped by a timeout or Ctrl-C writes
what it found before the stop. A path holding a linefeed cannot be written in the format,
so it is reported on stderr instead.

**Nothing is ever added to Music.app.** A file Music lacks may be half of a copy that never
finished, and importing it would turn a visible mistake into a broken album in the library;
the list leaves that to a person. `library_audit` (`../library_audit/library_audit.md`)
looks for the same class of mistake across a whole library folder.

**The list is the library's own data**, so it never belongs in a repository. The option is
refused, exit `2` before Music is asked anything, when `FILE`'s folder does not exist or lies
inside a git working tree (a `.git` entry in that folder or any folder above it, symbolic
links resolved), and with `--whole-library`, which reports no file as not in Music. The file
is written to a temporary file beside it and renamed over it (`src/report_file.py`), so a
reader never sees half a list; one that cannot be written is reported, and the run exits `1`.
The refusal is asked again just before the write, since the folder may have changed during
the run; refused then, the list is not written, and that is reported as a failed write.

## The names asked for

Explicit mode asks Music for every album whose name is one of these, for each MP3 of the
folder:

- the MP3's folder name, and its parent folder's name, so a `Disc 1` folder's album is
  asked for by the album folder's name;
- its album tag (`TALB`), when mutagen imports.

A wrong name only finds nothing, so every plausible one is asked. Every name travels to the
script as an argument, never spliced into its text. Without mutagen, an album whose tag
differs from its folder names is not found, and its files are reported `not in Music`; the
report then ends its `not in Music` list with a hint to install the `refresh_tags` extra.

## Bounds, and why a timeout ends the run

Every call carries two bounds:

- **30 s inside the script** (`with timeout of 30 seconds`). It is a bound per Apple event,
  not per call: when one event's reply is late, the script gets error -1712 and stops, but
  Music goes on working on the request.
- **35 s on the whole call**, enforced by killing `osascript` through `bounded_run`, which
  covers an `osascript` that never returns and a call whose many events each finish under 30
  s yet add up past it.

The slowest call worth making was measured well under both, on a library of about 21,000
file tracks: a 500-track batch took 4.04 s, and 12 tracks by direct `track id` 0.58 s. What
they guard against is the event that never answers: on the same library, a lookup `whose
location is` one file gave no answer in 120 s.

**A timeout ends the run.** Killing `osascript` does not stop Music: after a killed call it
stayed busy for about 20 s more, so the next call would queue behind the abandoned one.
The report names what was not refreshed: the track range from the batch that timed out to the
last track for `--whole-library`, and the album folder in hand and every later one for
explicit mode. A folder whose refresh call timed out is reported as
`stopped (may be partly refreshed)`, not as untouched, because Music may already have refreshed
some of its tracks; run it again to be sure. Any other failed call is local: that batch or album folder reports its error
and the run goes on.

**A timeout on the very first call, every run, is usually a locked session, not a dialog.**
While the login session is locked, Music answers no Apple event at all, even `get player
state`, and sits idle at no CPU, which looks from outside exactly like a hidden modal dialog.
Seen once: every call timed out with -1712 for hours, and the first call after logging in and
bringing Music forward answered at once. So a run needs a logged-in session; before hunting
for a dialog, check whether the session is locked.

## The report

The report goes to stdout; progress (one line per batch or album folder) and every skipped
input go to stderr. `--dry-run` says `would refresh` where a run says `refreshed`.

`--whole-library`, a run that stopped at a timeout in its third batch:

```text
whole library: refreshed 1000 of 21000 file tracks in 42 batches
not refreshed (stopped): tracks 1001-21000
stopped at a timeout: osascript did not finish within 35 s and was killed; Music may still be busy
total: refreshed 1000 of 21000 file tracks
```

A failed batch adds an `error: tracks 501-1000: <reason>` line, and a count that failed an
`error: counting the file tracks: <reason>` line.

Explicit mode, one row per album folder, then the files not found, then the total:

```text
/path/to/Artist/First Album: refreshed 12
/path/to/Artist/Second Album/Disc 1: refreshed 9, stale 1
/path/to/Artist/Second Album/Disc 2: refreshed 0, not in Music 1
/path/to/Other/Third Album: error: <the failed call's reason>
not in Music:
  /path/to/Artist/Second Album/Disc 2/01 Bonus.mp3
total: refreshed 21, not in Music 1, stale 1, errors 1, stopped 0 (album folders 4, MP3s 24)
```

A row is `refreshed N`, followed by `not in Music K`, `stale K`, and `unparsed rows K` when
each is not zero; or `error: <reason>` for a failed call; or `not refreshed (stopped)` for a
folder a timeout or Ctrl-C left; or `stopped (may be partly refreshed)` for the folder whose
refresh call the timeout or Ctrl-C interrupted, since Music goes on working on an abandoned
request. An `unparsed rows` count is a reply line in none of the
lookup's shape, which matches nothing. A stop adds its `stopped ...` line before the total.
Names are printed with each control character as a visible `\xNN` escape, so no name can
split a row or drive the terminal.

## Exit codes

| Code | Meaning |
| --- | --- |
| `0` | Everything asked for was refreshed, or reported `not in Music`. |
| `1` | A call failed, a track was stale, the run stopped at a timeout before the end, a named input could not be used (not a file, not an MP3, an album holding no MP3, an unreadable folder, a bad list line), or the missing list could not be written. A folder reached twice through a link is reported and does not count. |
| `2` | Could not start: not macOS, Music.app not running or the probe unanswered, bad options, nothing to refresh, an unreadable list file, or a `--missing-list` inside a git working tree or in a folder that does not exist. |
| `130` | Ctrl-C: the report covers the calls that finished before it, wherever in the run it is pressed. It prints no report only when pressed before the run's first call after the probe: while collecting, during the probe, or while reading album tags. |

## Tests

`test_tag_refresh.py` runs every suite in `tests/`. None reaches Music.app, the real
library, the network, or anything outside a temporary directory: every call goes through a
fake runner that plays `osascript` from an invented library and records each argument list,
so a suite asserts that the `is running` probe came first, that no name appears in any script
body, and that a dry run made no refresh call.

**The live read-only test**, `tests/test_live_lookup.py`, is the one exception, and it skips
unless you ask for it. It makes exactly one lookup against the real Music.app, for an album
folder you name, and asserts that a row matches one of its MP3s by inode; it never refreshes
anything. It runs only on macOS, with Music.app running, `APPLE_MUSIC_TOOLBOX_OFFLINE` unset, and
`TAG_REFRESH_LIVE_ALBUM` naming an album folder whose folder name is the album's name
in Music:

```bash
TAG_REFRESH_LIVE_ALBUM="$HOME/Music/Albums/<artist>/<album>" \
  python tests/test_live_lookup.py
```

No live refresh is automated: refreshing a real library is left to a person.

## The hand check

`samples/README.md` runs both explicit forms with `--dry-run` over a small tree of zero-byte
placeholder MP3s, on a Mac with Music open: every file is reported `not in Music`, exit `0`,
and nothing is refreshed. To check the tool against your own library, start with a dry run:

1. `tag_refresh.py --album <an album folder> --dry-run`: the row should say
   `would refresh` the album's track count, with nothing `not in Music`.
2. The same without `--dry-run`, then check the album in Music.app.
3. `tag_refresh.py --whole-library --dry-run` counts the batches; without
   `--dry-run` it took about 4 minutes 20 seconds for a library of about 21,000 tracks.
