#!/usr/bin/env python3
"""cc-enslaver — read-before-edit guard.

A single PreToolUse handler covering Read / Write / Edit. Recording and
gating live in the same hook event so they share a scope:

  Read    → record file_path; allow
  Write   → if target exists and is unrecorded: DENY (file is unread)
            else: record file_path; allow (covers both new-file creation
            and overwrite-of-known-file)
  Edit    → if target exists and is unrecorded: DENY
            else: allow

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
import sys
import traceback
from pathlib import Path

# Make `lib/` importable when run directly as a script.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib import state as state_lib  # noqa: E402

# --------------------------------------------------------------------------- #
# Tools this guard handles (PreToolUse matcher must include all of them).
# --------------------------------------------------------------------------- #
HANDLED_TOOLS = {"Read", "Write", "Edit"}

# --------------------------------------------------------------------------- #
# Deny message.
# --------------------------------------------------------------------------- #
DENY_TEMPLATE = """cc-enslaver · rule 04 violation (read before edit)

Tool: {tool_name}
Target: {file_path}

This file already exists on disk but has not been Read (or Written) in
this session. Per rule 04 (rules/04-full-context.md), edits must be
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


def _emit_deny(tool_name: str, file_path: str) -> None:
    """Write a structured deny response and exit 0.

    We use sys.stdout.buffer for UTF-8 correctness on Windows, where
    sys.stdout otherwise defaults to the system code page (e.g. cp936)
    and would mangle non-ASCII characters in the reason text.
    """
    payload = {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": DENY_TEMPLATE.format(
                tool_name=tool_name,
                file_path=file_path,
            ),
        }
    }
    encoded = (json.dumps(payload, ensure_ascii=False) + "\n").encode("utf-8")
    sys.stdout.buffer.write(encoded)
    sys.stdout.buffer.flush()
    sys.exit(0)


# --------------------------------------------------------------------------- #
# Single PreToolUse handler.
# --------------------------------------------------------------------------- #
def _handle_pre_tool_use(payload: dict) -> None:
    tool = payload.get("tool_name", "")
    if tool not in HANDLED_TOOLS:
        return
    file_path = (payload.get("tool_input") or {}).get("file_path")
    if not file_path:
        return
    session_id = payload.get("session_id") or "default"

    if tool == "Read":
        # Record the read so subsequent Edit/Write on this file is allowed.
        # Always allow — Read itself will fail naturally if the file does
        # not exist, and a phantom record of a non-existent path is
        # harmless (Edit's os.path.exists short-circuit covers it).
        state_lib.add_read(session_id, file_path)
        return

    if tool == "Write":
        # New file creation: nothing to gate; record so future ops know
        # the file has been seen by the agent.
        if not os.path.exists(file_path):
            state_lib.add_read(session_id, file_path)
            return
        # Existing file: agent must have seen it before (Read or Write).
        if not state_lib.has_read(session_id, file_path):
            _emit_deny(tool, file_path)
            return  # not reached; _emit_deny exits
        # Existing and known: allow + refresh record (no-op if already there).
        state_lib.add_read(session_id, file_path)
        return

    if tool == "Edit":
        # Editing a non-existent file is invalid input that Claude Code
        # itself will reject; we don't second-guess.
        if not os.path.exists(file_path):
            return
        if not state_lib.has_read(session_id, file_path):
            _emit_deny(tool, file_path)
        # Otherwise allow silently. We do NOT record on Edit because Edit
        # is downstream of a prior Read/Write that already recorded.


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
