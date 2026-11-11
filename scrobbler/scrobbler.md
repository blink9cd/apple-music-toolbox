# scrobbler

listensmith's Music.app adapter. A background app watches what Music.app plays, writes
every play heard for more than two seconds to a local queue as a listensmith `single`
record, sends that queue to the listensmith store on this Mac, sends a now-playing record
to the listensmith relay on this Mac for each change, and reports its health in a status
file that `scrobbler.py status` reads.

listensmith, the listen store and relay it pairs with, is not yet published. The record
contract the scrobbler writes ships here, as the copy under `contract/` with its schemas,
so any store that implements that contract can receive what it sends.

## What it never does

- **It never controls playback or changes the library.** It listens to Music.app's own
  playerInfo notice and makes two reads, the player's position and the current track's
  properties. No script it runs sets anything.
- **It never launches Music.app.** The app checks that Music.app is running before any
  script runs, compiles its scripts only on the first read after that check, and each
  script opens with its own running check as well.
- **It sends nothing beyond the loopback address.** Listens go to `127.0.0.1` on the
  store's port, and what is playing now to `127.0.0.1` on the relay's port, and nowhere
  else; the client follows no redirect and uses no proxy.
- **It never writes the store's token anywhere.** The token is read afresh for each send
  and is in no log, no status file and no error message.

## The two halves

- **The app**, a SwiftPM package under `app/`: a tested core (`ScrobblerCore`), a thin
  live layer that talks to Music.app (`ScrobblerLive`), and the `scrobbler` executable.
  The live layer and the executable are the real-host seams, kept free of logic and
  excluded from the coverage bar; the live smoke test, disabled unless
  `SCROBBLER_LIVE=1`, is what proves them (see *The live smoke test*).
- **The command line**, `scrobbler.py`, which builds, signs, installs and uninstalls the
  app and reports its health. It never reads the token and never talks to Music.app.

Both read one layout file, `layout.json`: the version, the bundle ID, the launch agent's
label, the file names and every home-relative path. The Python half reads it at runtime
through `src/scrob_layout.py`; the Swift half restates it as constants in
`ScrobblerCore`'s `Layout`, and a Swift test fails when the two disagree.

## The records

`ScrobblerCore` models the two submissions it sends, a listen (`ListenRecord`) and a
now-playing item (`NowPlayingRecord`), with one property per `additional_info` key the
contract copy under `contract/` defines. `RecordCoding` writes every record one way:
compact, keys sorted, slashes unescaped. Decoding refuses what the contract's structure
refuses: an undefined `ls_` key or any other undefined key outside `additional_info`, a null
on a defined key, a value of the wrong type, a listen type the record does not take, and a
key that belongs to the other kind of record. It keeps a plain key the contract allows but
does not define, so every valid sample reads back losslessly. Bounds, patterns and the rules
tying one key to another stay the schema's to check.

`contract_built/` holds the golden records the Swift tests build and compare byte for
byte, among them the `stopped` record the engine itself sends when Music.app quits;
`tests/test_contract_copy.py` validates each against the copied schemas. After a
deliberate change to a record, run the Swift tests once with `SCROBBLER_REGOLD=1` to rewrite
the files, then review the diff.

`status_built/` holds the same kind of golden copy of `status.json`: one with every field
set and one with every optional field `null`, each written by the app's real status writer.
`tests/test_scrob_status_golden.py` reads each with the Python status reader and checks
the values, so a key renamed on either side fails a test. The same `SCROBBLER_REGOLD=1` run
rewrites them.

`launch_argument/start-word.txt` holds the one argument the launch agent passes to the app.
`tests/test_scrob_launch_argument.py` requires it to equal `RUN_ARGUMENT`, and the Swift
`CommandLineTests` require the real parser to turn it into the run command, so renaming
the word on either side fails a test on that side, not an agent that exits 2 and restarts
every 10 seconds. A shared file was chosen over a Python test that reads the Swift source
because it exercises the parser's behavior, not a literal's spelling, and it follows the
`status_built/` pattern. It is hand-written, so it has no regold step.

### Refreshing the contract copy

`contract/` is a byte-for-byte copy of the contract's files, with `MANIFEST.sha256` beside
them; a test fails when a copied file no longer matches its manifest line. To refresh it
after a contract release, copy each of the contract's files over, then inside `contract/`
run:

