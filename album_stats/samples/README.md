# album_stats samples

Hand-verification pair for `album_stats`. Unlike its sibling `album_scan`, this
tool has **no offline mode**: its only input is a live Music.app library, so there is
no fake fixture that could stand in for one and no committed output file to diff
against. What stands in instead is a real not-found run, verbatim, and an illustrative
found run whose numbers depend on the library -- with the difference made explicit.

Both commands run from this project's root directory.

## The not-found case — reproduces on any machine

This one needs only a working Music.app; the artist and album are deliberately absurd,
so any library will fail to match them.

```bash
python album_stats/album_stats.py \
  --artist "Nobody At All" \
  --album "No Such Album"
```

Real run, captured verbatim on stderr:

```text
album_stats: no counts for Nobody At All - No Such Album (not in the library, or Music.app could not answer)
```

Exit code `1`, and **nothing at all on stdout** -- worth checking specifically, because
the whole point of routing messages to stderr is that `stdout` piped into a file stays
either valid JSON or empty, never a half-record with a warning glued into it.

### What you should see

- Exit code `1`.
- The message above on stderr, naming the artist and album you passed.
- Empty stdout. `... > /tmp/out.json; wc -c /tmp/out.json` should report `0`.

## The found case — depends on the library

The artist and album below are invented stand-ins: substitute an album your own library
holds, passing its **album artist**.

```bash
python album_stats/album_stats.py --artist "The Invented Quartet" --album "Placeholder Album"
```

Illustrative output for such an album -- the numbers depend on your library:

```text
album_stats: 3 of 12 favorited
```

```json
{
  "tracks": 12,
  "favorited": 3,
  "year": 2001
}
```

Exit code `0`.

### What you should see

The numbers above are illustrative: **not** reproducible on another machine, and not
stable on any -- `favorited` changes the moment somebody favorites or unfavorites a
track, which is the entire purpose of the field. Do not diff against them.

Verify the shape instead, which is what the tool actually guarantees:

- Exit code `0`.
- stdout parses as JSON with exactly the three keys `tracks`, `favorited` and `year`.
- `tracks` and `favorited` are integers, `tracks` is greater than `0`, and `favorited`
  is between `0` and `tracks` inclusive.
- `year` is a positive integer or `null`. It is the latest year tag among the tracks the
  query matched, and `null` means none of them carries one -- Music.app reports `0` for
  an untagged track, and `0` is not a year.
- The stderr line agrees with the JSON.

A reply violating any of these bounds is rejected rather than passed on (the tool exits
`1` instead), so output that violates one would mean a genuine defect.

To run it against your own library, pick any album you have and pass its **album
artist** -- not the track artist, which differs on a compilation.

### The star-rating variant

Add `--favorite-min-stars 4` to count tracks you rated at least four stars instead of
favorited ones. The stdout record keeps the same three keys, `favorited` now holding
that count, and the stderr line reads `album_stats: 2 of 12 rated at least 4 stars`
(illustrative numbers again). The same shape checks apply.

## Why no committed expected-output file

The media_feeds project's `album_scan` sample commits an `expected_album.json` because a fake library folder
fixes every key of its record except the folder-birth-date `added`. Nothing here is
fixed: the counts are a live reading of a mutable library, so a committed file would be
a snapshot that goes stale silently and invites a byte-for-byte comparison that is
guaranteed to fail for reasons that have nothing to do with the tool being wrong. The
shape assertions above are the part that genuinely holds.
