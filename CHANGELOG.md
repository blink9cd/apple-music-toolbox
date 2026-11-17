# Changelog

Notable changes to this project, newest first.

## 0.4.0 - 2026-11-17

### Added

- `runner`, Apple Music Toolbox Runner: a small signed Mac app (macOS 14 or later) that
  launchd starts in front of a scheduled Python job, so macOS charges the job's Music.app
  automation to the app, under one stable name, rather than to a Python interpreter that
  becomes a new client with every upgrade. The app takes
  `runner --python PATH --script PATH -- [arguments]`, checks its own bundle's signature
  every time it starts, refuses any interpreter or script the allowlist sealed into its
  Info.plist does not hold, starts the script as a child with `posix_spawn`, forwards
  SIGTERM, SIGINT, and SIGHUP to it, and exits with its status. The shipped
  `runner/allowlist.json` names only the grant probe; add your own scheduled scripts to
  it before installing.
- `runner.py`, which builds the app (`build --out`, with `--sign`), installs it
  (`install`: builds, signs, and verifies it, swaps it into place, records its signer,
  and then checks, with a person at the Mac to answer the prompt, that the app may
  control Music), removes it (`uninstall`), reports on it (`status`), and prints the
  installed executable's path for a job whose interpreter and script the allowlist holds
  (`locate`). `status` and `locate` demand the signer `install` recorded, so a bundle at
  the installed path that another identity signed, ad hoc included, is reported and
  refused. Signing reads the same setting file as `swift_gate --sign`, and the identity
  is never printed. `runner.md` states what the allowlist and the checks do not cover,
  among them that whoever starts the app chooses its environment, and so the code that
  runs, and the README's "Getting a signing identity" says how to find or make one.
- `runner/grant_probe`, the one read-only Music.app question `install` asks through the
  installed app to confirm its Automation permission. It never opens Music. `runner.py`
  reads at most 64 KiB of its result file and reports a larger one, or one nested too
  deeply to parse, as a one-line error.
- `signed_app`, a library of the steps both signed apps share: a release `swift build`
  that never writes into the checkout, the `.app` bundle and its Info.plist, signing and
  strict verification, `0700` folders made without following a link, and an upgrade
  in one atomic step (`renamex_np` with `RENAME_SWAP`), so a bundle is at the installed
  path at every moment. An install also removes the staging folders that an earlier,
  killed install left, once its process is gone.
- The scrobbler asks for Music.app's Automation permission before any read, while Music
  is running, and waits for the answer with no time limit, so the prompt is no longer
  withdrawn by a read's 5-second timeout. `status.json` gains `automation_asked_at`, and
  `status` reports a prompt left unanswered for more than 10 seconds. A refusal is asked
  about again at each notice and poll, so turning the switch on in System Settings clears
  it.
- The scrobbler trims its own `out.log` and `err.log` at each start, when either is over
  1 MiB, to its last whole lines within 64 KiB.
- Newly bundled shared library: `nested_checkout`, which tells a tree walker whether a
  directory is the top of another git checkout.
- The bundled `atomic_write` library gains `create_bytes`, which makes a file once and
  never over another, and `read_bytes_nofollow`, which reads only the regular file a path
  itself names (see `atomic_write.md`).

### Changed

- The scrobbler is named Listensmith Scrobbler: its app folder, display name, Automation
  prompt, and status lines say so. The bundle identifier is unchanged, so the Automation
  permission carries over, and `install` removes a copy left under the earlier name. It
  tells that copy from the new app by device and inode, not by spelling, so an upgrade
  that changes only the case of the app's name keeps the new app, under the new
  spelling, rather than deleting it.
- The scrobbler's launch agent restarts it only after a failed exit or a crash. The app
  exits 1 on a failure a fresh copy may get past (another copy holds the lock, the run
  loop stopped) and 0 on a refusal no restart can cure (the lock file or data folders
  cannot be used), so a refusal no longer repeats in `err.log` every 10 seconds.