```text
shasum -a 256 <paths> | LC_ALL=C sort -k2 > MANIFEST.sha256
```

`LC_ALL=C` keeps the manifest in code-point order, which its test demands; a UTF-8
locale's sort skips punctuation. Then run the Swift tests, since a changed bound or key
can change what the record builder may write.

## The app

### How a play is counted

The app reports and never judges: the store decides what counts as a listen, and the app
writes down what was heard.

- **Heard time comes only from Music.app's own reads.** While a track plays the app reads
  the player's position every 2 s, and credits the time between two reads only when the
  position moved with the clock. A read more than 1.5 s away from where the position should
  be is a scrub, and the interval it spans is not credited, so a scrub can undercount by one
  poll and never overcounts. A pause notice adds the time since the last read, at most one
  poll, but only when that read set the time base. Notices are hints, never evidence: they
  open, pause and close plays, but a sequence of notices with no position read between them
  credits nothing.
- **Notices are debounced.** Music.app sends them in duplicate pairs, and a scrub as a
  paused-then-playing pair a few milliseconds apart, so the newest notice in a quiet
  window of 250 ms is the one acted on.
- **A play is queued once more than 2 s of it was heard.** The floor applies to each piece
  of a play on its own. `duration_played` is the whole seconds heard, rounded down;
  `duration_ms` is the newest track length read.
- **A long pause splits a play.** A pause of 30 minutes or more closes the piece heard
  so far and starts the next piece of the same play, with the same play ID. Any input
  arriving more than 30 minutes after the last one is read the same way, as a pause from
  the last observation, so a Mac that slept splits the play on wake with no sleep notice.
- **A play restored after the app was down is not split by that rule**, however long the
  app was down: the restore reads the saved play, and the next position read decides
  whether the same track is still playing. The heard seconds stay correct.
- **Piece 999 rolls over.** The contract's last piece number is 999, so a play that
  reaches it closes and continues under a new play ID, from piece 1, keeping the same
  track's snapshot.
- **Going back to the start is a new play.** A read at 3 s or less after one past 3 s is a
  repeat, and opens a new play of the same track.
- **A play opened by a position read sends no now-playing until its snapshot arrives**,
  because the read carries no track names. A play opened by a notice sends one at once.
- **A play that cannot be recorded is counted, not invented.** A track with no artist or
  no title, or one whose record cannot be built within the contract, is skipped and counted
  in `status.json`'s `unrecordable_count`. No value outside a schema bound is ever queued:
  an optional integer outside its range is left out and `duration_played` is capped.
- **Music.app's zeros mean absent.** A BPM, track count, disc count, movement number,
  movement count or year of 0, an empty string and a missing date leave their key out. A
  rating of 0 is kept: it means unrated.
- **Text is capped.** A text field longer than 4096 bytes of UTF-8, in a notice or a
  snapshot, is dropped as if absent, so a hostile or broken notice cannot fill the queue.
- **The open play is saved** to `open_play.json`, in the state folder, on every change. On
  start the app reads it once: the same track still playing continues the play, anything else closes it
  with the seconds saved. A snapshot that failed as malformed or with no current track is
  not retried within that play; a restored play with no snapshot reads it once.

While a track plays, the app holds an activity assertion so App Nap cannot stretch the
two-second poll, and releases it on pause.

### Now playing

The app builds a contract-valid `playing_now` record on every change and on a 30 s
heartbeat, and one more with `ls_state` `stopped` when a play closes because Music.app quit
or the player stopped, carrying the closed play's track and its last position, so the
relay's pages go idle at once instead of after the stale window. Each goes two ways:

- **To `status.json`.** The newest is kept in `now_playing`, shown while paused, and set to
  `null` once the play closes.
- **To the relay.** Each is posted to `http://127.0.0.1:<relay_port>/1/submit-listens` with
  the store's token, by the same HTTP client the drainer uses but with a 2 s timeout; the
  relay answers 200 as ListenBrainz does. Nothing is queued: one request is in flight at a
  time, a record made meanwhile replaces the one waiting behind it, and a record whose
  send fails, is answered with anything but 200, or cannot start because the config or the
  token cannot be read is dropped, since the next heartbeat or change replaces it. A relay
  that is not running costs nothing but the refused connection, and appears in no status
  field.

