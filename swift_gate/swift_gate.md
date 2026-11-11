# swift_gate

Gate a SwiftPM package: a strict build, its tests, and 100% **region** coverage, at the one
macOS deployment floor the repository configures and in Swift language mode 6. In this
repository it is what builds the scrobbler's app, and what signs and verifies it.

Every `Package.swift` under `--path` is one package, gated in turn through five stages: the
manifest dump, the coverage-marker scan, the build, the tests, and the coverage measurement.
With `--sign`, a sixth signs and verifies the built executables (*Signing* below). The
pipeline is written down in one place, `src/swgate_stages.py`: `STAGES`, then the coverage
`VERDICT`, then the `FINISH` stage that takes the verdict.

## Why regions, not branches

Every other gate in the family measures branch coverage. For Swift that number is useless:
measured on Swift 6.4, the llvm-cov export SwiftPM writes reports `branches.count == 0` for a
function with three outcomes and none of them tested, so a branch percent reads 100% over
nothing. **Regions** are the unit llvm-cov actually counts for Swift code: each `if` arm, each
`?:` arm and each statement run gets one. A probe function with three untested outcomes showed
seven regions, three of them not covered, which is the signal the bar needs.

## Requirements

- **macOS.** On any other host the gate exits 2; it never passes Swift it could not build.
- **The Swift toolchain**: Xcode or the Command Line Tools. `--swift` names a driver;
  otherwise `swift` on `PATH` is used.
- **`[tool.swift_gate] macos_floor`** in the nearest `pyproject.toml` at or above `--path`.
  A missing key is exit 2: the floor is never a silent default.
- Python 3.11 or later (stdlib `tomllib`) for the gate itself.

## Usage

```text
python swift_gate.py --path <dir> [--exclude <path> ...] [--min-percent N] [--swift <driver>] [--scratch-path <dir>] [--timeout-seconds N] [--json] [--sign] [--signing-config <file>]
```

| Option | Required | Default | Meaning |
| --- | --- | --- | --- |
| `--path <dir>` | yes | none | A directory holding SwiftPM packages. |
| `--exclude <path>` | no | `[]` | Prune a path from discovery and coverage; repeatable. Unioned with `[tool.swift_gate] exclude`. |
| `--min-percent <N>` | no | `100.0` | Minimum region-coverage percentage required. |
| `--swift <driver>` | no | `None` (`swift` on `PATH`) | The swift driver to run: a bare name is looked up on `PATH`, anything with a directory part must be a file. |
| `--scratch-path <dir>` | no | `None` (`swift_gate` under the system temp dir) | Base dir for build scratch, one hashed subdir per package. |
| `--timeout-seconds <N>` | no | `1200.0` | Per-call timeout in seconds; a timeout fails the gate rather than hanging it. |
| `--json` | no | `False` (off) | Emit the result as JSON instead of the text report. |
| `--sign` | no | `False` (off) | After a passing verdict, sign and verify a copy of each executable product (*Signing*). Off: the setting is never read. |
| `--signing-config <file>` | no | `~/.config/swift_gate/signing.toml` | The signing setting; must live outside every checkout. A leading `~` is expanded when parsed, so `--help` shows the default symbolically. |

Each package builds into `<scratch base>/<first 16 hex of the sha256 of its resolved path>`,
so two packages never share build state and a run never writes into the checkout. Every
`swift` call passes that dir as `--scratch-path`, including the manifest dump; nothing lands in
the package's own `.build`.

## Discovery

- No `.swift` file and no `Package.swift` under `--path`: exit 0, `nothing to gate`.
- `.swift` files, or an `.xcodeproj` / `.xcworkspace`, that no `Package.swift` owns: exit 2,
  "swift_gate gates SwiftPM packages only". This holds even when a package sits beside
  them, because a loose file no package builds would otherwise pass unseen.
- Otherwise each directory holding a `Package.swift` is one package, gated in turn; the exit
  code is the worst package's.

The walk prunes `.build`, `.swiftpm`, `DerivedData`, the usual VCS and cache dirs, any
virtualenv, and every exclude. A dependency checkout under `.build` is therefore never a
subject. A folder of illustrative `.swift` samples is kept out the same way, by listing it in
`[tool.swift_gate] exclude`.

## Findings

Findings print as `CODE path:line: message`, paths relative to the package.

| Code | Meaning |
| --- | --- |
| `SWG001` | No macOS platform entry, or one whose version is not `macos_floor` exactly. |
| `SWG002` | Tools version below 6.0, a package-level language mode other than 6, or a target `swiftLanguageMode` setting other than 6. |
| `SWG003` | A `// coverage: ignore` marker without a nonblank reason. |
| `SWG004` | A reasoned marker that excludes no region, covered or not (dead). |
| `SWG005` | No code region measured under `Sources/`: the result verifies nothing. |

