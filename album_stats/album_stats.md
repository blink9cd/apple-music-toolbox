# album_stats

Reports one album's track count, its favorited-track count and its year, by asking
Apple Music directly. On request it counts tracks the listener rated at least N stars
instead of favorited ones (see "The star-rating mode" below). It answers a question
about an album a caller has **already chosen**; it has no ability to choose one, and
no knowledge of how the choice was made.

```bash
python album_stats/album_stats.py --artist "Fictionals" --album "Fictionals (Gold)"
```

Run from this project's root directory. On exit `0` it prints the record to
stdout and a one-line confirmation to stderr.

## Why `favorited`, and not `rating`

This is the finding the whole tool rests on, measured against a real library rather
than assumed:

| Query | Matched | Share |
| --- | --- | --- |
| `rating kind is user and rating > 0` | a handful of tracks | almost none |
| `favorited is true` | thousands of tracks | a large share |

A signal keyed on `rating` would read `0 of N` on essentially every album -- a dead
metric that looks like a working one.

The naming actively misleads: recent Music.app replaced the heart icon with a **star**
for "Favorite", so the control a listener presses when they "star a song" writes
`favorited`. The property literally named for rating stays almost empty.

Two related traps, both cheap to fall into and expensive to diagnose:

- **`loved` no longer exists.** It was renamed to `favorited`. A script still using it
  fails with `The variable loved is not defined. (-2753)`.
- **Keep `rating kind is user` if you ever do read `rating`.** Music can derive a track
  rating from an album rating, so a naive `rating > 0` silently counts tracks the
  listener never rated. (`rating kind is computed` measured 0 on that library -- but
  that is a fact about one library, not a guarantee about any other.)

`test_album_stats.py` pins the property choice -- the default script must ask for
`favorited is true` and mention neither `rating` nor `loved` -- so a rewrite that
reaches for the plausible-sounding property fails there rather than shipping wrong
numbers. `rating` appears only in the opt-in mode below, and `loved` in neither.

## The star-rating mode

A library that does carry star ratings can use them as the favorites signal instead:
`album_facts(..., min_stars=N)`, or `--favorite-min-stars N` on the command line, with
`N` from 1 to 5. The count then answers "how many of this album's tracks did the
listener rate at least N stars?", and is reported in the same `favorited` field, so a
record's shape does not depend on the signal.

- **Threshold:** Music.app stores a rating as 0 to 100, twenty per star, so `N` stars
  is `rating >= N*20` -- 3 stars is `rating >= 60`.
- **User ratings only:** the clause is `rating kind is user and rating >= N*20`. The
  `kind` half is the trap noted above made mandatory: an album-derived rating never
  counts, because the listener never gave it.
- **Same script otherwise:** only that one qualifying clause differs from the
  favorited script; the album match, the year loop, the reply and every bound variable
  name are identical, so the mode adds no new variable for the dictionary-collision
  trap below to bite. `tests/test_star_rating.py` pins that one-line difference, plus
  `rating kind is user`, the `>= N*20` threshold and the absence of `loved`.