### The files it writes

Everything lives under the data folder, `~/Library/Application Support/listensmith/scrobbler/`
(written `<data>` here), each folder mode 0700 and each file 0600. Every folder is checked,
through an open that does not follow a symbolic link, to belong to you and to be private
before anything is written in it. Every file is replaced atomically: a `.tmp-<uuid>` file
beside the target, written, flushed, renamed over the target, then the folder flushed.

| Path | What it holds |
| --- | --- |
| `<data>/queue/<listened_at>-<play id>-<piece>.json` | One compact `single` record per file, keys sorted. `listened_at` is 10 digits and the piece 3, so names sort in time order and a folder import replays in that order |
| `<data>/refused/<same name>.json` | A record the store refused for good, moved here from the queue; or one larger than the queue's read cap, written here instead of the queue, since it could never be read back to send |
| `<data>/refused/<stem>.why.json` | Beside it, the store's findings when its answer was a JSON object, else the fixed `{"findings":["store answer unreadable"]}`, so no arbitrary text from an answer lands in a file someone may print; for a record over the read cap, the fixed `{"findings":["record larger than the store's per-listen limit"]}`. Always written before the record, so a failed move leaves the record queued to be refused again |
| `<data>/state/status.json` | The heartbeat below |
| `<data>/state/open_play.json` | The play still being listened to, for a restart |
| `<data>/state/scrobbler.lock` | The single-instance lock |
| `<data>/logs/out.log`, `<data>/logs/err.log` | The agent's standard output and error, set by its plist |

A queued or open-play file is read without following a symbolic link, without blocking on
a FIFO, only when it is a regular file, and only up to a cap: for a queued record, the
store's per-listen limit plus a 4096-byte margin, and for the open play 64 KiB. A queued
record that fails any of those stays queued, and the send reports `queue unreadable` once
the rest are sent; an open-play file that fails them reads as no saved play. The limit is
the copied `contract/defaults.json`'s `max_listen_size`, and a Swift test pins
`QueueStore.storeListenLimit` to it, so a contract release that raises it fails that test
until the constant moves with it. The app never queues a record of its own past that cap: each text field it
reads is capped, but together they can still add up past it, so such a record goes
straight to `refused/` with the fixed finding above. It counts in `refused_count`, sets no
`last_queued_at` and no `last_send_error`, and is never sent.

`status.json` is written at start and every 30 s whether or not anything plays, so its
heartbeat means the app is alive. It is format 1, every time is Unix seconds as a JSON
number, and every key is written, with `null` for anything not yet known:

| Key | Meaning |
| --- | --- |
| `format`, `version`, `pid` | The file format, the app's version, and its process ID |
| `started_at`, `heartbeat_at` | When the app started, and when this file was written |
| `music_running`, `playing` | Whether Music.app runs, and whether the position poll is on |
| `queue_backlog`, `oldest_queued_at` | How many listens wait, and when the oldest started |
| `refused_count` | How many records the store refused |
| `last_queued_at`, `last_sent_at` | When a listen was last queued, and last accepted |
| `last_send_error` | The last failure, in the wording below; `null` after a handled answer |
| `unrecordable_count` | Plays skipped as unrecordable |
| `automation_denied` | Whether macOS refused the app's request to read Music.app |
| `now_playing` | The newest `playing_now` record, or `null` |

### Sending: the response table

The app sends one record per request, in name order, after every queued listen, at start,
and every 60 s while a backlog remains. Only one send runs at a time. The store's answer
decides each file:

| Answer | The file | `last_send_error` | Backs off |
| --- | --- | --- | --- |
| 200, accepted or a repeat | deleted | cleared | no, and the wait resets |
| 400 or 413 | moved to the refused folder with its sidecar | cleared | no, and the wait resets |
| 401 | kept | `token refused` | yes |
| 503 | kept | `store unavailable` | yes |
| any other code | kept | `store answered <code>` | yes |
| none: refused connection, timeout | kept | `store unreachable` | yes |

The rest of the wording comes from steps before a request:

