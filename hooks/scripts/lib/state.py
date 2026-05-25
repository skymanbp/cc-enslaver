"""Per-session state for cc-enslaver read-before-edit guard.

Each Claude Code session gets one JSON file recording every file the
agent has Read or Written. The PreToolUse guard consults this file to
decide whether an Edit/Write against an existing file may proceed.

Why per-session-id and not per-cwd: the same project may have multiple
concurrent sessions (e.g., user opens two Claude Code instances); each
must track its own context independently.

Why JSON-on-disk and not in-memory: hooks run as fresh subprocesses on
every event. There is no in-memory continuity between PostToolUse(Read)
firing and PreToolUse(Edit) firing five seconds later, so state must
land on disk.

Storage location resolution order:
    1. ${CLAUDE_PLUGIN_DATA}/sessions/   -- recommended for plugin hooks
    2. ${CLAUDE_PROJECT_DIR}/.claude/local/cc-enslaver/sessions/
    3. ~/.claude/local/cc-enslaver/sessions/
"""

from __future__ import annotations

import json
import os
from pathlib import Path

_PLUGIN_NAME = "cc-enslaver"


def state_dir() -> Path:
    """Resolve the directory holding per-session state files.

    Order: CLAUDE_PLUGIN_DATA → CLAUDE_PROJECT_DIR/.claude/local/<plugin>
    → ~/.claude/local/<plugin>. The directory is created on first call.
    """
    base_env = os.environ.get("CLAUDE_PLUGIN_DATA")
    if base_env:
        base = Path(base_env)
    else:
        proj = os.environ.get("CLAUDE_PROJECT_DIR")
        if proj:
            base = Path(proj) / ".claude" / "local" / _PLUGIN_NAME
        else:
            base = Path.home() / ".claude" / "local" / _PLUGIN_NAME

    sessions = base / "sessions"
    sessions.mkdir(parents=True, exist_ok=True)
    return sessions


def normalize_path(p: str) -> str:
    """Canonicalise a filesystem path for set-membership comparison.

    Uses realpath (resolve symlinks) + normcase (lowercase on Windows).
    Two paths to the same underlying file should compare equal even if
    one came in as forward slashes and the other as backslashes, or one
    as a relative path and the other absolute.
    """
    try:
        resolved = os.path.realpath(p)
    except OSError:
        # realpath can fail on weird Windows paths; fall back to abspath.
        resolved = os.path.abspath(p)
    return os.path.normcase(resolved)


def _safe_session_filename(session_id: str) -> str:
    # Session IDs are typically UUIDs but be defensive: never let an
    # arbitrary string create a path traversal or hidden file.
    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in session_id)
    return safe[:64] + ".json"


def _state_file(session_id: str) -> Path:
    return state_dir() / _safe_session_filename(session_id)


