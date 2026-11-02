# recently_added

The `count` most recently added albums per Apple Music's own "date added", read
through the app's supported AppleScript API. This module holds only the parsing and
orchestration logic; it has no CLI of its own and is never run directly.
`album_stats.py` here imports its subprocess seam. `album_scan.py`, in the media_feeds
project, imports the query and decides, via `--source`, whether to use it alone
(`music`), try it first and fall back to the folder scan (`auto`), or skip it
(`folder`); see `album_scan.md`'s "Why the folder scan's date is a heuristic".

## Why this exists, and why it lives in its own folder

Ranking albums by the library folder's filesystem birth time is wrong on a real
library. Against its three most-recently-added albums, Apple Music's own "date added"
reproduced the correct order exactly, while the folder scan missed one of them
entirely: its folder's birth time read months earlier than Music's "date added" (a
re-materialization stamp from iCloud Drive, not the date the album was added;
`~/Music/Albums` is the same directory, verified by inode+device, as its iCloud Drive
counterpart), and Music was right. Neither filesystem stamp (birth time or `st_mtime`)
is trustworthy on a synced library; Music.app's own ledger is, and it is reachable
through a supported, testable API. `~/Music/Library.musicdb`, Apple's undocumented
binary format, is ruled out: building on it would mean depending on a guessed wire
contract with no way to exercise it under test.

It lives in its own `recently_added/` folder, not as a second file inside
`album_stats`, because more than one tool imports it, and it carries its own tests and
doc: `album_stats.py` (`Runner` and `_real_run`), and media_feeds' `album_scan.py`
(the date source and the `Runner` seam), only under `--source music` or `auto`.
`album_stats.py`, a sibling in this project, finds it at one fixed place on
`sys.path`: a folder directly under the project root.
`album_scan.py` locates this whole project at run time (`--toolbox`, the
`APPLE_MUSIC_TOOLBOX` variable, or a bounded upward search), as its own
`album_scan.md` documents under "Finding the toolbox".

`AlbumRef`, the `(artist, album, added: date)` triple this module answers in, is
defined here, beside the query that produces it. media_feeds' `album_scan` and
`cover_art` keep their own copy of it, so neither published project needs the other.

## Rows are per-track; the collapse to per-album happens here

Music.app has no per-album "date added": the AppleScript emits one row per track, an
ISO-8601 timestamp plus the album artist and album. `_rank_albums` groups those rows by
`(artist, album)` before ranking, keeping each group's newest track time as that
album's added date, then sorts and slices to `count`. This collapse is a correctness
fix, not an optimization. A single running maximum over tracks is no substitute: it
looks right only at a result of size one, where a duplicate cannot appear, because
whichever track is newest simply carries its album. The moment `--count` asks for more
than one, a freshly-added twelve-track album would otherwise fill every slot with
copies of itself, since every one of its rows carries a timestamp newer than anything
else in the library.

## What a row may claim

The AppleScript concatenates each tag's text unescaped between its `tab` and
`linefeed` delimiters, so a tag can carry anything, including the row terminator. A
tag holding a line break followed by a `date<TAB>artist<TAB>album` triple therefore
reads as a second row, one whose every field the tag's author chose; dated far enough
in the future, it ranked as the newest album forever, ahead of every real addition.
`_rank_albums` closes that in Python alone (the AppleScript is unchanged, because only a
live run against Music.app could validate a script change):

- **Rows end at a linefeed and nothing else.** The script emits `linefeed`, so that is
  the only row terminator honored; `str.splitlines`, which the parser used before, also
  breaks a string at a form feed, a vertical tab, the ASCII separator controls, the C1
  NEL, and U+2028/U+2029, so a legitimate name holding one was cut there and its tail
  read as a malformed row.
- **A row holding a NUL is skipped.** No real tag carries one, and a name with one in
  it cannot be handed to a subprocess at all: the per-album counts query built from it
  would be refused before it ran.
