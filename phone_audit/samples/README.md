# phone_audit samples

A hand run of `phone_audit` against a fake `afcclient` serving a small invented phone, so
it never reaches a real iPhone and prints the same report on every machine. It needs `bash`,
`sqlite3` (macOS ships one), and a `python` that is the project's own environment, or any
Python 3.12 or later: the floor is `requires-python` in the project's `pyproject.toml`, and a
stock Mac's `python3` is older.

- `phone/MediaLibrary.sql` is the invented phone's music database, as SQL text: only the
  tables and columns the tool reads, under the phone's own names. Three rows point into the
  sync folders `F00` and `F01`, and one, a purchase, points elsewhere, so it is tallied as
  outside the sync rather than listed.
- `phone/files.tsv` is what the sync folders hold: one line per file, its folder, name and
  size, tab-separated.
- `fake_bin/afcclient` is the fake. Put first on `PATH`, it answers the tool's read-only
  calls in afcclient 1.4.0's own output format: `-v`, `ls -l` of the music folder and of each
  sync folder, and `get`, which builds the database from the SQL text into the file asked for
  (a fresh build each time, byte for byte the same) and reports the `-wal` and `-shm` files
  absent, as afcclient does a path the phone lacks. It serves only the paths afcclient
  uses, relative to the AFC root (the device's `/var/mobile/Media`): any other is a
  missing object. Any other command or flag it refuses.
- Two variables make the fake misbehave, for a hand check of how the tool takes it:
  `FAKE_AFCCLIENT_DISCONNECT=1` answers every device command with afcclient's unplugged
  line (exit `2` from the tool), and `FAKE_AFCCLIENT_STAT_FAIL=AAAA.mp3` prints that
  file's listing line zeroed, as afcclient does when a stat fails (an unparsed line, exit
  `1`).

What the invented phone holds: track 1's file is there at its size. Track 2 has a row and no
file, the fault the tool exists to find. Track 3's file is 8000 bytes where the database
expects 8192. The file ZZZZ.mp3 in F01 has no row: it is listed, not a finding.

The suite `tests/test_phone_samples.py` runs the command below against the fake, found on a
`PATH` holding only `fake_bin`, and fails when the command or what it prints stops matching
the blocks below.

## Run it

**Start it from this `samples/` folder.** The command puts `$PWD/fake_bin` first on `PATH`,
and only from here is that the fake's folder; from anywhere else a real `afcclient` would be
found instead. So each line first tests that `fake_bin/afcclient` is here: from another folder
the first line says so and the second runs nothing.

```bash
test -x fake_bin/afcclient || echo "run this from the samples folder: fake_bin/afcclient is not here" >&2
test -x fake_bin/afcclient && PATH="$PWD/fake_bin:$PATH" python ../phone_audit.py
```

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

Exit code `1`: there are findings. Progress goes to stderr: two database-copy lines, then a
line per listing. Add `--format json` for the same report as JSON.

## The HTML page

The same run as one page of tables. `--format html` writes to a file only, and `--report`
refuses a folder inside a git working tree, so the page goes to the temporary folder rather
than beside these files. Start it from this folder, as above:

```bash
test -x fake_bin/afcclient && PATH="$PWD/fake_bin:$PATH" python ../phone_audit.py --format html --report "${TMPDIR:-/tmp}/phone_audit_sample.html"
```

Nothing is printed to stdout, and the exit code is again `1`. Open the file in a browser: a
header saying when the phone was read, a summary table linking each of the three sections
with its count of `1`, then the sections (the row with no file, BBBB.mp3 in F00; the size
that differs; the stray ZZZZ.mp3 in F01), the summary figures, and a footer saying nothing
on the phone was changed. No `.html` file is kept in this folder: the suite runs this
command against a temporary folder of its own and checks the page was written.
