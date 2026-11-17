# runner

The command line that builds, installs and inspects Apple Music Toolbox Runner: a small
signed app launchd starts in front of a scheduled Python job, so macOS charges the job's
Music.app automation to the app, under one stable name, instead of to the interpreter.
The app is the Swift package under `app/`; `runner.py` manages it.

## Why it exists

macOS does not charge an Apple event to the process that sent it. It charges the
**responsible process**: the program launchd started, which every child of that program
inherits. `osascript`, which every Python tool here sends its Music.app scripts through,
is never the one charged; whatever launchd started above it is.

A LaunchAgent that names a Python interpreter therefore makes the interpreter the
client, and Privacy & Security > Automation lists it by its file name, such as
"python3.14". An interpreter installed by a package manager is a versioned file outside
any app bundle, known to macOS only by its path and its code, so every upgrade is a new
client: the old permission is left pointing at a file that is gone, and the job's next
unattended run fails until someone answers a new prompt.

The runner is a signed app bundle with a fixed bundle identifier. launchd starts the
app, the app starts the interpreter and the script as its child, and macOS charges the
job's Apple events to the app. A Python upgrade then changes nothing macOS looks at.

A run started from a terminal does not need the runner: macOS charges it to the
terminal app, which already has a name.

## The app

The executable inside the bundle takes one command line:

```text
runner --python PATH --script PATH -- [the script's own arguments]
```

It checks its own bundle's signature, reads the allowlist from its Info.plist, refuses
anything the list does not hold, starts the interpreter on the script with the script's
arguments as a child, waits, and exits with the child's status.

- **It spawns, and never replaces itself.** The child is started with `posix_spawn`.
  Replacing the runner's process image with the interpreter would keep the process and
  hand the responsibility back to the interpreter.
- **Both paths must be absolute**, each option is given once, and `--` is required, so
  one of the script's arguments can never be read as one of the runner's.
- **The child inherits the runner's environment** and its standard streams.
- **SIGTERM, SIGINT and SIGHUP are forwarded to the child**, so the signal launchd sends
  to end a job reaches the Python process doing the work. One that arrives before the
  child exists is held and delivered once it does.

| Exit | Meaning |
| --- | --- |
| the child's own | The child ended; a child killed by a signal is 128 plus the signal's number |
| `1` | The child could not be started, or its status was lost |
| `2` | Refused: a malformed command line, a bundle whose signature does not verify, an allowlist that is missing or malformed, or a path the allowlist does not hold |

Each refusal and failure is one `ERROR:` line on standard error.

## Prerequisites

- macOS 14 or later, and the Python release `requires-python` names in the project's
  `pyproject.toml`.
- A git checkout holding this tool. `build` and `install` ask git for the checkout's
  root (`git rev-parse --show-toplevel`, from this folder), because the allowlist's
  paths are relative to it; a copy outside every checkout is refused.
- `build` and `install` need the Swift toolchain and `codesign`.
- `build --sign` and `install` need a signing identity in the signing setting file
  `layout.json` names, outside every checkout (see *Signing*). The identity is never
  printed.
- Run `install` from the repository's main checkout, never a linked worktree, with the
  interpreter the scheduled jobs use, with Music open, and stay to answer the permission
  prompt macOS shows.
- Run `install` before installing a job that starts through the runner.

## Commands

```text
runner.py build --out DIR [--sign]
runner.py install
runner.py uninstall
runner.py status
runner.py locate --python PATH --script PATH
```

| Command | What it does |
| --- | --- |
| `build` | Builds the app bundle into `--out`, with the allowlist in its Info.plist; with `--sign`, signs it and verifies the signature |
| `install` | Builds, signs and verifies in a staging folder, swaps the bundle into the data folder, records its signer, then checks that the app may control Music |
| `uninstall` | Removes the bundle, and a grant-check agent a stopped install left. A job that starts through the runner then fails until it is reinstalled or the runner is |
| `status` | Reports whether the app is installed and its signature verifies as the identity it was installed with, and lists what it may start |
| `locate` | Prints the installed executable's absolute path on one line, for a job whose interpreter and script the installed allowlist holds |

