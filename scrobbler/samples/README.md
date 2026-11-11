# Replay sample

A hand-checkable run of the scrobbler's play engine, with no Music.app, no store and no
network. `trace.jsonl` is a recorded session of three invented tracks; `expected/` holds
the queue files the replay command writes for it, one listen per file.

## The trace

One event per line, each with its time in Unix seconds as `at` and exactly one of
`notice` (a playerInfo notice's fields), `position` or `snapshot` (the text that script
returned, its fields joined by the unit separator, written `\u001f`), or `quit`.

| Track | What happens | Queued |
| --- | --- | --- |
| Morning Ferry | Played through to its end, 30 s | One listen, 30 s heard |
| Gravel Hymn | Skipped after 1 s | Nothing: a play must pass 2 s |
| Long Weather | 21 s, paused for 40 minutes, 10 s more, then Music quits | Two pieces of one play |

A pause of 30 minutes or more splits a play, so Long Weather's two listens share a play
ID and carry pieces 1 and 2. The first piece's 21 s is the 20 s the position reads
measured plus the second between the last read and the pause notice.

## The hand check

From this folder, build the executable outside the tree and replay the trace into a
fresh folder:

```sh
out="$(mktemp -d)"
swift run --package-path ../app --scratch-path "$(mktemp -d)" scrobbler replay --trace trace.jsonl --out "$out"
diff -r expected "$out"
```

It prints `3 listens written`, and `diff -r` prints nothing. Play IDs count up from a
fixed start and the snapshot's dates are read in UTC, so the bytes are the same on every
machine. `ReplayTests` makes the same comparison on every gate run.
