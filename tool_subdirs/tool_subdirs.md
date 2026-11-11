# tool_subdirs.py

Shared library (not a CLI) owning the names — and the reachability rules — of the three
subdirectories a tool folder may contain.

## Why it exists

A file that outgrows the file-length bar has two possible fixes, and only one of them is
acceptable: **decompose it, never compress it.** Squeezing a file to fit a line cap trades
reviewability for a mechanical measurement, which is the opposite of what the cap is for.

But the layout rules make the obvious decomposition illegal. `folder_layout` gates any
`<x>.py` / `<x>.sh` whose stem differs from its folder name (`foreign-primary`), and
`python_gate` gates a module with no paired test (`unpaired-module`) and a test with no
paired subject (`unpaired-test`). A tool folder therefore cannot simply grow a second file.
This module defines the three subdirectories where it **may**:

| Name | Holds | Reachable from the parent via | Visibility |
| --- | --- | --- | --- |
| `tests/` | decomposed Python test suites | a `test_<folder>.py` aggregator | public |
| `lib/` | sourced shell helpers | the `<folder>.sh` primary script | private |
| `src/` | private Python modules | the `<folder>.py` primary script | private |

```text
utilities/folder_layout/          tools/shell_tool/
    folder_layout.py                  shell_tool.sh
    folder_layout.md                  shell_tool.md
    test_folder_layout.py             coverage.sh
    src/                              test_shell_tool.py
        report.py                     lib/
    tests/                                state.sh
        test_checks.py                    preflight.sh
        test_discovery.py
```

`tests/` is **public**: a runner reaches its contents through the aggregator. `lib/` and
`src/` are **private** — their contents exist only to serve the one tool whose folder they
sit in, and nothing outside it may import or source them. That split is why the two private
dirs share a reachability rule and a stray rule while `tests/` has its own.

## Why not the escape hatches that already exist

`folder_layout` accepts a multi-script folder via `[tool.folder_layout].allow`, and
`file_length` accepts an over-cap file via `[tool.file_length].exclude`. Both are
**whole-target opt-outs** — `folder_layout.py:316` skips an allowlisted folder entirely — so
using either to decompose buys the split at the price of a permanent blind spot. A pruned
subdirectory is a **typed location** instead: the parent stays fully gated, and only the
declared directory is exempt, under rules this module states.

## `src/` presumes a folder with ONE test unit

`python_gate` scopes coverage per unit, but it adds `src` to the source set of **every**
unit in the folder (`--source=<subject>,src`). With one test unit that is exactly right --
the private modules are measured, so `src/` cannot become a place to hide uncovered code.
With several, it makes every suite responsible for covering private modules it has no
reason to touch.

Measured on a four-unit folder: moving a D-Bus parser and backend into `src/` dropped one
unrelated suite to 32.97%, because it imported the parent module and was then charged for
private modules belonging to a different subject. Nothing was wrong with the tests.

So in a multi-script folder -- one carrying `[tool.folder_layout].allow` -- extract to
**sibling modules with paired tests** instead. Coverage then scopes per pair, which is what
the pairing rule is for, and the folder keeps the shape its allow entry already documents.
Reach for `src/` when the folder has a single primary and a single suite.

**`tests/` is not free parking for shared fixtures either.** A `tests/` dir with no
`test_<folder>.py` beside it is reported as a skipped grouped-suite dir -- correctly, since
nothing would run what it holds. (A fixture module that is not `test_*.py` is not a suite,
so the reach check below never asks it to be discovered.) Shared fixture data belongs in a sibling module with its
own paired suite, which is worth having anyway: a corrupted fixture otherwise surfaces as a
puzzling failure in whichever suite happens to touch it first.

## What a grouped file may rely on

A grouped file runs inside its aggregator's single `unittest` discovery, sharing one
process-global `sys.path` with every sibling loaded before it. Passing there proves the file
imports **after** those siblings, not that it imports on its own: an alphabetically earlier
sibling may have inserted a directory it needs too.

(A runner that opts an aggregator in to running each grouped file in its own process
gives that file a `sys.path` it shares with no sibling. The rule below still stands: the same file runs in one shared discovery at width 1,
under a plain `unittest` run, and in every unmarked aggregator.)