| Option | Command | Required | Default | Meaning |
| --- | --- | --- | --- | --- |
| `--out DIR` | `build` | yes | none | Folder to assemble the bundle in; it must not already hold one |
| `--sign` | `build` | no | off | Sign the bundle with the configured identity, then verify it |
| `--python PATH` | `locate` | yes | none | The interpreter the job runs under, exactly as the job will pass it |
| `--script PATH` | `locate` | yes | none | The script the job runs, exactly as the job will pass it |

## Exit codes

Every refusal and failure starts with `ERROR:` on standard error, never a traceback. It
is one line, with one exception: when `build --sign` or `install` cannot sign the bundle,
or the signature fails its check, the line `ERROR: codesign sign failed (exit N):` (or
`codesign verify`) is followed by what codesign wrote, on as many lines as it took, with
the signing identity redacted.

| Command | `0` | `1` | `2` |
| --- | --- | --- | --- |
| `build` | Built | The build, the signature or its check failed | Refused: no signing setting, a bad allowlist, no git checkout, a bundle already in `--out` |
| `install` | Installed, and the app may control Music | A step failed, or the grant check did not end in a grant | Refused: a linked worktree, no git checkout, no signing setting, a bad allowlist |
| `uninstall` | Removed, or nothing was installed | launchd or the file system failed | Refused: an untrusted layout file |
| `status` | Installed and trusted | The signer was never recorded or its record is unreadable or malformed, the signature fails, another identity signed the app, codesign cannot run, or the allowlist is unreadable | Not installed |
| `locate` | The path was printed | Not used, short of a file-system failure | Not installed, the signer record is missing, unreadable or malformed, codesign cannot run, the signature does not verify, another identity signed the app, the allowlist is unreadable, or a path is not in the allowlist |

An untrusted `layout.json` is exit `2` from every command.

## The allowlist

`allowlist.json` names the scripts the app may start, each relative to the repository
root: the grant probe, and each scheduled script of this checkout that starts through
the app. An absolute entry, one starting with `~`, one holding a `..` part and one that
is not a file in the checkout are each refused.

