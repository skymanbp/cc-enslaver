"""Per-session state for cc-enforcer read-before-edit guard.

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
    2. ${CLAUDE_PROJECT_DIR}/.claude/local/cc-enforcer/sessions/
    3. ~/.claude/local/cc-enforcer/sessions/
"""

from __future__ import annotations

import contextlib
import json
import os
import sys
import time
from pathlib import Path

if os.name == "nt":
    import msvcrt
else:
    import fcntl

_PLUGIN_NAME = "cc-enforcer"

# v0.24 — os.replace retry budget (see save()). The reader-collision
# window is micro-to-milliseconds; 8 attempts with a growing backoff
# (5ms, 10ms, … ≈ 180ms worst case) closes it without ever stalling a
# hook noticeably.
_REPLACE_ATTEMPTS = 8
_REPLACE_BACKOFF_BASE = 0.005


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


# Every collection field an accessor or mutator dereferences by shape:
# `.append` on a list, `.setdefault(...)[k]` on a dict. A wrong-typed
# value in ANY of them raises inside the lock and loses the mutation, so
# they are normalised as a class rather than one at a time.
_STATE_COLLECTION_FIELDS = {
    "read_files": list,
    "edited_files": list,
    "sync_acked_groups": list,
    "last_blocked_groups": list,
    "blocked_layers": list,
    "edits_per_file": dict,
    "baseline_mtimes": dict,
}

# Fields compared or arithmetically combined with numbers. A bool is
# excluded deliberately: `True` is an int in Python but never a valid
# turn number, and silently treating it as 1 would corrupt turn maths.
_STATE_NUMERIC_FIELDS = (
    "last_blocked_turn", "last_edit_turn", "stop_counter",
)


def _normalized(state: object, session_id: str) -> dict:
    """Coerce a parsed state document into the shape accessors assume.

    v0.25.1 — syntactically valid JSON with the wrong SHAPE used to break
    two ways, both silent. A top-level `[]` made `has_read` raise
    `AttributeError: 'list' object has no attribute 'get'`, which
    read_guard's outer handler swallowed as failing-open — so an unread
    file became editable. A top-level `{}` made `add_read` raise
    `KeyError: 'read_files'`, so a successful Read was never recorded and
    the NEXT edit was falsely denied. Both are now repaired in one place,
    on the single path every accessor and mutator already funnels through.

    v0.26.0 — driven by a SCHEMA instead of repairing one field. The
    v0.25.1 version fixed exactly the key that had been observed to raise
    (`read_files`) and left every sibling exposed — the audit's root cause
    β, "hardening scoped to the instance, never the class". Its own
    docstring claimed a top-level `{}` was repaired, yet `add_read` on
    `{}` still raised `KeyError: 'session_id'` from `save()`, which
    read_guard swallows as failing-open, so the Read was never recorded
    and the NEXT edit was falsely denied as unread. `edited_files`,
    `sync_acked_groups`, `edits_per_file`, `baseline_mtimes` and
    `stop_counter` were all one wrong-typed value away from the same
    failure via `.append` / `.setdefault` / `int()`.
    """
    if not isinstance(state, dict):
        return {"session_id": session_id, "read_files": []}
    # `session_id` is dereferenced unguarded by save(), which uses it to
    # pick the destination FILE. The record was located by `session_id`,
    # so that argument is authoritative and is written back
    # unconditionally — not merely when the stored value is missing or
    # non-string. A record whose stored id disagreed with its own filename
    # (hand-edited, or copied between sessions) otherwise redirected every
    # subsequent write to a different file: the mutation appeared to
    # succeed while the next read of this session saw nothing.
    state["session_id"] = session_id
    for key, kind in _STATE_COLLECTION_FIELDS.items():
        if key in state and not isinstance(state[key], kind):
            state[key] = kind()
    for key in _STATE_NUMERIC_FIELDS:
        value = state.get(key)
        if key in state and (isinstance(value, bool)
                             or not isinstance(value, (int, float))):
            del state[key]
    if not isinstance(state.get("read_files"), list):
        state["read_files"] = []
    return state


