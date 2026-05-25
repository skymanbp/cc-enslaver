#!/usr/bin/env python3
"""cc-enslaver — 圣旨 CRUD helper.

Used by the /cc-enslaver:edict slash command and by users editing the
edicts.toml file from the command line.

Subcommands:
  list                       Print all currently loaded edicts.
  add ID TEXT [--must|--should] [--deny-edit REGEX]* [--deny-bash REGEX]*
                             Append a new edict to the project edicts.toml.
  remove ID                  Remove the edict with the given id.
  reload                     Re-print the loaded edicts (sanity check).
  path                       Print the resolved edicts.toml location.

This script writes to ${CLAUDE_PROJECT_DIR}/.claude/cc-enslaver/edicts.toml
by default. Editing the file by hand is also fully supported — the format
is small enough that the file is the source of truth, and this script is
just an ergonomic shortcut.

Why we rewrite the whole file instead of patching:
  TOML has no canonical "append a table" operation in the stdlib (tomllib
  is read-only; tomli-w is third-party). We load → mutate → re-emit using
  a small purpose-built writer that preserves comments via a "header
  comment" convention. The schema is shallow enough that this is fine.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib import edicts as edicts_lib  # noqa: E402


_HEADER = """# cc-enslaver — 圣旨 (Imperial Edicts) file
#
# This file defines project-specific hard rules that the cc-enslaver
# plugin enforces on top of the built-in 9 rules.
#
# Schema:
#   [[edicts]]
#   id = "E01"                  # unique short id
#   text = "..."                # what the agent should see (imperative)
#   severity = "must"           # "must" -> physically DENY on match
#                               # "should" -> soft reminder only
#   deny_edit = ['''regex''']   # patterns matched against Edit/Write
#                               # new_string / content
#   deny_bash = ['''regex''']   # patterns matched against Bash commands
#   note = "..."                # optional rationale shown in the deny
#                               # reason (not required)
#
# Use triple-quoted strings ('''...''') for regexes to avoid TOML's
# escaping rules. Edits to this file take effect on the next hook event
# (no reload needed).

