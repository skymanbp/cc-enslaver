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
# Why not record per-file edit counts: rolling-patch detection (rule 09)
# could use that, but at v0.11 we tolerate the rolling-patch detection
# being soft (rule 09 doc-level discipline + Stop-hook layer (f) on the
# "missing root-cause/impact/solution markers" axis is enough). If we
# ever want PreToolUse-level rolling-patch DENY, we'll extend this with
# `edits_per_file: {path: count}` then.
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
