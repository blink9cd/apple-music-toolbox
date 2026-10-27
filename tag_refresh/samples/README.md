# tag_refresh samples

A hand run of `tag_refresh` in explicit mode, with `--dry-run`, so it looks albums up
in Music.app and refreshes nothing. It needs a Mac with Music.app open and the automation
permission for your terminal (the first run asks for it), and a `python` that is the project's
own environment, or any Python 3.12 or later: the floor is `requires-python` in the project's
`pyproject.toml`, and a stock Mac's `python3` is older.

`library/` holds two invented albums, one of them in two disc folders. Every `.mp3` in it is
a **zero-byte placeholder**, not audio: the tool stats each file and reads its album tag,
and a placeholder stats like any file and has no tag, so its tag reads as none. The albums
are invented, so Music.app holds none of them, and every file is reported `not in Music`.
Because zero bytes cannot carry metadata, the folder is exempt from the PII scan's
binary-metadata check for an empty file, which that check would otherwise report as unread;
the exemption is in the project's `pyproject.toml`, and every other check still runs here.

The suite `tests/test_cli_samples.py` runs the list-building block below in `bash`, then
both commands against a fake Music.app holding no tracks, and fails when a command or what
it prints stops matching the blocks below, with the placeholder filled in.

## Build the list file

A list file names absolute paths, so it is written at run time from wherever this folder
sits, rather than committed. Run from this `samples/` folder:

```bash
SAMPLES="$PWD"  # run from this tool's samples/ folder
LIST="$(mktemp -d "${TMPDIR:-/tmp}/amr-sample.XXXXXX")/changed.txt"
find "$SAMPLES/library" -name '*.mp3' | LC_ALL=C sort > "$LIST"
```

## 1. The list file

```bash
python ../tag_refresh.py --tracks-from "$LIST" --dry-run
```

```text
<samples>/library/The Invented Quartet/Placeholder Album: would refresh 0, not in Music 2
<samples>/library/The Made-Up Trio/Two Disc Placeholder/Disc 1: would refresh 0, not in Music 1
<samples>/library/The Made-Up Trio/Two Disc Placeholder/Disc 2: would refresh 0, not in Music 1
not in Music:
  <samples>/library/The Invented Quartet/Placeholder Album/01 First Placeholder.mp3
  <samples>/library/The Invented Quartet/Placeholder Album/02 Second Placeholder.mp3
  <samples>/library/The Made-Up Trio/Two Disc Placeholder/Disc 1/01 Third Placeholder.mp3
  <samples>/library/The Made-Up Trio/Two Disc Placeholder/Disc 2/01 Fourth Placeholder.mp3
total: would refresh 0, not in Music 4, stale 0, errors 0, stopped 0 (album folders 3, MP3s 4)
```

Exit code `0`: a file Music does not hold is reported, not an error. Progress, one
`album n/3` line per album folder, goes to stderr.

## 2. One album folder

```bash
python ../tag_refresh.py --album "library/The Made-Up Trio/Two Disc Placeholder" --dry-run
```

```text
<samples>/library/The Made-Up Trio/Two Disc Placeholder/Disc 1: would refresh 0, not in Music 1
<samples>/library/The Made-Up Trio/Two Disc Placeholder/Disc 2: would refresh 0, not in Music 1
not in Music:
  <samples>/library/The Made-Up Trio/Two Disc Placeholder/Disc 1/01 Third Placeholder.mp3
  <samples>/library/The Made-Up Trio/Two Disc Placeholder/Disc 2/01 Fourth Placeholder.mp3
total: would refresh 0, not in Music 2, stale 0, errors 0, stopped 0 (album folders 2, MP3s 2)
```

Exit code `0`. Both disc folders are walked, and each asks Music for its own name and its
parent's, `Two Disc Placeholder`.

## Comparing your output

`<samples>` stands for the full path of this `samples/` folder. Without the project's
`refresh_tags` extra (mutagen) installed, one `hint:` line follows the `not in Music` list in
each report; everything else should match line for line.
