#!/usr/bin/env python3
"""cc-enslaver — sync-gate (rule 12) config CRUD + diagnostics.

Backs the `/cc-enslaver:sync-gate` slash command. Writes to
``<project-root>/.claude/cc-enslaver/sync-gate.toml``, the per-project
opt-in config that drives Stop layer (i).

Why this exists (v0.31)
-----------------------
Imperial Edicts have had an authoring CLI since v0.12: validated writes,
and a `list` that shows what the loader ACTUALLY parsed. Sync-gate groups
had neither. The asymmetry mattered more than it looked, because
`sync_gate.load()` is failing-open by design:

    a typo'd glob → the group is skipped or matches nothing → layer (i)
    never fires → you believe a co-update invariant is guarded while
    nothing is guarding it, with one stderr line nobody reads.

That is worse than having no gate: an unenforced gate you trust is a
false negative you have stopped looking for. `check` is the answer — it
reports every group the loader kept, every group it DROPPED and why, and
every glob that matches no file in the repo.

Deliberately NOT automatic
--------------------------
`init` creates the file only when you ask. No hook writes into the user's
project directory — that invariant has held for every release, and the
only other writer (`manage_edicts.py`) is likewise user-invoked. An
auto-created empty template would also be functionally identical to no
file at all: zero groups means layer (i) still never fires, so it would
buy discoverability at the cost of an unrequested file in everyone's
`git status`.

Subcommands
-----------
  init                Create a commented template (refuses to clobber).
  list                Print the groups the loader actually parsed.
  check               list + report dropped groups and dead globs; exits
                      1 when anything is wrong, so it is usable in CI.
  add NAME --when G... --require G... [--mode all] [--note ...]
  remove NAME
  path                Print the resolved config location.

Hand-editing the file remains fully supported — it is small and the
schema is documented in its header. This CLI is the ergonomic path and,
more importantly, the only way to see what the loader made of it.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
# because the sys.path bootstrap above must run before these lib imports
from lib import projroot, sync_gate as sg  # noqa: E402
# because of the same sys.path bootstrap, this import cannot sit at top
from lib import tomlio  # noqa: E402


class SyncGateWriteError(RuntimeError):
    """Raised when a rewrite would produce an unusable config."""


_HEADER = """# cc-enslaver — repo-wide sync gate (rule 12)
#
# Co-update groups for THIS repo. Semantics of one group: if any file
# edited during a session matches a `when` glob, then at least one edited
# file must match a `require` glob — otherwise Stop layer (i) blocks the
# done-claim, unless the reply carries an explicit sync marker
# (`同步核对:` / `sync-check:`) explaining why the require side needs no
# change.
#
# Globs are matched with fnmatch against PROJECT-RELATIVE paths, and `*`
# crosses path separators (so "rules/*.md" also covers "rules/zh/").
#
#   mode = "any"  (default) — one require-side edit satisfies the group.
#   mode = "all"            — EVERY require glob needs an edited match.
#                             Use for lock-step invariants where one stale
#                             sibling is the failure mode.
#
# Run `/cc-enslaver:sync-gate check` after editing: a glob that matches
# nothing is silently inert, and this config is failing-open by design.
#
# [[groups]]
# name = "rules-fanout"
# when = ["rules/*.md"]
# require = ["docs/RULES.md", "prompts/*.md"]
# note = "Editing a rule fans out to the index and the injected prompts."

