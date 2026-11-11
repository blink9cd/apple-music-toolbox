#!/usr/bin/env python3
"""Own the names -- and the reachability rules -- of the subdirectories a tool folder may hold.

Why this exists
---------------
A file that outgrows the file-length bar has two possible fixes, and only one of
them is allowed here: **decompose it, never compress it.** Compressing a file to
fit a line cap trades a mechanical measurement for real reviewability, which is
the opposite of what the cap is for.

But the layout rules make the obvious decomposition illegal. ``folder_layout``
gates any ``<x>.py`` / ``<x>.sh`` whose stem differs from its folder name
(``foreign-primary``), and ``python_gate`` gates a module with no paired test
(``unpaired-module``) and a test with no paired subject (``unpaired-test``). So a
tool folder cannot simply grow a second file. This module defines the three
subdirectories where it *may*, and owns what each one costs:

======== ================================ ==================================
Name     Holds                            Reachable from the parent via
======== ================================ ==================================
``tests``  decomposed Python test suites    ``test_<folder>.py`` aggregator
``lib``    sourced shell helpers            ``<folder>.sh`` primary script
``src``    private Python modules           ``<folder>.py`` primary script
======== ================================ ==================================

``tests`` is the **public** one: its contents are a suite runner reaches through
an aggregator. ``lib`` and ``src`` are **private** -- their contents exist only
to serve the one tool whose folder they sit in, and nothing outside it may import
or source them. That split is why the two private dirs share a reachability rule
and a stray rule while ``tests`` has its own.

Why one module and not three
-----------------------------
All three are the same shape: a directory pruned from a gate's walk, whose
contents are reachable only through an explicit link from the parent. Pruning is
the easy half; saying what the pruning cost is the half that keeps a gate honest,
and every consumer needs the same two answers -- *what is this directory called*
and *what did skipping it hide*. Splitting that across three modules would write
the shape three times and force a reader to know all three exist. One module
owning "directories a tool folder may contain" is the single source of truth the
consumers ask, so none of them can drift onto a colliding name.

Why the names are these names -- collision counts, not preferences
-------------------------------------------------------------------
Each was measured against this tree first, because a consumer that prunes a name
already in use silently drops a real directory from a gate's discovery: ``tests``
over the singular ``test`` (two real C / C# trees), ``lib`` at zero collisions, and
``src``, which web, C and C# projects use for their own source trees -- the reason
:func:`holds_convention_content` exists. Every predicate matches the **whole** name,
case-sensitively. The counts and the rejected names are in ``tool_subdirs.md``.

The hazards that make this a library rather than three constants
-----------------------------------------------------------------
**Orphaning.** A pruned directory's contents run only if the parent links to
them, and the only thing that does is the parent's own aggregator or primary
script. The three ``*_orphan_reason`` functions report a pruned directory whose
contents nothing reaches; :func:`suite_reach_reason` reports the suites an
aggregator that DOES exist never loads.

**A name that is not the convention** (:func:`holds_convention_content`). Other
languages use two of these words, so a dir matching a name predicate can be a C,
C# or web source tree, whose orphan finding only a stub file could satisfy. The
content question scopes the orphan reports -- and ONLY those -- to their language.

**A stray unit marker** (:func:`stray_reason`, private dirs only). ``gate_tree``
discovers a sweep unit as any directory directly holding a ``coverage.sh`` or a
``test_*.py``, and gates a unit holding others with them excluded. Put either name
inside a ``lib/`` or ``src/`` and that directory registers as a unit nested in the
tool folder, so the tool is gated without it: the tool's own tests stop measuring
the code inside it while the sweep still reports PASS. The same two basenames are
``build_delivery_zip``'s release-mode excludes, so a release archive loses them
too. ``tests/`` is exempt from this rule because holding ``test_*.py`` is its
entire purpose; ``gate_tree`` knows that name and prunes it deliberately.

The reachability limit the listing reports share
-------------------------------------------------
The ``*_orphan_reason`` functions answer a **name** question: that a plausible
linking parent exists, not that it contains the ``import`` or ``source`` line. For
``tests/`` the gap is closed by :func:`suite_reach_reason`, which reads the
aggregator's SOURCE -- handed in by the caller, so this module stays pure -- because
a suite is test code, which no coverage run measures. That read is static, so it
does not prove a ``discover`` call targets ``tests/``, nor that a counted import
runs: one under ``if False:`` or in a never-called function counts all the same.
``lib/`` and ``src/`` keep the name-only answer, their gap covered from the other
side: unreached code adds uncovered lines to a coverage run that gates at 100%.

Entry point assumptions
-----------------------
Every function is pure -- no filesystem access, no I/O, no config. Consumers own
their own walking and pruning and pass in the names they already have; this
module owns only the conventions. It carries no ``stdio_utf8`` dependency and
cannot fail at import time.

The full rationale, the measurements behind each name, and the per-consumer
wiring table live in ``tool_subdirs.md``.
"""

