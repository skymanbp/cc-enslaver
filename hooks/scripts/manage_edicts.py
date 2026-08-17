#!/usr/bin/env python3
"""cc-enslaver — Imperial Edicts (圣旨) CRUD helper.

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
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
# because the sys.path bootstrap above must run before these lib imports
from lib import edicts as edicts_lib  # noqa: E402
# because of the same sys.path bootstrap, this import cannot sit at top
from lib import tomlio  # noqa: E402

# v0.31 — the two defensive `try: import` blocks that used to sit here are
# gone. `lib.tomlio` is always importable (it owns the missing-tomllib
# fallback internally), and the direct `import tomllib` was a THIRD copy of
# the same availability sentinel — the exact shape v0.30 spent a release
# collapsing. Both questions now have one answer each: `tomlio.available()`
# for "can we parse TOML at all", `tomlio.dumps_check()` for "would this
# document parse back".


class EdictWriteError(RuntimeError):
    """Raised when a rewrite would produce an unparseable edicts file."""


_HEADER = """# cc-enslaver — Imperial Edicts (圣旨) file
#
# This file defines project-specific hard rules that the cc-enslaver
# plugin enforces on top of the built-in 12 rules.
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
        # v0.18.1 — diagnostic now lists every fallback that was tried
        # so the operator can pick the right fix without guessing.
        sys.stderr.write(
            "Could not resolve project edicts.toml. Tried:\n"
            "  1. $CLAUDE_PROJECT_DIR — not set\n"
            "  2. cwd as project root — no .git/ or .claude/ marker here\n"
            "\n"
            "Fix one of:\n"
            "  • cd into the project root (containing .git/ or .claude/), or\n"
            "  • set CLAUDE_PROJECT_DIR=/path/to/project, or\n"
            "  • pass --global to write to ~/.claude/cc-enslaver/edicts.toml.\n"
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
    """Load and return the raw edicts list (as dicts), preserving order.

    v0.25.1 — routes through the hardened shared reader instead of a
    second, hand-rolled `tomllib.load`. v0.25 created lib/tomlio.py
    precisely so a UTF-8 BOM or a non-UTF-8 save would not disable
    enforcement, wired the two hook-side loaders to it, and then never
    swept the tree — so the very same edicts.toml that the hooks read
    fine still crashed `edict list` / `add` / `remove`. That split is the
    repo-wide-sync omission rule 12 exists to catch, committed by the
    release that introduced the shared module.
    """
    if not path.is_file():
        return []
    if not tomlio.available():
        sys.stderr.write("Python 3.11+ required (tomllib).\n")
        sys.exit(2)
    data = tomlio.parse_toml_file(
        path, lambda m: sys.stderr.write(f"[cc-enslaver edicts] {m}\n"),
    )
    if data is None:
        sys.stderr.write(f"Could not parse {path}; refusing to rewrite it.\n")
        sys.exit(2)
    raw = data.get("edicts", [])
    if not isinstance(raw, list):
        return []
    return [r for r in raw if isinstance(r, dict)]


# v0.30 — `_escape_triple_quoted` used to live here, marked "deprecated,
# kept only so an external caller does not break". There is no external
# caller and there cannot be one: it is a module-private helper in a
# script this repo never installs as an importable package, and nothing in
# the tree referenced it. The v0.26 audit correctly proved the
# triple-quoted literal form cannot round-trip a regex (it mangled any
# pattern containing `'''`, and could not encode a control character at
# all) and moved every caller to `_toml_basic_string`. Keeping the broken
# encoder next to the correct one only invites someone to reach for it.


# v0.31 — the encoder moved to `lib/tomlio.basic_string` so this writer and
# `manage_sync_gate.py` share one definition. Its two historical defects
# (a raw newline in a single-line basic string; DEL passing a `>= " "`
# guard) are documented there. The alias keeps this module's call sites
# unchanged and keeps the name that its own comments reference.
_toml_basic_string = tomlio.basic_string


def _dump_edict(e: dict) -> str:
    """Serialize one edict dict to a TOML [[edicts]] block.

    v0.26.0 — every value is coerced with `str()` before it reaches a
    string helper. Only `id` was, so a hand-written edict whose `text`,
    `severity` or `note` parsed as a non-string (all legal TOML: an
    integer, an array) raised `AttributeError: 'int' object has no
    attribute 'replace'`. That matters more than it looks: `_write_edicts`
    re-serialises EVERY edict on any add or remove, so one wrongly-typed
    field anywhere in the file broke the whole CLI — the same blast radius
    as the v0.25 multi-line-string corruption bug this function was last
    fixed for. `deny_edit` / `deny_bash` entries get the same treatment.
    """
    parts = ["[[edicts]]"]
    parts.append(f'id = "{_toml_basic_string(str(e["id"]))}"')
    parts.append(f'text = "{_toml_basic_string(str(e.get("text", "")))}"')
    sev = e.get("severity", "must")
    parts.append(f'severity = "{_toml_basic_string(str(sev))}"')
    note = e.get("note", "")
    if note:
        parts.append(f'note = "{_toml_basic_string(str(note))}"')
    for field in ("deny_edit", "deny_bash"):
        vals = e.get(field) or []
        if isinstance(vals, (str, bytes)):
            # A scalar where a list belongs: iterating it would emit one
            # entry per character.
            vals = [vals]
        if not isinstance(vals, (list, tuple)):
            vals = [vals]
        if vals:
            # v0.26.0 — basic strings, not triple-quoted literals. The
            # literal form silently mangled any regex containing `'''` and
            # could not encode a control character at all. Escaping the
            # backslashes a regex contains is lossless; losing the pattern
            # is not.
            inner = ", ".join(
                f'"{_toml_basic_string(str(v))}"' for v in vals
            )
            parts.append(f"{field} = [{inner}]")
    return "\n".join(parts) + "\n"


def _write_edicts(path: Path, edicts: list[dict]) -> None:
    """Rewrite the whole edicts file, refusing to leave it unparseable.

    v0.26.0 — this function re-serialises EVERY edict on any add/remove,
    so a single unencodable field used to take the entire file down:
    tomllib then rejected it, `load()` returned no edicts, and every
    `must` rule in the project silently stopped enforcing while the CLI
    printed "Added edict …". Parsing the result before committing it
    turns that silent, total failure into a loud, local one.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    body = _HEADER
    for e in edicts:
        body += _dump_edict(e) + "\n"
    err = tomlio.dumps_check(body)
    if err is not None:
        raise EdictWriteError(
            f"refusing to write {path}: the result would not parse "
            f"({err}). The file on disk is unchanged. This is a "
            f"serialisation bug — please report the edict content "
            f"that triggered it."
        )
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
        description="cc-enslaver Imperial Edicts (圣旨) CRUD helper",
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