"""


# --------------------------------------------------------------------------- #
# Path resolution.
# --------------------------------------------------------------------------- #
def _write_target() -> Path:
    """Where a new / rewritten config belongs.

    Goes through `sg.default_project_path()` — the DETERMINISTIC resolver —
    and never through `sg.config_path()`, which searches for an existing
    file. That distinction is not pedantry: the first draft of this module
    used the searching resolver, and because it tests each candidate with
    `.is_file()`, a run targeting a project that has no config yet fell
    through to the process cwd and appended the new group to **whatever
    repo the shell happened to be in**. It wrote two groups into this
    plugin's own config during its first smoke test.

    Unlike edicts there is NO home-directory global level: co-update globs
    name repo-relative paths, so a group is meaningless outside its repo.
    """
    target = sg.default_project_path()
    if target is None:
        sys.stderr.write(
            "Could not resolve a project root. Tried:\n"
            "  1. $CLAUDE_PROJECT_DIR — not set\n"
            "  2. cwd as project root — no .git/ or .claude/ marker here\n"
            "\n"
            "Fix one of:\n"
            "  • cd into the project root (containing .git/ or .claude/), or\n"
            "  • set CLAUDE_PROJECT_DIR=/path/to/project.\n"
            "\n"
            "There is no --global scope for sync-gate: its globs are\n"
            "repo-relative, so a group only means anything inside one repo.\n"
        )
        sys.exit(2)
    return target


# --------------------------------------------------------------------------- #
# Serialisation. Shares lib/tomlio's encoder with manage_edicts.py.
# --------------------------------------------------------------------------- #
def _array(values) -> str:
    return "[" + ", ".join(f'"{tomlio.basic_string(str(v))}"'
                           for v in values) + "]"


def _dump_group(g: sg.Group) -> str:
    parts = [
        "[[groups]]",
        f'name = "{tomlio.basic_string(g.name)}"',
        f"when = {_array(g.when)}",
        f"require = {_array(g.require)}",
    ]
    if g.mode != "any":
        parts.append(f'mode = "{tomlio.basic_string(g.mode)}"')
    if g.note:
        parts.append(f'note = "{tomlio.basic_string(g.note)}"')
    return "\n".join(parts) + "\n"


def _write_groups(path: Path, groups: list[sg.Group]) -> None:
    """Rewrite the config, refusing to leave it unparseable OR inert.

    Two checks, not one. `manage_edicts` verifies only that the result
    PARSES, which is necessary but not sufficient here: a group with an
    empty `when` or `require` is valid TOML that `sync_gate.load()` then
    silently SKIPS. Writing one would mean the CLI reporting success over a
    config that enforces nothing — the precise failure this tool exists to
    make impossible. So the result is round-tripped through the real loader
    and every group must come back.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    body = _HEADER + "\n".join(_dump_group(g) for g in groups)
    err = tomlio.dumps_check(body)
    if err is not None:
        raise SyncGateWriteError(
            f"refusing to write {path}: the result would not parse ({err}). "
            f"The file on disk is unchanged — this is a serialisation bug, "
            f"please report the group content that triggered it."
        )
    previous = path.read_text(encoding="utf-8") if path.is_file() else None
    path.write_text(body, encoding="utf-8")
    survived = {g.name for g in _load_groups(path)}
    missing = sorted(g.name for g in groups if g.name not in survived)
    if missing:
        if previous is None:
            path.unlink()
        else:
            path.write_text(previous, encoding="utf-8")
        raise SyncGateWriteError(
            f"refusing to keep {path}: group(s) {missing} parse as TOML but "
            f"are DROPPED by the loader, so they would enforce nothing. The "
            f"file on disk is unchanged. Every group needs a non-empty "
            f"`when` and `require`."
        )


def _load_groups(path: Path) -> list[sg.Group]:
    """Groups the real loader parses out of THIS file (never raises).

    `sg.load_file`, not `sg.load(root)`: the second instance of the same
    root cause as `_write_target`. `load()` re-enters the searching
    resolver, which can answer with a different file when the requested one
    is absent — so verifying a config we just wrote could have reported on
    somebody else's.
    """
    return sg.load_file(path) or []


# --------------------------------------------------------------------------- #
# Repo scan, for the `check` diagnostics.
# --------------------------------------------------------------------------- #
_SCAN_SKIP_DIRS = {
    ".git", ".hg", ".svn", "node_modules", "__pycache__", ".venv", "venv",
    ".mypy_cache", ".pytest_cache", ".ruff_cache", "dist", "build", ".ce",
}


