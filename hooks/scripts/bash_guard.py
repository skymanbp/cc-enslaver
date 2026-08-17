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
import sys
import traceback
from pathlib import Path

# Import the same state library read_guard uses, so registrations land in
# the same state files. `lib/` is alongside this script.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib import state as state_lib  # noqa: E402
# E402 is suppressed on every lib import below because they must follow
# the sys.path bootstrap above -- that is the stated reason, not laziness.
from lib import edicts as edicts_lib  # noqa: E402
# because the sys.path bootstrap above must run before this import
from lib import shellcmd  # noqa: E402


# --------------------------------------------------------------------------- #
# Static bypass patterns.
#
# Each entry is a regex against the full command string. The `name` is
# echoed in the deny reason so the agent knows exactly which pattern
# was matched. The `explanation` tells the agent how to recover.
# --------------------------------------------------------------------------- #
# v0.26.0 audit — these six moved from raw-text regex to ARGV predicates.
#
# Force-push detection was given a real command model in v0.26 while its
# six siblings kept scanning the whole command string, and the split
# produced exactly the errors a text heuristic produces in both
# directions: `chmod -v 777 f` and `git -C . rebase --skip` were MISSED
# (an unanticipated option sat where the regex expected the operand), the
# recursive-delete forms using the `--` terminator or quoting were missed,
# quoted flags were missed, and `echo git commit --no-verify` — which
# executes nothing — was wrongly DENIED.
#
# Each entry now carries `match(argv) -> bool`, evaluated per shell
# segment, so quoting, option order, global options and `--` are handled
# by the tokenizer instead of being re-guessed per pattern.

# Commands whose arguments are printed, not executed. Their own segment is
# skipped; a nested substitution inside them is still its own segment and
# is still checked, so an echoed force-push substitution remains a deny.
_INERT_COMMANDS = {"echo", "printf", "true", "false", ":"}


def _has_flag(argv: list[str], flag: str) -> bool:
    """True when `flag` appears as its own argv token (or `flag=value`)."""
    return any(a == flag or a.startswith(flag + "=") for a in argv[1:])


def _is_chmod_777(argv: list[str]) -> bool:
    if shellcmd.command_name(argv) not in ("chmod", "chmod.exe"):
        return False
    for tok in argv[1:]:
        if tok == "--":
            continue
        if tok.startswith("-"):
            continue          # -R, -v, -c, --recursive, … are options
        # The mode operand. `777`, `0777` and `7777` all grant world-write;
        # the old regex anticipated only the first two.
        if tok.isdigit() and tok[-3:] == "777":
            return True
        return False          # first operand is the mode; stop after it
    return False


def _is_git_rebase_skip(argv: list[str]) -> bool:
    sub, rest = shellcmd.git_subcommand(argv)
    return sub == "rebase" and "--skip" in rest


# essential (detector subject matter, not a path this script depends on):
# the home spellings below are what this check must RECOGNISE, so they are
# assembled by concatenation — the same technique read_guard uses on its
# own literals — to keep rule 11 from flagging its sibling guard.
_HOME_VAR = "$" + "HOME"
_TILDE = "~"
# Deleting anything AT OR UNDER these is catastrophic.
_SYSTEM_ROOTS = (
    "/bin", "/boot", "/etc", "/home", "/lib", "/opt", "/root",
    "/sbin", "/sys", "/usr", "/var",
)
# `/tmp` is deliberately different: wiping /tmp itself is catastrophic,
# but `rm -rf /tmp/my-build` is an ordinary scratch cleanup. The regex
# this replaced encoded the same carve-out (`tmp/?\s*$`), and dropping it
# would have turned a documented allow into a deny.
_TMP_ROOT = "/tmp"


