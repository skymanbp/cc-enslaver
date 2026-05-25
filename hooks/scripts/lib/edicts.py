"""cc-enslaver — 圣旨 (Imperial Edicts) system.

User-defined per-project hard rules that ride on top of the built-in 9
rules. Loaded from a TOML file (project-level by default), injected into
the session-start / user-prompt soft-layer reminders, and enforced as
PreToolUse DENY when a regex matches Edit / Write content or Bash
commands.

Why TOML and not YAML:
  Python stdlib ships `tomllib` (3.11+) but no YAML parser. cc-enslaver
  has a strict no-third-party-deps contract (see README + CLAUDE.md), and
  rolling a custom YAML subset is fragile. TOML's array-of-tables shape
  is verbose but unambiguous, which suits a config file users hand-edit.

File location resolution (first hit wins):
  1. ${CLAUDE_PROJECT_DIR}/.claude/cc-enslaver/edicts.toml — project,
     team-shareable, recommended
  2. ${HOME}/.claude/cc-enslaver/edicts.toml — personal global fallback

Schema:

    [[edicts]]
    id = "E01"
    text = "禁止使用 mongoose，统一用 prisma"
    severity = "must"   # must (default) | should
    deny_edit = ['''from ["']mongoose["']''']  # optional, list of regexes
    deny_bash = ['''npm (i|install) mongoose''']  # optional, list of regexes
    note = "已统一到 prisma；mongoose 在 PR #142 移除"  # optional

`text` is what the agent sees in the soft-layer injection — it must be
short and imperative. `deny_edit` / `deny_bash` are what the hard layer
matches; missing → soft-layer only. `severity = "should"` downgrades the
edict to soft-layer only (no DENY).

Failing-open everywhere: a malformed file, a missing file, or a broken
regex → the affected edict is skipped (with a stderr diagnostic) but no
tool call is blocked due to a bug in this loader.
"""

from __future__ import annotations

import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

try:
    import tomllib  # type: ignore[unused-ignore]
except ModuleNotFoundError:  # Python < 3.11 — cc-enslaver requires 3.11+
    tomllib = None  # type: ignore[assignment]


_PLUGIN_NAME = "cc-enslaver"
_EDICTS_FILENAME = "edicts.toml"
_VALID_SEVERITIES = {"must", "should"}


@dataclass(frozen=True)
class Edict:
    """One parsed edict with its compiled regex patterns.

    Compiled patterns live alongside the source-string `deny_*` lists so
    diagnostics can name which pattern matched without recompiling.
    """
    id: str
    text: str
    severity: str  # "must" | "should"
    note: str = ""
    deny_edit: tuple[str, ...] = ()
    deny_bash: tuple[str, ...] = ()
    # Compiled regex pairs: (source, compiled). A source whose compile
    # failed is dropped here (and a diagnostic is logged).
    _compiled_edit: tuple[tuple[str, re.Pattern[str]], ...] = field(default=())
    _compiled_bash: tuple[tuple[str, re.Pattern[str]], ...] = field(default=())

    @property
    def is_hard(self) -> bool:
        """True if this edict can physically DENY (must + has patterns)."""
        return self.severity == "must" and (
            bool(self._compiled_edit) or bool(self._compiled_bash)
        )


def edicts_path() -> Path | None:
    """Resolve the edicts.toml location, or None if not found.

    Tries CLAUDE_PROJECT_DIR first (project-level, team-shareable) then
    ~/.claude (personal fallback). Returns the first existing file.
    """
    proj = os.environ.get("CLAUDE_PROJECT_DIR")
    candidates = []
    if proj:
        candidates.append(Path(proj) / ".claude" / _PLUGIN_NAME / _EDICTS_FILENAME)
    candidates.append(Path.home() / ".claude" / _PLUGIN_NAME / _EDICTS_FILENAME)
    for c in candidates:
        if c.is_file():
            return c
    return None


def default_project_path() -> Path | None:
    """The recommended write-location for new edicts (project-level)."""
    proj = os.environ.get("CLAUDE_PROJECT_DIR")
    if not proj:
        return None
    return Path(proj) / ".claude" / _PLUGIN_NAME / _EDICTS_FILENAME


def _warn(msg: str) -> None:
    sys.stderr.write(f"[cc-enslaver edicts] {msg}\n")


