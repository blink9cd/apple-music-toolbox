# launchd_agent.py

Install, uninstall and read a user LaunchAgent, each step confirmed by launchd's own answer
rather than by a launchctl exit code. An import-only library: no CLI and no output.

## Why it exists

Every job that runs under launchd repeats one sequence: write the plist, boot out any loaded
copy, wait until launchd says it is gone, bootstrap the new one, and wait until launchd says it
is loaded. Each tool that carries its own copy of that sequence is one more place for a step to
be skipped or a wait to be trusted on an exit code. This module is that sequence written once;
in this repository the scrobbler's installer uses it.

It decides nothing about what an agent runs. The caller hands it a label, the plist's path and
the plist's bytes, and builds those bytes however it likes; `build_keepalive_plist` is there
for the common always-running case.

## Public surface

| Name | What it is |
| --- | --- |
| `LAUNCHCTL` | `/bin/launchctl`, by absolute path so a minimal PATH cannot shadow it |
| `PRINT_ABSENT_RC` | 113, `launchctl print`'s exit for a service its domain does not hold |
| `DEFAULT_DEADLINE_S`, `POLL_S` | how long one wait may take, and the pause between its reads |
| `LAUNCHCTL_TIMEOUT_S` | the bound on any one launchctl call |
| `AgentState` | `LOADED`, `ABSENT` or `UNKNOWN` |
| `LaunchdError` | launchd did not settle in the wanted state, or answered unknown |
| `Launchctl` | the seam: `run(argv, timeout)`, the `uid`, `clock` and `sleep` |
| `service_target(uid, label)` | `gui/<uid>/<label>` |
| `agent_state(ctl, label)` | one `launchctl print`, read as an `AgentState` |
| `ServicePrint` | one `launchctl print`: its state, its stdout when loaded, and why when unknown |
| `print_service(ctl, label)` | one `launchctl print`, kept whole |
| `wait_for(ctl, label, wanted, deadline_s)` | poll until launchd reports `wanted` |
| `install_agent(ctl, label=, plist_path=, plist=)` | write, replace and confirm loaded |
| `uninstall_agent(ctl, label=, plist_path=)` | unload, confirm absent, then remove the plist |
| `stop_agent(ctl, label=)` | unload and confirm absent, keeping the plist |
| `kickstart_argv(uid, label)` | the command that starts the agent now; never run here |
| `build_keepalive_plist(...)` | the plist of an agent launchd keeps running |
| `real_launchctl()` | the real host seam: `run_bounded`, `os.getuid()` and real time |

## The sequence, and why each wait exists

`launchctl print` has three answers, not two. Exit 0 is loaded, 113 is absent, and anything
else (a timeout and a launchctl that cannot run included) is unknown. An unknown answer ends a
wait at once with `LaunchdError` naming the exit code and stderr's first line. It is never
taken for either settled answer, and polling it would only hide that exit code behind the
deadline. A wait that reaches its deadline says which state it still read:
`<label>: still loaded after 30 s`.

`install_agent`:

1. Writes the plist atomically with mode 0644 (`atomic_write.replace_bytes`), creating its
   folder if absent. It is written before anything is unloaded, so no failure leaves the old
   agent gone with no plist to retry from.
2. Runs `bootout` on the target, ignoring its exit: a first install has nothing to boot out.
3. Waits for absent. `bootout` is not instantaneous, and a bootstrap of the same label while
   the old instance is still tearing down fails or races it.
4. Runs `bootstrap gui/<uid> <plist_path>`, ignoring its exit too: one racing the old
   instance's teardown can exit non-zero (an I/O error) while launchd goes on to load the
   agent.
5. Waits for loaded. This read-back is the confirmation; the exit codes above are not.
   When the agent never loads and bootstrap had exited non-zero, the error adds
   `launchctl bootstrap failed (exit N): <first line of stderr, else stdout>`, so a
   malformed plist or a bad program path says why rather than only `still absent`.

`uninstall_agent` runs `bootout`, waits for absent, and only then removes the plist. While
the agent is still loaded, or its state unknown, the plist is what a retry needs, so a failed
wait keeps it. An absent plist is not an error.