from __future__ import annotations

import ast
from collections.abc import Sequence

# ---------------------------------------------------------------------------
# The three names. Single definitions: every consumer asks rather than spells.
# ---------------------------------------------------------------------------
# Decomposed Python test suites, imported by a test_<folder>.py aggregator.
SUITE_DIR_NAME = "tests"
# Sourced shell helpers, sourced by the folder's <folder>.sh primary script.
LIB_DIR_NAME = "lib"
# Private Python modules, imported by the folder's <folder>.py primary script.
SRC_DIR_NAME = "src"

_PY_SUFFIX = ".py"
_SH_SUFFIX = ".sh"
_TEST_PREFIX = "test_"
# The conventional unnamed coverage driver. Inside a private dir it is a stray:
# it is one of gate_tree's two unit markers -- see _STRAY_CONSEQUENCE.
_COVERAGE_SCRIPT = "coverage.sh"
# The unittest.TestLoader method an aggregator calls to load every suite in a dir.
_DISCOVER_METHOD = "discover"
# unittest's load_tests protocol hook: beside it, an imported suite module can run.
_LOAD_TESTS_HOOK = "load_tests"

# Why the stray set is exactly these two shapes and not "anything test-shaped":
# they are gate_tree's unit markers, and they are also build_delivery_zip's
# release-mode basename excludes. A `test_*.sh` is neither, so flagging it would
# invent a rule no consumer enforces.
_STRAY_CONSEQUENCE = (
    "which makes gate_tree register it as its own sweep unit and gate the parent "
    "tool folder without it, and is dropped from a release delivery archive"
)


def is_suite_dir(name: str) -> bool:
    """True when *name* is the grouped-suite directory (``tests``).

    Whole-name and case-sensitive, so ``integration_tests`` is somebody else's
    layout. The plural was chosen because it collides with nothing: two real C /
    C# test trees are named ``test``, and pruning the singular would un-gate both.
    """
    return name == SUITE_DIR_NAME


def is_lib_dir(name: str) -> bool:
    """True when *name* is the sourced-shell-helper directory (``lib``).

    Whole-name and case-sensitive, so ``libexec`` and ``lib64`` are left alone.
    """
    return name == LIB_DIR_NAME


def is_src_dir(name: str) -> bool:
    """True when *name* is the private-Python-module directory (``src``).

    Whole-name and case-sensitive. Four ``src`` directories already exist in this
    tree, but every one holds web, C or C# sources and no ``.py`` / ``.sh``, so
    the Python and shell gates that consume this predicate cannot reach them.
    """
    return name == SRC_DIR_NAME


def is_private_dir(name: str) -> bool:
    """True for the two dirs whose contents serve only their own tool folder.

    ``lib`` and ``src`` -- but not ``tests``, whose suites a runner reaches
    through an aggregator. This is the set :func:`stray_reason` governs.
    """
    return is_lib_dir(name) or is_src_dir(name)


def is_tool_subdir(name: str) -> bool:
    """True for any directory name this module defines.

    The predicate a consumer uses when it prunes all three alike -- as
    ``folder_layout`` does, since ``foreign-primary`` would fire inside every one
    of them.
    """
    return is_suite_dir(name) or is_private_dir(name)


def _convention_suffix(dir_name: str) -> str:
    """The file suffix *dir_name*'s convention is actually made of.

    ``lib`` holds sourced shell helpers; ``tests`` and ``src`` hold Python. The
    contents and the parent's reacher are always the SAME language, and not by
    coincidence -- only shell can source shell, and only Python can import Python --
    so one suffix per convention serves both questions, and
    :func:`private_orphan_reason` takes its reacher's suffix from here rather than
    deciding it a second time.

    Raises :class:`ValueError` for a name this module does not define: it has no
    convention, so any suffix returned would be a fabrication.
    """
    if is_lib_dir(dir_name):
        return _SH_SUFFIX
    if is_suite_dir(dir_name) or is_src_dir(dir_name):
        return _PY_SUFFIX
    raise ValueError(f"not a tool subdirectory: {dir_name!r}")


