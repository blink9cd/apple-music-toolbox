# grant_probe

Asks Music.app one read-only question and records whether macOS allowed it. It is the
script `runner.py install` uses to check that Apple Music Toolbox Runner holds the
Automation permission for Music (see `../runner.md`).

## Who starts it

Only `runner.py install`, and only through the installed runner app: install loads a
one-shot launchd agent whose program is the app, and the app starts this script as its
child. macOS charges the question to the app, as it will charge a scheduled job's, so
the answer is the app's own. Run by hand from a terminal it would report the terminal's
permission instead, and could raise a prompt for the terminal.

## What it asks

One AppleScript line, through `/usr/bin/osascript`: the player state, and only when
Music is already running.

- **It never opens Music.** AppleScript's `is running` test sends no Apple event, so a
  closed Music stays closed and the outcome is `not-running`.
- **It never asks for Music's version.** AppleScript answers that from Music's bundle
  with no Apple event at all, so it would report a grant that was never given.
- **It has no `with timeout` clause.** The first time, macOS shows its permission prompt
  and holds the event until a person answers; a short timeout withdraws the prompt
  before it can be read. The osascript process is bounded by `GRANT_PROBE_TIMEOUT_S` in
  `grant_probe.py`, set longer than AppleScript's own default wait for an answer, so an
  unanswered prompt ends as osascript's own error.
- **It changes nothing.** It reads one value and writes one result file.

## Usage

```text
grant_probe.py --result FILE
```

| Option | Required | Default | Meaning |
| --- | --- | --- | --- |
| `--result FILE` | yes | none | File to write the outcome to, as one JSON document. Its folder must exist. |

Prerequisites: macOS, the Python release `requires-python` names in the project's
`pyproject.toml`, and the folder that will hold `--result`.

## The result

One JSON document, `{"outcome": ..., "detail": ...}`, mode 0600, replaced in one step so
a reader never sees half of it. The outcome and its detail are also printed as one line.

| Outcome | When | Detail |
| --- | --- | --- |
| `granted` | osascript exits 0 with a state | The player state |
| `not-running` | osascript exits 0 with no state: Music is closed, nothing was asked | Empty |
| `denied` | osascript's error ends `(-1743)` or `(-1744)` | The first line osascript wrote |
| `timed-out` | osascript's error ends `(-1712)`, or the `GRANT_PROBE_TIMEOUT_S` bound expired | The first line, or that it did not finish |
| `error` | Anything else, osascript failing to start included | The first line, or its exit code |

## Exit codes

| Code | Meaning |
| --- | --- |
| `0` | The result was written, whatever its outcome |
| `1` | The result could not be written; one `ERROR:` line names the kind of failure |
| `2` | A usage error |

## Tests

`test_grant_probe.py` replaces osascript with a fake in every test: nothing in it starts
a process, reaches Music.app or raises a permission prompt.
