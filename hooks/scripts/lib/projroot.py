"""cc-enslaver — "is this directory a project root?", in one place.

Both hand-edited configs this plugin reads are resolved relative to a
project root that has to be *guessed* when the environment does not name
it:

    .claude/cc-enslaver/edicts.toml      → lib/edicts.py
    .claude/cc-enslaver/sync-gate.toml   → lib/sync_gate.py

The guess exists because `CLAUDE_PROJECT_DIR` is not reliably propagated
to hook subprocesses on Windows (the v0.18.1 finding), so both loaders
fall back to the process cwd — but only when that cwd carries a
project-root marker, otherwise a session started in `~/Downloads` would
happily load a stranger's edicts.

Until v0.30 the predicate was copied into both modules, with
`sync_gate._looks_like_project_root` carrying the comment "Same
project-root heuristic as lib/edicts.py". A comment is not a mechanism:
it names the invariant without holding it, so whoever widens one copy
(say, to recognise `.hg` or a `pyproject.toml` marker) has no reason to
suspect the other exists. This module is the same answer `lib/tomlio.py`
gave to the same question one layer down — one definition, two consumers.

Deliberately narrow: a false positive here makes the wrong project's
hard rules apply to your session, which is strictly worse than the
plugin quietly finding no config at all.
"""

from __future__ import annotations

from pathlib import Path


def looks_like_project_root(p: Path) -> bool:
    """True if `p` carries a marker that strongly suggests a project root.

    Two markers, either one sufficient:

      * ``.git`` exists — a directory in a normal clone, but a FILE in a
        worktree or submodule, so this tests existence rather than
        directory-ness.
      * ``.claude/`` exists as a directory — Claude Code's per-project
        config dir.

    Both are checked because projects legitimately have one without the
    other: a fresh clone before ``.claude/`` is created, or a
    ``.claude``-only directory for a workspace that is not git-tracked.

    Never raises. A permission error or a network-filesystem hiccup
    resolves to "not a project root", because the caller's next step is
    to load rules from here and failing to find them is the safe outcome.
    """
    try:
        if (p / ".git").exists():
            return True
        if (p / ".claude").is_dir():
            return True
    except OSError:
        return False
    return False


def cwd_if_project_root() -> Path | None:
    """The process cwd when it looks like a project root, else None.

    The fallback both config loaders use when `CLAUDE_PROJECT_DIR` is
    absent. `Path.cwd()` itself can raise (a deleted working directory),
    which must degrade to "no candidate" rather than take the loader — and
    with it a whole enforcement layer — down.
    """
    try:
        cwd = Path.cwd()
    except OSError:
        return None
    return cwd if looks_like_project_root(cwd) else None
