# phone_audit.py

Find the tracks a Finder-synced iPhone lists with no audio file behind them, and the ones
whose file is not the size the phone's own database expects. It reads the phone over USB
through `afcclient`, from Homebrew's libimobiledevice, and never uses Music.app.
**Read-only**: it never writes to the phone, and every copy it makes goes to a private
temporary folder that is removed when the run ends.

## Why it exists

A track can stay in the phone's music database after its file there is gone. The phone
lists it, and it will not play. A Finder sync copies only what the phone lacks, and a phone
that lists the track does not lack it, so the row survives every sync. Music.app cannot see
a synced phone at all, so `library_audit` and every other Mac-side check miss it. The only
place the fault shows is on the phone: its database, and the folders its audio sits in.

This tool reads both and lists what disagrees, for a person to act on (see *Repairing a
row with no file*).

## Prerequisites

- **Homebrew's libimobiledevice** (`brew install libimobiledevice`), which provides
  `afcclient`. The tool has been proven on macOS only, though it makes no platform check
  of its own. It looks `afcclient` up on `PATH`; when it is missing a run exits `2` with
  one line naming the install.
- **The iPhone connected by USB, trusted by this Mac, and unlocked.** The pairing a Finder
  sync already uses is enough: no sudo, no extra permission, no developer mode. Whether the
  phone can be read while locked is unknown, so unlock it. With no device, a lockdown
  refusal or a call that does not answer in time, a run exits `2` with one line saying to
  connect the phone and unlock it.
- **Music closed on the phone,** so the database holds still while it is copied (see *The
  copy checks*).
- Python 3.12 or later, standard library only.

### The proven version

Homebrew pins libimobiledevice by formula, not by a lockfile, so the installed `afcclient`
can change under the tool. Every output format it parses was read from the source of
`afcclient` 1.4.0, and each run asks `afcclient -v` first. Another version, or one that
cannot be read, prints one warning line on stderr and the run goes on: a changed format
then shows as unparsed listing lines or a refused database, never as a silent miss.

## Usage

```text
phone_audit.py [--format text|json|html] [--report <file>] [--udid <UDID>]
```

| Option | Default | Description |
| --- | --- | --- |
| `--format` | `text` | The report's form: `text`, by section; `json`, the same content as one object; or `html`, one page of tables, which needs `--report` (all below). Never inferred: `--report phone.html` alone writes text. |
| `--report` | none | Write the report to this file instead of stdout, replaced whole. Refused, exit `2` before any work, when its folder does not exist or lies inside a git working tree; asked again just before the write. Required by `--format html`. |
| `--udid` | none | The phone to read when more than one is connected, passed as `-u UDID`. Left out, `afcclient` reads the only one. |

## What it reads, and the read-only guarantee

1. `afcclient -v`, for the version check.
2. `/iTunes_Control/iTunes/MediaLibrary.sqlitedb` and its `-wal` and `-shm` files, copied
   to this Mac twice.
3. `ls -l /iTunes_Control/Music`, for the sync folders that exist (folders named `F` and
   two digits), then `ls -l` of each.

**Why the paths start at `/iTunes_Control`.** The AFC service is jailed: its `/` is the
device's `/var/mobile/Media`, and `afcclient` starts every session there. So the
database the device keeps at `/var/mobile/Media/iTunes_Control/iTunes/` is
`/iTunes_Control/iTunes/` over AFC, and the device-absolute form is not found
(`Error: Failed to list '<path>': Not found (8)`). The jail-relative form was confirmed
against a real phone on 2026-10-26. The tests' fakes serve only these paths, so a return
to the device-absolute form fails them.

**The seam.** `src/afc_calls.py` is the only module that builds an `afcclient` argument
list or starts it. Its `ALLOWED_COMMANDS` holds `ls` and `get` (which copies from the
phone to the Mac), and any other command, or `get`'s `-f` (overwrite) and `-r`
(recurse), raises before a process exists. A test pins the set's exact value, and the CLI
suites check every argument list a run sent. A command's own flags go after `--`
(`afcclient -- ls -l <dir>`), or `afcclient`'s own option parser reads them as its own.

