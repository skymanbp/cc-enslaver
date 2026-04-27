#!/usr/bin/env python3
"""anti-laziness — read-before-edit guard.

Single hook script with two roles, dispatched by the `hook_event_name`
field in the stdin payload (Claude Code routes the events to us via the
matchers in hooks.json):

  PostToolUse  with matcher "Read|Write"
      Record the touched file in this session's state. Those files are
      now considered "known content" and may be Edited later.

  PreToolUse   with matcher "Edit|Write"
      Deny the call if the target file already exists on disk AND the
      session has not yet Read/Written it. Tells the agent to Read first.

Failing-open contract: if anything in this script raises, we still allow
the tool call and only log to stderr. Anti-laziness must never become
anti-progress; a bug in the guard cannot be permitted to brick the agent.

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
# Tools we care about, per role.
# --------------------------------------------------------------------------- #
RECORD_TOOLS = {"Read", "Write"}      # PostToolUse: append to read-trace
GUARD_TOOLS = {"Edit", "Write"}       # PreToolUse: deny if not read

# --------------------------------------------------------------------------- #
# Deny message.
#
# Goal: tell the agent precisely how to recover. A punitive deny that
# leaves the agent guessing would itself violate rule 04 (give the user
# the full context they need to act).
# --------------------------------------------------------------------------- #
DENY_TEMPLATE = """anti-laziness · rule 04 violation (read before edit)

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
# Event handlers.
# --------------------------------------------------------------------------- #
def _handle_post_tool_use(payload: dict) -> None:
    tool = payload.get("tool_name", "")
    if tool not in RECORD_TOOLS:
        return  # matcher should have prevented this; be defensive anyway
    file_path = (payload.get("tool_input") or {}).get("file_path")
    if not file_path:
        return
    session_id = payload.get("session_id") or "default"
    state_lib.add_read(session_id, file_path)


def _handle_pre_tool_use(payload: dict) -> None:
    tool = payload.get("tool_name", "")
    if tool not in GUARD_TOOLS:
        return
    file_path = (payload.get("tool_input") or {}).get("file_path")
    if not file_path:
        return

    # Allow creating a new file; guard only fires for existing targets.
    if not os.path.exists(file_path):
        return

    session_id = payload.get("session_id") or "default"
    if state_lib.has_read(session_id, file_path):
        return  # already seen; allow

    _emit_deny(tool, file_path)


# --------------------------------------------------------------------------- #
# Entry point.
# --------------------------------------------------------------------------- #
def main() -> int:
    try:
        raw = sys.stdin.read()
        if not raw.strip():
            return 0  # nothing to inspect, fail open
        payload = json.loads(raw)
        event = payload.get("hook_event_name", "")
        if event == "PostToolUse":
            _handle_post_tool_use(payload)
        elif event == "PreToolUse":
            _handle_pre_tool_use(payload)
        # Unknown event: do nothing, exit 0.
    except Exception:
        # Failing open: log and exit 0 so the agent is never blocked
        # by a bug in our own guard.
        sys.stderr.write("[anti-laziness] read_guard exception:\n")
        sys.stderr.write(traceback.format_exc())
    return 0


if __name__ == "__main__":
    sys.exit(main())
