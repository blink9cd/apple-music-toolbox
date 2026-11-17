# signed_app

The generic steps behind a small signed macOS app that this project builds from a Swift
package and runs under launchd: build it, assemble its `.app` bundle, sign and verify it,
and put it in place. It is a library with no command line; an app's own CLI supplies its
names, its package, its folders and its messages, and calls these steps. Two apps do:
the scrobbler (`../scrobbler/scrobbler.md`) and the runner (`../runner/runner.md`).

## Why a library

Every signed app here needs the same careful steps: a build that never writes into the
checkout or a shared temporary folder, a signing identity that never reaches any output,
folders no other user can swap a link into, and an upgrade done in one atomic step:
macOS's `renamex_np` with `RENAME_SWAP` exchanges the new bundle and the old one, so a
bundle is at the installed path at every moment, a crash included, and a failed exchange
moves nothing. The old bundle ends in the staging folder, which the caller removes. An
install killed partway leaves its staging folder behind, and a later install removes it
once the process that made it is gone.
Writing them once keeps one set of tests and one set of fixes behind every app.

## The modules

All three live in `src/`. A caller reaches them by importing `signed_app.py`, the front
module beside it, which puts `src/` on `sys.path` and then the shared libraries those
modules import (`bounded_run`, `launchd_agent` and swift_gate's `src/`), each at one
fixed place directly under the project root. The scrobbler finds `signed_app.py` the
same way, in the folder of that name beside its own.

| Module | What it holds |
| --- | --- |
| `app_host` | `Host`, every process-level fact a command reads (home, uid, pid, entry script, clocks, sleep, launchctl, the bounded tool runner, the two streams), so a test replaces each one; `tool_environment`, the untranslated, git-location-free environment for swift, codesign and git; `real_host`, this process's. |
| `app_bundle` | `Refused` (exit 2) and `BuildFailed` (exit 1); `BundleSpec`, the read-only names a bundle needs; `swift_build`, a release build into a scratch folder the caller made private, finding the product through `--show-bin-path`; `info_plist`, with the caller's Automation prompt and any `extra` keys merged last; `assemble`; `bundle_executable`, where the executable sits inside a bundle; `read_identity`, through swift_gate's reader, refusing a setting inside a checkout; `sign_bundle`; `verify_argv`, which with an optional `requirement` also demands that requirement of the signer (`-R=<text>`; a valid signature that does not meet it exits `REQUIREMENT_UNMET_EXIT`); and `designated_requirement`, the signature's designated requirement as `codesign -d -r-` states it, for an app to record and demand later. It names the signing certificate, so it never appears in a message. |
| `app_install` | `make_private`, which makes a folder and its missing parents mode 0700 through descriptors, refusing a link, another user's folder, or one it cannot read; `swap_in`, the one-step bundle swap (an exchange through `exchange_paths`, after which an entry spelled otherwise, as a case-only rename leaves on a volume that ignores case, takes the exact name; or a plain rename for a first install); `same_entry`, which tells two paths apart by the entry they name (device and inode, never following a link), never by spelling; `sweep_stale_work`, which removes the `.staging-<pid>` and `.old-<pid>-<app>` folders of installs whose process is gone, never a link or a file, warning on one it cannot remove; `refuse_linked_worktree`, which refuses an entry script in a linked git worktree. |

## What a caller supplies

- **Names:** any object with read-only `bundle_id`, `display_name`, `executable`,
  `version` and `app_name` satisfies `BundleSpec`; each app passes its layout.
- **Words:** the Automation prompt, and every message that names the app, stay with the
  caller, so an app's output does not change when a step moves here.
- **Folders:** the package, the scratch folder (made private first, with `make_private`),
  the output folder, and the signing setting's path.

## Safety properties

- The signing identity is never printed: codesign's output is redacted with
  `swgate_signing.redact` before it reaches a `BuildFailed` message.
- Every tool call is bounded (`SWIFT_TIMEOUT_S`, `CODESIGN_TIMEOUT_S` and `GIT_TIMEOUT_S`
  in `src/app_bundle.py`) and runs with `LC_ALL=C`, since git's "not a git repository" is read as text.
- No step follows a link it did not expect: `make_private` opens each level without
  following one, and `assemble` refuses a bundle that already exists.

## Tests

`test_signed_app.py` folds the suites in `tests/` into one run. `tests/_app_fixtures.py`
holds the fakes every signed app's suites build on: `FakeClock`, `FakeLaunchd`,
`FakeTools` (swift, codesign and git, scripted and logged) and `make_host_kit`, a host on
a temporary home. No test reaches the real codesign, launchctl, swift, git repository,
Music.app or home folder. From the repository root:

```bash
python signed_app/test_signed_app.py
```