def _quarantine_unparseable(f: Path, session_id: str) -> None:
    """Move an unparseable state file aside so the session can recover.

    Overwriting it would destroy the only evidence of what went wrong,
    and refusing to touch it would strand the session forever (every
    later mutation skipped, every Read unrecorded). Renaming does
    neither: the next call sees no file and starts clean.
    """
    dest = f.with_name(f.name + ".corrupt")
    try:
        if dest.exists():
            dest.unlink()
        f.replace(dest)
        moved = str(dest.name)
    except OSError as exc:
        # essential: quarantine is best-effort recovery. Failing to move
        # the file must not escalate into blocking the user's tool call,
        # so the error is reported and the caller still fails open.
        moved = f"<could not move aside: {exc}>"
    sys.stderr.write(
        f"[cc-enforcer] state for {session_id!r} is unparseable after a "
        f"retry; moved to {moved}. This session starts from an empty "
        f"record — earlier reads/baselines in it are gone.\n"
    )


def _load_for_mutation(session_id: str) -> dict | None:
    """Load for a locked read-modify-write cycle; None = do not mutate.

    v0.24: a transient OSError (e.g. an antivirus scanner briefly
    holding the file on Windows) is retried once. If the file exists
    but STILL cannot be read, this returns None and the mutator must
    skip its mutation entirely: proceeding with the empty fallback
    record would save it back over the real file — erasing every
    recorded read, edit, baseline and counter of the session. Losing
    one mutation is the strictly smaller failure (same failing-open
    direction as the lock). A genuinely corrupt file (JSONDecodeError)
    still resets to a fresh record immediately — that file's content is
    already gone, so the reset loses nothing extra.
    """
    f = _state_file(session_id)
    if not f.exists():
        return {"session_id": session_id, "read_files": []}
    for attempt in (0, 1):
        try:
            return _normalized(json.loads(f.read_text(encoding="utf-8")), session_id)
        except json.JSONDecodeError:
            # v0.26.0 audit — a decode error is NOT proof of permanent
            # corruption. A concurrent writer's torn file reads exactly
            # like this, and the pre-v0.26 branch returned a FRESH record
            # immediately, which the calling mutator then saved back over
            # the real file: total session amnesia (reads, baselines,
            # counters, acks), and SILENTLY — unlike the OSError path,
            # this branch printed nothing at all.
            #
            # Retry first; only a second failure is treated as real
            # corruption, and then the file is moved aside rather than
            # overwritten, so the session can start clean without
            # destroying the evidence.
            if attempt == 0:
                time.sleep(0.01)
                continue
            _quarantine_unparseable(f, session_id)
            return None
        except OSError:
            if attempt == 0:
                time.sleep(0.01)
    sys.stderr.write(
        f"[cc-enforcer] state for {session_id!r} unreadable after retry; "
        f"skipping this mutation (failing open)\n"
    )
    return None


def load(session_id: str) -> dict:
    """Load the session's state, or return a fresh empty record.

    Read-only counterpart of _load_for_mutation: an unreadable file
    degrades to an empty record, which is safe here because accessors
    never save it back.
    """
    state = _load_for_mutation(session_id)
    if state is None:
        return {"session_id": session_id, "read_files": []}
    return state