| `last_send_error` | When | Backs off |
| --- | --- | --- |
| `token unreadable: <reason>` | the token file broke a rule below; the reason is `missing`, `notRegularFile`, `wrongOwner`, `tooOpen`, `tooLarge`, `malformed` or `unreadable` | no |
| `config refused: <key>` | the config file broke a rule below; the key is `store_port`, `relay_port`, `(file)` for the file as a whole, or `(unnamed key)` | no |
| `queue unreadable` | the queue folder could not be listed, or a queued file could not be read safely | no |
| `queue unwritable` | an answered file could not be deleted or moved, or a new listen could not be queued | yes, for a send |

A failure that backs off waits 5, 15, 60, then 300 s before the next send, staying at 300 s
while it lasts; any handled answer (200, 400 or 413) resets it. `scrobbler.py status` warns
on `token refused`, `token unreadable: ...`, `config refused: ...`, `queue unreadable` and
`queue unwritable`, which a retry cannot cure; the others wait for the store.

**The HTTP client** posts only to the store's and the relay's submit endpoints on the
loopback address, `http://127.0.0.1:<store_port>/1/submit-listens` and
`http://127.0.0.1:<relay_port>/1/submit-listens`, with an ephemeral session: every proxy
setting off, automatic proxy configuration and discovery off, no cache, cookie or
credential store, and any redirect refused, so the token is sent to nothing but those two
loopback ports. A request times out after 10 s to the store and 2 s to the relay, and at most
64 KiB of an answer is read. A failure is reported by its URL error code only. The bundle's
Info.plist allows local networking, which plain `http` to the loopback address needs under
App Transport Security.

### The token

The store's write token is `~/.config/listensmith/token`, which the store makes. The app
reads it with the store's own rules: opened without following a symbolic link and without
blocking on a FIFO, then checked on the open descriptor, so the file checked is the file
read. It must be a regular file, belong to you, grant nothing to group or others, hold at
most 4096 bytes, and hold exactly 64 lowercase hex characters with at most one trailing
newline. It is sent to the store with each listen and to the relay with each now-playing
record, and to nothing else. It is read afresh for each send that has something to send and
held only for that send: never cached, logged or written. No refusal carries any of the file's content.

The token goes to whatever process is listening on the store's and the relay's loopback
ports (`store_port` and `relay_port`, under The config below), and the app cannot tell the
store or the relay from another program that bound its port first. On a Mac shared with
other local accounts, any of them can listen on a loopback port, so keep the store and the
relay running while the app runs, or stop the agent with `scrobbler.py uninstall` while
either is down.

### The config

`~/.config/listensmith/scrobbler.json`, optional, read afresh for each send. With no file
the defaults hold. The file is one JSON object, at most 64 KiB, whose only keys are:

| Key | Default | Rule |
| --- | --- | --- |
| `store_port` | 47831, the contract's store port | an integer from 1024 to 65535, never the relay's port |
| `relay_port` | 47832, the contract's relay port | an integer from 1024 to 65535, never the store's port |

The two ports are compared once both are read, so each may move as long as they differ.
When they are equal, the error names `relay_port` if the file set it, else `store_port`.

Any other key, a value outside the rule, a file that is not one JSON object, and a file
that is not a regular file each refuse the whole config, named by key, never by content.

### One copy at a time

The app takes an exclusive, non-waiting `flock` on `<data>/state/scrobbler.lock` before it
does anything else, and the kernel drops it when the process ends, however it ends.

- **Held by another copy:** one line, `another scrobbler is already running`, and exit 0.
- **The lock file cannot be opened** (a symbolic link at its path included): one line,
  `the instance lock file could not be opened`, and exit 1.

The launch agent restarts the app on any exit, at most once every 10 s. So while a copy
you started by hand holds the lock, the agent's copy starts, finds the lock held and exits
every 10 s, until the hand-run copy exits.

### The app's command line

| Command | What it does | Exit |
| --- | --- | --- |
| `run` | runs the app until it is stopped; the only way to start it, and the argument the launch agent's plist passes | 0 when another copy holds the lock, 1 on a lock, folder or run-loop failure |
| `--version` | prints the version | 0 |
| `replay --trace <file> --out <folder>` | replays a recorded trace into a queue folder; see *The replay sample* | 0 written, 1 a replay error |

An empty command line, an unknown word, a positional value or a missing option is a usage
error: the message and the usage, exit 2. The program name in the usage comes from the
command line, never a fixed name.