`stop_agent` is `uninstall_agent` without the last step: it runs `bootout` and waits for
absent, and leaves the plist alone. It is for a caller that replaces what the agent runs and
then loads it again with `install_agent`: if anything fails in between, the plist is still
there, so the agent still reads as installed rather than as never installed.

A timeout of `bootout` or `bootstrap` is ignored for the same reason as their exits: the wait
after each reads the real state.

Two failures escape as `OSError` rather than `LaunchdError`:

- **A launchctl that cannot be run at all.** The `print` read-back turns that into an unknown
  answer, but `bootout` and `bootstrap` do not catch it, so `install_agent` raises the
  `OSError` from its `bootout`, after the new plist is written; `uninstall_agent` raises it
  before anything is removed. Either way, re-running recovers once launchctl runs.
- **A plist that cannot be removed.** `uninstall_agent` unlinks the plist only after launchd
  confirmed the agent absent, so an unlink failure surfaces as `OSError` with the agent
  already unloaded; only the stale plist remains.

`build_keepalive_plist` sets `RunAtLoad` and `KeepAlive`, a `ThrottleInterval` of 10 seconds
so a crashing agent is not restarted in a tight loop, `ProcessType` `Background`, the two log
paths, and the agent's whole `PATH`, since launchd's own is minimal. launchd opens the log
paths at spawn and does not create their folder, so the caller creates it. It refuses a label
that `os_schedule_gen.launchd_plist_path` would refuse, by calling it, so a label cannot name
a file outside `~/Library/LaunchAgents`.

## Using it

```python
from pathlib import Path

import launchd_agent

ctl = launchd_agent.real_launchctl()
plist = launchd_agent.build_keepalive_plist(
    label="local.example.serve",
    program_arguments=["<python>", "<script>", "--mode", "serve"],
    working_directory="<working-folder>",
    log_paths=("<logs>/out.log", "<logs>/err.log"),
    path_value="/usr/bin:/bin",
)
plist_path = Path.home() / "Library" / "LaunchAgents" / "local.example.serve.plist"
launchd_agent.install_agent(
    ctl, label="local.example.serve", plist_path=plist_path, plist=plist
)
```

A caller outside `utilities/` reaches the module by searching upward from its own file
for the nearest ancestor holding `utilities/<name>`, as callers in this tree do,
or by a fixed candidate in an export that vendors it, where the folder sits at a known depth
above the caller (the exported scrobbler tries one fixed `parents[1]` path per library).

## How it finds its own libraries

It imports the libraries `_LIBRARIES` names, and finds each by a bounded upward search from
its own file (`_nearest_library`). Each ancestor it reads is tried as
`<ancestor>/utilities/<name>` and then as `<ancestor>/<name>`, and the nearest folder holding
`<name>.py` is appended to `sys.path`.

- **Both shapes, because the module ships in two layouts.** In this tree each library is a
  folder under `utilities/`; an export that vendors them ships each folder flattened at the
  export root, with no `utilities/` folder above it. A search for the first shape alone
  found nothing in an export, so the module could not be imported there.
- **Two ancestors, and no more** (`_ANCESTORS_SEARCHED`): the module's own folder and the
  folder holding it. In both layouts every library is a sibling of this module's folder,
  so both are found there. Searching every ancestor would also reach the folders above an
  export's root, where a same-named folder beside a clone would be imported in place of
  the real library.
- **Appended, not prepended,** so the standard library and the caller's own modules stay
  ahead of anything the search adds.

## Tests

`test_launchd_agent.py` scripts launchd with a fake whose `run` answers each expected argv from
a queue and fails the test on any other, so each test pins the order of the calls and that
nothing else ran. A fake clock advances only when the library sleeps. Temporary folders stand
in for `~/Library/LaunchAgents`, so the suite never touches the real launchd.

One live test installs `local.launchd-agent.selftest` running `/usr/bin/true` from a temporary
folder, reads it loaded, uninstalls it and reads it absent. It mutates the real launchd, so it
is skipped unless the operator opts in with `LAUNCHD_AGENT_LIVE=1`, on macOS:

```bash
LAUNCHD_AGENT_LIVE=1 python -m unittest test_launchd_agent.LiveLaunchdTest -v
```