def _is_dangerous_rm_target(op: str) -> bool:
    stripped = op.rstrip("/")
    if stripped == "":            # `/` or `//`
        return True
    if stripped == _TMP_ROOT:
        return True
    for root in _SYSTEM_ROOTS:
        if stripped == root or stripped.startswith(root + "/"):
            return True
    if stripped == _HOME_VAR or stripped.startswith(_HOME_VAR + "/"):
        return True
    return stripped == _TILDE or stripped.startswith(_TILDE + "/")


def _is_catastrophic_rm(argv: list[str]) -> bool:
    if shellcmd.command_name(argv) not in ("rm", "rm.exe"):
        return False
    recursive = force = False
    operands: list[str] = []
    seen_terminator = False
    for tok in argv[1:]:
        if tok == "--" and not seen_terminator:
            seen_terminator = True
            continue
        if not seen_terminator and tok.startswith("--"):
            if tok == "--recursive":
                recursive = True
            elif tok == "--force":
                force = True
            continue
        if not seen_terminator and tok.startswith("-") and len(tok) > 1:
            recursive = recursive or ("r" in tok[1:] or "R" in tok[1:])
            force = force or ("f" in tok[1:])
            continue
        operands.append(tok)
    if not (recursive and force):
        return False
    return any(_is_dangerous_rm_target(op) for op in operands)


