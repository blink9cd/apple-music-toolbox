# play_count_baseline.py

Write Music.app's lifetime play count for every track in its library as one JSON file, a
listensmith baseline that validates against the contract's `baseline.schema.json`.
listensmith, the listen store this tool pairs with, is not yet published. The contract
it writes to ships here, as the copy under `scrobbler/contract/` (its schemas included),
so any store that implements that contract can load the file.
**Read-only**: it never writes to Music.app, never launches it, and never reads the
library's files. macOS only.

## Why it exists

The scrobbler records listens from the moment it is installed; what Music.app counted before
that is lost unless it is captured once. This tool captures it, as a snapshot listensmith
loads, so a later snapshot can tell "first played since" from "not in the library then". It
knows nothing about the store beyond the schema, and the store knows nothing about Apple.

## Its shape

- **One tool of its own**, in Python, reaching Music.app only through tag_refresh's
  `music_calls` seam.
- **What it reads:** every track, and every field AppleScript gives for it; a track never
  played is written with a play count of 0, and the tracks are sorted by persistent ID.
- **Where it writes:** `--output` is required, refused inside a git working tree or when it
  exists already, and the file is written atomically, at mode 0600.
- **The check:** every baseline is checked with `jsonschema` against the contract copy,
  which the toolbox's `contract` extra provides.

## Prerequisites

- **macOS**, where Music.app and `osascript` exist. Anywhere else a run exits `2` with one
  line before it reads anything.
- **Music.app already running.** The tool asks `application "Music" is running`, which
  answers without launching it, before it says anything else to Music; when Music is not
  running it exits `2`.
- **The automation permission** for the terminal that runs it, to control Music (System
  Settings > Privacy & Security > Automation). The first run asks for it.
- **The toolbox's `contract` extra** (`pip install ".[contract]"` from the project root),
  which holds `jsonschema`. Every baseline is checked with it before it is written and again
  after, so without it the run exits `2`, naming the extra, before Music is asked anything.

## Usage

```text
play_count_baseline.py --output <file>
```

| Option | Default | Description |
| --- | --- | --- |
| `--output` | required | The baseline file to write. There is no default. Refused, exit `2` before Music is asked anything, when it exists already (a dangling link included), when its folder does not exist, or when it lies inside a git working tree. |

Loading it: `listensmith store import --path FILE`.

## What a run does

1. Refuses a non-macOS platform, then the target as above, then a missing `contract` extra.
2. Asks whether Music.app is running.
3. Notes the capture time, counts the library's tracks, lists them 1000 at a time (a
   progress line `tracks <first>-<last> of <total>` on stderr for each batch), then counts
   again. A count that changed, a batch that answered a different number of rows than it was
   asked for, or any row that could not be read is refused with exit `1`: a partial baseline
   is never written, since a track missing from it would later read as its first play.
4. Maps the rows, one field at a time (`track_entry` in `src/baseline_map.py`), tracks
   sorted by persistent ID. A library
   where no track can be written (empty, or every track lacking a name or an artist) is
   refused, because the contract needs at least one track. The document is checked against
   the contract copy; a document with findings is refused and the first ten are printed,
   each as a path into the document and the rule it breaks, never the value.
5. Checks the target again, so a file made while Music.app was read is not replaced, then
   writes the
   document atomically, at mode 0600, as sorted, indented UTF-8 JSON. It then reads the file
   back and checks it again; a file that cannot be read back, or does not parse or validate,
   is reported unconfirmed, exit `1`.
6. Prints the summary and exits `0`.

A Music.app call that fails or times out, at any step, exits `2` with one line naming the
step (`the probe`, `the count`, `the list of tracks <first>-<last>`, or `the recount`),
whether it failed or timed out, and the AppleScript error number when there is one, such as
`Music.app failed at the count (error -1728)`. osascript's own message is never printed:
an AppleScript runtime error quotes the value it failed on, which can be a title or a path.

## The summary

On stderr, aggregates only, so it can be pasted into a bug report or a note without
carrying any library value:

```text
tracks read: <n>
tracks written: <n>
excluded, no name: <n>
excluded, no artist: <n>
missing <key>: <n>
```

with one `missing` line for each optional key a track may lack, in the order of
`baseline_map.OPTIONAL_KEYS` (`src/baseline_map.py`). No library value (a title, artist,
album, genre, or file path) is ever printed, and a refusal names only the `--output` path
given.

## Exit codes

| Code | Meaning |
| --- | --- |
| `0` | The baseline was written and read back valid. |
| `1` | The library refused: it changed during the read, a batch or row could not be read, no track could be written, the document failed the schema, or the written file could not be confirmed. |
| `2` | Could not start or write: not macOS, `--output` refused, the `contract` extra missing, Music.app not running, a Music.app call failed or timed out, or the file could not be written. |
| `130` | Interrupted (Ctrl-C). Before the file is written, nothing is, and the line says `nothing written`; during its read-back, the line says `--output was written but not confirmed`, and the file is left unconfirmed. |

## Tests

`test_play_count_baseline.py` runs every suite in `tests/`. All but one fake Music.app at
the `music_calls` runner seam with invented tracks (`tests/baseline_fixtures.py`) and write
only into a temporary folder outside any checkout, so none of them can reach Music.app or
the real library.

One suite does reach Music.app, and only when asked: `tests/test_baseline_live.py` runs the
whole tool with the real runner, after an `is running` probe that never launches Music, and
every call it makes only reads. It writes into a fresh temporary folder outside every
checkout and asserts validity alone: the run exits `0` and the file validates against the
contract copy. No title, artist, album, path, or count from the library is asserted,
printed, or kept. It skips unless `PLAY_COUNT_BASELINE_LIVE` is `1`, under
`APPLE_MUSIC_TOOLBOX_OFFLINE`, off macOS, and when Music.app is not running:

```bash
PLAY_COUNT_BASELINE_LIVE=1 python play_count_baseline/test_play_count_baseline.py
```

## The hand check

`samples/README.md` runs the tool against a fake `osascript` answering from four invented
tracks, so it never reaches the real Music.app and writes the same baseline everywhere but
for `captured_at`.