def _compile_patterns(
    edict_id: str, kind: str, patterns: list[str],
) -> tuple[tuple[str, re.Pattern[str]], ...]:
    """Compile a list of regex source strings; drop the broken ones."""
    out: list[tuple[str, re.Pattern[str]]] = []
    for pat in patterns:
        try:
            out.append((pat, re.compile(pat)))
        except re.error as e:
            _warn(
                f"edict {edict_id} has invalid {kind} regex {pat!r}: {e}. "
                f"Skipping this pattern (other patterns still apply)."
            )
    return tuple(out)


def _parse_one(raw: dict) -> Edict | None:
    """Validate + compile one [[edicts]] entry. Returns None if unusable."""
    eid = raw.get("id")
    text = raw.get("text")
    if not isinstance(eid, str) or not eid.strip():
        _warn(f"skipping edict with missing / non-string id: {raw!r}")
        return None
    if not isinstance(text, str) or not text.strip():
        _warn(f"edict {eid}: missing / non-string 'text', skipping")
        return None

    severity = raw.get("severity", "must")
    if severity not in _VALID_SEVERITIES:
        _warn(
            f"edict {eid}: severity {severity!r} not in {sorted(_VALID_SEVERITIES)}; "
            f"falling back to 'must'"
        )
        severity = "must"

    note = raw.get("note", "")
    if not isinstance(note, str):
        note = str(note)

    def _coerce_pat_list(field_name: str) -> list[str]:
        v = raw.get(field_name, [])
        if v is None:
            return []
        if not isinstance(v, list):
            _warn(f"edict {eid}: {field_name} is not a list, ignoring")
            return []
        out: list[str] = []
        for item in v:
            if isinstance(item, str) and item:
                out.append(item)
            else:
                _warn(f"edict {eid}: {field_name} entry {item!r} not a non-empty string, skipping")
        return out

    edit_src = _coerce_pat_list("deny_edit")
    bash_src = _coerce_pat_list("deny_bash")

    edit_pats = _compile_patterns(eid, "deny_edit", edit_src)
    bash_pats = _compile_patterns(eid, "deny_bash", bash_src)

    return Edict(
        id=eid,
        text=text.strip(),
        severity=severity,
        note=note.strip(),
        deny_edit=tuple(edit_src),
        deny_bash=tuple(bash_src),
        _compiled_edit=edit_pats,
        _compiled_bash=bash_pats,
    )


def load() -> list[Edict]:
    """Load and return the list of edicts.

    Empty list when:
      • no edicts.toml exists (the normal case for projects not using
        圣旨)
      • the file is empty / has no `[[edicts]]` tables
      • tomllib unavailable (Python < 3.11 — should never happen given
        cc-enslaver's stated Python 3.13 baseline)

    Never raises: any parse / IO error is logged to stderr and an empty
    list returned, so the surrounding hooks fall through to their usual
    behaviour.
    """
    if tomllib is None:
        return []
    p = edicts_path()
    if p is None:
        return []
    try:
        with p.open("rb") as f:
            data = tomllib.load(f)
    except OSError as e:
        _warn(f"could not read {p}: {e}")
        return []
    except tomllib.TOMLDecodeError as e:
        _warn(f"invalid TOML in {p}: {e}")
        return []

    raw_list = data.get("edicts", [])
    if not isinstance(raw_list, list):
        _warn(f"{p}: top-level 'edicts' must be an array of tables")
        return []

    out: list[Edict] = []
    seen_ids: set[str] = set()
    for raw in raw_list:
        if not isinstance(raw, dict):
            _warn(f"{p}: edicts entry is not a table, skipping: {raw!r}")
            continue
        ed = _parse_one(raw)
        if ed is None:
            continue
        if ed.id in seen_ids:
            _warn(f"{p}: duplicate edict id {ed.id!r}, keeping first definition")
            continue
        seen_ids.add(ed.id)
        out.append(ed)
    return out


