# nested_checkout.py

Shared library (not a CLI) owning one question for every tree walker: **is this
directory the top of another checkout?** It is answered from the `.git` entry git itself
uses to find a checkout's top, not from a directory name or an ignore rule.

## The problem it solves

A tool may keep linked worktrees inside the checkout they belong to: a session-worktree
layout, for example, puts each under `.claude/worktrees/<name>/`, a full copy of the
tree. A walker rooted at that checkout that descends into one gates, counts, lints or
(for a cleaner) deletes another session's files as if they were its own.

Most walkers were safe only by accident. Some pruned every dot-directory, or the name
`.claude`; the rest leaned on `.gitignore` listing the worktrees' folder and on git
answering the ignore query. Each of those covers one location, and the ignore route
fails open whenever git cannot answer. A nested checkout anywhere else, or one that is
not ignored, was still walked.

## The contract

| Name | Returns |
| --- | --- |
| `MARKER` | `".git"`, the entry that marks a checkout's top |
| `is_nested_checkout(directory)` | `True` when *directory* holds a `.git` entry, a file or a directory |
| `is_under_nested_checkout(path, root)` | `True` when a directory strictly below *root*, at or above *path*'s parent, is a checkout |

- **A `.git` directory** marks a clone; **a `.git` file** marks a linked worktree (it
  holds a `gitdir:` pointer). Both count, because both are a separate copy of a tree.
- **Presence is the contract.** The file's pointer is not parsed: a stricter check could
  only miss a real checkout and walk it.
- **Both are pure queries.** They read paths and write nothing. A missing path reads as
  not a checkout.
- **A path not strictly below *root*** (outside it, or *root* itself) is never under a
  nested checkout, and nothing at or above *root* is ever examined.

## The root exemption, and why

**The walk's own root is never tested.** It is normally a checkout too: the primary
checkout's root holds a `.git` directory, and a worktree's root holds a `.git` file. A
tool pointed AT a worktree (a gate run from inside a session worktree, or a cleanup tool
measuring one) must walk it, so judging the root would blank the whole run.

That inversion has happened. A walker once tested its root's own absolute path parts
against its prune names; in a layout that keeps every linked worktree under
`.claude/worktrees/`, run from a worktree it pruned every hit and checked nothing, the very failure the prune
existed to remove. Prune only what the walk reports below its root.

## A `.git` file also marks a submodule

A git submodule's working tree holds a `.git` FILE too, so this predicate prunes a
submodule exactly as it prunes a worktree, and every gate built on it would silently stop
walking that submodule's sources. A repository that adds a submodule must decide whether
its gates should walk it, and if so teach this library to tell the two apart (a
submodule's `gitdir:` pointer names `.git/modules/`, a worktree's names
`.git/worktrees/`).

## Usage

Import it the way the gate family imports its other flat libraries: a `sys.path`
bootstrap resolved from the importing file's own location, so the tool stays
location-independent.

```python
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "nested_checkout"))

import nested_checkout  # noqa: E402 - import follows the sys.path bootstrap above
```

### The `os.walk` idiom

At the existing prune step, alongside the tool's own name set. `os.walk` reports only
children in `dirnames`, so the root is exempt for free:

```python
for here_name, dirnames, _ in os.walk(root):
    here = Path(here_name)
    dirnames[:] = [
        d
        for d in dirnames
        if d not in _PRUNE_DIRS and not nested_checkout.is_nested_checkout(here / d)
    ]
```

Prefer this wherever a walk has a prune step: pruning never visits the nested tree, while
filtering pays for every path it then discards.

### The glob-then-filter idiom

A walker that globs first (`root.rglob(...)`, `root.glob(...)`) has no prune step, so it
asks about each hit's ancestor chain instead:

```python
hits = [
    path
    for path in root.rglob("*.md")
    if not nested_checkout.is_under_nested_checkout(path, root)
]
```

Pass the same *root* the glob ran from, so both sides spell the paths alike. Membership
is lexical: both sides must be resolved or both unresolved, both absolute or both
relative; otherwise the answer is False and the checkout is walked.

A checkout's own top is not "under" a nested checkout (only its ancestors are tested), so a
walker that keeps DIRECTORY hits must also reject a hit that is itself a checkout top:

```python
keep = hit == root or not (
    nested_checkout.is_nested_checkout(hit)
    or nested_checkout.is_under_nested_checkout(hit, root)
)
```

## Worked example

With linked worktrees kept under `.claude/worktrees/`, as in the layout above:

```text
<root>/.git                               directory -> root: never tested
<root>/.claude/worktrees/agent-x/.git     file      -> is_nested_checkout(agent-x) == True
<root>/.claude/worktrees/agent-x/a/b.py             -> is_under_nested_checkout(b.py, root) == True
<root>/.claude/settings.json                        -> is_under_nested_checkout(...) == False
<root>/tool/tool.py                                 -> is_under_nested_checkout(...) == False
```

## Testing nested_checkout itself

From the repository root:

```text
python nested_checkout/test_nested_checkout.py
```
