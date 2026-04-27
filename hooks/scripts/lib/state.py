"""Per-session state for anti-laziness read-before-edit guard.

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
    2. ${CLAUDE_PROJECT_DIR}/.claude/local/anti-laziness/sessions/
    3. ~/.claude/local/anti-laziness/sessions/
"""

from __future__ import annotations

import json
import os
from pathlib import Path

_PLUGIN_NAME = "anti-laziness"


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
