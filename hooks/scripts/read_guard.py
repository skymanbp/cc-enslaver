#!/usr/bin/env python3
"""cc-enslaver — read-before-edit guard + patch-style content guard.

A single PreToolUse handler covering Read / Write / Edit. Recording and
gating live in the same hook event so they share a scope:

  Read    → record file_path; allow
  Write   → if target exists and is unrecorded: DENY (file is unread)
            else: record file_path; record last_edit_turn; allow
  Edit    → if target exists and is unrecorded: DENY (file is unread)
            else if new_string contains unjustified patch markers: DENY
            else: record last_edit_turn; allow

Why everything in PreToolUse (and not split with PostToolUse):
  Empirically (Claude Code v2.1.x), `PostToolUse` does not fire for tool
  calls whose `tool_input.file_path` lies outside the current project's
  working directory, but `PreToolUse` *does* fire for such calls. If we
  recorded in Post and gated in Pre, an out-of-project Read would never
  be recorded, then the next out-of-project Edit on the same file would
  be denied even though the agent *just* read it. v0.3.1 shipped that
  bug; v0.3.2 fixes it by moving recording to Pre, which has a scope
  consistent with the gating side.

  The trade-off: in Pre we record speculatively (before the tool has
  actually succeeded). If a Read fails, we still recorded the path —
  but a later Edit against that same (non-existent) path is allowed
  anyway by the `os.path.exists` short-circuit, so the speculative
  record is harmless.

v0.11.0 — Two new responsibilities, both for rule 08 + rule 09:

  1. **Patch-style new_string interception** (rule 09). Before allowing
     an Edit / Write that passed the read-before-edit gate, scan the
     `new_string` for "patch markers" that bypass type/lint/test
     systems without justification: `try: ... except: pass`, `# noqa`,
     `# type: ignore`, `// @ts-ignore`, `// eslint-disable`,
     `time.sleep(...) # race/wait/workaround`. Each marker must carry
     a "why" rationale in an immediately adjacent comment (containing
     "because" / "原因" / "why" / a substantive justification) to be
     allowed through. Bare markers = laziness = DENY.

  2. **Edit-turn recording** (rule 08 + 09 Stop-hook backstop). When
     an Edit or Write passes all checks, stamp `last_edit_turn =
     current turn_count` into session state. The Stop hook's layers
     (e) and (f) only fire on turns where an edit actually happened,
     so this stamp is what scopes them.

Failing-open contract: if anything in this script raises, we still
allow the tool call and only log to stderr. A bug in the guard cannot
be permitted to brick the agent.

Hook output spec (verified against
https://code.claude.com/docs/en/hooks.md as of 2026-04-27):

    {
      "hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "permissionDecision": "deny",
        "permissionDecisionReason": "<human-readable reason>"
      }
    }

`allow` is the default when no JSON is emitted, so we stay silent on
the non-blocking paths.
"""

from __future__ import annotations

import json
import os
import re
import sys
import traceback
from pathlib import Path

# Make `lib/` importable when run directly as a script.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib import state as state_lib  # noqa: E402
from lib import edicts as edicts_lib  # noqa: E402

# --------------------------------------------------------------------------- #
# Tools this guard handles (PreToolUse matcher must include all of them).
# --------------------------------------------------------------------------- #
HANDLED_TOOLS = {"Read", "Write", "Edit"}

# --------------------------------------------------------------------------- #
# Deny messages.
# --------------------------------------------------------------------------- #
UNREAD_DENY_TEMPLATE = """cc-enslaver · rule 04 + 08 violation (read-before-edit)

Tool: {tool_name}
Target: {file_path}

This file already exists on disk but has not been Read (or Written) in
this session. Per rule 04 (rules/04-full-context.md) + rule 08
(rules/08-read-before-edit-think-before-write.md), edits must be
preceded by a complete reading of the target file so you understand
the surrounding architecture and downstream impact.

To proceed:
  1. Call Read on this file (the entire file, not just the diff context).
  2. After reading, retry the {tool_name}.

If you are intentionally creating a NEW file, this guard would not have
fired -- it triggers only when the target already exists. The fact that
it fired means there is content here you have not yet examined.

If you have already Read this file in this session but the guard still
denies (Claude Code occasionally short-circuits Read to a result cache
without firing the hook -- a known issue), you can register the file
as read via the v0.4.0 escape hatch. From a Bash tool call:

  # 1. Compute SHA-256 of the file currently on disk:
  HASH=$(python -c 'import hashlib,sys; print(hashlib.sha256(open(sys.argv[1],"rb").read()).hexdigest())' PATH)
  # 2. Register:
  python "${{CLAUDE_PLUGIN_ROOT}}/hooks/scripts/register_read.py" --file PATH --hash "$HASH"

The PreToolUse(Bash) hook recomputes the hash from disk and only
registers if it matches your claim, so the escape hatch cannot itself
be used to bypass the read requirement.
"""