def save(state: dict) -> bool:
    """Persist the state atomically; True when it actually landed.

    v0.26.0 — the return value exists because "the mutation was lost" and
    "the mutation succeeded" were indistinguishable to callers. The
    register_read escape hatch was the sharp case: it recorded the file,
    the save was abandoned, and the user was told `register_read: ok`
    while the read had NOT been registered — the plugin telling exactly
    the kind of untruth it exists to prevent.

    Atomic replacement means a concurrent reader can never observe a
    half-written JSON file (which load() would silently "repair" into a
    fresh empty record — i.e. amnesia about every recorded read). The
    temp name embeds the pid so two unlocked writers (the failing-open
    path of `_session_lock`) cannot collide on the same temp file.

    Windows retry (v0.24): os.replace against a target a concurrent
    process holds open fails with PermissionError (sharing violation),
    because CPython's open() does not request FILE_SHARE_DELETE. In
    v0.23 the read paths were lock-free (has_read / was_just_blocked /
    get_edited_files / … called load() without the session lock), so
    the hooks' own readers collided with their own writers — measured
    300/300 lost saves under 8 tight-loop readers, and live session
    dirs carried orphan `<sid>.json.<pid>.tmp` files from exactly these
    failures (the v0.23 lock only serialized writer-vs-writer). v0.24
    removes the self-collision at the root by routing read accessors
    through the same lock (_load_shared); this retry remains as
    defense-in-depth against non-cooperating EXTERNAL readers
    (antivirus / indexers / backup agents), whose open windows are
    micro-to-milliseconds. If the window somehow persists, give up on
    THIS save (failing open, same contract as the lock) and remove the
    temp file so no orphans pile up.
    """
    f = _state_file(state["session_id"])
    tmp = f.with_name(f"{f.name}.{os.getpid()}.tmp")
    tmp.write_text(
        json.dumps(state, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    for attempt in range(_REPLACE_ATTEMPTS):
        try:
            os.replace(tmp, f)
            return True
        except PermissionError:
            # Windows sharing violation from a concurrent lock-free
            # reader; back off briefly and retry (see docstring).
            time.sleep(_REPLACE_BACKOFF_BASE * (attempt + 1))
    try:
        tmp.unlink()
    except OSError:
        # Cleanup-of-cleanup: the temp file is cosmetic debris and the
        # mutation is already lost.
        # Rationale: removing it must never raise past the failing-open
        # save contract; swallowing here is deliberate.
        pass
    sys.stderr.write(
        f"[cc-enforcer] state save abandoned after {_REPLACE_ATTEMPTS} "
        f"os.replace attempts (concurrent reader held {f.name}); "
        f"this mutation is lost (failing open)\n"
    )
    return False


# --------------------------------------------------------------------------- #
# Cross-process session lock (v0.23 — lost-update fix).
#
# Every hook invocation is a separate OS process, and Claude Code fires
# tool calls in parallel: N parallel Reads → N concurrent read_guard
# processes all doing load() → mutate → save() on the SAME session file.
# Without a mutex that is a textbook lost-update race — measured on this
# machine at 10 parallel hooks: 2-3 of 10 recorded paths lost per round.
# The visible symptom is a false rule-04 DENY ("file not Read this
# session") right after the file WAS read; since v0.23 a lost
# `edited_files` entry can also corrupt the layer-(i) sync-gate verdict
# in either direction.
#
# The fix is a per-session advisory file lock held across each
# read-modify-write cycle: msvcrt.locking on Windows, fcntl.flock on
# POSIX — both stdlib. The lock lives in a sibling `<sid>.json.lock`
# file (never the state file itself, so locking cannot interfere with
# the atomic os.replace above). gc_state prunes `*.json` only, so stale
# lock files are never deleted out from under a holder; they are a few
# bytes each.
#
# Failing-open contract (unchanged): if the lock cannot be acquired for
# any reason, the mutation proceeds UNLOCKED with a stderr diagnostic —
# a locking bug must degrade to the pre-v0.23 racy behavior, never to a
# bricked agent. (Windows note: msvcrt LK_LOCK retries for ~10 s then
# raises OSError, which lands in the same failing-open path; real hook
# critical sections are single-digit milliseconds.)
# --------------------------------------------------------------------------- #
@contextlib.contextmanager
def _session_lock(session_id: str):
    lock_path = state_dir() / (_safe_session_filename(session_id) + ".lock")
    fh = None
    locked = False
    try:
        try:
            fh = open(lock_path, "ab")
            fh.seek(0)
            if os.name == "nt":
                msvcrt.locking(fh.fileno(), msvcrt.LK_LOCK, 1)
            else:
                fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
            locked = True
        except OSError as exc:
            # Failing open: proceed unlocked rather than block the hook.
            sys.stderr.write(
                f"[cc-enforcer] state lock unavailable ({exc}); "
                f"proceeding unlocked\n"
            )
        yield
    finally:
        if fh is not None:
            if locked:
                try:
                    fh.seek(0)
                    if os.name == "nt":
                        msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)
                    else:
                        fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
                except OSError as exc:
                    sys.stderr.write(
                        f"[cc-enforcer] state unlock failed ({exc})\n"
                    )
            fh.close()


def _load_shared(session_id: str) -> dict:
    """Load session state under the session lock (v0.24 read path).

    Why readers lock too: on Windows, a writer's os.replace fails with
    PermissionError while ANY process holds the target open, and
    CPython's open() does not request FILE_SHARE_DELETE. v0.23 locked
    only the mutators, so the hooks' own lock-free readers collided
    with their own writers — measured 300/300 lost saves under
    tight-loop readers. Serializing reads through the same lock removes
    the self-collision entirely at the design level; the save() retry
    remains as defense-in-depth against non-cooperating external
    readers (antivirus / indexers / backup agents). Mutators must NOT
    call this (they already hold the lock; Windows byte-range locks are
    not reentrant across handles) — they call `_load_for_mutation`
    directly, inside the lock they already hold.
    """
    with _session_lock(session_id):
        return load(session_id)


def add_read(session_id: str, file_path: str) -> bool:
    """Mark a file as Read (or Written) in this session.

    Returns True when the record is durable — either newly persisted or
    already present. False means the caller must not claim the file was
    registered (see `save`).
    """
    with _session_lock(session_id):
        state = _load_for_mutation(session_id)
        if state is None:
            return False
        norm = normalize_path(file_path)
        if norm in state["read_files"]:
            return True
        state["read_files"].append(norm)
        return save(state)


def has_read(session_id: str, file_path: str) -> bool:
    """True if this session has previously Read or Written this file.

    v0.25 — fails OPEN when the state file exists but cannot be read.
    `load()` degrades an unreadable record to an EMPTY one, and for this
    accessor "empty" is not neutral: it is a positive assertion of "never
    read", which read_guard turns into a hard DENY. So a transient
    Windows sharing violation (antivirus / indexer / backup agent — the
    same cause `save()` already retries against) produced the exact false
    "you have not Read this file" DENY that v0.23/v0.24 were chasing,
    while stderr simultaneously announced "failing open". Distinguishing
    "no state yet" (fresh record → False → deny, correct) from "state
    unreadable" (None → True → allow) restores the failing-open contract
    on the gating path.
    """
    with _session_lock(session_id):
        state = _load_for_mutation(session_id)
    if state is None:
        return True
    return normalize_path(file_path) in state.get("read_files", [])


# --------------------------------------------------------------------------- #
# Stop-hook one-shot guard (v0.6.0).
#
# rule 06 enforcement at Stop time: when the agent claims "done" without
# evidence, we block the Stop and force one more turn. To avoid an infinite
# loop, we record that we just blocked, and refuse to block twice in a row.
# --------------------------------------------------------------------------- #
def record_stop_block(
    session_id: str,
    turn_count: int | None,
    layer_id: str | None = None,
    blocked_groups: list[str] | None = None,
) -> None:
    """Mark that this session's Stop was blocked at the given turn_count.

    The next Stop check consults `was_just_blocked` to skip re-blocking.
    `layer_id` (v0.24, e.g. "(i)") records WHICH layer blocked: the
    grace path only honors a sync-marker acknowledgement when the block
    being recovered from was actually the sync gate — otherwise a reply
    that merely quotes "sync-check" while recovering from an unrelated
    layer would silently ack every pending group.

    `blocked_groups` (v0.25.1) records WHICH sync groups that layer-(i)
    block actually presented, so the recovery reply can only acknowledge
    those. Without it the grace path re-derived "everything pending right
    now" and swallowed groups that first became violated DURING the
    recovery turn — permanently suppressing a violation the agent was
    never shown and never answered.
    """
    with _session_lock(session_id):
        state = _load_for_mutation(session_id)
        if state is None:
            return
        state["last_blocked_turn"] = turn_count
        if layer_id is not None:
            state["last_blocked_layer"] = layer_id
            spent = state.setdefault("blocked_layers", [])
            if layer_id not in spent:
                spent.append(layer_id)
        if blocked_groups is not None:
            state["last_blocked_groups"] = list(blocked_groups)
        save(state)


def get_last_blocked_layer(session_id: str) -> str | None:
    """Layer id ("(a)".."(i)") of the most recent Stop block, or None."""
    state = _load_shared(session_id)
    layer = state.get("last_blocked_layer")
    return layer if isinstance(layer, str) else None


def get_forgiven_layers(session_id: str) -> set[str]:
    """Layers already spent (blocked once) in the current recovery sequence.

    v0.29 — grace used to be per SEQUENCE, not per layer: after any block
    `was_just_blocked` returned True and stop_guard returned 0 before
    evaluating a single layer, so a reply that fixed the layer it had been
    told about while still violating a different one sailed through. Field
    case: layer (a) blocked for missing evidence, the recovery reply
    supplied the evidence but still carried no `tldr`, and layer (h) —
    which had never blocked and never been named — was skipped entirely.
    Every un-named layer was therefore unenforceable in exactly the
    situation it exists for.

    Forgiveness is now scoped to the layers in this set. A layer already
    in it stays forgiven, which is the anti-deadlock property that
    motivated the original guard (no layer can block twice for the same
    recovery). A layer NOT in it may still block once, and doing so adds
    it — so escalation is bounded by the number of layers and terminates.
    `clear_blocked_layers` empties the set on any allowed Stop, starting
    the next sequence clean.
    """
    state = _load_shared(session_id)
    spent = state.get("blocked_layers")
    if not isinstance(spent, list):
        return set()
    return {layer for layer in spent if isinstance(layer, str)}


def clear_blocked_layers(session_id: str) -> None:
    """Empty the per-sequence forgiven-layer set (called on an allowed Stop)."""
    with _session_lock(session_id):
        state = _load_for_mutation(session_id)
        if state is None:
            return
        if state.get("blocked_layers"):
            state["blocked_layers"] = []
            save(state)


def get_last_blocked_groups(session_id: str) -> list[str]:
    """Sync-group names presented by the most recent layer-(i) block."""
    state = _load_shared(session_id)
    groups = state.get("last_blocked_groups")
    if not isinstance(groups, list):
        return []
    return [g for g in groups if isinstance(g, str)]


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
    state = _load_shared(session_id)
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
# When the agent successfully Edits or Writes a file, we set
# `edited_since_last_stop` and — only when the payload carried one — stamp
# `last_edit_turn`. The edit-gated Stop layers (e)/(f)/(g)/(i) fire when
# `did_edit_this_turn` is True, which the flag alone satisfies; the
# turn-number match is the secondary path, since production Stop payloads
# ship no turn_count (v0.23 — see `record_edit_turn`). Either way the
# rule-08/09/12 closing checks stay scoped to turns that actually modified
# files, avoiding false positives on read-only / analysis turns.
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
    """Record that an edit happened in the current (in-flight) turn.

    Called from read_guard immediately after a successful Edit or Write
    (Pre-tool-use; "successful" here means the guard did not DENY — the
    tool may still fail downstream, but that's harmless: the rule-08/09
    closing checks only matter when the agent claims completion in the
    same turn as a real edit, and a failed Edit followed by a done-claim
    is itself a rule-06 violation caught by layer (a)).

    Two signals are written:
      - `edited_since_last_stop = True` — ALWAYS. This is the signal the
        Stop hook actually consumes in production, where hook payloads
        carry no `turn_count` (verified live in v0.23: a session with 27
        recorded edits had no `last_edit_turn` key at all — every stamp
        call had silently no-op'd, so the edit-gated Stop layers
        (e)/(f)/(g)/(i) had NEVER fired outside the test suite). The
        flag is cleared by stop_guard on every ALLOWED Stop (a turn
        boundary); a BLOCKED Stop keeps it set, because the agent's
        recovery reply still belongs to the same logical turn.
      - `last_edit_turn = turn_count` — only when a real turn_count was
        supplied (test harnesses; a future Claude Code that ships the
        field). Preserves the original exact-match semantics.
    """
    with _session_lock(session_id):
        state = _load_for_mutation(session_id)
        if state is None:
            return
        state["edited_since_last_stop"] = True
        if turn_count is not None:
            state["last_edit_turn"] = turn_count
        save(state)


def clear_edit_flag(session_id: str) -> None:
    """Mark the turn boundary: clear `edited_since_last_stop`.

    Called by stop_guard on every ALLOWED Stop. Deliberately NOT called
    on blocked Stops — the recovery reply is the same logical turn and
    must still face the edit-gated layers.
    """
    with _session_lock(session_id):
        state = _load_for_mutation(session_id)
        if state is None:
            return
        if state.get("edited_since_last_stop"):
            state["edited_since_last_stop"] = False
            save(state)


def did_edit_this_turn(session_id: str, turn_count: int | None) -> bool:
    """True if the current turn performed an Edit/Write.

    Two ways to be true:
      - exact turn match: `last_edit_turn == turn_count` (the original
        v0.11 semantics, exercised by the test suite which passes real
        turn_count values), or
      - the production path: `edited_since_last_stop` is set (payloads
        without turn_count — see record_edit_turn).

    A read-only / pure-analysis turn never trips the edit-gated layers,
    regardless of how the agent phrases the closing message.
    """
    state = _load_shared(session_id)
    if state.get("edited_since_last_stop"):
        return True
    if turn_count is None:
        return False
    return state.get("last_edit_turn") == turn_count


def next_stop_turn(session_id: str) -> int:
    """Increment and return the session's Stop counter.

    Production Stop payloads carry no `turn_count`, which used to make
    the one-shot guard vacuous too (`record_stop_block(sid, None)` +
    `was_just_blocked(sid, None)` never matched, so a block could repeat
    every single turn). stop_guard now synthesizes a monotonically
    increasing turn number from this counter whenever the payload lacks
    one — Stop fires exactly once per turn, so the counter IS a turn
    number, and the [last+1, last+3] grace-window arithmetic works
    unchanged.
    """
    with _session_lock(session_id):
        state = _load_for_mutation(session_id)
        if state is None:
            return 0
        counter = int(state.get("stop_counter", 0)) + 1
        state["stop_counter"] = counter
        save(state)
        return counter


# --------------------------------------------------------------------------- #
# Edited-file set (v0.23.0 — rule 12 repo-wide sync gate).
#
# `last_edit_turn` (above) only answers "did an edit happen this turn?";
# the sync gate needs "WHICH files were edited this session?" so it can
# match them against the project's co-update groups
# (.claude/cc-enforcer/sync-gate.toml). read_guard appends to this set
# on every ACCEPTED Edit / Write (same call sites as record_edit_turn —
# a denied edit never landed, so it is not recorded). Paths are stored
# normalized (realpath + normcase) like `read_files`.
# --------------------------------------------------------------------------- #
def record_edited_file(session_id: str, file_path: str) -> None:
    """Add `file_path` to this session's edited-file set (idempotent)."""
    with _session_lock(session_id):
        state = _load_for_mutation(session_id)
        if state is None:
            return
        edited = state.setdefault("edited_files", [])
        norm = normalize_path(file_path)
        if norm not in edited:
            edited.append(norm)
            save(state)


def get_edited_files(session_id: str) -> list[str]:
    """Return the normalized paths of every file edited this session."""
    state = _load_shared(session_id)
    edited = state.get("edited_files") or []
    return [p for p in edited if isinstance(p, str)]


def get_sync_acked_groups(session_id: str) -> list[str]:
    """Group names already acknowledged for this session (layer (i)).

    `edited_files` is session-cumulative and never pruned, so without an
    acknowledgement record a once-unmet group would re-block every
    post-grace edit turn for the rest of the session — even after the
    agent explicitly answered it with a sync marker. Acknowledged groups
    are therefore remembered per session: one explicit answer per group
    is enough.
    """
    state = _load_shared(session_id)
    acked = state.get("sync_acked_groups") or []
    return [g for g in acked if isinstance(g, str)]


def ack_sync_groups(session_id: str, group_names: list[str]) -> None:
    """Record `group_names` as acknowledged for this session (idempotent)."""
    if not group_names:
        return
    with _session_lock(session_id):
        state = _load_for_mutation(session_id)
        if state is None:
            return
        acked = state.setdefault("sync_acked_groups", [])
        changed = False
        for name in group_names:
            if name not in acked:
                acked.append(name)
                changed = True
        if changed:
            save(state)


# --------------------------------------------------------------------------- #
# Rolling-patch counter (v0.13.0 — rule 09 hard interception; API made
# atomic in v0.24).
#
# Counter semantics:
#   - try_record_small_edit(sid, path, threshold) → atomically decide
#     AND record one small edit: refuse (no increment) when the counter
#     would reach `threshold`, else increment. One lock acquisition
#     covers both, closing the v0.13-v0.23 check-then-act race where two
#     parallel hooks both read count=2, both allowed, and the forbidden
#     4th small edit landed.
#   - reset_edit_count(sid, path) → clear the counter, called on a
#     systematic rewrite (≥ 50 lines / ≥ 1500 chars on new_string) and
#     on Write-new (a fresh file has no rolling history — v0.24).
#
# The classification logic (small / medium / systematic) lives in
# read_guard; this module owns the counter storage + the atomic
# threshold decision. Threshold = 4 means the 4th small edit attempt is
# refused — the recorded count stays at 3 until a systematic rewrite
# resets it, so subsequent small-edit attempts also DENY.
# --------------------------------------------------------------------------- #
def try_record_small_edit(
    session_id: str, file_path: str, threshold: int,
) -> tuple[bool, int]:
    """Atomically decide-and-record one small edit against `threshold`.

    Returns (allowed, prior_count). When prior_count + 1 >= threshold
    the edit is refused and the counter is NOT incremented (a refused
    edit never lands; counting it would double-count and silently
    disable the threshold). Decision and increment share one lock
    acquisition — the previous two-step API (read the count, then
    increment in a separate locked call) let two parallel hooks both
    observe count=2 and both allow.
    """
    with _session_lock(session_id):
        state = _load_for_mutation(session_id)
        if state is None:
            return (True, 0)
        counters = state.setdefault("edits_per_file", {})
        norm = normalize_path(file_path)
        prior = int(counters.get(norm, 0))
        if prior + 1 >= threshold:
            return (False, prior)
        counters[norm] = prior + 1
        save(state)
        return (True, prior)


def reset_edit_count(session_id: str, file_path: str) -> None:
    """Clear the small-edit counter for `file_path` (systematic rewrite)."""
    with _session_lock(session_id):
        state = _load_for_mutation(session_id)
        if state is None:
            return
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
    with _session_lock(session_id):
        state = _load_for_mutation(session_id)
        if state is None:
            return
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
    state = _load_shared(session_id)
    baselines = state.get("baseline_mtimes") or {}
    norm = normalize_path(file_path)
    if norm not in baselines:
        return (False, None)
    return (True, baselines[norm])
