"""cc-enforcer — repo-wide sync gate (rule 12, v0.23).

Passive physical enforcement of rule 12 ("repo-wide sync — co-update
every reference, not just the target file"). A project opts in by
committing a TOML config at

    <project-root>/.claude/cc-enforcer/sync-gate.toml

declaring co-update groups. Semantics of one group:

    "If any file edited THIS SESSION matches one of the `when` globs,
     then at least one file edited this session must match one of the
     `require` globs — otherwise the closing reply must explicitly
     acknowledge the sync check (Stop layer (i) marker escape)."

Schema (TOML array-of-tables, same no-third-party-deps rationale as
lib/edicts.py — stdlib tomllib parses it, no YAML dependency):

    [[groups]]
    name = "rules-fanout"
    when = ["rules/*.md"]
    require = ["prompts/*.md", "docs/RULES.md"]
    mode = "any"   # optional: "any" (default) | "all"
    note = "Editing a rule fans out to the injected prompts + the index."

`mode` controls the require side: "any" is satisfied when at least one
edited file matches at least one `require` glob; "all" demands every
`require` glob individually be matched by some edited file (use it for
lock-step invariants like version manifests, where updating one sibling
but not the other IS the historical failure mode).

Known accepted limitation: recording happens in PreToolUse (same
precedent as `last_edit_turn` / mtime baselines — PostToolUse does not
fire for out-of-project files, the v0.3.2 root cause), so an edit the
user rejects at the permission prompt can leave a phantom entry in
`edited_files`. The cost is bounded: the Stop-layer marker escape plus
the per-session group acknowledgement (stop_guard records
`sync_acked_groups` after an acknowledged block/escape) cap it at one
corrective turn per group per session.

Matching semantics:
  - Globs are matched with fnmatch against PROJECT-RELATIVE paths, so
    they are portable across machines (no absolute paths in the config).
  - fnmatch's `*` crosses path separators (e.g. "rules/*.md" also
    matches "rules/zh/06-x.md"). That is deliberate: co-update intent
    is usually per-subtree, and it keeps the config short.
  - fnmatch normcases both sides, so matching is case-insensitive on
    Windows and separator-agnostic (patterns may use forward slashes).
  - Edited files outside the project root are ignored.

Enforcement point: stop_guard.py layer (i), edit-turns only, with the
same one-shot guard / grace window as every other layer. The escape
hatch is a sync-acknowledgement marker in the reply (see
stop_guard.SYNC_MARKERS) — "checked the co-update set, no change
needed" is a legitimate outcome, it just has to be said out loud.

Failing-open everywhere: no config file → no groups → layer (i) never
fires (per-project opt-in). Malformed TOML / broken entry → skipped
with a stderr diagnostic, never a block caused by a loader bug.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from fnmatch import fnmatch
from pathlib import Path

try:
    # because the ignore is unused on 3.11+ where tomllib resolves
    import tomllib  # type: ignore[unused-ignore]
except ModuleNotFoundError:
    # because Python < 3.11 has no tomllib and the gate must fail open
    tomllib = None  # type: ignore[assignment]

from . import projroot, tomlio

_PLUGIN_NAME = "cc-enforcer"
_CONFIG_FILENAME = "sync-gate.toml"


_VALID_MODES = {"any", "all"}


@dataclass(frozen=True)
class Group:
    """One co-update group from the config."""
    name: str
    when: tuple[str, ...]
    require: tuple[str, ...]
    note: str = ""
    mode: str = "any"  # "any" | "all" — see the module docstring


@dataclass(frozen=True)
class Violation:
    """One unmet group: `when` matched this session, `require` did not."""
    group: Group
    when_hits: tuple[str, ...]  # project-relative edited files that matched


def _warn(msg: str) -> None:
    sys.stderr.write(f"[cc-enforcer sync-gate] {msg}\n")


# v0.30 — this was a verbatim copy of the edicts predicate, introduced
# with the docstring "Same project-root heuristic as lib/edicts.py". Both
# now call `lib/projroot.py`, so the sentence is enforced instead of
# merely asserted.
_looks_like_project_root = projroot.looks_like_project_root


def config_path(cwd: str | None = None) -> Path | None:
    """Resolve the sync-gate.toml to read, or None when the project has none.

    Resolution order (first existing file wins):
      1. ``<cwd>/.claude/cc-enforcer/sync-gate.toml`` — the Stop payload's
         cwd is the session's project directory, the most reliable signal.
      2. ``${CLAUDE_PROJECT_DIR}/.claude/cc-enforcer/sync-gate.toml``.
      3. ``$(process cwd)/.claude/cc-enforcer/sync-gate.toml`` — only when
         the process cwd carries a project-root marker (the v0.19 edicts
         fallback, for Windows subprocesses that drop the env var).

    Unlike edicts there is NO home-directory global level: co-update
    groups are inherently per-repo (the globs name repo-relative paths).
    """
    candidates: list[Path] = []
    if cwd:
        candidates.append(Path(cwd) / ".claude" / _PLUGIN_NAME / _CONFIG_FILENAME)
    proj = os.environ.get("CLAUDE_PROJECT_DIR")
    if proj:
        candidates.append(Path(proj) / ".claude" / _PLUGIN_NAME / _CONFIG_FILENAME)
    try:
        proc_cwd = Path.cwd()
    except OSError:
        proc_cwd = None
    if proc_cwd is not None and _looks_like_project_root(proc_cwd):
        candidates.append(proc_cwd / ".claude" / _PLUGIN_NAME / _CONFIG_FILENAME)
    seen: set[Path] = set()
    for c in candidates:
        if c in seen:
            continue
        seen.add(c)
        try:
            if c.is_file():
                return c
        except OSError:
            continue
    return None


def default_project_path(cwd: str | None = None) -> Path | None:
    """Where a NEW config belongs — deterministic, never a search.

    v0.31, and this function exists because its absence was a real bug.
    `config_path()` above is a READ resolver: it tries several roots and
    takes the first that already holds a file, which is exactly right for
    a hook that must find whatever config governs the session even when
    `CLAUDE_PROJECT_DIR` is missing.

    Using that same resolver to pick a WRITE target is a different
    question answered with the wrong tool. When the intended project has
    no config yet, every one of its candidates fails `.is_file()` and the
    search falls through to the *process cwd* — so a CLI run with
    `CLAUDE_PROJECT_DIR` pointed at project A, from a shell sitting in
    project B, appends A's group to **B's** config. Observed live during
    development: the sync-gate CLI wrote two groups into this repo's own
    config while under test against a scratch repo.

    So: resolve the ROOT first (explicit cwd → `CLAUDE_PROJECT_DIR` → the
    process cwd, but only if it carries a project marker), then derive the
    path from it. Whether a file is already there is irrelevant to where a
    new one goes. `lib/edicts.py` has modelled this split since v0.18.1
    (`edicts_path` vs `default_project_path`); this is the missing twin.

    Returns None when no root can be resolved — the caller must surface
    that rather than guess.
    """
    for candidate in (cwd, os.environ.get("CLAUDE_PROJECT_DIR")):
        if candidate:
            return Path(candidate) / ".claude" / _PLUGIN_NAME / _CONFIG_FILENAME
    root = projroot.cwd_if_project_root()
    if root is None:
        return None
    return root / ".claude" / _PLUGIN_NAME / _CONFIG_FILENAME


def _coerce_glob_list(raw: dict, field_name: str, gname: str) -> tuple[str, ...]:
    v = raw.get(field_name, [])
    if v is None:
        return ()
    if not isinstance(v, list):
        _warn(f"group {gname}: {field_name} is not a list, ignoring")
        return ()
    out: list[str] = []
    for item in v:
        if isinstance(item, str) and item.strip():
            pat = item.strip()
            # Project-relative paths never start with "./", so a
            # "./"-prefixed glob would silently never match — for a
            # `require` glob that means the group is permanently
            # unsatisfiable. Normalize the common spelling instead.
            while pat.startswith(("./", ".\\")):
                pat = pat[2:]
            if pat:
                out.append(pat)
            else:
                _warn(f"group {gname}: {field_name} entry {item!r} is empty after normalization, skipping")
        else:
            _warn(f"group {gname}: {field_name} entry {item!r} not a non-empty string, skipping")
    return tuple(out)


def load(cwd: str | None = None) -> tuple[Path, list[Group]] | None:
    """Resolve the project's sync-gate config and load it.

    Returns (config_path, groups), or None when the project has no
    config (the normal case — the gate is per-project opt-in). Any
    parse / IO error degrades to None with a stderr diagnostic.
    """
    if tomllib is None:
        return None
    p = config_path(cwd)
    if p is None:
        return None
    groups = load_file(p)
    if groups is None:
        return None
    return (p, groups)


def load_file(p: Path) -> list[Group] | None:
    """Parse EXACTLY this file — no resolution, no fallback to another root.

    Split out of `load()` in v0.31 as the second half of the same fix as
    `default_project_path`. A caller that already knows which file it means
    — because it just wrote it, or was handed the path — must not go back
    through the searching resolver: `load(str(path.parents[2]))` re-enters
    `config_path`, whose fallback chain can answer with a DIFFERENT file
    when the requested one is absent. Verifying a freshly written config
    that way could report on somebody else's.

    None means "unusable" (missing / unparseable); `[]` means "parsed, no
    usable groups" — the distinction `load()` already depended on.
    """
    if tomllib is None:
        return None
    # Shared reader: strips a UTF-8 BOM and turns a non-UTF-8 file into a
    # diagnostic instead of an uncaught UnicodeDecodeError. Without it a
    # sync-gate.toml saved as GBK/ANSI crashed stop_guard's layer (i)
    # evaluation, which also skipped the turn-boundary `clear_edit_flag`.
    data = tomlio.parse_toml_file(p, _warn)
    if data is None:
        return None

    raw_list = data.get("groups", [])
    if not isinstance(raw_list, list):
        _warn(f"{p}: top-level 'groups' must be an array of tables")
        return []

    groups: list[Group] = []
    seen_names: set[str] = set()
    for raw in raw_list:
        if not isinstance(raw, dict):
            _warn(f"{p}: groups entry is not a table, skipping: {raw!r}")
            continue
        name = raw.get("name")
        if not isinstance(name, str) or not name.strip():
            _warn(f"{p}: skipping group with missing / non-string name: {raw!r}")
            continue
        name = name.strip()
        if name in seen_names:
            _warn(f"{p}: duplicate group name {name!r}, keeping first definition")
            continue
        when = _coerce_glob_list(raw, "when", name)
        require = _coerce_glob_list(raw, "require", name)
        if not when or not require:
            _warn(f"{p}: group {name!r} needs non-empty 'when' and 'require', skipping")
            continue
        note = raw.get("note", "")
        if not isinstance(note, str):
            note = str(note)
        mode = raw.get("mode", "any")
        # v0.25.1 — isinstance guard: `mode = []` is valid TOML and
        # `list not in set` raises `TypeError: unhashable type: 'list'`,
        # which escaped load() and took Stop's layer (i) down with it —
        # including the turn-boundary `clear_edit_flag` that runs on the
        # same path. Sibling fix in lib/edicts.py (`severity`).
        if not isinstance(mode, str) or mode not in _VALID_MODES:
            _warn(f"{p}: group {name!r} mode {mode!r} not in {sorted(_VALID_MODES)}; using 'any'")
            mode = "any"
        seen_names.add(name)
        groups.append(Group(
            name=name, when=when, require=require, note=note.strip(), mode=mode,
        ))
    return groups


def matches_any(rel_path: str, patterns: tuple[str, ...]) -> bool:
    """True when `rel_path` matches at least one glob in `patterns`.

    The single definition of "does this edited file belong to this glob".
    Public because `manage_sync_gate.py --check` reports which globs match
    nothing, and a diagnostic that answers that question differently from
    the gate is worse than no diagnostic: it would certify a config the
    gate then ignores. (v0.31)

    fnmatch semantics, deliberately: `*` crosses path separators (so
    `rules/*.md` also covers `rules/zh/`), and both sides are normcased, so
    matching is case-insensitive on Windows and tolerant of forward-slash
    patterns against backslash paths.
    """
    return any(fnmatch(rel_path, pat) for pat in patterns)


def project_root(config: Path) -> Path:
    """Repo root implied by a config at `.claude/cc-enforcer/sync-gate.toml`.

    Three levels up. Extracted so `evaluate()` and the CLI derive it the
    same way rather than each counting `.parents[2]` for themselves.
    """
    return config.parents[2]


def _project_relative(abs_path: str, root: str) -> str | None:
    """Project-relative form of `abs_path` under `root`, or None if outside.

    Both sides are expected pre-normalized (realpath + normcase, the
    lib/state.py canonical form); we normalize `root` defensively.
    """
    norm_root = os.path.normcase(os.path.realpath(root))
    try:
        rel = os.path.relpath(abs_path, norm_root)
    except ValueError:
        # Different drive on Windows → definitively outside the project.
        return None
    # Compare path components, not text: a directory literally named
    # "..data" is inside the project even though rel.startswith("..").
    if rel == ".." or rel.startswith(".." + os.sep):
        return None
    return rel


def evaluate(edited_abs_paths: list[str], cwd: str | None = None) -> list[Violation]:
    """Check the session's edited-file set against the project's groups.

    `edited_abs_paths` is the normalized absolute-path list recorded by
    read_guard (state key `edited_files`). Returns the unmet groups; an
    empty list means either "all groups satisfied" or "project has no
    sync-gate config" — both are non-blocking.
    """
    loaded = load(cwd)
    if loaded is None:
        return []
    config, groups = loaded
    if not groups or not edited_abs_paths:
        return []
    root = str(project_root(config))
    rel_edited = [
        rel for rel in (_project_relative(p, root) for p in edited_abs_paths)
        if rel is not None
    ]
    if not rel_edited:
        return []
    violations: list[Violation] = []
    for g in groups:
        when_hits = tuple(f for f in rel_edited if matches_any(f, g.when))
        if not when_hits:
            continue
        if g.mode == "all":
            # Every require glob must individually have an edited match
            # (lock-step invariants: one stale sibling is the failure).
            require_hit = all(
                any(fnmatch(f, pat) for f in rel_edited) for pat in g.require
            )
        else:
            require_hit = any(matches_any(f, g.require) for f in rel_edited)
        if not require_hit:
            violations.append(Violation(group=g, when_hits=when_hits))
    return violations