# --------------------------------------------------------------------------- #
# Rolling-patch classification thresholds (v0.13.0 — rule 09 hard layer).
#
# Heuristics — deliberately tunable as module-level constants so they can
# be reviewed in one place:
#
#   "small edit"      = max(|old|, |new|) < SMALL_EDIT_MAX_CHARS chars
#                       AND max(lines(old), lines(new)) ≤ SMALL_EDIT_MAX_LINES
#   "systematic"      = max chars ≥ SYSTEMATIC_MIN_CHARS
#                       OR  max lines ≥ SYSTEMATIC_MIN_LINES
#   "medium"          = neither (no counter change)
#
# DENY fires when the predicted next small-edit count would be ≥
# ROLLING_PATCH_THRESHOLD. The recorded count is *not* incremented on
# DENY (a denied edit never landed; counting it would double-count and
# silently disable the threshold). Recovery: do one systematic edit to
# reset the counter to 0.
# --------------------------------------------------------------------------- #
SMALL_EDIT_MAX_CHARS = 200
SMALL_EDIT_MAX_LINES = 10
SYSTEMATIC_MIN_CHARS = 1500
SYSTEMATIC_MIN_LINES = 50
ROLLING_PATCH_THRESHOLD = 4


def _lines(text: str) -> int:
    """Line count of `text`. Treats empty string as 0 lines, not 1."""
    if not text:
        return 0
    return text.count("\n") + 1


def _classify_change(old_string: str, new_string: str) -> str:
    """Return 'systematic' / 'small' / 'medium' for an edit's footprint.

    For Edit, both old and new are meaningful. For Write, callers pass
    old_string="" so the classification falls back to new_string alone.
    For Edit-with-empty-old_string (rare insertion case) the same applies.
    """
    old = old_string or ""
    new = new_string or ""
    max_chars = max(len(old), len(new))
    max_lines = max(_lines(old), _lines(new))
    if max_chars >= SYSTEMATIC_MIN_CHARS or max_lines >= SYSTEMATIC_MIN_LINES:
        return "systematic"
    if max_chars < SMALL_EDIT_MAX_CHARS and max_lines <= SMALL_EDIT_MAX_LINES:
        return "small"
    return "medium"


ROLLING_PATCH_DENY_TEMPLATE = """cc-enslaver · rule 09 violation (rolling-patch interception)

Tool: {tool_name}
Target: {file_path}
Rolling-patch counter: {current_count} small edit(s) already applied
this session; this would be attempt #{attempt_count} — at or above the
threshold of {threshold}.

Per rule 09 (rules/09-systematic-modification.md), the cumulative
pattern of repeated **small** edits to the same file without a single
**systematic** rewrite is forbidden as "rolling patches":

> 同一文件本会话 ≥ 4 次小幅 Edit 而没有一次系统性重写，属于反应式累加。

Each small edit fixes one symptom in isolation; the aggregate signal
is that you have not re-engaged with the file's overall structure or
identified the root cause.

Classification used here:
  small      = max(|old_string|, |new_string|) < {small_chars} chars
               AND max line count ≤ {small_lines}
  systematic = max chars ≥ {sys_chars} OR max line count ≥ {sys_lines}
               (resets the counter to 0)
  medium     = anything in between (does not count, does not reset)

To proceed, do one of:

  (1) **Systematic rewrite**: combine your pending small fixes into a
      single Edit (or Write) of ≥ {sys_lines} lines / ≥ {sys_chars}
      chars on `new_string` / `content`. This counts as systematic and
      resets the counter to 0 for this file.

  (2) **Batch multiple typo-class fixes**: if you genuinely have several
      independent small unrelated changes, expand the surrounding context
      so each individual Edit clears the small-edit threshold (≥ 10
      lines / ≥ 200 chars), or use Write to replace the whole file at
      once.

  (3) **Stop and surface**: tell the user "this file needs a systematic
      rewrite; please review my plan before I continue". Let them
      decide whether to relax the constraint or refactor the approach.

Note: this is NOT the patch-marker check — your new_string is clean of
try/except: pass, # noqa, @ts-ignore, etc. It is the AGGREGATE PATTERN
check: too many small fixes signal a comprehension gap, not a
suppression.
"""


