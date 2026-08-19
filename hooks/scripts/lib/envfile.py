"""cc-enforcer — CLAUDE_ENV_FILE hygiene (v0.34).

Claude Code hands every hook process a CLAUDE_ENV_FILE: a shell file
sourced into subsequent Bash tool calls. SessionStart fires on session
launch AND on every compact/resume, so a plugin that appends its
`export` lines unconditionally on that event grows the file without
bound. Field failure (2026-08-17, booked from a CodeEraser session):
the codex companion plugin re-appended three exports per compact until
the accumulated environment crossed ~8 KB and every Bash call died
silently — the session lost its hands with no diagnostic.

The true origin is the third-party plugin's non-idempotent append.
That is outside this repo's control (a patch to a cached plugin copy
dies on its next version pin), but the CLASS is squarely in this
plugin's remit: session protection against duplicate export
accumulation, whoever writes it. Deduplication keeps the LAST
occurrence per variable name — byte-equivalent to what sourcing the
whole file already yields (later exports win) — so the observable
environment cannot change; only the growth goes.

Failing open is the contract throughout: the file belongs to the
harness, other plugins append to it concurrently, and a hygiene pass
that can corrupt it or crash the injection would be worse than the
disease. Anything this line-based model does not fully represent
(non-export lines other than blanks/comments, a quoted value that
spans lines) refuses the whole pass and leaves the file untouched.
"""

from __future__ import annotations

import os
import re
import sys
from collections.abc import Mapping
from pathlib import Path

# A self-contained `export NAME=<value>` line. Continuation lines of a
# multi-line value do not match — which is exactly why anything beyond
# exports/blanks/comments refuses the pass (see dedupe_text).
_EXPORT_LINE = re.compile(r"^export\s+([A-Za-z_][A-Za-z0-9_]*)=")

_BLANK_OR_COMMENT = re.compile(r"^\s*(#.*)?$")


def _leaves_quote_open(line: str) -> bool:
    """True when a quoted value on this line never closes.

    An unterminated quote means the value continues on the next line —
    the multi-line shape whose opening line must never be dropped.
    Plain shell semantics: inside quotes only the matching close quote
    matters; outside, a backslash escapes the next character (so the
    appender idiom `'\\''` round-trips correctly).
    """
    quote = ""
    i = 0
    while i < len(line):
        ch = line[i]
        if quote:
            if ch == quote:
                quote = ""
        elif ch in "'\"":
            quote = ch
        elif ch == "\\":
            i += 1
        i += 1
    return bool(quote)


def dedupe_text(text: str) -> tuple[str, int]:
    """Collapse duplicate `export NAME=…` lines, keeping the LAST one.

    Returns (new_text, dropped). dropped == 0 means `text` came back
    unchanged — including every refusal: a line that is neither an
    export nor blank/comment, or an export whose quote stays open,
    makes the whole pass a no-op rather than a gamble.
    """
    lines = text.splitlines(keepends=True)
    last_for: dict[str, int] = {}
    for i, line in enumerate(lines):
        m = _EXPORT_LINE.match(line)
        if m is None:
            if _BLANK_OR_COMMENT.match(line):
                continue
            return (text, 0)
        if _leaves_quote_open(line):
            return (text, 0)
        last_for[m.group(1)] = i
    keep = set(last_for.values())
    kept = [
        line
        for i, line in enumerate(lines)
        if _EXPORT_LINE.match(line) is None or i in keep
    ]
    dropped = len(lines) - len(kept)
    return ("".join(kept), dropped) if dropped else (text, 0)


def maybe_dedupe(environ: Mapping[str, str] | None = None) -> int:
    """Dedupe the session's CLAUDE_ENV_FILE in place. Never raises.

    Returns the number of dropped lines (0 = untouched or not
    applicable). Every failure mode is one stderr note and a clean
    return — the auto-GC contract: maintenance must never affect the
    injection payload or block session startup.
    """
    env = os.environ if environ is None else environ
    raw = env.get("CLAUDE_ENV_FILE", "")
    if not raw:
        return 0
    try:
        path = Path(raw)
        if not path.is_file():
            return 0
        new_text, dropped = dedupe_text(path.read_text(encoding="utf-8"))
        if dropped:
            path.write_text(new_text, encoding="utf-8")
            sys.stderr.write(
                f"[cc-enforcer] env-file hygiene: collapsed {dropped} "
                f"duplicate export line(s) in CLAUDE_ENV_FILE\n"
            )
        return dropped
    except Exception as exc:
        sys.stderr.write(f"[cc-enforcer] env-file hygiene skipped: {exc}\n")
        return 0