STATIC_PATTERNS = [
    {
        "name": "--no-verify (skipping commit hooks)",
        "match": lambda argv: _has_flag(argv, "--no-verify"),
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
        "match": lambda argv: _has_flag(argv, "--no-gpg-sign"),
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
        "match": _is_chmod_777,
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
        "match": _is_git_rebase_skip,
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
        "match": lambda argv: _has_flag(argv, "--break-system-packages"),
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
        "match": _is_catastrophic_rm,
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


# v0.30 — `_CMD_SEPARATOR` and `_SHORT_FLAG_CLUSTER` used to live here.
# They were the v0.25 text heuristic's separator list and short-option
# matcher; v0.26 replaced that heuristic with `lib/shellcmd`'s parse model
# and left both constants behind, referenced by nothing. Keeping a dead
# regex next to a live detector is worse than useless: the next reader has
# to prove it is unreachable before they can trust the one below it.


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

    v0.26.0 — the text heuristic is replaced by an actual parse
    (`lib/shellcmd`). Scanning a *slice of text* for co-occurring words
    was wrong in both directions at once:

      * False DENY on text that is not an invocation — an `echo` of a
        force-push string, or `git config alias.deploy "push --mirror"`,
        where the subcommand is `config`, not `push`. (The first of these
        blocked a legitimate probe during this very audit.)
      * False ALLOW on `git push origin +main` and
        `git push origin +:refs/heads/main`: a force refspec need not
        contain a colon, and a deletion refspec has an empty source side,
        so the old colon-requiring pattern saw neither.
      * False ALLOW whenever git's global options ran past the arbitrary
        120-character window between `git` and `push`.

    Now: split into segments, take the ones whose argv[0] IS git, resolve
    the real subcommand past any global options, and inspect the argv
    that follows it.
    """
    hit = False
    for argv in shellcmd.segments(cmd):
        if shellcmd.command_name(argv) not in ("git", "git.exe"):
            continue
        subcommand, args = shellcmd.git_subcommand(argv)
        if subcommand != "push":
            continue
        for tok in args:
            # `--force-with-lease` is the SAFE variant and is a distinct
            # token, so exact comparison lets it through without the
            # substring gymnastics the text version needed.
            if tok == "--force" or tok.startswith("--force="):
                hit = True
            elif tok == "--mirror":
                # Force-updates every mirrored ref.
                hit = True
            elif tok.startswith("+") and len(tok) > 1:
                # git's own spelling of "force this ref", with or without
                # a colon: `+main`, `+main:main`, `+:refs/heads/main`.
                hit = True
            elif (len(tok) > 1 and tok[0] == "-" and tok[1] != "-"
                    and "f" in tok[1:] and tok[1:].isalpha()):
                # Stacked short options: `-f`, `-fu`, `-uf`.
                hit = True
            if hit:
                break
        if hit:
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


# v0.30 — `_split_command` used to live here. It was the last remnant of
# this module's own tokeniser: v0.26 reduced its body to a one-line
# delegation to `shellcmd.tokenize`, and nothing has called it since. Its
# docstring narrated the v0.25 / v0.25.1 tokenising bugs, which is why it
# looked load-bearing; that history now lives where the tokeniser does
# (`lib/shellcmd.tokenize`) and in the CHANGELOG, not in a dead wrapper.


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

    v0.26.0 — command position is resolved by parsing rather than by
    walking backwards over dashes. The old heuristic treated the operand
    of ANY dash-flag as a potential script, so `python -c
    register_read.py …` — where `-c`'s operand is inline CODE and the
    script never runs — registered the file as read. It also rejected
    `python -X utf8 register_read.py …`, a spelling its own docstring
    claimed to support, and every versioned interpreter (`python3.13`).
    """
    # v0.26.0 audit — the registration must be the WHOLE command.
    #
    # Scanning every segment ignored shell control flow, so
    # `false && register_read.py --file F --hash H` granted read credit
    # for a command the shell never runs. The hook fires BEFORE execution
    # and cannot know which branch of a compound command will be taken,
    # and this hatch's entire value is that its credit is trustworthy —
    # so anything other than a single, unconditional invocation is not a
    # registration. (`&&`, `||`, `|`, `;`, backgrounding and substitution
    # all produce extra segments.) The command is not denied; it simply
    # earns no credit, and the real script still runs and reports.
    parsed = shellcmd.segments(command)
    non_empty = [a for a in parsed if a]
    if len(non_empty) != 1:
        return None
    for argv in non_empty:
        # The script must be what this segment actually executes: either
        # argv[0] itself, or the script operand of a Python interpreter.
        args: list[str] | None = None
        if os.path.basename(argv[0].replace("\\", "/")) == _REGISTER_SCRIPT_NAME:
            args = argv[1:]
        else:
            script = shellcmd.python_script_arg(argv)
            if (script is not None
                    and os.path.basename(script.replace("\\", "/"))
                    == _REGISTER_SCRIPT_NAME):
                args = argv[argv.index(script) + 1:]
        if args is None:
            continue
        # Parse the trailing tokens for --file and --hash, in both the
        # space-separated and the `=`-joined spelling.
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
                    values[name] = tok[len(flag) + 1:]
                    i += 1
                    matched = True
                    break
            if not matched:
                i += 1
        if "file" in values and "hash" in values:
            return {"file": values["file"], "hash": values["hash"]}
    return None


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
    #
    # v0.26.0 — the registration must actually PERSIST. When the save was
    # abandoned (a concurrent reader holding the state file through every
    # retry) this returned True regardless, the stub script printed
    # `register_read: ok`, and the agent proceeded believing rule 04 was
    # satisfied — only to be DENIED on the next Edit with no explanation
    # that the registration had silently evaporated. Deny loudly instead:
    # a failed registration the agent knows about is recoverable, a
    # successful-looking one that did nothing is not.
    if not state_lib.add_read(session_id, str(fpath)):
        _emit_register_deny(
            command,
            "register_read: the registration could not be persisted to "
            "session state (another process is holding the state file).\n"
            "Nothing was recorded — retry in a moment, or simply Read the "
            "file again, which is the primary path this hatch exists to "
            "work around.",
        )
        return False
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

        # Static patterns first, evaluated per shell segment against argv
        # (v0.26.0) rather than against the raw command string.
        for argv in shellcmd.segments(command):
            if not argv:
                continue
            if shellcmd.command_name(argv) in _INERT_COMMANDS:
                # `echo git commit --no-verify` executes nothing. A nested
                # substitution is a SEPARATE segment and is still checked.
                continue
            for pat in STATIC_PATTERNS:
                if pat["match"](argv):
                    _emit_deny(command, pat["name"], pat["rule"],
                               pat["explanation"])
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