A build joins each entry to the root of the checkout that holds `runner.py`, pairs them
with the interpreter running the build (unresolved: a virtual environment's `python` is
a link, and the job passes the link's own path), and writes both into the bundle's
Info.plist under `AMTRunnerAllowlist`. The signature then covers the list.

macOS does not check a bundle's Info.plist again when it launches the executable, so an
edited list would not stop the app by itself. The app therefore checks its own bundle's
signature every time it starts, before it reads the list, and refuses to run when the
check fails. It matches each path as an exact string, with nothing normalized, and
`locate` reads the installed list the same way.

To let the app start another script: add its path to `allowlist.json`, run `install`
again with the interpreter that job will use, then install the job.

## What the allowlist and the checks do not cover

- **The allowlist seals paths, not contents.** The signature covers the list of paths.
  It does not cover the files at those paths, the modules they import, or the
  interpreter: whatever sits at an allowlisted path when the app starts it runs under
  the app's permission. The interpreter's path is stored unresolved on purpose, so the
  file a virtual environment's link leads to can change while the list stays the same.
- **The signer check detects a swapped app; it does not prevent one.** `status` and
  `locate` demand that the installed bundle meet the signer `install` recorded (see
  *Status*), so a bundle at the installed path that another identity signed, ad hoc
  included, is reported and refused. macOS itself still grants that bundle: measured on
  2026-11-16, an ad hoc re-signed bundle at the installed path got a grant from Music
  with no prompt. A job agent that already names the app keeps starting it, because
  launchd asks nothing of `locate` at run time; the next `status` is what says so.
- **The record is only as safe as the folder it is in.** Anything that runs as the same
  user can rewrite the signer record along with the bundle, and the check then passes.
  It catches a bundle replaced on its own, not a writer that knows to replace both.
- **The app's check of itself stays a validity check.** The executable verifies its own
  bundle's signature before it reads the allowlist, and it does not ask who signed it. A
  swapped bundle carries a swapped executable, which controls its own check, so a signer
  check inside the bundle would prove nothing; the guard belongs outside it, in
  `status` and `locate`.
- **Whoever starts the app chooses its environment, and so the code that runs.** The
  app hands the child its own environment unchanged, and that environment is whatever
  the app was started with: launchd's, as the job's agent sets it, or anything a process
  running as the same user passes when it starts the app itself. `PYTHONPATH` or
  `PYTHONSTARTUP` there point the interpreter at other code than the allowlisted script.
  The app is also signed without the hardened runtime, so `DYLD_INSERT_LIBRARIES` and its
  kin load a library into the app itself. The allowlist names the interpreter and the
  script that start, not what they then load.
- **The script's arguments are not checked.** Everything after `--` is handed to the
  script as it came. The allowlist names which script runs, not what it is asked to do.
- **The build's scratch folder outlives the build.** `build` and `install` compile in
  `<data>/.scratch` (see *Files*), which no command removes, so a later build starts
  from what an earlier one left there.

## Signing

The identity is read from the signing setting `layout.json` names
(`~/.config/swift_gate/signing.toml`), the same file and format swift_gate's `--sign`
reads, by swift_gate's own reader:

```toml
identity = "<codesign identity>"
```

To find an identity, or make one, see *Getting a signing identity* in the
[project README](../README.md).

The file must live outside every checkout, even while absent, because a file created
inside one is one `git add` from a commit; such a setting is refused, and so is an absent
one, with how to write it. Signing is
`codesign --force --sign <identity> --timestamp=none` on the bundle, then
`codesign --verify --strict --verbose=2`. The identity is never printed in full: only its
first word and an ellipsis, and every line of codesign's output passes through
swift_gate's redaction, which scrubs certificate names and team IDs, before it is shown.

## Install

For the person who installs it, once per Mac:

1. Write the signing setting, naming your codesign identity (see *Signing*).
2. Open Music, so macOS has something to ask about.
3. From the repository's main checkout, with the interpreter the scheduled jobs use,
   run `runner.py install`, and stay at the Mac.
4. When macOS asks whether Apple Music Toolbox Runner may control Music, allow it. The
   prompt's own words are `RUNNER_PROMPT` in `src/run_install.py`.
5. Install ends with `Apple Music Toolbox Runner may control Music.` and exit `0`. Then
   install each job that starts through it.

What `install` does, in order:

- It refuses a linked git worktree, an absent signing setting, and an allowlist that
  does not hold this checkout's grant probe, before it builds anything.
- It removes the staging folders an install whose process is gone left in the data
  folder (one it cannot remove is a warning), then builds, signs and verifies the new
  bundle in a staging folder of its own inside the data folder, and reads the new bundle's designated requirement there
  (`codesign -d -r-`), so a failed build, or a requirement codesign cannot state,
  leaves the installed app untouched.
- It exchanges the new bundle and the old one in one atomic step, so an app is at the
  installed path at every moment, and then removes the staging folder, which now holds
  the old one. A failed exchange moves nothing. A staging folder it cannot remove is a
  warning: the new app is in place. A job running through the old app keeps running.
- It records the new bundle's designated requirement as the app's signer, in the data
  folder (see *Files*). A record it cannot write fails the install with exit `1`, one
  line naming the kind of failure. The new bundle stays installed and the grant check
  does not run, and until the next `install`, `status` and `locate` judge the new bundle
  against the earlier record: a match when the identity is unchanged, "not signed by the
  identity it was installed with" when it changed, and "never recorded" when there was
  none. Run `install` again.
- It runs the grant check below, whose verdict is its exit code. The new bundle stays in
  place whatever the verdict.

Run `install` again after any change to the app, to `allowlist.json`, to the
interpreter's path, or to where the checkout lives. The app has no launchd agent of its
own: each scheduled job's agent starts it.

`uninstall` removes the bundle and a grant-check agent a stopped install left, and keeps
the rest of the data folder. It changes no privacy setting.

### The grant check

After the swap, `install` loads a one-shot launchd agent that starts
`grant_probe/grant_probe.py` through the installed app (see
`grant_probe/grant_probe.md`), so the question is charged to the app exactly as a
scheduled job's will be. It waits for the result file the probe writes, for no longer
than `GRANT_DEADLINE_S` in `src/run_grant.py`, which is longer than the probe's own
bound, and unloads the agent whatever happened. An agent and a result that an earlier,
stopped install left are removed before the new agent is loaded, so neither can answer
for this check. A result file larger than `MAX_RESULT_BYTES`, unreadable, or not a
parseable JSON object with a text outcome and detail (deep nesting included) is an error
result, never a crash. The result decides what install says:

| Outcome | Exit | What install says |
| --- | --- | --- |
| Granted | `0` | The app may control Music |
| Music not running | `1` | Open Music and run install again |
| Denied | `1` | Allow Music under System Settings > Privacy & Security > Automation > Apple Music Toolbox Runner, then run install again |
| No answer, or no result in time | `1` | The permission prompt was not answered; run install again |
| The probe failed | `1` | The first line of what went wrong |

Only a person at the Mac can answer the prompt, which is why the question is asked here
and never left to a scheduled run.

## Status

`status` prints one verdict line, then its reasons:

| Verdict | Exit | When |
| --- | --- | --- |
| `HEALTHY` | `0` | The bundle is there, its signature verifies as the identity it was installed with, and its allowlist can be read. The lines below name the app, the interpreter and each script it may start |
| `NEEDS ATTENTION` | `1` | The signer was never recorded, or its record cannot be read or is malformed; another identity signed the app; the signature fails `codesign --verify --strict`; codesign could not run; or the allowlist is missing or malformed. One line says which |
| `NOT INSTALLED` | `2` | There is no bundle in the data folder |

Both `status` and `locate` read the signer record first, then run
`codesign --verify --strict --verbose=2 -R=<the recorded requirement>` on the bundle,
and read the allowlist only once that passes. codesign takes requirement text as the
value of `-R` with a leading `=` (an argument of `-R=` followed by the text, or `-R`
then `=` and the text); without the `=`, it reads the value as a file's path. Its exit
tells the failures apart: `3` is a valid signature that does not meet the requirement,
reported as "the app is not signed by the identity it was installed with", and any
other nonzero exit is a signature that does not verify. A record that holds something
codesign cannot parse also exits `1`, and so reads as a signature that does not verify;
either way the answer is to run `install` again. Neither the record nor codesign's
output is ever printed: both name the signing certificate. `locate` says the same
things as one `ERROR:` line and exit `2`.

It reads the bundle only. It does not ask macOS whether the permission still stands:
only an Apple event sent through the app can, which is what `install`'s grant check
does.

## When macOS asks again

The rule this tool was designed on is that macOS keeps the permission against the app's
bundle identifier and the certificate that signed it. Nothing here has measured that for
this app: no rebuild, identity change, or uninstall and reinstall has been tried, so the
rows below are that rule applied, to be confirmed at the first install. They also assume
the signing identity is a certificate. An ad hoc signature names no certificate and
changes with every build, so with one, expect the prompt again after every `install`,
whatever a row says about the permission standing. `install` ends with the grant check
either way, so its last line is the measurement.

| What changed | What the rule says it takes |
| --- | --- |
| This checkout was updated past the change that records the app's signer, with a runner installed before it | Run `install` once. Until then there is no signer record, so `status` says NEEDS ATTENTION and `locate` refuses ("the app's signer was never recorded"), and a job's installer stops; a job already installed keeps running. One `install` writes the record and clears both |
| Python was upgraded, and the interpreter path the allowlist holds still works | Nothing. The app is the client, and the list holds a path, not a file |
| The interpreter's path changed, a script moved, or the checkout moved | Run `install` again. Until then the app and `locate` refuse the new path with exit `2`. With a certificate identity the rebuilt app is the same client, so the permission should stand, and the grant check reports whether it does |
| The app was rebuilt and installed again with the same certificate identity | The permission should stand, with no prompt. The grant check reports whether it does |
| The signing identity changed | Be at the Mac for `install`: macOS should read the app as a new one, and the grant check then raises the prompt again. `install` does not compare the new identity with the installed bundle's, so the prompt is how the change shows |
| The permission was switched off in System Settings, or the prompt was denied | Allow Music under System Settings > Privacy & Security > Automation > Apple Music Toolbox Runner. Until then macOS refuses every Apple event a job sends through the app (osascript error `-1743`), and `install`'s grant check says so |
| The app was uninstalled and installed again | The same as a rebuild. `uninstall` itself changes no privacy setting |

## Starting a job through it

A job's installer asks `locate` for the app, passing the interpreter and the script
exactly as its agent will, and writes what `locate` prints as the program of the job's
LaunchAgent:

```text
ProgramArguments = [<path locate printed>, --python, <interpreter>, --script, <script>, --, <the job's own arguments>]
```

`locate` answers for those two paths only: exit `0` means the installed app will start
them, and any other exit means the job's installer should stop and say that the runner
must be installed first. The path is the installed bundle's, so a job installed before
the bundle moved needs installing again.

## Files

| Path | What it holds |
| --- | --- |
| `layout.json` | The app's names, version and home-relative paths |
| `allowlist.json` | The scripts the app may start |
| `<data>/Apple Music Toolbox Runner.app` | The installed bundle; `<data>` is the `data_dir` folder `layout.json` names, under the home folder |
| `<data>/signer_requirement.txt` | The designated requirement of the bundle `install` last signed, on one line, mode `0600`; `status` and `locate` demand it. It names the signing certificate, so it is never printed, and `uninstall` leaves it |
| `<data>/grant/result.json` | The last grant check's result |
| `<data>/logs/grant.err.log` | What the grant check's run wrote to standard error |
| `<data>/.scratch` | The Swift build's scratch folder, kept between builds |
| `<data>/.staging-<pid>` | The bundle an install is building, then the old bundle it replaced; gone when the install ends, or, after a killed install, swept by the next one |
| `<data>/grant/<grant label>.plist` | The grant check's one-shot agent, written and removed by `install`; `layout.json` holds the label. It is kept out of `~/Library/LaunchAgents` on purpose: launchd loads every plist there at login, and an unload launchd cannot confirm keeps the plist for a retry |

Every folder under `<data>` that these commands make is made private to its user, by
signed_app's `make_private` (see `../signed_app/signed_app.md`).

## Tests and the hand check

`test_runner.py` folds the suites in `tests/`, and the probe's own suite in
`grant_probe/`, into one run; swift, codesign, git, launchd
and the clocks are signed_app's fakes, and no test reaches Music.app, osascript or the
home folder. `samples/README.md` is the hand check of an unsigned build.

The Swift tests under `app/Tests/RunnerCoreTests` cover the app's core with a fake
spawner, and start no process. The live layer (the spawner, the signal forwarder and the
self-check) is excluded from coverage, and `app/Tests/RunnerLiveTests` is what proves the
first two: it runs only with `RUNNER_LIVE=1`, and starts `/usr/bin/true` and `/bin/sh`
only, never Music.app or osascript. From the `app/` folder:

```sh
RUNNER_LIVE=1 swift test --scratch-path "$(mktemp -d)"
```

The outside `--scratch-path` keeps SwiftPM's `.build` out of the tree. The self-check is
proven by the installed app: the grant check ends in a grant only when it passes.

From the repository root, the Python suite, which runs the grant probe's suite too:

```bash
python runner/test_runner.py
```