PATCH_DENY_TEMPLATE = """cc-enslaver · rule 09 violation (patch-style new_string)

Tool: {tool_name}
Target: {file_path}
Pattern matched: {pattern_label}

Snippet (the offending segment in your new_string):
{snippet}

Per rule 09 (rules/09-systematic-modification.md), the modification
you are trying to commit contains a "patch marker" that silences
type / lint / test / error handling **without justifying why**.

Allowed forms require a why-comment on the same line or an
immediately adjacent line, containing one of: `because`, `原因`,
`why`, `正当`, or a concrete justification (issue id / spec ref /
clear technical rationale). Bare suppressions are not allowed.

Examples of acceptable forms:

  # noqa: E501  -- URL string exceeds 100 chars; splitting hurts readability
  LONG_URL = "https://..."

  // @ts-ignore: third-party lib has incomplete type, see issue #1234
  const result = legacy.foo();

If you actually meant to fix the underlying issue (rule 03), do that
instead of suppressing the signal. If the suppression is truly
warranted, add the rationale comment and retry. If you genuinely need
to bypass this guard, surface the deny to the user and let them edit
manually -- the discipline exists to flag laziness, not block you.
"""


def _emit_deny(template: str, **fields: object) -> None:
    """Write a structured deny response and exit 0.

    We use sys.stdout.buffer for UTF-8 correctness on Windows, where
    sys.stdout otherwise defaults to the system code page (e.g. cp936)
    and would mangle non-ASCII characters in the reason text.
    """
    reason = template.format(**fields)
    _emit_raw_deny(reason)


def _emit_raw_deny(reason: str) -> None:
    """Write a structured deny response (with a pre-built reason) and exit 0."""
    payload = {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }
    }
    encoded = (json.dumps(payload, ensure_ascii=False) + "\n").encode("utf-8")
    sys.stdout.buffer.write(encoded)
    sys.stdout.buffer.flush()
    sys.exit(0)


# --------------------------------------------------------------------------- #
# Patch-style markers (rule 09, v0.11.0).
#
# Each entry is (label, regex). The regex matches the *bare* marker form.
# We then look at a small surrounding window (±1 line) for a "why" comment;
# if one is present, the marker is considered justified and we let it
# through. Otherwise → DENY.
#
# Design notes:
#   - Detection is intentionally conservative: only the well-known
#     suppression idioms. False negatives (a clever workaround we don't
#     match) cost a soft-layer reminder; false positives (denying a
#     legitimate use) cost the agent a turn. Conservative regex set keeps
#     false-positive rate low.
#   - The "try: ... except: pass" detector spans newlines because the
#     bare-pass idiom always does.
# --------------------------------------------------------------------------- #
PATCH_MARKERS: list[tuple[str, re.Pattern[str]]] = [
    (
        "Python: bare try / except: pass (silent exception swallow)",
        re.compile(
            r"(^|\n)[ \t]*try[ \t]*:[ \t]*\n"
            r"(?:[ \t]+[^\n]*\n)+?"
            r"[ \t]*except\b[^:\n]*:[ \t]*\n"
            r"[ \t]*pass[ \t]*(?:\n|$)",
            re.MULTILINE,
        ),
    ),
    (
        "Python: # noqa without rationale",
        re.compile(r"#[ \t]*noqa(?::[ \t]*[A-Z]+\d+(?:[ \t]*,[ \t]*[A-Z]+\d+)*)?[ \t]*(?:\n|$)"),
    ),
    (
        "Python: # type: ignore without rationale",
        re.compile(r"#[ \t]*type:[ \t]*ignore(?:\[[^\]]*\])?[ \t]*(?:\n|$)"),
    ),
    (
        "TypeScript: // @ts-ignore without rationale",
        re.compile(r"//[ \t]*@ts-ignore[ \t]*(?:\n|$)"),
    ),
    (
        "TypeScript: // @ts-expect-error without rationale",
        re.compile(r"//[ \t]*@ts-expect-error[ \t]*(?:\n|$)"),
    ),
    (
        "JavaScript/TypeScript: // eslint-disable[-next-line] without rationale",
        re.compile(
            r"//[ \t]*eslint-disable(?:-next-line|-line)?"
            r"(?:[ \t]+[a-zA-Z0-9/_-]+(?:[ \t]*,[ \t]*[a-zA-Z0-9/_-]+)*)?[ \t]*(?:\n|$)"
        ),
    ),
    (
        "Python: time.sleep used to mask a race/wait/workaround",
        re.compile(
            r"\btime\.sleep\([^)]*\)[ \t]*#[ \t]*(?:wait|race|workaround|hack|fix(?:me)?)\b",
            re.IGNORECASE,
        ),
    ),
]