def holds_convention_content(dir_name: str, subdir_filenames: Sequence[str]) -> bool:
    """True when *dir_name*'s own listing holds the language its convention is for.

    The name alone cannot decide this: web, C and C# projects name their own source
    tree ``src``, which no ``<folder>.py`` could ever import, and the orphan finding
    such a dir would earn is satisfiable only by a stub written to quiet a gate. A
    caller therefore asks this BEFORE :func:`suite_orphan_reason` /
    :func:`private_orphan_reason`, and skips the orphan question when it is false.

    *subdir_filenames* is the DIRECT listing of the subdirectory itself: both
    conventions import top-level from it, so a nested-only tree is not their shape,
    and an empty dir hides no code. :func:`stray_reason` is deliberately NOT gated on
    this -- ``gate_tree`` keys unit discovery on the filename alone, so a
    ``coverage.sh`` in a C project's ``src`` still drops that project from the sweep.

    Raises :class:`ValueError` via :func:`_convention_suffix` for a name this module
    does not define: a clean answer to a question that does not apply is a wrong one.
    """
    suffix = _convention_suffix(dir_name)
    return any(name.endswith(suffix) for name in subdir_filenames)


def _normalized(name: str) -> str:
    """Fold ``-`` to ``_``, the way ``folder_layout._normalized`` does.

    A tool folder may be hyphenated (a framework task key such as ``lock-phone``)
    while a Python module name cannot be. ``folder_layout`` treats the two
    spellings as the same name, so this module must too: an unfolded comparison
    here would report a folder as an orphan while its layout gate called the very
    same file tidy -- two rules disagreeing about one convention.
    """
    return name.replace("-", "_")


def aggregator_filename(tool_folder_name: str) -> str:
    """The ``test_<folder>.py`` aggregator a ``tests/`` dir's parent must hold.

    This is the file that preserves ``python_gate``'s ``test_<name>.py`` <->
    ``<name>.py`` pairing while the real suites live one level down. It is the
    CONVENTIONAL importer, not provably the only possible one: a folder whose
    script is not named for the folder -- a delivery *area* rather than a single
    tool -- reaches the same suites from a suite named for that script instead.
    That is why :func:`suite_orphan_reason` reports this file's absence without
    concluding from it. The fold applies because a Python module name cannot
    contain a hyphen.
    """
    return f"{_TEST_PREFIX}{_normalized(tool_folder_name)}{_PY_SUFFIX}"


def primary_script_filename(tool_folder_name: str, dir_name: str) -> str:
    """The ``<folder>`` script that links *dir_name*'s contents into the tool.

    ``lib/`` is sourced by a ``.sh``; ``src/`` is imported by a ``.py``. The
    folder's own spelling is returned rather than a folded one: it always
    satisfies ``folder_layout``'s folded comparison, so a reader is never told to
    rename a folder that is already tidy.

    Raises :class:`ValueError` for a *dir_name* that is not a private dir --
    ``tests/`` pairs with :func:`aggregator_filename` instead, and a silent
    wrong answer here would be a reachability report that cannot come true.
    """
    if is_lib_dir(dir_name):
        return f"{tool_folder_name}{_SH_SUFFIX}"
    if is_src_dir(dir_name):
        return f"{tool_folder_name}{_PY_SUFFIX}"
    raise ValueError(f"not a private tool subdirectory: {dir_name!r}")


def _holds_named_file(
    parent_filenames: Sequence[str], folder_name: str, suffix: str
) -> bool:
    """True when *parent_filenames* holds a *suffix* file named for *folder_name*.

    The comparison is hyphen/underscore-folded on both sides, matching
    ``folder_layout``'s own rule, so either spelling of a hyphenated folder's
    script satisfies it.
    """
    folded = _normalized(folder_name)
    for filename in parent_filenames:
        stem, _, extension = filename.rpartition(".")
        if f".{extension}" == suffix and _normalized(stem) == folded:
            return True
    return False


def _is_test_module(filename: str) -> bool:
    """True when *filename* is a Python test module by ``python_gate``'s naming rule."""
    return filename.startswith(_TEST_PREFIX) and filename.endswith(_PY_SUFFIX)