# --------------------------------------------------------------------------- #
# Soft-layer injection rendering.
# --------------------------------------------------------------------------- #
def render_injection(edicts: list[Edict]) -> str:
    """Render the edicts as a compact markdown block for injection.

    Returns an empty string when there are no edicts so injection hooks
    can simply concatenate this onto their base prompt.
    """
    if not edicts:
        return ""
    lines = [
        "",
        "---",
        "",
        "## 🏛️ 圣旨（项目自定义硬规则；优先级 > 通用 9 条）",
        "",
        "> 用户自定义、可热更新。`must` = 物理强制（违反即 DENY）；`should` = 软提醒。",
        "",
        "| ID | Severity | Imperative | Hard-enforced |",
        "|----|----------|-----------|---------------|",
    ]
    for e in edicts:
        sev = "🚨 **must**" if e.severity == "must" else "⚠️ should"
        hard_bits: list[str] = []
        if e._compiled_edit:
            hard_bits.append(f"Edit/Write × {len(e._compiled_edit)}")
        if e._compiled_bash:
            hard_bits.append(f"Bash × {len(e._compiled_bash)}")
        hard = " · ".join(hard_bits) if hard_bits else "—"
        # Escape pipes in the text to keep the markdown table well-formed.
        text = e.text.replace("|", r"\|").replace("\n", " ")
        lines.append(f"| `{e.id}` | {sev} | {text} | {hard} |")
    lines.append("")
    lines.append(
        "> 违反 must 圣旨的 Edit/Write/Bash 会被 PreToolUse DENY，"
        "deny reason 会指明具体圣旨 ID。"
    )
    lines.append("")
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# Hard-layer scanning. Used by read_guard (Edit / Write content) and
# bash_guard (Bash command).
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class EdictHit:
    """One matching edict + the specific regex that matched."""
    edict: Edict
    pattern_source: str
    snippet: str  # short, for the deny reason


def _line_window(text: str, span_start: int, span_end: int) -> str:
    """Return the line containing [span_start, span_end] (no extension)."""
    line_start = text.rfind("\n", 0, span_start)
    line_start = 0 if line_start == -1 else line_start + 1
    line_end = text.find("\n", span_end)
    line_end = len(text) if line_end == -1 else line_end
    return text[line_start:line_end]


def find_edit_violation(edicts: list[Edict], content: str) -> EdictHit | None:
    """Scan Edit/Write `new_string` / `content` against every must edict.

    Returns the first hit (by edict order, then pattern order). `should`
    edicts are skipped — they ride on the soft layer only.
    """
    if not content:
        return None
    for ed in edicts:
        if ed.severity != "must":
            continue
        for src, pat in ed._compiled_edit:
            m = pat.search(content)
            if m:
                snip = _line_window(content, m.start(), m.end())
                if len(snip) > 240:
                    snip = snip[:237] + "..."
                return EdictHit(edict=ed, pattern_source=src, snippet=snip)
    return None


def find_bash_violation(edicts: list[Edict], command: str) -> EdictHit | None:
    """Scan a Bash command against every must edict's deny_bash list."""
    if not command:
        return None
    for ed in edicts:
        if ed.severity != "must":
            continue
        for src, pat in ed._compiled_bash:
            m = pat.search(command)
            if m:
                # Bash commands are usually one line; use the matched
                # span itself as snippet so the deny is precise.
                snip = command if len(command) <= 240 else command[:237] + "..."
                return EdictHit(edict=ed, pattern_source=src, snippet=snip)
    return None


def deny_reason(hit: EdictHit, *, kind: str, tool_or_cmd: str) -> str:
    """Build the cc-enslaver-style deny reason for a 圣旨 hit.

    kind: "Edit" / "Write" / "Bash" — used in the headline.
    tool_or_cmd: file_path for Edit/Write, command for Bash.
    """
    ed = hit.edict
    note_line = f"Note: {ed.note}\n" if ed.note else ""
    return (
        f"cc-enslaver · 圣旨 {ed.id} violation (user-defined hard edict)\n\n"
        f"Edict: {ed.text}\n"
        f"{note_line}"
        f"Tool: {kind}\n"
        f"Target: {tool_or_cmd}\n"
        f"Matched pattern: {hit.pattern_source!r}\n\n"
        f"Snippet:\n{hit.snippet}\n\n"
        f"This is a project-level edict defined in "
        f".claude/cc-enslaver/edicts.toml. It has severity = 'must',\n"
        f"which means the violation is physically blocked (not a soft\n"
        f"reminder).\n\n"
        f"To proceed:\n"
        f"  • Comply with the edict (recommended), or\n"
        f"  • Surface the conflict to the user — they may want to relax\n"
        f"    the edict (`severity = \"should\"`) or remove it.\n"
        f"  • Do NOT silently rewrite the edict or rationalize a bypass.\n"
    )