A failed manifest dump, build or test run is exit 1 with SwiftPM's own diagnostics. Manifest
and marker findings do not stop the pipeline, so one run reports them together with the
coverage shortfall.

## The coverage marker

Swift has no compiler-honored coverage pragma, so the gate defines one and applies it to the
export:

```swift
public func debugLabel(_ value: Int) -> String {  // coverage: ignore: a debugger-only aid
```

- A marker excludes every code region that **starts on the marker's line**.
- A marker on a line declaring `func` or `init` also excludes **every region of that function**:
  the function whose first region starts on the first line, at or after the marker, whose code
  holds `{`. A wrapped signature, whose brace sits on a later line, is reached that way.
- Only the package's own `Sources/` are scanned; test targets need no marker.
- A marker with no reason (`SWG003`) excludes nothing. A marker that excludes nothing
  (`SWG004`) is checked after the export is in, so a marker left behind after its code moved
  cannot go on claiming an exemption.

A closure inside a marked function is its own function in the export, with its own first
region, so it is not excluded by the function marker; mark its line instead.

## The floor and the language mode

The manifest is read from `swift package dump-package`. The keys, verified live on SwiftPM
with Swift 6.4:

| Key | Shape | Used for |
| --- | --- | --- |
| `name` | string | the package name |
| `platforms[]` | `{"platformName": "macos", "version": "14.0", "options": []}` | SWG001 |
| `toolsVersion._version` | `"6.0.0"` | SWG002 |
| `swiftLanguageVersions` | `null`, or `["6", ...]` from `swiftLanguageModes:` | SWG002 |
| `targets[].settings[]` | `{"tool": "swift", "kind": {"swiftLanguageMode": {"_0": "5"}}}` | SWG002 |
| `products[]` | `{"name": "hello", "targets": ["Hello"], "type": {"executable": null}}`; a library's type is `{"library": ["automatic"]}` | `--sign` |
| `targets[].type` | `"executable"` for an `.executableTarget`; `"regular"`, `"test"` otherwise | `--sign` (implicit products) |

Versions compare with trailing zero parts dropped, so a floor of `"14"` equals a platform
version of `14.0`, while `13.0` and `15.0` are both SWG001: the floor is exact, not a minimum,
because one floor for every package is the point. A null `swiftLanguageVersions` means the
tools version's default, which is 6 for tools 6.0. The deprecated `swiftLanguageVersion`
setting key is read too. A dump of any other shape is exit 2, never read as "no platforms".

## Coverage parsing