def suite_orphan_reason(
    tool_folder_name: str, parent_filenames: Sequence[str]
) -> str | None:
    """Why *tool_folder_name*'s ``tests/`` is orphaned, or ``None`` when it is not.

    *parent_filenames* is the direct file listing of the tool folder containing
    the ``tests/`` directory. When it holds the expected aggregator this returns
    ``None`` -- whether that file reaches them is :func:`suite_reach_reason`'s
    question. Otherwise it returns one line, no embedded newline, naming the exact
    filename the reader has to create; ``None`` rather than ``""`` lets a caller
    filter falsy values without a blank row (``nothing_examined.note``'s convention).

    The absence is the VERDICT either way, so a gating caller is unaffected by which
    line comes back; what differs is how much it claims. A delivery *area* names its
    suite for the script it covers, not the folder, so "nothing runs them" is drawn
    only when no test module sits beside the dir; otherwise the candidates are named
    and the conclusion is left to whoever opens them.
    """
    expected = aggregator_filename(tool_folder_name)
    if expected in parent_filenames:
        return None
    head = (
        f"grouped-suite dir {SUITE_DIR_NAME}/ was skipped, but no {expected} sits "
        "beside it to import those suites"
    )
    candidates = sorted(name for name in parent_filenames if _is_test_module(name))
    if not candidates:
        return f"{head}, so nothing runs them"
    return f"{head}; {', '.join(candidates)} may, which this check does not confirm"


def _imported_modules(node: ast.AST) -> list[tuple[str, bool]]:
    """``(dotted module, is a star import)`` for each module an import *node* loads.

    ``from tests import x`` loads ``tests.x``. A relative import loads none here: an
    aggregator is a top-level module, so ``from .`` cannot load a suite beside it.
    """
    if isinstance(node, ast.Import):
        return [(alias.name, False) for alias in node.names]
    if not isinstance(node, ast.ImportFrom) or node.level or not node.module:
        return []
    if node.module == SUITE_DIR_NAME:
        return [(f"{node.module}.{alias.name}", False) for alias in node.names]
    return [(node.module, any(alias.name == "*" for alias in node.names))]


def _reached_stems(tree: ast.Module) -> set[str] | None:
    """Stems of the suites *tree* runs; ``None`` (every suite) if it calls ``discover``.

    A dotted module names its first part, or its second when the first is the suite
    dir itself (``tests.test_x``); which imports count: :func:`unreached_suites`.
    """
    imported: set[str] = set()
    starred: set[str] = set()
    for node in ast.walk(tree):
        func = node.func if isinstance(node, ast.Call) else None
        if isinstance(func, ast.Attribute) and func.attr == _DISCOVER_METHOD:
            return None
        for dotted, is_star in _imported_modules(node):
            parts = dotted.split(".")
            stem = (
                parts[1] if parts[0] == SUITE_DIR_NAME and len(parts) > 1 else parts[0]
            )
            imported.add(stem)
            if is_star:
                starred.add(stem)
    hooked = any(
        isinstance(node, ast.FunctionDef) and node.name == _LOAD_TESTS_HOOK
        for node in tree.body
    )
    return imported if hooked else starred


def _suites_in(suite_filenames: Sequence[str]) -> list[str]:
    """The ``test_*.py`` entries of a ``tests/`` listing, sorted for a stable report."""
    return sorted(name for name in suite_filenames if _is_test_module(name))


def unreached_suites(
    aggregator_source: str, suite_filenames: Sequence[str]
) -> list[str]:
    """The ``test_*.py`` in *suite_filenames* that *aggregator_source* does not run.

    *suite_filenames* is the ``tests/`` dir's DIRECT listing; fixtures and helpers in
    it are not suites. Count only what runs -- a suite is reached by:

    * a call to any method named ``discover`` (``TestLoader``'s), which reaches all;
    * a STAR import of its module (``from test_x import *``, ``from tests.test_x
      import *``), which binds its TestCases where unittest's module load finds them;
    * any import of its module, in any spelling, in an aggregator that also defines a
      top-level ``load_tests`` -- the hook that can add an imported module's tests.

    A bare or named import without ``load_tests`` binds a module or a helper, not the
    suite's tests, so it does not count. Unparseable source reaches nothing -- the
    syntax error is lint's finding (``ValueError`` is a null byte on older versions).
    """
    try:
        stems = _reached_stems(ast.parse(aggregator_source))
    except (SyntaxError, ValueError):
        stems = set()
    if stems is None:
        return []
    suites = _suites_in(suite_filenames)
    return [name for name in suites if name.removesuffix(_PY_SUFFIX) not in stems]