- **A row dated more than one day past `today` is skipped.** A track cannot have been
  added tomorrow. The one day of slack exists because Music.app's ISO date is local time
  with no offset, so a track added late in the evening can read as "tomorrow" to a run
  whose own clock sits in another zone.

What this removes is the one power an injected row adds (a date its author picks),
and no more: the text-mode capture turns CR and CRLF into LF before the parser sees
them, so a CR or LF inside a tag still ends a row, and the text a forged row carries
is text a crafted tag could already have carried on its own.

## What it does

- `newest_albums_from_music(count, *, run=_real_run, timeout=_MUSIC_TIMEOUT_SECONDS,
  today=None)`: the `count` most recently added albums per Music.app's own "date
  added", newest first. It never raises: Music.app absent, not running, not scriptable, automation
  permission denied, a timeout, a non-zero `osascript` exit, empty output, and output
  with no parseable line all come back as `[]`. A single malformed line, or one with
  an empty artist/album (an unset field, not a parse failure; see `_rank_albums`),
  is skipped rather than failing the whole answer. This mirrors
  `cover_art.artwork_url`'s never-raises contract, for the identical reason: the
  caller decides what "no answer" means, not this function via an exception. Returns
  fewer than `count` when Music.app names fewer distinct albums than that: a short
  answer, not an error. The timeout default is `_MUSIC_TIMEOUT_SECONDS` in
  `recently_added.py`, sized from the live measurement recorded beside it; it is
  not restated here (this module has no CLI, so there is no `--help` to point at),
  because a restated number would drift silently. `today` is
  the date a row's "date added" is judged against (see "What a row may claim"
  above); `None`, the default, reads the current date when the function runs, and a
  test injects a fixed one.
- `Runner`: the `(argv, timeout_seconds) -> subprocess.CompletedProcess[str]`
  injection seam, like `cover_art.py`'s `Fetcher`. `_real_run` does not
  call `subprocess.run` directly. It delegates to `bounded_run.run_bounded`, because
  a capturing `subprocess.run(timeout=...)` reads as bounded and is not (on expiry
  CPython kills only the direct child, then blocks re-reading pipes a surviving
  grandchild still holds open). Every unit test in `test_recently_added.py`
  injects a fake `run` instead of exercising either, so nothing there spawns a real
  `osascript` process or touches Music.app.
- The AppleScript itself asks Music.app for every track added within the lookback
  window `_MUSIC_LOOKBACK_DAYS` sets, and emits one `date<TAB>album artist<TAB>album`
  line per track. Music.app has no per-album "date added"; the newest track's stamp
  is what this tool means by "when the album was added". The date is coerced to
  `«class isot»`, AppleScript's ISO-8601 string form, specifically so the Python side
  gets one fixed shape it can full-match and parse, and ranks by the parsed value.
  `as string` alone produces a locale-dependent form ("Thursday, March 15, 2001 at
  11:00:33 PM") that must never be parsed.

## Usage

Not a standalone CLI. `album_stats.py` here imports its `Runner` and `_real_run`, and
`album_scan.py`, in the media_feeds project, imports the query and owns deciding the
source (`--source auto|music|folder`) and doing anything with the result.

## Testing

`test_recently_added.py` (same folder) exercises `newest_albums_from_music` against
a fake `run`, covering every failure branch listed above plus the collapse-then-rank
logic: an album's many rows collapsing to one entry when `count` asks for three, an
album taking its newest track's time (not its oldest, and not the first row
encountered) as its added date in both row orders, and results coming back
newest-album-first. It pairs with this module by the ordinary same-directory
`<name>.py` / `test_<name>.py` naming convention. The one thing this suite cannot
prove, that the AppleScript itself still means what this module assumes about
Music.app's real dictionary, is the job of album_scan's `test_live_music.py` in the
media_feeds project: a live smoke test at the process boundary, run against the real
`osascript`, that skips when it cannot reach Music.app.

It ships no `samples/` directory: a pure library with no CLI, whose "output" is a
Python value or an empty list, never a file, so there is no input-to-output pair a
samples directory could show.
