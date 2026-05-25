#!/usr/bin/env python3
"""cc-enslaver — bash guard.

PreToolUse handler with matcher `Bash`. Two responsibilities:

  1. Bypass-pattern blocking. Denies known "lazy bypass" patterns:
       --no-verify          skipping git/commit hooks
       --no-gpg-sign        skipping commit signature
       git push --force     irreversible overwrite (no --force-with-lease)
       chmod 777            world-writable permissions
     Each match emits a structured deny citing rule 03.

  2. Read-cache escape hatch (v0.4.0). When the agent invokes
     `register_read.py --file PATH --hash SHA`, this guard runs *in the
     PreToolUse phase* — which is the only place where `session_id` is
     available — and processes the registration:
       - Recompute SHA-256 of the file on disk.
       - If hash matches the agent claim: add file to session state via
         `state_lib.add_read`, then ALLOW (the user-facing stub script
         runs and prints confirmation).
       - If hash mismatches or the file is missing: DENY with diagnostic.
     The hash check is what prevents the escape hatch from itself
     becoming a laziness vector: an agent that has not opened the file
     cannot produce its current hash.

Failing-open: any exception is logged to stderr and the tool call is
allowed. A bug in this guard cannot block the agent.
"""

from __future__ import annotations

import hashlib
import json
import re
import shlex
import sys
import traceback
from pathlib import Path

# Import the same state library read_guard uses, so registrations land in
# the same state files. `lib/` is alongside this script.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib import state as state_lib  # noqa: E402
from lib import edicts as edicts_lib  # noqa: E402


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
DENY_TEMPLATE = """cc-enslaver · rule {rule} violation (bypass pattern)

Pattern matched: {name}
Command: {command}

{explanation}
"""


def _emit_raw_deny(reason: str) -> None:
    """Write a structured deny response (with a pre-built reason)."""
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


def _emit_deny(command: str, pattern_name: str, rule: str, explanation: str) -> None:
    """Write a built-in-pattern deny (rule 03 / 09 templated)."""
    _emit_raw_deny(DENY_TEMPLATE.format(
        rule=rule,
        name=pattern_name,
        command=command,
        explanation=explanation,
    ))


# --------------------------------------------------------------------------- #
# Read-cache escape hatch: register-as-read.
# --------------------------------------------------------------------------- #

# Match any python invocation whose argv contains a script ending in
# `register_read.py`. We match the basename rather than a full path because
# the path includes ${CLAUDE_PLUGIN_ROOT} which Claude Code expands and may
# differ across install locations / OSes.
_REGISTER_SCRIPT_NAME = "register_read.py"


def _parse_register_invocation(command: str) -> dict | None:
    """If `command` is a register_read.py invocation, return parsed args.

    Returns a dict {"file": str, "hash": str} on success, or None if the
    command is not a register invocation. Tolerates malformed register
    invocations by returning None (the regular bypass-pattern checks then
    apply, and the script call itself will fail at argparse time).
    """
    try:
        tokens = shlex.split(command, posix=True)
    except ValueError:
        return None
    # Find the script-path token. Match by basename so we are robust to
    # whatever absolute path Claude Code expanded ${CLAUDE_PLUGIN_ROOT} to.
    script_idx = None
    for i, tok in enumerate(tokens):
        if tok.endswith(_REGISTER_SCRIPT_NAME):
            script_idx = i
            break
    if script_idx is None:
        return None
    # Parse the trailing tokens for --file and --hash.
    args = tokens[script_idx + 1 :]
    file_path = None
    hash_val = None
    i = 0
    while i < len(args):
        if args[i] == "--file" and i + 1 < len(args):
            file_path = args[i + 1]
            i += 2
        elif args[i] == "--hash" and i + 1 < len(args):
            hash_val = args[i + 1]
            i += 2
        else:
            i += 1
    if file_path is None or hash_val is None:
        return None
    return {"file": file_path, "hash": hash_val}


def _compute_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _handle_register_invocation(command: str, session_id: str):
    """Process a register_read.py invocation.

    Returns:
        True  -- registration succeeded; caller should ALLOW
        False -- registration failed; this function already emitted DENY
        None  -- command is not a register invocation
    """
    parsed = _parse_register_invocation(command)
    if parsed is None:
        return None

    fpath = Path(parsed["file"])
    claimed_hash = parsed["hash"].lower().strip()

    if not fpath.is_absolute():
        _emit_register_deny(
            command,
            "register_read needs an absolute --file path "
            "(got " + repr(parsed["file"]) + ").",
        )
        return False
    if not fpath.is_file():
        _emit_register_deny(
            command,
            "register_read: file does not exist on disk: " + str(fpath),
        )
        return False
    if not (len(claimed_hash) == 64
            and all(c in "0123456789abcdef" for c in claimed_hash)):
        _emit_register_deny(
            command,
            "register_read: --hash must be 64 lowercase hex chars (SHA-256). "
            "Got: " + repr(parsed["hash"]),
        )
        return False

    actual_hash = _compute_sha256(fpath)
    if actual_hash != claimed_hash:
        _emit_register_deny(
            command,
            "register_read: hash mismatch.\n"
            "  --hash:  " + claimed_hash + "\n"
            "  on-disk: " + actual_hash + "\n"
            "Either you have not actually read the file, or it changed since "
            "you computed the hash. Re-Read with fresh content and retry.",
        )
        return False

    # All checks pass: register the file in session state.
    state_lib.add_read(session_id, str(fpath))
    return True


def _emit_register_deny(command: str, reason: str) -> None:
    """Deny output specific to register-flow failures (different template
    from the bypass-pattern deny so the agent sees the actual diagnostic)."""
    msg = (
        "cc-enslaver · register_read rejected\n\n"
        "Command: " + command + "\n\n"
        + reason + "\n"
    )
    payload = {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": msg,
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

        # Read-cache escape hatch: register-as-read invocation.
        # Process this BEFORE bypass-pattern checks so a register command
        # cannot false-match unrelated regexes.
        session_id = payload.get("session_id") or "default"
        reg_handled = _handle_register_invocation(command, session_id)
        if reg_handled is True:
            return 0  # ALLOW -- registration succeeded; stub script will run
        if reg_handled is False:
            return 0  # DENY emitted; do not fall through to bypass checks
        # reg_handled is None: not a register invocation; continue.

        # Static regex patterns next.
        for pat in STATIC_PATTERNS:
            if pat["regex"].search(command):
                _emit_deny(command, pat["name"], pat["rule"], pat["explanation"])
                return 0

        # Compound: git push --force without --force-with-lease.
        fp = _detect_force_push(command)
        if fp:
            _emit_deny(command, fp["name"], fp["rule"], fp["explanation"])
            return 0

        # 圣旨 (user-defined hard edicts, v0.12). Run after the built-in
        # static + compound checks so a project edict can never accidentally
        # whitelist `--no-verify` & co. (it would have to write a pattern
        # that NOT-matches such a command, which is fine — but the order
        # makes "built-in disciplines always run first" the design contract).
        loaded_edicts = edicts_lib.load()
        if loaded_edicts:
            hit = edicts_lib.find_bash_violation(loaded_edicts, command)
            if hit is not None:
                _emit_raw_deny(edicts_lib.deny_reason(
                    hit, kind="Bash", tool_or_cmd=command,
                ))
                return 0

        # No bypass detected; allow by exiting silently.
    except Exception:
        sys.stderr.write("[cc-enslaver] bash_guard exception:\n")
        sys.stderr.write(traceback.format_exc())
    return 0


if __name__ == "__main__":
    sys.exit(main())