def suite_reach_reason(
    tool_folder_name: str, aggregator_source: str, suite_filenames: Sequence[str]
) -> str | None:
    """Why an EXISTING aggregator leaves ``tests/`` suites unrun, or ``None``.

    The present-aggregator twin of :func:`suite_orphan_reason`, asked when that
    returns ``None``; the caller reads the aggregator's source (UTF-8) and the
    ``tests/`` listing. The file's existence was once the whole check, and an
    aggregator holding only its own tests passed it while a suite beside it never
    ran. Every unreached suite is named, so one pass fixes all; no embedded newline.
    """
    unreached = unreached_suites(aggregator_source, suite_filenames)
    if not unreached:
        return None
    return (
        f"{aggregator_filename(tool_folder_name)} sits beside grouped-suite dir "
        f"{SUITE_DIR_NAME}/ but neither discovers, star-imports nor load_tests-imports "
        f"{', '.join(unreached)}, so nothing runs them"
    )


def unreadable_aggregator_reason(
    tool_folder_name: str, error: Exception, suite_filenames: Sequence[str]
) -> str | None:
    """Why an aggregator the caller could not READ leaves ``tests/`` suites unrun.

    A read that failed (not UTF-8, unreadable, a broken link) reaches nothing, as
    unparseable source does; the line names *error* so it is not mistaken for a
    missing import, flattened to one line. ``None`` when there is no suite to miss.
    """
    unreached = _suites_in(suite_filenames)
    if not unreached:
        return None
    failure = " ".join(f"{type(error).__name__}: {error}".split())
    return (
        f"{aggregator_filename(tool_folder_name)} beside grouped-suite dir "
        f"{SUITE_DIR_NAME}/ could not be read ({failure}), so it reaches none of "
        f"{', '.join(unreached)} and nothing runs them"
    )


def private_orphan_reason(
    dir_name: str, tool_folder_name: str, parent_filenames: Sequence[str]
) -> str | None:
    """Why a private *dir_name* is orphaned, or ``None`` when it is not.

    Covers both private dirs, because their rule is the same one: the contents
    are reachable only from the folder's own primary script, of the language that
    can reach them. A ``lib/`` beside a Python-only tool is unreachable however
    the folder is named, and so is a ``src/`` beside a shell-only one -- shell
    cannot import a module and Python cannot source a shell helper.

    The returned line carries no embedded newline and names the file the reader
    has to create. Raises :class:`ValueError` for a non-private *dir_name*, via
    :func:`primary_script_filename`.
    """
    expected = primary_script_filename(tool_folder_name, dir_name)
    suffix = _convention_suffix(dir_name)
    verb = "source" if is_lib_dir(dir_name) else "import"
    if _holds_named_file(parent_filenames, tool_folder_name, suffix):
        return None
    return (
        f"private dir {dir_name}/ was skipped, but no {expected} sits beside it "
        f"to {verb} its contents, so nothing reaches them"
    )


def _is_stray(filename: str) -> bool:
    """True when *filename* must never appear inside a private dir.

    Exactly ``coverage.sh`` and ``test_*.py`` -- gate_tree's two unit markers,
    which are also the delivery zip's two release-mode basename excludes. The
    ``test_`` test is suffix-qualified, so ``testing_utils.py`` (a name that
    merely starts alike) is not caught.
    """
    if filename == _COVERAGE_SCRIPT:
        return True
    return filename.startswith(_TEST_PREFIX) and filename.endswith(_PY_SUFFIX)


def stray_reason(dir_name: str, subdir_filenames: Sequence[str]) -> str | None:
    """Why a private dir's contents are unsafe, or ``None`` when they are not.

    *subdir_filenames* is the direct file listing of the ``lib/`` or ``src/``
    directory itself. A ``coverage.sh`` or a ``test_*.py`` in there silently drops
    the parent tool folder from ``gate_tree``'s sweep and vanishes from a release
    archive, so both are reported.

    **Every** offender is named, not just the first: a reader who fixed only the
    one file the report mentioned would re-run the gate and meet the next, so
    naming them all makes the fix a single pass. The line carries no embedded
    newline.

    Raises :class:`ValueError` for a non-private *dir_name*. ``tests/`` is not
    merely exempt from this rule, it is its opposite -- holding ``test_*.py`` is
    the whole point, and ``gate_tree`` prunes that name deliberately -- so asking
    this question about it is a caller bug, not a clean answer.
    """
    if not is_private_dir(dir_name):
        raise ValueError(f"not a private tool subdirectory: {dir_name!r}")
    strays = sorted(name for name in subdir_filenames if _is_stray(name))
    if not strays:
        return None
    return f"private dir {dir_name}/ holds {', '.join(strays)}, {_STRAY_CONSEQUENCE}"
