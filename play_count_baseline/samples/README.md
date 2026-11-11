# play_count_baseline samples

A hand run of `play_count_baseline` against a **fake `osascript`**, so it never reaches the
real Music.app and writes the same baseline on every machine but for one value. It needs a
Mac (the tool refuses any other platform before it reads anything), `bash`, and a `python`
that is the project's own environment with the `contract` extra installed, or any Python 3.12
or later with `jsonschema`: the floor is `requires-python` in the project's `pyproject.toml`,
and a stock Mac's `python3` is older.

- `fake_bin/osascript` is the fake. Put first on `PATH`, it answers the tool's three
  read-only scripts (is Music running, how many tracks, list their play counts) from four
  invented tracks, and refuses any other script:
  - a played file track with every field set, its album artist differing from its artist;
  - a file track never played, so it has no played date, whose album artist is its artist
    and so is left out;
  - a cloud-only track with no path, and no album artist, disc number, genre, or year;
  - a track with an empty artist, which the contract cannot hold, so it is excluded.

  Its paths name an invented volume; no file is read, since the tool only copies a path.
- `expected-baseline.json` is the baseline the command below writes. Its `captured_at` is
  the clock of the run that made it, and the one value a new run differs in.

The suite `tests/test_baseline_samples.py` runs the command below in `bash`, against the
fake, with a `PATH` holding no real `osascript`, and fails when the command, what it prints
or what it writes stops matching this folder.

## Run it

**Start it from this `samples/` folder.** The command puts `$PWD/fake_bin` first on `PATH`,
and only from here is that the fake's folder; from anywhere else the real `osascript` would
be found instead. So the running line first tests that `fake_bin/osascript` is here: from
another folder the first line says so and no baseline is written. `TZ=UTC` fixes the zone the
played dates are read in, so `last_played_at` comes out the same on every machine. The
tool refuses an `--output` that exists or lies inside a git working tree, so the baseline
goes to a fresh folder under `$TMPDIR` (`/tmp` when it is unset), and the last line
compares it with `expected-baseline.json`, leaving out `captured_at`:

```bash
test -x fake_bin/osascript || echo "run this from the samples folder: fake_bin/osascript is not here" >&2
out="$(mktemp -d "${TMPDIR:-/tmp}/play_count_baseline.XXXXXX")/baseline.json"
test -x fake_bin/osascript && PATH="$PWD/fake_bin:$PATH" TZ=UTC python ../play_count_baseline.py --output "$out"
test -f "$out" && diff <(grep -v '"captured_at"' expected-baseline.json) <(grep -v '"captured_at"' "$out") && echo "matches expected-baseline.json but for captured_at"
```

On stdout, from the last line:

```text
matches expected-baseline.json but for captured_at
```

On stderr, the progress line and the summary, aggregates only:

```text
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
```

The tool exits `0`, and the file is written at mode 0600. Without `TZ=UTC` the two
`last_played_at` values shift by the machine's offset from UTC on those dates, and `diff`
shows those two lines.