**Why the seam reads stdout, not only the exit code.** A failed `afcclient` command still
exits `0`; its error is one stdout line starting `Error:` (`Error: Failed to list
'<path>': <reason> (<n>)`). Only a connection failure exits non-zero (`1`, with its reason
on stderr), and a bad option exits `2`. So a call fails on any exit but `0` or on any
stdout line starting `Error:`; trusting the exit code alone would read a failed listing as
an empty folder, and report every row in it as having no file. A large copy prints a
progress line redrawn with carriage returns, which is not an error. A phone unplugged
mid-command is said on stdout too, a `[disconnected]` line and exit `0`; the seam treats
that line as an unreachable phone, exit `2` with the connect-and-unlock line. A path the
phone lacks is recognized by its error code, `(8)`, not by the words before it.

Every call has its own bound, a named constant in `afc_calls.py`: a copy of the database
gets longer than a listing. With no phone connected `afcclient` exits at once; with
`--udid` and only a different phone connected, it waits for the one named, so the first
call runs out its whole bound (`GET_TIMEOUT_S`) before the run exits `2`. The bound is what
turns a phone that never answers into an error rather than a hang. Calls run
through `bounded_run`, which kills the whole process tree at the bound, with `COLOR=0` so
no color escape wraps a listed name (any that slipped through is removed before parsing).

## The copy checks

The phone's media daemon may write to the database at any moment, and the three files are
not copied in one instant, so a single copy can be torn. So the tool:

- copies all three files twice, each set into its own folder inside one private temporary
  folder (mode `0700`), never passing `-f` and always to a fresh name, and confirms each
  copied file exists;