# Rationale keywords. The line containing a patch marker, or its immediate
# neighbours (±1 line), must contain at least one of these tokens (case-
# insensitive) for the marker to be considered justified.
RATIONALE_TOKENS = (
    "because", "原因", "why", "正当", "rationale", "reason",
    # Common justification leads
    "see issue", "see pr", "see comment", "see ticket", "tracking",
    "intentional", "intentionally", "deliberate", "deliberately",
    # Third-party-lib excuse (acceptable as a stated reason)
    "third-party", "third party", "vendor",
    # Spec / standard reference
    "per spec", "per rfc", "per standard",
)


def _line_window(text: str, span_start: int, span_end: int) -> str:
    """Return the line containing [span_start, span_end] plus ±1 line.

    Used to look for a "why" rationale in the immediate neighbourhood of
    a suppression marker.
    """
    line_start = text.rfind("\n", 0, span_start)
    line_start = 0 if line_start == -1 else line_start + 1
    line_end = text.find("\n", span_end)
    line_end = len(text) if line_end == -1 else line_end
    # Extend one line up
    prev_start = text.rfind("\n", 0, max(0, line_start - 1))
    prev_start = 0 if prev_start == -1 else prev_start + 1
    # Extend one line down
    next_end = text.find("\n", line_end + 1)
    next_end = len(text) if next_end == -1 else next_end
    return text[prev_start:next_end]


def _has_rationale(snippet: str) -> bool:
    snippet_lc = snippet.lower()
    return any(tok in snippet_lc for tok in RATIONALE_TOKENS)


def _find_unjustified_patch_marker(new_string: str) -> tuple[str, str] | None:
    """Scan `new_string` for the first unjustified patch marker.

    Returns (label, surrounding_snippet) on hit, or None on clean.
    """
    if not new_string:
        return None
    for label, pat in PATCH_MARKERS:
        for m in pat.finditer(new_string):
            window = _line_window(new_string, m.start(), m.end())
            if not _has_rationale(window):
                # Trim snippet to a reasonable size for the deny message.
                short = window if len(window) <= 240 else window[:237] + "..."
                return label, short
    return None