- The scrobbler makes its data folder, each missing folder above it, and its own
  subfolders `0700`, each opened without following a link, so a link at any of them is
  refused.
- `install` swaps the scrobbler's bundle in one atomic step through `signed_app`, and
  any failure, a `launchctl` that cannot be run included, is one `ERROR:` line, never a
  traceback.
- `library_audit`, `play_count_baseline`, `recently_added`, `tag_refresh`, and the
  scrobbler escape each percent sign, U+001F, tab, linefeed, and carriage return inside
  a name or path that Music.app returns, and read it back exactly. A name holding a
  delimiter can no longer split its row or forge another, and a track whose path holds a
  line break is placed like any other instead of ending `library_audit`'s batch.
- `play_count_baseline` publishes its output with a hard link, so a file another process
  made at the output path after the run's check is refused, exit 2, and left as it was.
- `library_audit` and `phone_audit` share one report delivery and one set of HTML table
  cells.
- `swift_gate` redacts the configured signing identity from codesign's output wherever
  codesign echoes it, short identities included, along with certificate names and team
  IDs.
- `bounded_run.md` records that the Windows job-object path now passes on a Windows
  runner at 100% branch coverage.
- Tests and comments only otherwise: the property tests load a Hypothesis profile
  renamed `deterministic`, several suites are regrouped, invisible characters in tests
  are written as escapes, and comments and docstrings gain serial commas.

### Fixed

- The scrobbler reads the track ID from Music's player notice under its real key,
  `PersistentID`. Before, every notice arrived without an ID and was dropped, so a resume
  was never seen and no listen was queued.
- The scrobbler treats Automation error `-1744` as a denial, as it does `-1743`, and a
  timed-out read (`-1712`) as a read to retry once permission is confirmed.
- The bundled `pyproject_config` reports a hostile `pyproject.toml` as a `ConfigError`
  rather than a traceback, and names an unresolvable entry by its position, never its
  value.

## 0.3.0 - 2026-11-10

### Added

- `scrobbler`, a Mac app (macOS 14 or later, built with Swift 6 or later) that records
  what Music.app plays. It reads Music.app's own playback position, never launches it,
  splits a play on a pause of 30 minutes or more, and queues each listen as a record in
  the listen contract that ships in `scrobbler/contract/`. It posts queued listens one at
  a time to a listen store on the loopback interface, retrying with a 5, 15, 60, and 300
  second backoff, and sends now-playing and stopped records to a relay on the loopback
  interface. It writes a `status.json` heartbeat, runs as a single instance, and refuses a
  token file other users could read. It pairs with listensmith, a listen store that is not
  yet published; any store that implements the contract works.
- `scrobbler.py`, which builds the app (`build --out`, with `--sign` to sign it), installs
  it as a user LaunchAgent (building and signing it first) and confirms it started,
  uninstalls the agent while keeping the app and its data, prints its version (`version`),
  and reports on it (`status`, with `--session-check` to print one line per problem,
  nothing when healthy, and always exit 0).
- `play_count_baseline`, which reads every track's play count from Music.app, never
  writing to it or launching it, and writes a baseline file in the listen contract's
  format, for a listen store to import. A track with no name or no artist is left out and
  counted. It never replaces an existing output file.
- A `contract` extra, `jsonschema` with its pinned requirements, which
  `play_count_baseline` needs to check every baseline it writes. The `test` extra repeats
  the same pins for the contract tests.
- Newly bundled shared libraries: `launchd_agent`, `atomic_write`, `os_schedule_gen`,
  `swift_gate` with `pyproject_config` and `venv_prune`, and `tool_subdirs`, plus a root
  `.swiftlint.yml`.

### Changed

- The license is now two files. `LICENSE` holds the GNU AGPL v3 text exactly as the Free
  Software Foundation publishes it, so GitHub and other tools recognize it. `NOTICE` holds
  the copyright line and the "or any later version" grant. The terms are unchanged:
  AGPL-3.0-or-later.
