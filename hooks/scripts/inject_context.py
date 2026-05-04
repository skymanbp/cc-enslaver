#!/usr/bin/env python3
"""
cc-enslaver — context injection hook.

Single entry-point for every Claude Code hook this plugin subscribes to.
Reads the matching prompt file from `../../prompts/` and emits the JSON
shape that Claude Code expects for the corresponding hook event.

Why one script instead of three:
  Per CLAUDE.md §2.6 (minimum effective change), three near-identical
  scripts is duplication. A single dispatch on --event is the smallest
  surface that still keeps each event's contract explicit.

Why Python (not bash):
  Hook scripts must run on Windows / macOS / Linux without a guaranteed
  bash + jq toolchain. The user's environment ships Python 3.13 globally;
  Python's stdlib is sufficient (no third-party deps).

Hook output spec (verified against
https://code.claude.com/docs/en/hooks.md as of 2026-04-27):

    {
      "hookSpecificOutput": {
        "hookEventName": "<EventName>",
        "additionalContext": "<string>"
      }
    }

We always exit 0 — this hook is purely additive (soft layer). Hard-layer
blocking hooks live in separate scripts (none in v0.1).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# --------------------------------------------------------------------------- #
# Event → prompt file mapping.
# Update both this map AND `hooks/hooks.json` when adding a new event.
# --------------------------------------------------------------------------- #
EVENT_TO_PROMPT: dict[str, str] = {
    "SessionStart": "session-start.md",
    "UserPromptSubmit": "user-prompt.md",
}

# Plugin root resolution:
#   This script lives at  <plugin-root>/hooks/scripts/inject_context.py
#   So plugin root is two levels up from __file__.
PLUGIN_ROOT = Path(__file__).resolve().parents[2]
PROMPTS_DIR = PLUGIN_ROOT / "prompts"


def load_prompt(filename: str) -> str:
    """Read prompt content from prompts/<filename>. Fail loudly on missing file.

    Failing loudly (rather than returning '') is itself an cc-enslaver
    measure: a silent empty injection would mask broken configuration.
    """
    path = PROMPTS_DIR / filename
    if not path.is_file():
        # Surface the misconfiguration to Claude Code's error stream.
        # We still exit 0 with an empty additionalContext so the hook
        # does not block the user; but the diagnostic goes to stderr.
        sys.stderr.write(
            f"[cc-enslaver] missing prompt file: {path}\n"
            f"  expected one of: {sorted(EVENT_TO_PROMPT.values())}\n"
        )
        return ""
    return path.read_text(encoding="utf-8")


def emit(event_name: str, additional_context: str) -> None:
    """Write the hook response JSON to stdout as UTF-8 bytes.

    We bypass `sys.stdout` and write to its underlying buffer directly,
    because on Windows the default `sys.stdout` encoding is the system
    code page (e.g. cp936), which would silently corrupt non-ASCII
    characters in the prompt content. Claude Code reads hook output as
    UTF-8 regardless of platform, so we must emit UTF-8 bytes.
    """
    payload = {
        "hookSpecificOutput": {
            "hookEventName": event_name,
            "additionalContext": additional_context,
        }
    }
    encoded = (json.dumps(payload, ensure_ascii=False) + "\n").encode("utf-8")
    sys.stdout.buffer.write(encoded)
    sys.stdout.buffer.flush()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="cc-enslaver context injection hook",
    )
    parser.add_argument(
        "--event",
        required=True,
        choices=sorted(EVENT_TO_PROMPT.keys()),
        help="Which hook event this invocation corresponds to.",
    )
    args = parser.parse_args()

    # Drain stdin if Claude Code piped hook input to us; we do not currently
    # use it, but reading prevents a SIGPIPE on the parent side.
    try:
        sys.stdin.read()
    except Exception:
        pass

    prompt_filename = EVENT_TO_PROMPT[args.event]
    additional_context = load_prompt(prompt_filename)
    emit(args.event, additional_context)
    return 0


if __name__ == "__main__":
    sys.exit(main())