The app logs to the unified log under the subsystem `local.listensmith.scrobbler`, in the
categories `app`, `music` and `coordinator`. AppleScript failures are logged by their
error number only, never with a message, a script result or a track value.

### Talking to Music.app

The live layer is the only code that touches Music.app, and it holds no decision a test
could reach. Each read runs one of two AppleScripts inside `with timeout of 5 seconds`.
The reads run on the app's main thread, so a hung Music.app can block the app for up to
5 s per Apple event. An AppleScript error maps to a reason: -1743 is Automation denied,
-1728 is no current track, -600 and -609 mean Music.app quit mid-read, and any other number
reads as a malformed answer. The app also watches for Music.app quitting; if that notice
never arrives, the next read finds Music.app gone and closes the play the same way.
Between the in-script running check and the first Apple event there is an unavoidable
window of well under a millisecond in which a launch could race the check.

**The tripwire.** Creating the live bridge inside a test runner (an `xctest` or
`swiftpm-testing-helper` process, or any path holding a `.xctest` bundle) stops the
process unless `SCROBBLER_LIVE=1` is set, so no gate run can reach Music.app by accident.
Set it on the one command that needs it: exporting `SCROBBLER_LIVE=1` in a shell lets
every later gate run in that shell reach Music.app.

**What only a live run can prove**, and the live smoke test checks:

- how `NSAppleScript` turns a track's class, the player state and the media kind into text;
- that the running Music.app has the favorited, disliked, album favorited and album
  disliked properties (a Music.app without them fails the snapshot as malformed, and the
  play falls back to the notice's fields);
- that compiling a script that names Music.app does not launch it;
- that the quit notice arrives in an app with no `NSApplication` object;
- that the date parts, the location read and the length ceiling parse on real tracks, and
  that the notice's persistent ID matches the snapshot's.

## Commands

These are `scrobbler.py`'s; the app's own are above. A refusal (a linked worktree, no
signing identity, a signing setting inside a checkout, a layout file the tool cannot
trust) is one `ERROR:` line and exit 2; a build, sign, verify or launchd step that fails is
one `ERROR:` line and exit 1.

| Command | What it does | Exit |
| --- | --- | --- |
| `version` | prints the layout's version | 0, 2 refused |
| `build --out DIR [--sign]` | builds and assembles the bundle in `DIR`; with `--sign`, signs and verifies it | 0 built, 1 failed, 2 refused |
| `install` | builds, signs and verifies the app, swaps it into the data folder, loads its LaunchAgent, and waits for the app to report its start | 0 started, 1 failed or never started, 2 refused |
| `uninstall` | unloads the LaunchAgent and removes its plist; keeps the app, the queue, the state and the config | 0, 1 when launchd will not settle, 2 refused |
| `status [--session-check]` | the health report below | 0 healthy, 1 needs attention, 2 cannot judge or not installed |

| Option | Command | Required | Default | Meaning |
| --- | --- | --- | --- | --- |
| `--out DIR` | `build` | yes | none | the folder to assemble `listensmith scrobbler.app` in; one already holding the bundle is refused, never overwritten |
| `--sign` | `build` | no | off | sign the bundle with the configured identity, then verify it strictly |
| `--session-check` | `status` | no | off | one line per problem, nothing when healthy or not installed, always exit 0 |

### build

`swift build -c release` on the package under `app/`, with its scratch folder in the
data folder's `.scratch` folder, keyed on the package's path. A build never writes into
the checkout, and never into a shared temporary folder, where another user on the Mac
could replace the product between the build and the signature. The data folder, the
scratch folder and its parent are each mode 0700, and a symbolic link planted in place of
any of them is refused. The scratch folder stays between builds: it is SwiftPM's
incremental cache. SwiftPM is asked where it put the product (`--show-bin-path`) rather than the
layout being assumed. Inside the bundle's Contents folder are the executable, in MacOS, and Info.plist;
the property list names the bundle ID, the display name, the executable, the layout's
version, macOS 14.0 as the floor, `LSUIElement` (no Dock icon), and the text macOS shows
when the app first asks to read Music.app. It holds no signing value.

### Signing

The identity is read from the signing setting `layout.json` names
(`~/.config/swift_gate/signing.toml`), the same file and format swift_gate's `--sign`
reads, by swift_gate's own reader:

```toml
identity = "<codesign identity>"
```

The file must live outside every checkout, even while absent, because a file created
inside one is one `git add` from a commit; such a setting is refused, and so is an absent
one, with how to write it. Signing is
`codesign --force --sign <identity> --timestamp=none` on the bundle, then
`codesign --verify --strict --verbose=2`. The identity is never printed in full: only its
first word and an ellipsis, and every line of codesign's output passes through
swift_gate's redaction, which scrubs certificate names and team IDs, before it is shown.

### install

1. Refuses an entry script in a linked git worktree: such a checkout is often removed
   once its work is done, and the agent should run from the repository's main checkout,
   which stays. A copy outside every repository may install. git is asked with any
   inherited git location settings dropped, so it answers about the entry script's own
   folder.
2. Reads the signing identity, refusing as above.
3. Builds, signs and verifies a new bundle in `.staging-<pid>/` inside the data folder, so
   a failed build leaves the running app and its agent untouched.
4. Asks launchd about the agent. An unexpected answer is exit 1 before anything is
   replaced, since the swap deletes the old app. A loaded agent is stopped and its plist
   kept, so a failure from here on still reads as installed in `status`.
5. Swaps the bundle in: the old one renamed aside, the new one renamed in, the old one
   deleted. A failed rename puts the old one back. An aside folder an earlier run left is
   removed first. An old app that cannot be deleted is a warning, not a failure: the new
   app is already in place.
6. Writes the agent's plist (the installed app's executable with `run`, kept alive, from
   the data folder, logging to out.log and err.log in its logs folder, `PATH` `/usr/bin:/bin`)
   and loads it, confirmed by launchd's own read-back.