- The environment-declaration test also scans Swift sources.
- The README covers the new tools' requirements, install, and tests, and type-checking one
  folder at a time.

### Fixed

- `library_audit` no longer reports a false difference between files and tracks when
  Music.app holds a disc number past four digits: such a track now counts as disc 1, as
  its file's tag does.

## 0.2.1 - 2026-11-09

### Added

- `bounded_run`'s `run_bounded` takes `inherit_stderr=True`, which gives the child the
  caller's own stderr instead of a pipe, so a long run's progress lines appear as they
  are written rather than when it ends. The result's `stderr` is then `""`.

### Fixed

- Two of `bounded_run`'s tests failed on Windows and now run only where their subject
  does. The check that an unkillable `ps` is abandoned runs on POSIX alone, as its only
  caller does, and the late-tracking live test waits for a grandchild process on POSIX
  alone, since on Windows the child is still suspended at that point.

### Documentation

- `tag_refresh` explains that a timeout on the very first call of every run usually
  means the login session is locked, not that a hidden dialog is open: while the session
  is locked, Music answers no Apple event at all.

## 0.2.0 - 2026-11-02

### Changed

- `album_stats/tests/test_live_star_rating.py` no longer launches Music.app. It asks
  `application "Music" is running`, which names Music outside any `tell` block, and runs
  its one read-only query only when the answer is `true`; otherwise it skips. Before, it
  checked with a `tell` block, which starts Music.app when it is not running. New tests
  with a fake `run` seam pin the check, and they run offline too.

### Added

- `help_formatter` gains `RawNoneHidingFormatter` and `UnsetHidingFormatter`, which hide
  a default of `None` (and, for the second, an empty list) in `--help`, since no one could
  type either value.

### Fixed

- `--help` no longer prints a default no one could type: `album_stats` drops
  `(default: None)` for `--favorite-min-stars`, and `tag_refresh` (`--whole-library`,
  `--dry-run`) and `library_audit` (`--decode`) drop `(default: False)` for their
  switches. An omitted switch now parses as `None` rather than `False`, so code that
  calls `build_parser()` should test it for truth, not compare it with `False`.
- `bounded_run`: a `ps` snapshot that overruns its bound is killed, given one second to be
  reaped, then abandoned, instead of being waited on with no bound. Under heavy load macOS
  `ps -A` can sit for minutes where `SIGKILL` cannot end it.
- `html_page`'s page check, which the tools' tests run on every page they write, now
  reports every URL-bearing attribute and any `srcdoc`, matches a scheme with its colon
  (`javascript:` included), matches attribute values with their character references
  decoded and CSS with its escapes decoded, knows every void element, and reports an
  attribute given twice. It reads the page's markup only, so a name that looks like a URL
  is no longer a problem.
- `library_audit/tests/test_audit_live.py` and `phone_audit/tests/test_phone_live.py`
  load their own file a second time to check its skip markers, and now register that copy
  in `sys.modules` while it loads. A dataclass in the file looks itself up there as its
  body runs, so before, that second load failed instead of returning the markers.
- `stdio_utf8.spell_unsafe` also escapes U+061C, the Arabic letter mark, a direction
  mark like the others it escapes.

### Documentation

- The README gains an Install section with a virtual environment, since Homebrew and
  Debian Python refuse a system-wide `pip install`; shows the offline switch before the
  test loop; and says what `test_live_star_rating.py` does.
- Stale claims are corrected: `recently_added` ranks by the parsed date, not the raw
  string; `album_stats` finds its sibling folders from its own location; and the README
  no longer calls `recently_added` what the whole project turns on.
- The prose in the docs, comments, and `--help` is rewritten without dashes and without
  capitals or bold used for emphasis, and the shared libraries' docs are rewritten for a
  reader outside the tree they came from.
- `pyproject.toml` keeps only the tables a shipped tool or test reads.

## 0.1.0 - 2026-10-27

- Initial release.