The tests run serially, as `swift test --skip-build --enable-code-coverage --no-parallel`,
because the counts are the verdict. LLVM's profile counters are plain, non-atomic increments,
and swift-testing runs a package's tests in parallel in one process unless the flag is passed
(SwiftPM's help says `--no-parallel` is the default, which is true of XCTest only). Two tests
entering one function at once can lose an entry increment, and a region counted by
subtraction from that counter, such as a ternary's last arm, then reads 0: a miss the tests did
cover, which passes on a rerun. Measured on a stress package, 8 parallel tests of a million
calls each recorded 3.9 to 4.7 million entries; serially, exactly 8 million every run. A test
that itself calls the code from several tasks at once can still race its own counters, so
keep the coverage-bearing calls of a concurrent test on one task.

After the test run, `swift test --show-codecov-path` names
the export; with the build layout of current SwiftPM it sits under
`<scratch>/out/Products/Debug/codecov/`, not `.build/debug`, which is why the path is asked
for rather than assumed. Every `codecov/*.json` under the scratch dir is deleted before the test
run, so a run that writes no fresh report fails instead of reading an old one.

The export is `llvm.coverage.json.export` 3.0.1. Each `data[0].functions[]` entry carries
`filenames` and `regions`, and each region is the 8-tuple `[line_start, col_start, line_end,
col_end, count, file_id, expanded_file_id, kind]`, where `file_id` indexes that function's
`filenames`. The gate keeps:

- regions whose file lies under the package's `Sources/` and under no exclude, which drops the
  test targets, dependency checkouts and the SwiftPM-generated test runner;
- code regions only (`kind == 0`): expansion, skipped, gap and branch regions are not code a
  test runs.

A span reported more than once counts once, covered if any report of it ran. Percent is
covered over total after marker exclusions; each uncovered region prints as `file:line:col`.
An export of any other shape is exit 2.

## Configuration

```toml
[tool.swift_gate]
macos_floor = "14"
exclude = ["samples"]
```

Read through `pyproject_config` from the nearest `pyproject.toml` at or above
`--path`. That file answers even when it lacks the table: it is never walked past, so a
pyproject above the checkout cannot supply the floor. `exclude` entries are relative to that
file's directory; `macos_floor` is a string. A config error names the file relative to
`--path`, never by its absolute path.

## Signing

`--sign` adds one stage after the coverage verdict. The identity is a local setting, kept
outside every checkout so it is never committed, and a missing one is reported and passes.
Off, the stage does not run and the setting is not read. On, it reads the setting first, before any build:

```toml
# ~/.config/swift_gate/signing.toml, by default: never inside a checkout
identity = "Apple Development: Example (ABCDE12345)"
```

- **Where it may live.** Two `git` questions name the checkouts. In `--path`,
  `git rev-parse --show-toplevel` names the target's checkout and
  `git worktree list --porcelain` names every worktree of it. From the setting path's
  nearest existing directory, `git -C <dir> rev-parse --show-toplevel` names any repository
  holding the setting itself: the target's, a nested one, or an unrelated one such as a
  dotfiles checkout of the home directory. A setting path at or under any of them is exit 2,
  "the signing identity must live outside every checkout", even while the file is
  absent, because a file created there later is one `git add` from a commit.
  - A root matches by spelling and by file identity, so `~/Workspace/signing.toml` is
    refused for a checkout at `~/workspace` on a case-insensitive volume.
  - The file read is the resolved path the check accepted, not the path as given.
  - Only git's "not a git repository" means there is no checkout to refuse. Any other
    failure (dubious ownership, a corrupt or unreadable `.git`), a `git` that cannot run or
    times out, or a failed worktree list is exit 2 rather than a skipped check.
  - `git` runs without `GIT_DIR`, `GIT_WORK_TREE`, `GIT_COMMON_DIR` and
    `GIT_CEILING_DIRECTORIES`, so a gate launched from a git hook, or under a ceiling, still
    asks about the real paths, and with `LC_ALL=C`, so the "not a git repository" match
    holds in a translated session.
- **Absent:** each package reports `signing: not configured (<path> absent)` and passes.
- **Malformed** (not TOML, not UTF-8, a missing, empty or non-string `identity`): exit 2. No
  message quotes the file's content.
- **Configured:** only a package whose verdict passed is signed; a failed one reports
  `signing: skipped, the gate already failed`. The executables are the dump's `products[]`
  of type `executable`, then each `targets[]` of type `executable` that no declared
  executable product names: SwiftPM builds an implicit product of the target's own name for
  it. None is `signing: nothing to sign`. The product dir is asked of SwiftPM
  (`swift build --show-bin-path` with the same `--scratch-path`), never assumed, since its
  layout varies by toolchain. Each product is copied to a temp dir, and the copy gets
  `codesign --force --sign <identity> --timestamp=none`, then
  `codesign --verify --strict --verbose=2`. Either nonzero is exit 1 with codesign's
  redacted output; `codesign` that cannot run is exit 2.
- **Shown, never in full.**
  - The identity prints as its first word plus `…` (`Apple…`). A one-word identity (a
    SHA-1 hash, a bare team ID, the ad-hoc `-`) has no safe prefix and prints as
    `<identity>…`.
  - codesign's output is redacted whatever the identity, because an ambiguous identity makes
    codesign echo the full common name of every certificate it matched. Each
    `<Type>: <Name> (<ID>)` common name keeps only its type (`Apple Development: …`), the
    name running to the nearest team ID even when it holds a colon, a parenthesis or a
    quote, and
    each parenthesized ten-character team ID becomes `(…)`. The configured identity and
    its own team ID are scrubbed too, except where the rendering would not shorten the
    identity, so the ad-hoc `-` leaves codesign's own `--flags` intact.
  - Every path under the running user's home, in swift_gate's own messages and in
    codesign's, prints from `~/`, so a log pasted into an issue carries neither a team ID
    nor the home directory's layout.

## Exit codes

| Code | Meaning |
| --- | --- |
| `0` | Every package clean, or nothing to gate. |
| `1` | A finding, a failed dump, build or test run, no coverage report, a timeout (naming the stage), coverage below `--min-percent`, or with `--sign` a failed `codesign` sign or verify. |
| `2` | Could not run: not macOS, no toolchain, Swift outside any SwiftPM package, no or a malformed `macos_floor`, unreadable config, an untrusted dump or export, or with `--sign` a malformed signing setting, one inside a checkout, or no `codesign`. |

## Example

`tests/fixtures/floorpkg` is a library at the macOS 14 floor with one function of three
outcomes, fully tested, and one reasoned function marker. Gated from a copy beside a
`pyproject.toml` carrying the floor:

```text
== <tmp>/floorpkg
PASS: 0 finding(s), region coverage 100.00%
Gated 1 SwiftPM package(s) at >= 100% regions.
SWIFT_GATE FINAL RESULT: PASS
```

With the `zeroIsZero` test removed, the same run fails and names the region that test reached:

```text
== <tmp>/floorpkg
miss Sources/Floor/Floor.swift:13:23
region coverage 83.33% < 100%
FAIL: 0 finding(s), region coverage 83.33%
```