7. Polls status.json, in the data folder's state folder, until the app reports a start
   newer than the moment the old agent was stopped, waiting 0.5, 1, 2, then 4 s between
   reads, for at most 30 s. That moment is taken after the stop, not before the build, so
   a start the old app reported during a long build cannot pass for the new one's. An app
   that never reports is exit 1, naming its error log.

A file-system failure on the way, such as a LaunchAgents folder that cannot be written, is
one `ERROR:` line and exit 1.

At the first play, macOS asks whether listensmith scrobbler may control Music
(Automation). Allow it, or no play is logged.

### status

Exit 2 "not installed" when the agent's plist is absent, asking nothing else. Otherwise,
"cannot judge" (exit 2) when launchctl gives an unexpected answer or codesign cannot run,
and "needs attention" (exit 1) for each of: the agent not loaded; the app missing; the
app failing `codesign --verify --strict`; `status.json` missing, unreadable, not a
regular file, over 64 KiB, not JSON (Infinity and NaN included), of another format, or
holding a time that is not finite; a heartbeat older than 90 s; Automation denied; any play the store refused; a
last send error a retry cannot cure (`token refused`, `token unreadable: ...`,
`config refused: ...`, `queue unreadable`, `queue unwritable`); and a queued play older than an hour, with the last send error.
Text the app wrote is shown cut to 120 characters, with any character that does not print
replaced by `?`, so it can neither forge a line nor reach the terminal as a control.
The output is the verdict line, one `- <kind>: <text>` line per reason, then a table:

```text
listensmith scrobbler: HEALTHY (exit 0)

| Item | State |
| --- | --- |
| agent | loaded |
| app | signed |
| backlog | 0 |
| refused | 0 |
| newest queued | 20 s ago |
| last sent | 40 s ago |
| version | 0.1.0 |
```

`--session-check` is the session-start hook's form: one line per reason,
`listensmith scrobbler: <kind> -- <text>; details: scrobbler.py status`, with the home
folder written as `$HOME`, nothing when healthy or not installed, and always exit 0; a
layout file it cannot trust is one `session check failed` line, naming no path. Every
launchctl and codesign call it makes is clamped to one 20 s budget.

### Help

```text
usage: scrobbler.py [-h] COMMAND ...

listensmith's Music.app adapter: manage the scrobbler app.

positional arguments:
  COMMAND
    version    print the scrobbler's version
    build      build the app bundle, and with --sign sign it
    install    build, sign and install the app and its LaunchAgent
    uninstall  unload the LaunchAgent; keep the app, queue, state and config
    status     report the scrobbler's health

options:
  -h, --help   show this help message and exit

Prerequisites: the Python release requires-python names in the project's
pyproject.toml, and macOS 14 or later. build and install need the Swift
toolchain and codesign; build --sign and install need a signing identity in
the signing setting file layout.json names, outside every checkout. Run
install from the repository's main checkout, never a linked worktree; see
scrobbler.md.
```