def load(session_id: str) -> dict:
    """Load the session's state, or return a fresh empty record."""
    f = _state_file(session_id)
    if not f.exists():
        return {"session_id": session_id, "read_files": []}
    try:
        return json.loads(f.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        # A corrupt state file should not block the agent. Reset it.
        return {"session_id": session_id, "read_files": []}


def save(state: dict) -> None:
    f = _state_file(state["session_id"])
    f.write_text(
        json.dumps(state, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def add_read(session_id: str, file_path: str) -> None:
    """Mark a file as Read (or Written) in this session."""
    state = load(session_id)
    norm = normalize_path(file_path)
    if norm not in state["read_files"]:
        state["read_files"].append(norm)
        save(state)


def has_read(session_id: str, file_path: str) -> bool:
    """True if this session has previously Read or Written this file."""
    state = load(session_id)
    return normalize_path(file_path) in state.get("read_files", [])


# --------------------------------------------------------------------------- #
# Stop-hook one-shot guard (v0.6.0).
#
# rule 06 enforcement at Stop time: when the agent claims "done" without
# evidence, we block the Stop and force one more turn. To avoid an infinite
# loop, we record that we just blocked, and refuse to block twice in a row.
# --------------------------------------------------------------------------- #
def record_stop_block(session_id: str, turn_count: int | None) -> None:
    """Mark that this session's Stop was blocked at the given turn_count.

    The next Stop check consults `was_just_blocked` to skip re-blocking.
    """
    state = load(session_id)
    state["last_blocked_turn"] = turn_count
    save(state)


def was_just_blocked(session_id: str, turn_count: int | None) -> bool:
    """True if the previous Stop in this session was already blocked.

    Used by stop_guard to avoid infinite "block → continue → block again"
    loops. Specifically returns True iff `turn_count` is one more than
    the recorded `last_blocked_turn` (i.e., the agent has had exactly one
    chance to recover after the prior block).

    If `turn_count` is None (Claude Code didn't supply it), we conservatively
    return True whenever any prior block was recorded — preferring false
    negatives (no block) to false positives (infinite loop).
    """
    state = load(session_id)
    last = state.get("last_blocked_turn")
    if last is None:
        return False
    if turn_count is None:
        return True
    # Allow a generous window: if the agent's turn_count is anywhere in
    # [last + 1, last + 3], treat the most recent block as still "fresh"
    # and don't re-block. After 3 turns of grace, we're free to block again.
    return last < turn_count <= last + 3


# --------------------------------------------------------------------------- #
# Edit-turn recording (v0.11.0 — for rule 08 + rule 09 Stop-hook layers).
#
# When the agent successfully Edits or Writes a file, we stamp the current
# turn_count into `last_edit_turn`. The Stop hook layers (e) and (f) only
# fire when `last_edit_turn == current turn_count`: this scopes the
# rule-08/09 closing checks to turns that actually modified files,
# avoiding false positives on read-only / analysis turns.
#
# v0.13 — adds the rolling-patch counter (`edits_per_file`) that v0.11
# foreshadowed. PreToolUse(Edit|Write) classifies the incoming edit as
# "small" (≤ 10 lines AND < 200 chars on both sides) or "systematic"
# (≥ 50 lines OR ≥ 1500 chars on new_string/content) and either
# increments the per-file counter (small) or resets it to zero
# (systematic). When the predicted count would reach 4, read_guard DENYs
# without incrementing — making rolling patches a physically-blocked
# rule-09 violation rather than a Stop-layer-only nudge.
# --------------------------------------------------------------------------- #
def record_edit_turn(session_id: str, turn_count: int | None) -> None:
    """Stamp `last_edit_turn = turn_count` on the session state.

    Called from read_guard immediately after a successful Edit or Write
    (Pre-tool-use; "successful" here means the guard did not DENY — the
    tool may still fail downstream, but that's harmless: the rule-08/09
    closing checks only matter when the agent claims completion in the
    same turn as a real edit, and a failed Edit followed by a done-claim
    is itself a rule-06 violation caught by layer (a)).
    """
    if turn_count is None:
        return
    state = load(session_id)
    state["last_edit_turn"] = turn_count
    save(state)


def did_edit_this_turn(session_id: str, turn_count: int | None) -> bool:
    """True if the session's last Edit/Write was stamped at exactly
    `turn_count`.

    Used by stop_guard layer (e)+(f) to scope the rule-08/09 closing
    checks to "turns that actually modified files". A read-only / pure-
    analysis turn never trips these layers, regardless of how the agent
    phrases the closing message.

    If `turn_count` is None (Claude Code didn't supply it), we
    conservatively return False — better to occasionally miss a layer
    (e)/(f) trigger than to false-positive on a non-editing turn.
    """
    if turn_count is None:
        return False
    state = load(session_id)
    return state.get("last_edit_turn") == turn_count


# --------------------------------------------------------------------------- #
# Rolling-patch counter (v0.13.0 — rule 09 hard interception).
#
# Counter semantics:
#   - get_edit_count(sid, path) → current count of small edits applied
#     to `path` in this session (0 if never edited or after reset).
#   - record_small_edit(sid, path) → increment by 1, return new count.
#     Called only when the guard has decided to ALLOW a small edit.
#   - reset_edit_count(sid, path) → clear the counter, called on a
#     systematic rewrite (≥ 50 lines / ≥ 1500 chars on new_string).
#
# The DENY decision lives in read_guard (which has all the classification
# logic); this module just stores the count. Threshold = 4 means the 4th
# small edit attempt is denied — the recorded count stays at 3 until a
# systematic rewrite resets it, so subsequent small-edit attempts also
# DENY (the agent must do a systematic change to recover).
# --------------------------------------------------------------------------- #
def get_edit_count(session_id: str, file_path: str) -> int:
    """Return the small-edit count for `file_path` in this session."""
    state = load(session_id)
    counters = state.get("edits_per_file") or {}
    return int(counters.get(normalize_path(file_path), 0))


def record_small_edit(session_id: str, file_path: str) -> int:
    """Increment the small-edit counter for `file_path`; return new count.

    Should only be called after the guard has decided to ALLOW the edit
    (i.e., when `get_edit_count(...) + 1 < ROLLING_PATCH_THRESHOLD`).
    """
    state = load(session_id)
    counters = state.setdefault("edits_per_file", {})
    norm = normalize_path(file_path)
    counters[norm] = int(counters.get(norm, 0)) + 1
    save(state)
    return counters[norm]


def reset_edit_count(session_id: str, file_path: str) -> None:
    """Clear the small-edit counter for `file_path` (systematic rewrite)."""
    state = load(session_id)
    counters = state.get("edits_per_file") or {}
    norm = normalize_path(file_path)
    if norm in counters:
        del counters[norm]
        state["edits_per_file"] = counters
        save(state)


# --------------------------------------------------------------------------- #
# File-state baseline (v0.16.0 — rule 01/06 honest-claim verification).
#
# Stop layer (g) catches the "claimed to edit X but didn't actually edit X"
# pattern. To do so it needs a baseline of what each file looked like the
# first time the agent encountered it this session. The baseline is
# captured lazily by read_guard on the first Read / Edit / Write of each
# file — earlier interactions don't have a meaningful baseline.
#
# Schema:
#     state["baseline_mtimes"] = {
#         normalized_path: <float mtime>      file existed at baseline time
#                       | None,               file did NOT exist at baseline time
#     }
#
# A path being absent from the dict means we never saw it — Stop layer
# (g) treats that as "no claim verification possible" (skip, no block).
#
# We store mtime (not hash) for cheapness; the verifier compares
# current mtime against the recorded one and treats any difference as
# evidence of modification. The signal is one-directional: if the file
# actually changed externally between read and Stop, we may treat a
# false claim as true (false-negative on lying). This is the chosen
# trade-off — false-positive on honest claims is worse.
# --------------------------------------------------------------------------- #
def record_baseline(session_id: str, file_path: str) -> None:
    """Record the current on-disk state of `file_path` (lazy, idempotent).

    First time we encounter a file, capture either its current mtime or
    None (if missing on disk). Subsequent calls are no-ops — the
    baseline is whatever the first encounter saw, regardless of later
    modifications.
    """
    state = load(session_id)
    baselines = state.setdefault("baseline_mtimes", {})
    norm = normalize_path(file_path)
    if norm in baselines:
        return  # already captured
    try:
        baselines[norm] = os.path.getmtime(file_path)
    except OSError:
        baselines[norm] = None
    save(state)


def get_baseline(session_id: str, file_path: str) -> tuple[bool, float | None]:
    """Return (have_baseline, baseline_mtime_or_None).

    have_baseline=False → we never captured a baseline for this file;
    caller should treat any claim about it as unverifiable.
    have_baseline=True + mtime=None → file did NOT exist at baseline time.
    have_baseline=True + mtime=float → file existed with that mtime.
    """
    state = load(session_id)
    baselines = state.get("baseline_mtimes") or {}
    norm = normalize_path(file_path)
    if norm not in baselines:
        return (False, None)
    return (True, baselines[norm])