def _repo_files(root: Path) -> list[str]:
    """Project-relative paths of every tracked-ish file under `root`."""
    out: list[str] = []
    for p in root.rglob("*"):
        if not p.is_file():
            continue
        rel_parts = p.relative_to(root).parts
        if _SCAN_SKIP_DIRS.intersection(rel_parts):
            continue
        out.append(p.relative_to(root).as_posix())
    return out


# --------------------------------------------------------------------------- #
# Commands.
# --------------------------------------------------------------------------- #
def cmd_init(_: argparse.Namespace) -> int:
    path = _write_target()
    if path.is_file():
        sys.stderr.write(
            f"{path} already exists — refusing to overwrite it.\n"
            f"Use `list` / `check` to inspect it, or edit it by hand.\n"
        )
        return 1
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_HEADER, encoding="utf-8")
    print(f"created {path}")
    print("0 group(s) — Stop layer (i) stays inert until you add one.")
    print("Next: /cc-enslaver:sync-gate add NAME --when GLOB --require GLOB")
    return 0


def cmd_path(_: argparse.Namespace) -> int:
    existing = sg.config_path()
    if existing is not None:
        print(existing)
        return 0
    root = projroot.cwd_if_project_root()
    if root is None:
        print("(no project root resolved; set CLAUDE_PROJECT_DIR)")
        return 1
    print("(file does not exist yet; would be created at:)")
    print(root / ".claude" / "cc-enslaver" / "sync-gate.toml")
    return 0


def _print_groups(path: Path, groups: list[sg.Group]) -> None:
    print(f"config: {path}")
    print(f"{len(groups)} group(s) loaded:\n")
    for g in groups:
        mode = "" if g.mode == "any" else f"  [mode={g.mode}]"
        print(f"  {g.name}{mode}")
        print(f"    when    = {list(g.when)}")
        print(f"    require = {list(g.require)}")
        if g.note:
            print(f"    note    = {g.note}")


def cmd_list(_: argparse.Namespace) -> int:
    path = sg.config_path()
    if path is None:
        print("(no sync-gate.toml found — Stop layer (i) is inert here)")
        print("To create one: /cc-enslaver:sync-gate init")
        return 0
    groups = _load_groups(path)
    if not groups:
        print(f"config: {path}")
        print("0 group(s) loaded — Stop layer (i) is inert.")
        print("If you expected groups here, run `check`: a group with an "
              "empty when/require is dropped silently.")
        return 0
    _print_groups(path, groups)
    return 0


def cmd_check(_: argparse.Namespace) -> int:
    """Report what loaded, what was dropped, and which globs match nothing.

    Exits 1 on any finding. The whole point is that `sync_gate.load()` is
    failing-open: it degrades to "no groups" and prints one stderr line, so
    a misconfigured gate looks exactly like a healthy one from the outside.
    """
    path = sg.config_path()
    if path is None:
        print("(no sync-gate.toml found — Stop layer (i) is inert here)")
        print("To create one: /cc-enslaver:sync-gate init")
        return 0

    raw = tomlio.parse_toml_file(
        path, lambda m: sys.stderr.write(f"[cc-enslaver sync-gate] {m}\n"),
    )
    if raw is None:
        print(f"config: {path}")
        print("FAIL: the file does not parse. Every group in it is inert.")
        return 1

    declared = [g for g in raw.get("groups", []) if isinstance(g, dict)]
    groups = _load_groups(path)
    _print_groups(path, groups)

    problems: list[str] = []

    kept = {g.name for g in groups}
    for entry in declared:
        name = entry.get("name")
        label = name if isinstance(name, str) and name.strip() else repr(entry)
        if not isinstance(name, str) or name.strip() not in kept:
            problems.append(
                f"group {label}: DECLARED in the file but DROPPED by the "
                f"loader — it enforces nothing. Check that `name` is a "
                f"non-empty string and that both `when` and `require` are "
                f"non-empty lists of strings."
            )

    root = sg.project_root(path)
    files = _repo_files(root)
    print(f"\nscanned {len(files)} file(s) under {root}\n")
    for g in groups:
        for field, patterns in (("when", g.when), ("require", g.require)):
            for pat in patterns:
                hits = [f for f in files if sg.matches_any(f, (pat,))]
                mark = "ok " if hits else "!! "
                print(f"  {mark}{g.name}.{field}  {pat!r} → "
                      f"{len(hits)} file(s)")
                if not hits:
                    problems.append(
                        f"group {g.name}: {field} glob {pat!r} matches NO "
                        f"file in the repo. A `when` glob that matches "
                        f"nothing makes the group inert; a `require` glob "
                        f"that matches nothing makes it permanently "
                        f"unsatisfiable."
                    )

    if not problems:
        print("\nOK — every group loaded and every glob matches something.")
        return 0
    print(f"\n{len(problems)} problem(s):")
    for p in problems:
        print(f"  • {p}")
    print("\nRemember: this config is failing-open. A broken group does not "
          "raise — it just stops guarding, silently.")
    return 1