## Install and uninstall

For the person who installs it, once per Mac:

1. Install and start the listensmith store first: it makes the token at
   `~/.config/listensmith/token` that the app reads.
2. Write the signing setting, `~/.config/swift_gate/signing.toml`, naming your codesign
   identity (see *Signing*). One stable identity keeps the Automation grant across
   reinstalls.
3. From the repository's main checkout, run `scrobbler.py install`. It ends once the new app has
   reported its start.
4. Play a track. macOS asks once whether listensmith scrobbler may control Music; allow
   it. The prompt reads: "listensmith scrobbler reads the track Music is playing so it can
   log your plays on this Mac. It never changes playback or your library."
5. Run `scrobbler.py status`: `HEALTHY` with a recent heartbeat, and the backlog back at 0
   after the first send.
6. To hear about a problem without asking, run `scrobbler.py status --session-check` from
   a shell's startup file or a session-start hook: it prints nothing when healthy.

Re-run `install` after any change to the app; it swaps the bundle and restarts the agent.
`scrobbler.py uninstall` unloads the agent and removes its plist, and keeps the app, the
queue, the refused records, the state, the logs and the config, so a later `install` picks
up where it stopped. Nothing it keeps is deleted for you; remove the data folder by hand
only once its queue is empty.

## The live smoke test

The live layer is excluded from coverage, so this test is what proves it. It reads the
player's position and the current track, compares the persistent IDs, and waits up to 10 s
for a notice; it never controls playback and prints no track value. From the `app/`
folder:

```sh
SCROBBLER_LIVE=1 swift test --scratch-path "$(mktemp -d)" --filter LiveSmokeTests
```

The outside `--scratch-path` keeps SwiftPM's `.build` out of the tree. Run it twice:

1. **With Music.app quit.** The first test passes, reporting Music.app not running, and
   checks Music.app is still not running after the bridge is made and after both reads;
   the snapshot test is skipped. Confirm by eye that Music.app did not open.
2. **With a local file track playing**, and skip to the next track within 10 s of
   starting the run, so a notice arrives to compare. Both tests pass. When no notice
   arrives, the test prints `no notice arrived within 10 s; skip a track to exercise it`.

A stopped player with Music.app running fails the snapshot test, which needs a current
track. Under `swift test` macOS asks whether the terminal may control Music, not the app;
a denial fails the first test as Automation denied.

## The replay sample

`samples/` holds a hand-checkable run of the play engine with no Music.app, no store and no
network: `samples/trace.jsonl`, a recorded session of three invented tracks, and `samples/expected/`, the
queue files the replay writes for it. `samples/README.md` has the trace format, what each
track exercises, and the commands; in short, from `samples/`:

```sh
out="$(mktemp -d)"
swift run --package-path ../app --scratch-path "$(mktemp -d)" scrobbler replay --trace trace.jsonl --out "$out"
diff -r expected "$out"
```

It prints `3 listens written`, and `diff -r` prints nothing. Each trace line holds a time,
`at`, and exactly one of `notice`, `position`, `snapshot` or `quit`; blank lines are
skipped, and a malformed line is an error naming its line number. Notices are taken as
already debounced, play IDs count up from a fixed start, and snapshot dates are read in
UTC, so the output is the same on every machine. The out folder must be private, as
`mktemp -d` makes it, because the queue writer refuses a folder others can reach.
`ReplayTests` makes the same comparison on every gate run.

## Tests

The Swift tests (`app/Tests/ScrobblerCoreTests`) cover `ScrobblerCore` to 100% of its
regions with fakes for Music.app, the scheduler and the transport; none links the live
layer. The transport's guarantees are tested at a loopback socket the test itself binds.

Every Python suite runs against a temporary home and fakes: swift, codesign and git are a
scripted runner, launchd a scripted set of loaded labels, and time a clock that moves only
when something sleeps, so no test builds, signs, loads an agent, or reads the real home.
The signing identity in them is an invented one, and the tests assert it appears in no
output.