# --------------------------------------------------------------------------- #
# Single PreToolUse handler.
# --------------------------------------------------------------------------- #
def _handle_pre_tool_use(payload: dict) -> None:
    tool = payload.get("tool_name", "")
    if tool not in HANDLED_TOOLS:
        return
    tool_input = payload.get("tool_input") or {}
    file_path = tool_input.get("file_path")
    if not file_path:
        return
    session_id = payload.get("session_id") or "default"
    turn_count = payload.get("turn_count")

    if tool == "Read":
        # Record the read so subsequent Edit/Write on this file is allowed.
        # Always allow — Read itself will fail naturally if the file does
        # not exist, and a phantom record of a non-existent path is
        # harmless (Edit's os.path.exists short-circuit covers it).
        state_lib.add_read(session_id, file_path)
        return

    # Load edicts once per invocation (v0.12). Cheap (one disk read of a
    # small TOML file) and avoids stale state between Edits in the same
    # session if the user is iterating on edicts.toml.
    loaded_edicts = edicts_lib.load()

    def _check_edicts(content: str) -> None:
        """Scan content against all must edicts; DENY on first hit."""
        if not loaded_edicts:
            return
        hit = edicts_lib.find_edit_violation(loaded_edicts, content)
        if hit is not None:
            _emit_raw_deny(edicts_lib.deny_reason(
                hit, kind=tool, tool_or_cmd=file_path,
            ))
            return  # unreachable; _emit_raw_deny exits

    def _check_rolling_patch(old_string: str, new_string: str) -> None:
        """Rule-09 rolling-patch counter (v0.13).

        Classify the change and either DENY (small-edit threshold met),
        reset the counter (systematic rewrite), or increment-and-allow
        (small edit under threshold). Medium-sized changes are a no-op:
        too big to count as "rolling" but too small to count as a
        re-engagement reset.
        """
        kind = _classify_change(old_string, new_string)
        if kind == "systematic":
            state_lib.reset_edit_count(session_id, file_path)
            return
        if kind != "small":
            return  # "medium" — leave counter untouched
        current = state_lib.get_edit_count(session_id, file_path)
        attempt = current + 1
        if attempt >= ROLLING_PATCH_THRESHOLD:
            _emit_deny(
                ROLLING_PATCH_DENY_TEMPLATE,
                tool_name=tool,
                file_path=file_path,
                current_count=current,
                attempt_count=attempt,
                threshold=ROLLING_PATCH_THRESHOLD,
                small_chars=SMALL_EDIT_MAX_CHARS,
                small_lines=SMALL_EDIT_MAX_LINES,
                sys_chars=SYSTEMATIC_MIN_CHARS,
                sys_lines=SYSTEMATIC_MIN_LINES,
            )
            return  # unreachable; _emit_deny exits
        state_lib.record_small_edit(session_id, file_path)

    if tool == "Write":
        target_exists = os.path.exists(file_path)
        # New file creation: nothing to gate on read-before-edit, and
        # no prior small-edit history to consider (it's a fresh file).
        if not target_exists:
            state_lib.add_read(session_id, file_path)
            # rule 09 patch-style check still applies even for new files —
            # writing a brand-new file full of `# noqa` is still laziness.
            content = tool_input.get("content") or ""
            hit = _find_unjustified_patch_marker(content)
            if hit is not None:
                _emit_deny(
                    PATCH_DENY_TEMPLATE,
                    tool_name=tool,
                    file_path=file_path,
                    pattern_label=hit[0],
                    snippet=hit[1],
                )
                return  # unreachable; _emit_deny exits
            # 圣旨 check (v0.12) — applies to new files too.
            _check_edicts(content)
            state_lib.record_edit_turn(session_id, turn_count)
            return
        # Existing file: agent must have seen it before (Read or Write).
        if not state_lib.has_read(session_id, file_path):
            _emit_deny(
                UNREAD_DENY_TEMPLATE,
                tool_name=tool,
                file_path=file_path,
            )
            return  # not reached; _emit_deny exits
        # Existing and known: now check the new content for patch markers.
        content = tool_input.get("content") or ""
        hit = _find_unjustified_patch_marker(content)
        if hit is not None:
            _emit_deny(
                PATCH_DENY_TEMPLATE,
                tool_name=tool,
                file_path=file_path,
                pattern_label=hit[0],
                snippet=hit[1],
            )
            return
        # 圣旨 check (v0.12).
        _check_edicts(content)
        # Rolling-patch check (v0.13). A Write to an existing file is
        # effectively a full-file replacement; classify by `content`
        # alone (old_string="" yields the right small/systematic split).
        _check_rolling_patch("", content)
        state_lib.add_read(session_id, file_path)
        state_lib.record_edit_turn(session_id, turn_count)
        return

    if tool == "Edit":
        # Editing a non-existent file is invalid input that Claude Code
        # itself will reject; we don't second-guess.
        if not os.path.exists(file_path):
            return
        if not state_lib.has_read(session_id, file_path):
            _emit_deny(
                UNREAD_DENY_TEMPLATE,
                tool_name=tool,
                file_path=file_path,
            )
            return  # unreachable; _emit_deny exits
        # Check the new_string for patch markers. Edit can also carry a
        # replace_all flag; the new_string is what actually lands in the
        # file, so that's what we scan.
        new_string = tool_input.get("new_string") or ""
        old_string = tool_input.get("old_string") or ""
        hit = _find_unjustified_patch_marker(new_string)
        if hit is not None:
            _emit_deny(
                PATCH_DENY_TEMPLATE,
                tool_name=tool,
                file_path=file_path,
                pattern_label=hit[0],
                snippet=hit[1],
            )
            return  # unreachable; _emit_deny exits
        # 圣旨 check (v0.12) — scan the incoming new_string.
        _check_edicts(new_string)
        # Rolling-patch check (v0.13).
        _check_rolling_patch(old_string, new_string)
        # Edit allowed — stamp the edit-turn for Stop layers (e)+(f).
        # We do NOT add_read here because Edit is downstream of a prior
        # Read/Write that already recorded.
        state_lib.record_edit_turn(session_id, turn_count)


# --------------------------------------------------------------------------- #
# Entry point.
# --------------------------------------------------------------------------- #
def main() -> int:
    try:
        raw = sys.stdin.read()
        if not raw.strip():
            return 0  # nothing to inspect, fail open
        payload = json.loads(raw)
        if payload.get("hook_event_name") == "PreToolUse":
            _handle_pre_tool_use(payload)
        # Any other event (including the legacy PostToolUse if it ever
        # arrives): no-op, exit 0. Recording is fully owned by Pre now.
    except Exception:
        # Failing open: log and exit 0 so the agent is never blocked
        # by a bug in our own guard.
        sys.stderr.write("[cc-enslaver] read_guard exception:\n")
        sys.stderr.write(traceback.format_exc())
    return 0


if __name__ == "__main__":
    sys.exit(main())