So a grouped file may rely on exactly the directories its aggregator puts on `sys.path` **for
its suites**, plus whatever its own bootstrap inserts -- never on a directory an earlier
sibling inserted, nor on one the aggregator inserts only for its own imports. Unless the
aggregator declares otherwise, that context is the suite dir (discovery's top-level dir),
then the tool folder. An aggregator that gives its suites a different set declares it in an
`# import-alone:` comment, because nothing in its code separates the two audiences: one
`sys.path.insert` looks the same whichever it serves.

A check that holds the contract imports each grouped file alone in a fresh interpreter given
exactly that context.

## Decomposing a CLI: keep the argument parser with the entry point

Splitting a CLI folder has one seam that looks obvious and is not. Extracting the `argparse`
construction into an argument layer leaves the argv parser in one module and `main` in
another, and `stdio_policy` reads any non-test module that parses argv as an entry point that
must force UTF-8 streams -- a finding its baseline cannot absorb. The check is right: the
parser is part of the CLI's own surface. Keep `parse_args` beside `main`, and let the
argument module own validation only.

The same split also converts every `print` in the extracted layers into `PRINT_IN_LIBRARY`,
because those layers no longer own the process's stdout. Pass the stream down from the module
that parses argv rather than baselining the findings -- they are new, and the baseline is for
absorbing history.

## Why one module and not three

All three conventions are the same shape: a directory pruned from a gate's walk whose
contents are reachable only through an explicit link from the parent. Pruning is the easy
half; **saying what the pruning cost is the half that keeps a gate honest**, and every
consumer needs the same two answers — *what is this directory called* and *what did skipping
it hide*.

Writing that shape in three modules would triplicate it and force a reader to know all three
exist. One module owning "directories a tool folder may contain" is the single source of
truth consumers ask, so none can drift onto a colliding name.

## Why the names are these names — collision counts, not preferences

Each name was measured against this tree before it was chosen, because the failure mode of a
wrong name is **silent**: a consumer that prunes a name already in use removes a real
directory from a gate's discovery and keeps reporting PASS for code nobody is checking.

| Name | Chosen | Rejected alternatives, and why |
| --- | --- | --- |
| `tests` | plural | `test` names **two** real C / C# test trees the sweep gates today |
| `lib` | 0 collisions | `helpers` = 1 real dir **and** a delivery-zip carve-out; `shared` = 3 real dirs |
| `src` | 4 dirs, none of them this convention | — (the name is shared; content decides) |

`helpers` fails twice, and the second failure is the dangerous one: `CARVEOUT_DIRS` is
applied at `build_delivery_zip.sh:234`, *before* the whitelist at `:239-241`, so a `helpers/`
directory is pruned from the archive and the shipped installer dies on its first `source`.
`shared` is the parent of a baselined installer script.

`src` is the interesting case, and the only name here that another language owns too:
web, C and C# projects all call their own source tree `src`. So unlike `tests` and `lib`,
the collision cannot be designed away by choosing a different word — the name is simply
shared, and a name predicate alone cannot tell whose convention a given `src` follows.

`holds_convention_content` is what tells them apart, by reading the directory's own listing
rather than a fact about today's tree. A `src/` of `.cs` files is not a private-Python-module
dir however it is named, so no `<folder>.py` is demanded of its parent; a `src/` of `.py`
files is, and its parent is held to the reacher exactly as before. This replaced an earlier
"measured safe today" note here, which rested on no `.py` existing under any of the four —
a property of other files that would have gone false silently, and did: the C and C# trees
were reported as orphaned private dirs on the strength of their name alone.

Every predicate matches the **whole** name and is case-sensitive, so `integration_tests`,
`libexec`, `src_gen` and a differently-cased `Src` are somebody else's layout and are left
alone. The safe failure direction is to report an unexpected directory rather than silently
drop one from a gate's discovery.

## The hazards

### Orphaning — the three `*_orphan_reason` functions, and `suite_reach_reason`

A pruned directory's contents run only if the parent links to them, and the only thing that
does is the parent's own aggregator or primary script. A `tests/` with no aggregator holds
suites nothing runs; a `lib/` with no `<folder>.sh` holds helpers nothing sources; a `src/`
with no `<folder>.py` holds modules nothing imports.

An aggregator that **exists** can still orphan a suite, so `tests/` is asked a second
question once `suite_orphan_reason` returns `None`. `unreached_suites` parses the
aggregator's source and returns each `test_*.py` in the `tests/` listing it does not run;
`suite_reach_reason` wraps that in a report line naming every one, sorted. The rule counts
only what runs. A suite is reached by exactly one of:

- a call to any method named `discover` (`unittest.TestLoader.discover`, through any
  receiver), which reaches every suite;
- a **star** import of its module — `from test_x import *` or `from tests.test_x import *`
  — which binds the suite's `TestCase` classes into the aggregator's namespace, where
  unittest's module load finds them;
- **any** import of its module — `import test_x`, `import tests.test_x`, `from tests import
  test_x`, `from test_x import Helper`, or a star import — in an aggregator that also
  defines a top-level `load_tests` function, the protocol hook through which an imported
  module's tests can join the run.

A bare, dotted or named import with no `load_tests` beside it does **not** count: it binds a
module or a helper, not the suite's tests, so unittest never runs them. A relative import
reaches nothing (an aggregator is a top-level module, not a package member). Unparseable
source reaches nothing, so every suite is reported — the syntax error is lint's finding, and
calling it reach would be a clean answer about code nothing runs. An aggregator the caller
cannot **read** (not UTF-8, unreadable, a broken link) reaches nothing too:
`unreadable_aggregator_reason` names the read failure and every suite, and each caller
catches `OSError` and `UnicodeDecodeError` to ask it instead of raising a traceback.

**What this does not prove.** The check is a static read of the source. It does not confirm
that a `discover` call targets `tests/` rather than some other directory, and an import or a
`load_tests` counts wherever it is written — under `if False:` or inside a function nothing
ever calls — exactly as if it ran. It closes the shape that bit (an aggregator that never
mentions its suites), not every way an aggregator can fail to run them.

It exists because the file's existence was once the whole check. An aggregator holding only
its own tests passed it, and a regression test filed in the `tests/` beside it never ran
while its folder gated PASS at 100% coverage. The two aggregator shapes
in the tree both satisfy it: most call `loader.discover(...)`, and a few put `tests/` on
`sys.path` and star-import each suite by name, where a suite added without its import line
is now reported alone.

The language matters, not just the name: `private_orphan_reason` rejects a `lib/` beside a
Python-only tool and a `src/` beside a shell-only one, because shell cannot import a module
and Python cannot source a shell helper. The reason it returns says `source` or `import`
accordingly — a reader told to "import" a shell helper would write a line that cannot work.

The question also **presupposes** that the directory is the convention its name claims, which
is the next hazard's subject. A caller asks `holds_convention_content` first and skips the
orphan question when it is false; asking anyway produces a finding a reader cannot act on.

### A name that is not the convention — `holds_convention_content`

All three names describe **Python and shell** decomposition, and two of the three words are
also ordinary directory names in other languages. A directory can therefore satisfy
`is_src_dir` perfectly and still be a C, C# or web source tree — at which point the
reachability rule above is asking the wrong question. The finding it produces is true by the
rule's letter and unactionable by its intent: no `c.py` will ever sit beside a C project's
`src/`, so the only way to satisfy the gate is a stub module written to quiet it, which is
worse than the finding.

`holds_convention_content(dir_name, subdir_filenames)` answers it from the directory's own
**direct** listing — `.py` for `tests/` and `src/`, `.sh` for `lib/`. Direct is deliberate:
a consumer puts `src/` itself on `sys.path` and imports from it top-level, and an aggregator
imports its suites the same way, so a nested-only tree is not the shape either convention
takes. An empty directory is not the convention either, and needs no orphan finding regardless
— it hides no code.

It narrows the orphan reports and **nothing else**. The stray rule below stays unconditional
because it asks a different question: whether a filename re-registers the directory as one of
`gate_tree`'s sweep units. That keys on the name alone, so a `coverage.sh` inside a C
project's `src/` drops that project from the sweep exactly as it would inside a tool's. A
single guard covering both questions would have silenced it.

### A stray unit marker — `stray_reason` (private dirs only)

The sharpest failure of the lot. `gate_tree` discovers a sweep unit as any directory directly
holding a `coverage.sh` or a `test_*.py`, and gates a unit holding others with them excluded
(`gatetree_discovery.py`, `nested_units`). Put either name inside a `lib/` or `src/` and that
directory registers as a unit nested in the tool folder — **the tool is gated without it**,
so the tool's own tests stop measuring the code inside it and the sweep still reports PASS.

The same two basenames are `build_delivery_zip.sh:96`'s release-mode `TEST_EXCLUDES`, so a
release archive would lose them too.

The rule is pinned to exactly those two shapes: a `test_*.sh` is neither a `gate_tree` marker
nor a zip exclude, so flagging it would invent a rule no consumer enforces. Asking
`stray_reason` about `tests/` raises `ValueError` — holding `test_*.py` is that directory's
entire purpose and `gate_tree` prunes it deliberately, so there is no clean answer, and a
silent one would be worse than a crash.

## Public surface

| Name | Meaning |
| --- | --- |
| `SUITE_DIR_NAME` · `LIB_DIR_NAME` · `SRC_DIR_NAME` | `"tests"` · `"lib"` · `"src"` |
| `is_suite_dir(name)` · `is_lib_dir(name)` · `is_src_dir(name)` | Whole-name, case-sensitive. |
| `is_private_dir(name)` | `lib` or `src` — the set `stray_reason` governs. |
| `is_tool_subdir(name)` | Any of the three; what `folder_layout` prunes. |
| `aggregator_filename(folder)` | The `test_<folder>.py`; folds `-` to `_`. |
| `primary_script_filename(folder, dir_name)` | `<folder>.sh` for `lib`, `<folder>.py` for `src`; `ValueError` otherwise. |
| `suite_orphan_reason(folder, parent_filenames)` | One-line reason the aggregator is absent, else `None`. |
| `unreached_suites(aggregator_source, suite_filenames)` | The `test_*.py` the source does not run (discover, star import, or import + `load_tests`), sorted. |
| `unreadable_aggregator_reason(folder, error, suite_filenames)` | One-line reason naming the read failure and every suite, else `None`. |
| `suite_reach_reason(folder, aggregator_source, suite_filenames)` | One-line reason naming every unreached suite, else `None`. |
| `private_orphan_reason(dir_name, folder, parent_filenames)` | One-line reason, else `None`. |
| `holds_convention_content(dir_name, subdir_filenames)` | Is this dir the convention its name claims? `ValueError` for an undefined name. |
| `stray_reason(dir_name, subdir_filenames)` | One-line reason, else `None`; `ValueError` for `tests`. |

Both fold rules agree with `folder_layout._normalized`: a tool folder may be hyphenated (a
framework task key such as `lock-phone`) while a Python module name may not, so
`aggregator_filename` folds. A shell filename accepts a hyphen, so `primary_script_filename`
returns the folder's own spelling — which always satisfies the folded comparison — while
`private_orphan_reason` *accepts* either spelling. Deriving the fold here rather than
re-inventing it keeps this module's answer identical to the one `folder_layout` enforces.

Every reason returns `None` rather than `""` so a caller building report lines can filter
falsy values without emitting a blank row — the convention `nothing_examined.note`
established — and none carries an embedded newline, so a caller can splice it into a
per-finding report row.

## The reachability limit the listing reports share

The three `*_orphan_reason` functions check that a plausible linking parent **exists by
name**, not that it actually contains the `import` or `source` line. A parent holding the
right filename that never links to its subdirectory still reads as reachable to them.

For `tests/` that gap is closed by `suite_reach_reason`, which reads the aggregator's
**source** — handed in by the caller, so no function here opens a file and every one stays
pure. `tests/` is the one that needed it: a suite is test code, which no coverage run
measures, so an unrun suite leaves no trace in any figure. For `lib/` and `src/` the gap is
closed from the other side instead: unreached code contributes uncovered lines to its tool's
coverage run, which gates at 100%.

## Consumers

| Consumer | What it asks | What happens without it |
| --- | --- | --- |
| `folder_layout` | prune all three; report orphans (where the content matches), unreached suites + strays | `foreign-primary` / `foreign-test` on every file inside them |
| `python_gate` | prune `tests/` and `src/`; state whether the aggregator reaches each suite | `unpaired-test` on a nested suite; `unpaired-module` on a private module |
| `gate_tree` | prune `tests/`; report its orphans and unreached suites | the `tests/` dir registers as a unit and the parent is **gated without its own suites** |

| `project_export` | whether a root-level folder of the export is the `tests/` dir, so a suite at the root keeps loading its own grouped files | each file in the root's `tests/` is also launched alone beside the root suite that loads it, where it can lack the path set-up that aggregator provides |
| `kcov_cover.sh` | the `lib/` name to stage and include | the helper is unreachable at trace time, then invisible to the coverage denominator |

### The one unenforced rule: a `lib/` helper must carry `# sourced-script`

`shell_lint`'s SL001–SL003 — no `exit`, no `set -e` leaking into the operator's shell, a
guard for the executed case — apply **only** to a file carrying the `# sourced-script`
marker. A helper that omits it is silently unchecked for the three hazards that matter most
in a file the operator's own shell runs.

Every `.sh` in a `lib/` is sourced by definition, so the directory could serve as the
declaration and put its contents in scope automatically. That change is **deferred, not
rejected**: `shell_lint.py` sits at 698 lines against a 500-line cap with its baseline entry
at 698, so it cannot gain a line until roughly 200 come out of it — disproportionate to a
scope predicate. Recorded here so the gap is known rather than invisible.

Until then the rule is **Tier 3, per adopting tool**: assert it in that tool's own suite with
a test that globs the `lib/` directory, so a new helper is covered the day it lands.

`gate_tree` deliberately does **not** prune `lib/` or `src/`: neither holds one of its unit
markers, so neither registers. Verified with `find_units` on a fixture — it returned the
parent tool folder and not the subdirectory. `stray_reason` exists to keep that true.

## Usage

```python
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tool_subdirs"))

import tool_subdirs  # noqa: E402 - import follows the sys.path bootstrap above
```

Prune by asking, and report what the prune skipped:

```python
dirnames[:] = [d for d in dirnames if not tool_subdirs.is_tool_subdir(d)]
...
reason = tool_subdirs.suite_orphan_reason(folder.name, filenames)
if reason is None:  # the aggregator exists: ask whether it reaches each suite
    source = (folder / tool_subdirs.aggregator_filename(folder.name)).read_text(encoding="utf-8")
    reason = tool_subdirs.suite_reach_reason(folder.name, source, suite_filenames)
if reason:
    findings.append(f"  {folder}  {reason}")
```

## Notes

- Every function is **pure** — no filesystem access, no I/O, no config. It therefore carries
  no `stdio_utf8` dependency and cannot fail at import time.
- It ships no `samples/`: there is no input→output transform, so it is a shared library in
  `[tool.samples_presence].exempt`'s documented sense.
- Wiring a sibling-imported library takes a surface invisible to the import itself:
  `[tool.mypy] mypy_path` in this repository's `pyproject.toml`, so that
  `import tool_subdirs` resolves when a single folder is type-checked alone.
- A tool that decomposes into `lib/` or `src/` adds no surface of its own: a packaging step
  that walks a tool folder recursively ships those modules with it.

## History

This module replaces `suite_dirs`, which owned the `tests/` convention alone. The `lib/` and
`src/` conventions were added when the shell and Python *production* decomposition gaps were
found: a shell script over the cap had no lawful split at all, and two gate files
(`folder_layout.py` at 501, `shell_lint.py` at 698) could not grow by even one line without a
rising `file_length` baseline. Three modules of the same shape was the alternative; one was
chosen for the reasons above.

## Testing tool_subdirs itself

From the repository root:

```bash
python tool_subdirs/test_tool_subdirs.py
```