def cmd_add(args: argparse.Namespace) -> int:
    path = _write_target()
    existing = _load_groups(path) if path.is_file() else []
    if any(g.name == args.name for g in existing):
        sys.stderr.write(
            f"Group {args.name!r} already exists. Use `remove` first.\n"
        )
        return 1
    new = sg.Group(
        name=args.name,
        when=tuple(args.when),
        require=tuple(args.require),
        note=(args.note or "").strip(),
        mode="all" if args.all else "any",
    )
    _write_groups(path, existing + [new])
    print(f"added group {args.name!r} → {path}")
    print(f"  when    = {list(new.when)}")
    print(f"  require = {list(new.require)}   [mode={new.mode}]")
    print("\nRun `/cc-enslaver:sync-gate check` to confirm both globs "
          "actually match files.")
    return 0


def cmd_remove(args: argparse.Namespace) -> int:
    path = sg.config_path()
    if path is None:
        sys.stderr.write("No sync-gate.toml found.\n")
        return 1
    existing = _load_groups(path)
    if not any(g.name == args.name for g in existing):
        sys.stderr.write(f"No group named {args.name!r} in {path}.\n")
        return 1
    _write_groups(path, [g for g in existing if g.name != args.name])
    print(f"removed group {args.name!r} → {path}")
    return 0


def main(argv: list[str] | None = None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        # Defensive: reconfigure exists since 3.7 and we require 3.11+, but a
        # test harness may have replaced stdout with a non-TextIOWrapper.
        # Rationale: a console-encoding tweak must never abort the command.
        pass

    parser = argparse.ArgumentParser(
        description="cc-enslaver sync-gate (rule 12) config helper",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("init", help="Create a commented template.").set_defaults(
        func=cmd_init)
    sub.add_parser("list", help="Print the groups the loader parsed."
                   ).set_defaults(func=cmd_list)
    sub.add_parser("check", help="Diagnose dropped groups and dead globs."
                   ).set_defaults(func=cmd_check)
    sub.add_parser("path", help="Print the resolved config location."
                   ).set_defaults(func=cmd_path)

    p_add = sub.add_parser("add", help="Append a co-update group.")
    p_add.add_argument("name", help="Unique short group name.")
    p_add.add_argument(
        "--when", action="append", required=True, metavar="GLOB",
        help="Editing a file matching this arms the group. May repeat.",
    )
    p_add.add_argument(
        "--require", action="append", required=True, metavar="GLOB",
        help="At least one edited file must match this. May repeat.",
    )
    p_add.add_argument(
        "--all", action="store_true",
        help='mode = "all": EVERY require glob needs an edited match '
             "(lock-step invariants). Default is any-of.",
    )
    p_add.add_argument("--note", help="Why these files move together.")
    p_add.set_defaults(func=cmd_add)

    p_rm = sub.add_parser("remove", help="Remove a group by name.")
    p_rm.add_argument("name")
    p_rm.set_defaults(func=cmd_remove)

    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except SyncGateWriteError as exc:
        sys.stderr.write(f"{exc}\n")
        return 2


if __name__ == "__main__":
    sys.exit(main())