"""


def _project_path() -> Path:
    p = edicts_lib.default_project_path()
    if p is None:
        sys.stderr.write(
            "CLAUDE_PROJECT_DIR is not set; cannot resolve project edicts.toml. "
            "Set CLAUDE_PROJECT_DIR or use --global.\n"
        )
        sys.exit(2)
    return p


def _global_path() -> Path:
    """Personal-global edicts.toml under ~/.claude (v0.14)."""
    return Path.home() / ".claude" / "cc-enslaver" / "edicts.toml"


def _resolve_path(use_global: bool = False) -> Path:
    """Pick write target. --global → ~/.claude; otherwise project-level."""
    return _global_path() if use_global else _project_path()


def _read_raw_edicts(path: Path) -> list[dict]:
    """Load and return the raw edicts list (as dicts), preserving order."""
    if not path.is_file():
        return []
    try:
        import tomllib
    except ModuleNotFoundError:
        sys.stderr.write("Python 3.11+ required (tomllib).\n")
        sys.exit(2)
    with path.open("rb") as f:
        data = tomllib.load(f)
    raw = data.get("edicts", [])
    if not isinstance(raw, list):
        return []
    return [r for r in raw if isinstance(r, dict)]


def _escape_triple_quoted(s: str) -> str:
    """Make a string safe inside a TOML triple-quoted literal '''...'''."""
    # The only sequence we must avoid is ''' itself; tomli accepts
    # everything else literally inside single-quoted triple strings.
    return s.replace("'''", r"'' + \"'\" + ''")


def _dump_edict(e: dict) -> str:
    """Serialize one edict dict to a TOML [[edicts]] block."""
    parts = ["[[edicts]]"]
    parts.append(f"id = \"{e['id']}\"")
    # Text: use regular string with escaping for embedded quotes.
    text = e.get("text", "").replace("\\", "\\\\").replace('"', '\\"')
    parts.append(f'text = "{text}"')
    sev = e.get("severity", "must")
    parts.append(f'severity = "{sev}"')
    note = e.get("note", "")
    if note:
        n = note.replace("\\", "\\\\").replace('"', '\\"')
        parts.append(f'note = "{n}"')
    for field in ("deny_edit", "deny_bash"):
        vals = e.get(field) or []
        if vals:
            inner = ", ".join(
                f"'''{_escape_triple_quoted(v)}'''" for v in vals
            )
            parts.append(f"{field} = [{inner}]")
    return "\n".join(parts) + "\n"


def _write_edicts(path: Path, edicts: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    body = _HEADER
    for e in edicts:
        body += _dump_edict(e) + "\n"
    path.write_text(body, encoding="utf-8")


# --------------------------------------------------------------------------- #
# Commands.
# --------------------------------------------------------------------------- #
def cmd_list(_: argparse.Namespace) -> int:
    loaded = edicts_lib.load()
    if not loaded:
        p = edicts_lib.edicts_path()
        if p is None:
            print("(no edicts file found)")
            print(f"To create one, run: edict add E01 \"...\" --must --deny-bash REGEX")
        else:
            print(f"(edicts file is empty: {p})")
        return 0
    p = edicts_lib.edicts_path()
    print(f"Source: {p}")
    print(f"{len(loaded)} edict(s):\n")
    for e in loaded:
        sev = "must" if e.severity == "must" else "should"
        hard = ""
        if e._compiled_edit:
            hard += f" deny_edit×{len(e._compiled_edit)}"
        if e._compiled_bash:
            hard += f" deny_bash×{len(e._compiled_bash)}"
        if not hard:
            hard = " (soft-only)"
        print(f"  [{e.id}] {sev}{hard}")
        print(f"    {e.text}")
        if e.note:
            print(f"    note: {e.note}")
    return 0


def cmd_add(args: argparse.Namespace) -> int:
    path = _resolve_path(use_global=getattr(args, "global_", False))
    existing = _read_raw_edicts(path)
    if any(r.get("id") == args.id for r in existing):
        sys.stderr.write(f"Edict id {args.id!r} already exists. Use 'remove' first.\n")
        return 1
    sev = "should" if args.should else "must"
    new = {"id": args.id, "text": args.text, "severity": sev}
    if args.note:
        new["note"] = args.note
    if args.deny_edit:
        new["deny_edit"] = list(args.deny_edit)
    if args.deny_bash:
        new["deny_bash"] = list(args.deny_bash)
    existing.append(new)
    _write_edicts(path, existing)
    scope = "global" if getattr(args, "global_", False) else "project"
    print(f"Added edict {args.id!r} ({sev}, {scope}) → {path}")
    return 0


def cmd_remove(args: argparse.Namespace) -> int:
    # Try project first; if not found there, try global. Explicit --global
    # overrides this fallback.
    if getattr(args, "global_", False):
        paths = [_global_path()]
    else:
        paths = [_project_path(), _global_path()]
    for path in paths:
        if not path.is_file():
            continue
        existing = _read_raw_edicts(path)
        if any(r.get("id") == args.id for r in existing):
            keep = [r for r in existing if r.get("id") != args.id]
            _write_edicts(path, keep)
            print(f"Removed edict {args.id!r} → {path}")
            return 0
    sys.stderr.write(f"No edict with id {args.id!r} found in any edicts.toml.\n")
    return 1


def cmd_reload(_: argparse.Namespace) -> int:
    # Loading is what every hook does anyway; this command is mostly a
    # sanity check + reformatter. Print loaded edicts as proof.
    return cmd_list(_)


def cmd_path(_: argparse.Namespace) -> int:
    p = edicts_lib.edicts_path()
    if p is None:
        # No existing file. Print where one *would* be created.
        d = edicts_lib.default_project_path()
        if d is None:
            print("(CLAUDE_PROJECT_DIR not set)")
            return 1
        print(f"(file does not exist yet; would be created at:)\n{d}")
        return 0
    print(p)
    return 0


def main() -> int:
    # v0.17 — Force stdout to UTF-8 so non-ASCII characters (× in the
    # list output, Chinese edict text, etc.) survive on Windows where
    # the default stdout encoding is the system code page (cp1252 /
    # cp936) which mangles UTF-8 bytes. Rationale: reconfigure() exists
    # since Python 3.7 and we require 3.11+; the try/except is purely
    # defensive in case stdout has been replaced by a non-TextIOWrapper
    # in some unusual harness (e.g. captured by a test runner that
    # wraps it).
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        # Defensive — reason given in the block comment above.
        pass

    parser = argparse.ArgumentParser(
        description="cc-enslaver 圣旨 (Imperial Edicts) CRUD helper",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("list").set_defaults(func=cmd_list)
    sub.add_parser("reload").set_defaults(func=cmd_reload)
    sub.add_parser("path").set_defaults(func=cmd_path)

    p_add = sub.add_parser("add", help="Append a new edict.")
    p_add.add_argument("id", help="Unique short identifier, e.g. E01.")
    p_add.add_argument("text", help="What the agent should see (imperative).")
    group = p_add.add_mutually_exclusive_group()
    group.add_argument("--must", action="store_true", help="severity=must (default)")
    group.add_argument("--should", action="store_true", help="severity=should (soft only)")
    p_add.add_argument(
        "--deny-edit", action="append", default=[], metavar="REGEX",
        help="Regex matched against Edit/Write new_string. May repeat.",
    )
    p_add.add_argument(
        "--deny-bash", action="append", default=[], metavar="REGEX",
        help="Regex matched against Bash commands. May repeat.",
    )
    p_add.add_argument("--note", help="Optional rationale shown in deny reason.")
    p_add.add_argument(
        "--global", action="store_true", dest="global_",
        help="Write to personal global ~/.claude/cc-enslaver/edicts.toml "
        "instead of project-level .claude/cc-enslaver/edicts.toml (v0.14).",
    )
    p_add.set_defaults(func=cmd_add)

    p_rm = sub.add_parser("remove", help="Remove an edict by id.")
    p_rm.add_argument("id")
    p_rm.add_argument(
        "--global", action="store_true", dest="global_",
        help="Restrict removal to the global ~/.claude edicts.toml. "
        "Without this flag, looks in project then falls back to global (v0.14).",
    )
    p_rm.set_defaults(func=cmd_remove)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