- **Never the default:** `min_stars=None` and an absent `--favorite-min-stars` keep the
  favorited count, so a caller that passes nothing -- the personal site's refresh among
  them -- gets favorited. A value outside 1 to 5 raises ValueError from `album_facts`
  (a caller's programming error, not a Music.app outcome) and exits 2 from the CLI.
- **Zero is still an answer:** an album present with no track rated that high returns
  `favorited=0`; `None` still means Music.app could not be asked or the album is absent.

No faked test can prove Music.app accepts the rating clause at runtime: only
`tests/test_live_star_rating.py` can. It sends the rating script for the album Music.app
reports as most recently added and requires an answer, and it runs by hand against a
real library, never in the gate (it skips under `APPLE_MUSIC_TOOLBOX_OFFLINE`).

## Why both artist and album

Matching on the album title alone is not enough. Two albums can share a title across
different artists, and compilations make it worse. The query constrains `album artist`
**and** `album`; a test asserts both clauses are present, because dropping one produces
a tool that still returns plausible numbers -- just the wrong ones, for a different
record.

Note that the album artist is not always the track artist: on a compilation they
differ, which is exactly the case this guards.

## Why a `whose` clause, and not a loop

A `whose` clause is evaluated inside Music.app and answers immediately, even across a
library of tens of thousands of tracks. Iterating tracks and reading a property from
each is unusably slow, because every property access is its own Apple Event -- a probe
reading two properties per track timed out on a few thousand tracks. Both
counts and the year come back from one round trip.

The year is the one per-track read, and it loops only over the tracks the `whose`
clause already matched: one Apple Event per track on the album, never one per track in
the library. That loop is what reads every matched track's tag rather than the first
one's -- see "Who consumes this" below for which year it keeps.

Naming an AppleScript variable after a term in Music's own dictionary fails at RUNTIME
with `Access not allowed. (-10003)`, which reads exactly like a denied automation
permission and is not one.

**Two innocent-looking words are known to collide:** `computed`, and `matched`, which
fails as `Can't set «constant eClSkMat» ... Access not allowed. (-10003)`. No faked
unit test can catch this -- only the live boundary test, `test_live_favorites.py` in
the media_feeds project's `album_scan`, runs the script against Music.app. The
defense is to *invent* variable names (`lp`, `nAll`, `nFav`, `yr`, `albTracks`,
`albTrk`, `trkYr`) rather than reach for the natural-sounding word, and
`test_album_stats.py` refuses both known collisions as bound names.

## What leaves Music.app

**Three integers, and nothing else.** The boundary is drawn at the *query*, not at the
output: Music.app is asked to `count` matching tracks and for each matched track's
`year`, which the script reduces to one number before replying, so no title, filename
or other piece of library content is ever returned, logged, or held in memory to be
filtered out later. A filter applied after the fact is one edit away from
leaking; a query that never asks is not.

The counts themselves are intended to be committed and published -- that is the point
of the tool. The artist and album names appear only in the no-counts stderr message,
and are values the caller supplied on the command line in the first place.

## Why it does not own its subprocess seam

The real-process seam is `recently_added.py`'s `_real_run`, imported rather than
reimplemented. That function already carries the bounded-subprocess discipline -- a
plain `subprocess.run(capture_output=True, timeout=...)` reads as bounded and is not,
for the reasons its own docstring gives -- and a second copy would be a second thing to
keep correct. This tool supplies the script and parses the reply; it does not run
processes.

The import finds `recently_added` by searching upward from this file, so the tool
keeps working wherever the project tree is checked out.

## Usage

```text
python album_stats.py --artist ARTIST --album ALBUM [--timeout TIMEOUT]
                      [--favorite-min-stars N]
```

Run `--help` for the current default of each optional (this doc does not restate them,
so it cannot drift from the parser):

| Option | Required | Description |
| --- | --- | --- |
| `--artist` | yes | The album artist to match, exactly. Not always the track artist. |
| `--album` | yes | The album title to match, exactly. |
| `--timeout` | no | Seconds to allow the Music.app query before abandoning it. |
| `--favorite-min-stars` | no | Count tracks the listener rated at least `N` stars (1-5) instead of favorited ones. Unset means favorited. |

Exit `0` wrote the counts. Exit `1` means no counts: either the album is not in the
library, or Music.app could not answer (absent, not running, not scriptable, or
automation permission denied). Those are not distinguished, deliberately -- see below.

## Who consumes this, and the never-raises contract

Under a Music.app source (`--source music`, or `auto` while Music.app answers),
media_feeds' `album_scan.py` calls `album_facts()` once for each album it records,
after resolving which albums are newest, and folds the result into that album's record. That record's
consumer decides how to display it.

`album_facts()` **never raises**, with one exception: a `min_stars` outside 1 to 5
raises ValueError before any query, because that is a caller's programming error rather
than a Music.app outcome. Otherwise Music.app absent, not running, not scriptable,
automation permission denied, a timeout, a non-zero exit, an unparseable reply, and an
album that simply is not in the library all come back as `None`. This mirrors
`recently_added.newest_albums_from_music`, for the same reason: the caller decides
what "no answer" means, rather than this function deciding for it by raising. A record
without counts is a normal outcome, not an error.

One distinction the parser does draw: an album present with nothing favorited yet
returns `AlbumFacts(tracks=N, favorited=0, ...)`, which is a real answer, while an album
that matched nothing returns `None`. They are different facts, so they are not
collapsed.

`year` is the **latest** year tag among the tracks the query matched, and draws the
same distinction: Music.app returns `0` for a track with no year tag, and when no
matched track is tagged that becomes `None` rather than the number zero, so a consumer
can omit the year instead of printing one that does not exist. **It is the FILE'S TAG,
not a release date** — an album ripped from a remaster reports the reissue year, and
nothing here can tell a wrong tag from a right one.

Why every track and why the latest:

- **Every track, because one untagged track must not blank the album.** Reading a
  single track would record no year whenever that track is untagged, however many of
  the others are tagged -- and a `whose` clause returns tracks in Music.app's own
  order, so "the first one" need not be track 1. An untagged track's `0` never beats a
  real year, so it drops out on its own.
- **The latest, because of compilations.** A compilation's tracks can carry their
  original years, while the year a store lists for a compilation is its own release, on
  or after all of them. The store's year is what `cover_art` weighs this one against
  when it picks a cover, so the latest tag is the one nearest it. The earliest would be
  furthest, sometimes by decades.

## Worked example

`samples/README.md` holds the not-found case as a real, captured run and the found case
as an illustrative one, with their commands, output and exit codes. The not-found case
reproduces on any machine with Music.app; the found case's numbers depend on the
library, which that file explains.

## Running the test suite

From the `album_stats` directory (the module is imported by name):

```bash
python -m unittest test_album_stats
```

Every test that reaches the seam drives a fake `run`. Two files in `tests/` are the
exceptions, and neither can mutate the library. `test_live_literal.py` spawns the real
`/usr/bin/osascript` on a bare string literal, reaching neither Music.app nor the
network. `test_live_star_rating.py` sends the star-rating query to the real Music.app,
read-only, and skips off macOS, when Music.app is unreachable, and whenever
`APPLE_MUSIC_TOOLBOX_OFFLINE` is set. The favorited query meets the real Music.app in
`test_live_favorites.py`, in the media_feeds project's `album_scan`.

To run the star-rating live case by hand, from the `album_stats` directory with
`APPLE_MUSIC_TOOLBOX_OFFLINE` unset and Music.app running:

```bash
python tests/test_live_star_rating.py -v
```
