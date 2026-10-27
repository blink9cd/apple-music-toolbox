# library_audit samples

A hand run of `library_audit` over a small invented library folder, against a **fake
`osascript`**, so it never reaches the real Music.app and prints the same report on every
machine. It needs a Mac (the tool refuses any other platform before it reads anything), `bash`,
and a `python` that is the project's own environment, or any Python 3.12 or later: the floor is
`requires-python` in the project's `pyproject.toml`, and a stock Mac's `python3` is older.

- `library/` is the library folder: three invented albums. One file, `05 Stray Placeholder.mp3`,
  has no track in the fake Music. The third album, the duo's, is split by its artist's
  spelling: two of its files name the artist with a typographic hyphen (U+2010), one with
  an ASCII hyphen, and the two print alike.
- `outside/` holds one file the fake Music has a track for, outside `library/`, so it is
  tallied rather than listed.
- `fake_bin/osascript` is the fake. Put first on `PATH`, it answers the tool's three read-only
  scripts (is Music running, how many tracks, list them) from nine invented tracks that
  point into this folder: six of the library's files, one missing file (`02 Second
  Placeholder.mp3`), one shared track with no file but a cloud copy, and the file in
  `outside/`. Two of its tracks carry a sync finding: Music.app lists a size of 4096 bytes
  for the quartet's zero-byte first file, and the duo's track 2 is unchecked. Every other
  track is checked and lists no size.
  Any other script it refuses.

Every audio file here is a placeholder holding no audio: the tool stats each file and reads
its tags, never its audio. The quartet's and the trio's files, and the one outside, are
**zero-byte placeholders**, which stat like any file and have no tags, so with mutagen
installed each library file among them is listed under `unreadable tags` and grouped by its
folder. The duo's three files are each an ID3 tag and nothing else, written here with
mutagen from invented names: the album artist, album, track (`n/4`) and disc frames, and
no artist frame, which the PII scan's binary-metadata check would read as naming a person.
Their track numbers interleave across the two spellings and leave track 4 to no file, so
the report names one split album, still missing 4, and no gap. The gone
track's location names the quartet's folder, so it counts toward that folder too: the folder's
three files against its three tracks (two matched, one gone) agree, and the placeholder album's
album-level findings are the stray file with no track and the track whose file is gone. No
file here is an iCloud placeholder, and the decode is not run. Because zero bytes cannot
carry metadata, `library/` and `outside/` are exempt from the PII scan's binary-metadata
check for an empty file (and only that: the duo's tags are read and pass), which that check
would otherwise report as unread; the exemption is in the project's `pyproject.toml`, and
every other check still runs here.

The suite `tests/test_audit_samples.py` runs the command below against the fake, named by its
path, and fails when the command or what it prints stops matching the blocks below, with the
placeholder filled in.

## Run it

**Start it from this `samples/` folder.** The command puts `$PWD/fake_bin` first on
`PATH`, and only from here is that the fake's folder; from anywhere else the real
`osascript` would be found instead. So each line first tests that `fake_bin/osascript` is
here: from another folder the first line says so and the second runs nothing.

```bash
test -x fake_bin/osascript || echo "run this from the samples folder: fake_bin/osascript is not here" >&2
test -x fake_bin/osascript && PATH="$PWD/fake_bin:$PATH" python ../library_audit.py --library library
```

```text
library: <samples>/library
files with no Music.app track: 1
  <samples>/library/The Invented Quartet/Placeholder Album/05 Stray Placeholder.mp3
Music.app tracks whose file is gone: 1
  The Invented Quartet / Placeholder Album, disc 1 track 2 [local only]: <samples>/library/The Invented Quartet/Placeholder Album/02 Second Placeholder.mp3
track-number gaps: 0
albums split by spelling: 1
  The Split-Level Duo / Split Placeholder Album, disc 1: 2 spellings, still missing 4
    1. The Split-Level Duo / Split Placeholder Album: track 2
    2. The Split‐Level Duo / Split Placeholder Album: tracks 1, 3
    1 and 2 differ in the artist: U+002D HYPHEN-MINUS vs U+2010 HYPHEN
files with no track number: 0
files and Music.app tracks differ: 0
unreadable tags: 4
  <samples>/library/The Invented Quartet/Placeholder Album/01 First Placeholder.mp3
  <samples>/library/The Invented Quartet/Placeholder Album/04 Fourth Placeholder.mp3
  <samples>/library/The Invented Quartet/Placeholder Album/05 Stray Placeholder.mp3
  <samples>/library/The Made-Up Trio/Lone Placeholder/01 Lone Placeholder.m4a
unreadable files and folders: 0
iCloud placeholders: 0
Music.app size differs from the file: 1
  <samples>/library/The Invented Quartet/Placeholder Album/01 First Placeholder.mp3: Music.app 4096, file 0
  note: Music.app's record is stale; tag_refresh makes it reread the file
unchecked tracks: 1
  The Split-Level Duo / Split Placeholder Album, disc 1 track 2: <samples>/library/The Split-Level Duo/Split Placeholder Album/02 Split Placeholder.mp3
  note: an unchecked track is skipped only when the phone syncs only checked songs
decode check not run (--decode)
the sync checks see this Mac only: Music.app cannot see an iPhone, so a track the phone lists but cannot play is not found here
summary: findings 9; audio files 7, Music.app tracks 9; cloud-only 1, outside --library 1, unparsed rows 0, sizes unknown 0
```

Exit code `1`: there are findings. Progress, one `tracks 1-9 of 9` line, goes to stderr.

## The HTML report

The same run as one page of tables. `--format html` writes to a file only, and `--report`
refuses a folder inside a git working tree, so the page goes to the temporary folder rather
than beside these files:

```bash
test -x fake_bin/osascript && PATH="$PWD/fake_bin:$PATH" python ../library_audit.py --library library --format html --report "${TMPDIR:-/tmp}/library_audit_sample.html"
```

Nothing is printed to stdout, and the exit code is again `1`. Open the file in a browser: a
summary table listing every check with its count, the checks that found something linked to
their own section (the stray file, the gone track, the split album, the four unreadable tags,
the stale size and the unchecked track), and the decode read as `not run`. Paths under
`library/` are shown relative to it. No `.html` file is kept in this folder: the suite runs
this command against a temporary folder of its own and checks the page was written.

## Comparing your output

`<samples>` stands for the full path of this `samples/` folder, with any symbolic link in it
resolved. Without the project's `refresh_tags` extra (mutagen) installed, the `track-number
gaps`, `albums split by spelling`, `files with no track number` and `unreadable tags`
sections are replaced by one `tag checks skipped: mutagen not installed` line and the
summary counts 4 findings; the count check goes by folder throughout and comes out the
same, and everything else should match line for line. Add `--format json` for the same report as JSON.
