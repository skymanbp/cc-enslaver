#!/usr/bin/env python3
"""anti-laziness — bash bypass-pattern guard.

PreToolUse handler with matcher `Bash`. Inspects the `command` string of
every Bash tool call and denies known "lazy bypass" patterns:

  --no-verify          skipping git/commit hooks
  --no-gpg-sign        skipping commit signature
  git push --force     irreversible overwrite (without --force-with-lease)
  chmod 777            world-writable permissions

Each detected pattern emits a structured deny with a reason that
explains *why* it is a violation of rule 03 (rules/03-root-cause.md)
and how to address the real underlying problem.

Failing-open: a bug in this guard cannot block the agent. Any exception
is logged to stderr and the tool call is allowed.

Why a separate script from read_guard.py:
  read_guard owns per-session disk state (PostToolUse Read|Write +
  PreToolUse Edit|Write); bash_guard is purely stateless string
  inspection. Splitting them keeps the two failure modes (state
  corruption vs. regex bug) independent and the responsibilities
  audit-able in isolation.

Output contract (same as read_guard's deny path):
  {
    "hookSpecificOutput": {
      "hookEventName": "PreToolUse",
      "permissionDecision": "deny",
      "permissionDecisionReason": "<reason>"
    }
  }
"""

from __future__ import annotations

import json
import re
import sys
import traceback


# --------------------------------------------------------------------------- #
# Static bypass patterns.
#
# Each entry is a regex against the full command string. The `name` is
# echoed in the deny reason so the agent knows exactly which pattern
# was matched. The `explanation` tells the agent how to recover.
# --------------------------------------------------------------------------- #
STATIC_PATTERNS = [
    {
        "name": "--no-verify (skipping commit hooks)",
        # Word-boundary on the right; left side ensures it is a flag
        # (preceded by whitespace or start of command) not part of a
        # longer flag like --no-verify-extra.
        "regex": re.compile(r"(?:^|\s)--no-verify(?:\s|$)"),
        "rule": "03",
        "explanation": (
            "The `--no-verify` flag skips git/commit hooks. Hooks exist to "
            "catch broken code; bypassing them ships broken code. Per rule 03 "
            "(rules/03-root-cause.md), fix the hook-failure root cause "
            "instead of bypassing the hook. If the user has explicitly "
            "instructed you to bypass, ask them to run the command manually "
            "rather than acting on their behalf."
        ),
    },
    {
        "name": "--no-gpg-sign (skipping commit signature)",
        "regex": re.compile(r"(?:^|\s)--no-gpg-sign(?:\s|$)"),
        "rule": "03",
        "explanation": (
            "Skipping GPG signing strips commit verification. If signing is "
            "broken, fix the signing setup. Per rule 03 "
            "(rules/03-root-cause.md), do not bypass verification to make a "
            "command go through."
        ),
    },
    {
        "name": "chmod 777 (world-writable)",
        # Matches: `chmod 777`, `chmod -R 777`, `chmod 0777`, `chmod -R 0777`.
        "regex": re.compile(r"\bchmod\s+(?:-R\s+)?0?777\b"),
        "rule": "03",
        "explanation": (
            "World-writable permissions (777) almost never solve the "
            "underlying access issue and introduce security risk. Per rule 03 "
            "(rules/03-root-cause.md), identify the actual user or process "
            "that needs access and grant it specifically (e.g., `chown` + "
            "a restrictive mode like 750 or 640)."
        ),
    },
]


def _detect_force_push(cmd: str) -> dict | None:
    """Detect `git push --force` (or `-f`) without `--force-with-lease`.

    `--force-with-lease` is the safe variant: it refuses to overwrite if the
    remote moved underneath you. We allow it; we only block the unconditional
    `--force` / `-f`.
    """
    if not re.search(r"\bgit\s+push\b", cmd):
        return None
    # Strip --force-with-lease (and its optional =refspec value) before
    # checking for --force. Otherwise the substring `--force` inside
    # `--force-with-lease` would falsely match below.
    sanitised = re.sub(r"--force-with-lease(?:=\S+)?", "", cmd)
    if re.search(r"(?:\s|^)(?:--force|-f)(?:\s|$)", sanitised):
        return {
            "name": "git push --force without --force-with-lease",
            "rule": "03",
            "explanation": (
                "Force-pushing can irreversibly overwrite teammates' work. "
                "Per rule 03 (rules/03-root-cause.md): use "
                "`--force-with-lease` (refuses the push if the remote moved), "
                "or rebase and do a regular push, or address the divergence "
                "root cause. If you are absolutely certain force-push is "
                "warranted, ask the user to run it manually."
            ),
        }
    return None


# --------------------------------------------------------------------------- #
# Deny output helper (same shape as read_guard's deny; duplicated rather
# than imported to keep this script's failure modes independent).
# --------------------------------------------------------------------------- #
DENY_TEMPLATE = """anti-laziness · rule {rule} violation (bypass pattern)

Pattern matched: {name}
Command: {command}

{explanation}
"""


def _emit_deny(command: str, pattern_name: str, rule: str, explanation: str) -> None:
    """Write the deny JSON to stdout as UTF-8 bytes (Windows-safe)."""
    payload = {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": DENY_TEMPLATE.format(
                rule=rule,
                name=pattern_name,
                command=command,
                explanation=explanation,
            ),
        }
    }
    encoded = (json.dumps(payload, ensure_ascii=False) + "\n").encode("utf-8")
    sys.stdout.buffer.write(encoded)
    sys.stdout.buffer.flush()


# --------------------------------------------------------------------------- #
# Entry point.
# --------------------------------------------------------------------------- #
def main() -> int:
    try:
        raw = sys.stdin.read()
        if not raw.strip():
            return 0
        payload = json.loads(raw)
        if payload.get("hook_event_name") != "PreToolUse":
            return 0
        if payload.get("tool_name") != "Bash":
            return 0
        command = (payload.get("tool_input") or {}).get("command", "")
        if not command:
            return 0

        # Static regex patterns first.
        for pat in STATIC_PATTERNS:
            if pat["regex"].search(command):
                _emit_deny(command, pat["name"], pat["rule"], pat["explanation"])
                return 0

        # Compound: git push --force without --force-with-lease.
        fp = _detect_force_push(command)
        if fp:
            _emit_deny(command, fp["name"], fp["rule"], fp["explanation"])
            return 0

        # No bypass detected; allow by exiting silently.
    except Exception:
        sys.stderr.write("[anti-laziness] bash_guard exception:\n")
        sys.stderr.write(traceback.format_exc())
    return 0


if __name__ == "__main__":
    sys.exit(main())
