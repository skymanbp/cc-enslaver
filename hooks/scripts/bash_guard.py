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
import os
import re
import shlex
import sys
import traceback
from pathlib import Path

# Import the same state library read_guard uses, so registrations land in
# the same state files. `lib/` is alongside this script.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib import state as state_lib  # noqa: E402
# noqa: E402 on both lib imports because they must follow the sys.path bootstrap
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
    # ----------------------------------------------------------------- #
    # v0.14 — three additional bypass patterns.
    #
    # Selected from the v0.12 / v0.13 CHANGELOG roadmap. Each one has a
    # narrow regex so false-positive rate stays low; `git reset --hard`
    # was deliberately NOT added because reliably detecting "with
    # uncommitted changes" requires `git status` invocation which is too
    # invasive for a synchronous hook.
    # ----------------------------------------------------------------- #
    {
        "name": "git rebase --skip (silently abandoning a conflict)",
        # Matches the --skip subcommand of git rebase, anywhere in the
        # command after `git rebase`. Word boundary on the right.
        "regex": re.compile(r"\bgit\s+rebase\b[^\n]*\s--skip\b"),
        "rule": "03",
        "explanation": (
            "`git rebase --skip` abandons the conflicting commit silently "
            "rather than resolving the conflict. Per rule 03 "
            "(rules/03-root-cause.md), conflicts arise from real semantic "
            "divergence — skipping them loses code or hides design issues "
            "that surface for a reason. Either: (1) resolve the conflict "
            "(`git status` to see what's in conflict, edit, `git add`, "
            "`git rebase --continue`), (2) abort and pick a different "
            "rebase strategy (`git rebase --abort`), or (3) if you are "
            "absolutely sure the skipped commit is unnecessary, ask the "
            "user to run --skip manually."
        ),
    },
    {
        "name": "pip install --break-system-packages (bypassing PEP 668)",
        "regex": re.compile(r"(?:^|\s)--break-system-packages\b"),
        "rule": "03",
        "explanation": (
            "`--break-system-packages` bypasses the PEP 668 protection "
            "added in Python 3.11+ to prevent pip from modifying the "
            "system Python and breaking package-manager-installed "
            "software. Per rule 03 (rules/03-root-cause.md), the fix "
            "is to install into a venv (`python -m venv .venv && source "
            ".venv/bin/activate && pip install …`), pipx for tools, or "
            "the system package manager (`apt install python3-X`). "
            "Breaking the system Python to make one install succeed is "
            "the canonical symptom-over-root-cause anti-pattern."
        ),
    },
    {
        # essential: the home-variable spellings below are this detector's
        # SUBJECT MATTER, not a path this script itself depends on — rule
        # 11's detector would otherwise flag its own sibling guard. (See
        # read_guard's `_PATH_DEP_PATTERNS`, which splits its home-var
        # literal across concatenation for the same self-scan reason.)
        "name": "rm -rf on root / $HOME / ~",
        # Catches the catastrophic forms:
        #   rm -rf /
        #   rm -rf /<system-dir>
        # essential (detector subject matter, not a real path dependency):
        #   rm -rf $HOME[/...]
        #   rm -rf ~  / rm -rf ~/...
        # while still allowing rm -rf /tmp/foo, rm -rf ./node_modules,
        # rm -rf relative paths.
        "regex": re.compile(
            r"\brm\s+(?:-[rRf]+\s+)+"
            r"(?:/(?:\s|$|bin\b|boot\b|etc\b|home\b|lib\b|opt\b|root\b|sbin\b|sys\b|tmp/?\s*$|usr\b|var\b)"
            # essential: home-var spelling is the pattern being detected.
            r"|\$HOME\b|~/?(?:\s|$))"
        ),
        "rule": "03",
        "explanation": (
            # essential: names the spellings in the user-facing deny text.
            "Recursive force-deletion against system root, $HOME, or ~ "
            "is catastrophic and almost never the right tool. Per rule "
            "03 (rules/03-root-cause.md), if you need to clean a build "
            "artifact use the project's clean target (`make clean`, "
            "`npm run clean`, etc.) or remove a more specific path; if "
            "you need to reset the workspace, use git (`git clean -fdx` "
            "scoped to the worktree, or `git reset --hard HEAD` after "
            "stashing). If the user truly asked for a destructive root-"
            "level rm, surface the deny and let them run the command "
            "manually — do not act on their behalf for irrecoverable "
            "operations."
        ),
    },
]


# Shell command separators. A compound command is split on these so a
# flag is only ever attributed to the sub-command that owns it (v0.25).
_CMD_SEPARATOR = re.compile(r"&&|\|\||;|\n|\|")

# A single-dash short-option cluster, e.g. `-f`, `-fu`, `-uf`, `-fq`.
# `git push -fu origin main` IS a force push (git accepts stacked short
# options), so matching only the exact token `-f` under-blocks.
_SHORT_FLAG_CLUSTER = re.compile(r"(?:^|\s)-([A-Za-z]+)(?=\s|$)")