- treats a missing `-wal` or `-shm` (the phone's not-found error) as absent, and a missing
  main database as a refusal;
- refuses, exit `2`, unless every file is present or absent alike in both sets and hashes
  the same (SHA-256): "the database changed while it was copied; close Music on the phone
  and run again". The `-shm` is hashed too, though SQLite rebuilds it from the `-wal`, so
  a refusal can be needless: run again;
- opens the first copy read-only (`file:...?mode=ro`), with its `-wal` beside it under the
  same base name, since committed rows can live only there, and requires
  `PRAGMA integrity_check` to answer exactly `ok`, else exit `2`;
- removes the temporary folder however the run ends, Ctrl-C included.

## The join

The query is one named constant, `ROWS_QUERY` in `src/phone_db.py`. A row's file is
`base_location.path` + `/` + `item_extra.location`, joined through
`item.base_location_id`, as a read-only probe of a current phone's database confirmed. It
also reads `item_extra.file_size` (the expected size), `item_extra.title`,
`item.disc_number`, `item.track_number`, `album.album` through `item.album_pid`, and
`item_artist.item_artist` through `item.item_artist_pid`; the name columns are the ones the
live smoke test confirms. Every join is a `LEFT JOIN`, so a row missing a name is reported
with it empty, never dropped. A database without these tables or columns is refused, exit
`2`, naming what is missing: the layout may change in an iOS release.

Only a row whose base location path ends in a folder named `F` and two digits is in the
sync, and that folder is its sync folder. Rows elsewhere (purchases, downloads, podcasts),
or with no base location, are counted as `outside the sync`, not listed.

A row and a file match on (sync folder, file name), compared exactly. In each sync folder
only plain files count; anything else listed there is counted as `other entries`. A listing
line not in `afcclient`'s layout is counted as an unparsed line, said on stderr, and is a
finding: it is never dropped. That includes the line `afcclient` prints for an entry
whose stat failed: every field zeroed, a link count of `0`, a size of `0`, and the epoch in
the local zone. It is counted as unparsed, never read as a file of 0 bytes.

## The report

```text
rows with no file on the phone: 1
  The Placeholder Band / Invented Album, disc 1 track 2: Second Placeholder [F00/BBBB.mp3]
  note: a plain Finder sync does not repair these; add a character to each title, sync, restore it and sync again (phone_audit.md, "Repairing a row with no file")
size differs: 1
  The Placeholder Band / Invented Album, disc 1 track 3: Third Placeholder [F01/CCCC.m4a]: phone file 8000, database 8192
files with no row: 1
  F01/ZZZZ.mp3: 2048 bytes
  note: listed only; neither a sync nor this tool removes them
summary: findings 2; rows in the sync 3, files 3; outside the sync 1, unparsed lines 0, sizes unknown 0, other entries 0
```

- **Rows with no file on the phone**, a finding: artist, album, disc, track number, and
  title from the phone's own database, then where the file should be.
- **Size differs**, a finding: the file is there, at another size than the database's. A
  row whose expected size is zero or missing is not judged, and is counted as
  `sizes unknown`.
- **Files with no row**, not a finding: listed with their size only. Neither a sync nor a
  read-only tool removes them.
- Each note appears only when its section lists something. Every list is sorted, so the
  same phone gives the same report. A control character in a name is printed as its `\xNN`
  escape, so no name can split a line.

`--format json` prints one plain-ASCII object, every other character escaped:

| Key | Holds |
| --- | --- |
| `schema` | `1`, this layout's version. |
| `no_file` | One object per row with no file: `item_pid`, `artist`, `album`, `disc`, `track`, `title`, `folder`, `name`, `database_size` (null when unknown). |
| `size_differs` | The same fields per row, plus `phone_size`. |
| `files_no_row` | One object per file: `folder`, `name`, `size`. |
| `summary` | `findings`, `rows_in_sync`, `files`, `outside_sync`, `unparsed_lines`, `sizes_unknown`, `other_entries`. |

The report names real tracks, so keep it out of any repository: stdout, or a `--report`
outside one.

### The HTML page

`--format html` writes the same report as one page of tables, for reading in a browser. It
goes to a file only, so it needs `--report`: without one the run exits `2` with one line on
stderr, before the phone is asked anything. The format is never inferred from the report's
name: `--report phone.html` with the default format writes text. The `--report` refusals
and the user-only, replaced-whole write are the same as for any format.

The page is rendered from the very object the JSON format serializes, so the two never
disagree. Its frame (the style, light and dark, the tables, and the summary) is the
shared `html_page` library in `html_page/` at the project root (`html_page.md` there),
found at one fixed place on `sys.path`, so this page and `library_audit`'s look alike. It is one self-contained HTML5
document: inline CSS, no script, and nothing a browser would fetch. It holds:

- a header: that the phone was read, and when, to the minute in this Mac's local time;
- a summary table of the three sections with their counts, each linked to its section;
- one section per check, in the text report's order, each with its heading, its count, and
  one sentence under it, then a table. A section that found nothing keeps its heading,
  count `0`, and sentence, with no table.
  - **Tracks with no file on the phone**: Artist, Album, Disc, Track, Title, and Phone file
    (the sync folder, then the file's name in it). One table sorted by artist, album,
    disc, and track; an album's artist and album appear on its first row only, and its
    other rows sit beneath it with those cells blank and no rule between them (an
    empty name on the first row reads as a dash, so it never looks like one of those),
    so each album stands out when choosing which to trial a repair on. Its sentence keeps the
    text report's note: a plain sync does not repair these, and the title round trip does.
  - **Size differs**: the same columns, then Phone size and Database size.
  - **Files with no row**: Phone file and Size; listed only, not a finding.
- the summary figures: findings, rows in the sync, files, outside the sync, unparsed
  lines, sizes unknown, and other entries;
- a footer: nothing on the phone was changed.

Every name is escaped, and shown with each control character as a visible `\xNN`, as in
the text report. Tables scroll sideways inside their own frame, so on a phone the page
itself does not.

## Repairing a row with no file

**Why a plain sync does not.** A Finder sync copies a track's audio only when the track's
tags differ from what the phone lists. A row with no file whose tags match the Mac's looks
current to the sync, so it is skipped, and its file stays missing. A newer modified date
alone is not enough: a file rewritten with the same tags, or changed and changed back
before a sync, is skipped too.

**The proven route: a title round trip.** Proven on 2026-10-26 against every row with no file
on a real phone:

1. In Music, add a character to the title of each track this tool lists (for example
   " 2" at the end), so every one differs from the phone's row. Music writes the title into
   the file.
2. Sync, and let it finish. The sync copies each track's audio afresh.
3. Run this tool: the rows have left the "no file" list.
4. Restore each original title exactly, and sync again. The phone's titles return, and the
   copied files stay.
5. Run this tool once more to confirm nothing went missing.

Restore the titles you saved, rather than deleting the added character by hand, so a title
that already ended the same way is not cut short. A retag that changes the names for its own
reasons repairs the same way, but only the rows whose tags it actually changed.

**Not needed.** Two other routes are untried: unchecking the tracks with Finder's "Sync
only checked songs and videos", syncing, and checking them again; and deleting them on the
phone under Settings > General > iPhone Storage > Music. Removing the tracks from Music.app and adding them again would also work, but it loses
play counts, dates, and playlist membership.

## Exit codes

| Code | Meaning |
| --- | --- |
| `0` | Nothing found. Files with no row, outside-the-sync rows, unknown sizes, and other entries are tallies, not findings. |
| `1` | Findings: a row with no file, a size that differs, or an unparsed listing line. |
| `2` | Could not run: `afcclient` not on `PATH`, the phone not connected, unlocked, or trusted, or unplugged mid-run, a call that timed out, a local file (the private temporary folder or a copy) that could not be used, a phone with no music database, a database that changed while it was copied, failed its integrity check, or lacks the expected tables, a listing that failed, bad options (`--format html` without `--report` among them), a `--report` inside a git working tree or in a folder that does not exist, or a report that could not be written. |
| `130` | Ctrl-C: before the report, nothing is printed or written and the copies are removed; while it is delivered, a `--report` file is left as it was and printed text may stop part way. |

## Tests

`test_phone_audit.py` runs every suite in `tests/`. None reaches a phone. The HTML page's
suite parses each page back and checks that every element closes, every link resolves,
nothing is fetched or run, and a hostile name renders as text. The CLI suites
hand the entry point a fake runner that answers in `afcclient` 1.4.0's own output format
from an invented phone, builds the database from SQL text at each copy (no binary fixture is
committed), and records every argument list; each run is checked to have sent only `-v` or
an allowlisted command after `--`, never `-f`. The samples suite runs the README's command
against `samples/fake_bin/afcclient`, looked up on a `PATH` holding only that folder, so it
cannot find a real `afcclient` even if the fake went missing.

**The live smoke test** (`tests/test_phone_live.py`) runs the real tool once against the
connected phone with `--format json` into a temporary `--report`, and checks only that it
exits `0` or `1` and that the JSON parses with the expected keys. It is skipped unless
`PHONE_AUDIT_LIVE=1`, because it needs the operator at a connected, trusted, and unlocked
phone, and it skips whenever `APPLE_MUSIC_TOOLBOX_OFFLINE` is set and off macOS, whatever
`PHONE_AUDIT_LIVE` says. It reads only, through the same seam as every run.

## The hand check

`samples/README.md` runs the tool against a fake `afcclient` serving an invented phone, so
it never reaches a real one and prints the same report everywhere. To check your own phone,
connect and unlock it, close Music on it, and run `phone_audit.py` with no options.