def _detect_force_push(cmd: str) -> dict | None:
    """Detect `git push --force` (or `-f` / `-fu` / …) without `--force-with-lease`.

    `--force-with-lease` is the safe variant: it refuses to overwrite if the
    remote moved underneath you. We allow it; we only block the unconditional
    `--force` / short-flag form.

    v0.25 — two defects fixed, both stemming from scanning the WHOLE command
    string instead of the `git push` sub-command:

      * False DENY: `rm -f build.log && git push origin main` matched the
        bare `-f` owned by `rm` and was denied as a force push. Any chained
        `-f` (`make -f Makefile`, `docker build -f Dockerfile .`) did the
        same.
      * False ALLOW: `git push -fu origin main` — a genuine force push with
        `--set-upstream` — never matched, because the old token regex
        required `-f` to be delimited by whitespace on both sides. The exact
        operation this guard exists to stop rode through.

    Both are fixed by splitting the command on shell separators, keeping
    only the segments that actually invoke `git push`, and looking for `f`
    inside each single-dash option cluster within those segments.
    """
    segments = [
        seg for seg in _CMD_SEPARATOR.split(cmd)
        if re.search(r"\bgit\s+push\b", seg)
    ]
    if not segments:
        return None
    hit = False
    for seg in segments:
        # Strip --force-with-lease (and its optional =refspec value) before
        # checking for --force. Otherwise the substring `--force` inside
        # `--force-with-lease` would falsely match below.
        sanitised = re.sub(r"--force-with-lease(?:=\S+)?", "", seg)
        if re.search(r"(?:\s|^)--force(?:\s|$)", sanitised):
            hit = True
            break
        if any("f" in cluster
               for cluster in _SHORT_FLAG_CLUSTER.findall(sanitised)):
            hit = True
            break
    if hit:
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


def _split_command(command: str) -> list[str] | None:
    """Tokenise a shell command, preserving Windows path separators.

    v0.25 — `shlex.split(command, posix=True)` treats a backslash as an
    escape character, so an UNQUOTED Windows path came back mangled:

        C:\\Users\\me\\note.txt   ->   C:Usersmenote.txt

    `_handle_register_invocation` then denied with "file does not exist on
    disk", i.e. the documented recovery path for a false rule-04 DENY was
    itself broken on this plugin's own primary platform. It survived 21
    releases because every existing test quotes the path (`--file "%s"`),
    and quoting happens to survive posix splitting.

    On Windows we therefore split in non-posix mode (backslash is a plain
    character there) and strip the quotes shlex leaves attached; on POSIX
    the original semantics are kept, where a backslash escape is real.
    """
    posix = os.name != "nt"
    try:
        tokens = shlex.split(command, posix=posix)
    except ValueError:
        return None
    if posix:
        return tokens
    out: list[str] = []
    for tok in tokens:
        if len(tok) >= 2 and tok[0] == tok[-1] and tok[0] in ("'", '"'):
            tok = tok[1:-1]
        out.append(tok)
    return out


def _parse_register_invocation(command: str) -> dict | None:
    """If `command` is a register_read.py invocation, return parsed args.

    Returns a dict {"file": str, "hash": str} on success, or None if the
    command is not a register invocation. Tolerates malformed register
    invocations by returning None (the regular bypass-pattern checks then
    apply, and the script call itself will fail at argparse time).

    v0.25 — the `--flag=value` spelling is now understood. register_read.py
    parses its own argv with argparse, which accepts both `--file X` and
    `--file=X`; this hand-parser only knew the space-separated form, so on
    the `=` form the hook silently classified the command as "not a
    registration", never called add_read, and let the stub script print
    "register_read: ok" — a success message for a registration that never
    happened, leaving the next Edit denied with no clue why.
    """
    tokens = _split_command(command)
    if tokens is None:
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
    # Parse the trailing tokens for --file and --hash, in both the
    # space-separated and the `=`-joined spelling.
    args = tokens[script_idx + 1 :]
    values: dict[str, str] = {}
    i = 0
    while i < len(args):
        tok = args[i]
        matched = False
        for name in ("file", "hash"):
            flag = f"--{name}"
            if tok == flag and i + 1 < len(args):
                values[name] = args[i + 1]
                i += 2
                matched = True
                break
            if tok.startswith(flag + "="):
                values[name] = tok[len(flag) + 1 :]
                i += 1
                matched = True
                break
        if not matched:
            i += 1
    if "file" not in values or "hash" not in values:
        return None
    return {"file": values["file"], "hash": values["hash"]}


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

        # ------------------------------------------------------------- #
        # Check order (v0.25 — CHANGED, and the change is the fix).
        #
        # Until v0.24 the register_read escape hatch was processed FIRST
        # and returned 0 on success, on the assumption that the command
        # simply *was* a registration. But the checks below scan the whole
        # command string, and a command can CONTAIN a registration while
        # doing other things:
        #
        #     python …/register_read.py --file F --hash H && git push --force
        #
        # was ALLOWED — the entire bypass catalog, the force-push detector
        # and every 圣旨 were skipped for the rest of the compound command.
        # Registration and bypass-scanning are orthogonal; both must run.
        #
        # So: run every DENY check first, and register only once the whole
        # command is known to be clean. This also means a command that is
        # going to be denied never mutates session state — the same
        # ordering principle as v0.24's read_guard fix, where a DENIED
        # Write must not grant read-before-edit authorization.
        #
        # A bare, legitimate registration is unaffected: none of the
        # patterns below match a `register_read.py --file … --hash …`
        # command (verified by the regression suite's clean-registration
        # case), so it still falls through to the registration step.
        # ------------------------------------------------------------- #
        session_id = payload.get("session_id") or "default"

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

        # Read-cache escape hatch: register-as-read invocation. Reached
        # only when the command cleared every deny check above.
        reg_handled = _handle_register_invocation(command, session_id)
        if reg_handled is False:
            return 0  # DENY emitted (bad hash / missing file / bad args)
        # True  -> registration succeeded; ALLOW (stub script will run).
        # None  -> not a register invocation; ALLOW (nothing matched).

        # No bypass detected; allow by exiting silently.
    except Exception:
        sys.stderr.write("[cc-enslaver] bash_guard exception:\n")
        sys.stderr.write(traceback.format_exc())
    return 0


if __name__ == "__main__":
    sys.exit(main())
