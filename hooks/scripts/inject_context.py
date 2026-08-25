#!/usr/bin/env python3
"""
cc-enforcer — context injection hook.

The plugin's soft layer. `hooks/hooks.json` registers five hook entries
across four scripts; this one serves the two injection events —
SessionStart and UserPromptSubmit — by reading the matching prompt file
from `../../prompts/` and emitting the JSON shape that Claude Code
expects for the corresponding hook event. The hard (blocking) layers are
separate scripts: read_guard.py and bash_guard.py on PreToolUse,
stop_guard.py on Stop.

Why one script for both injection events instead of two:
  Per CLAUDE.md §2.6 (minimum effective change), two near-identical
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

We always exit 0 — this hook is purely additive (soft layer). Every
blocking decision belongs to the three guard scripts named above.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

# Make `lib/` importable when run directly as a script.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib import edicts as edicts_lib  # noqa: E402 — sys.path mutated above
from lib import envfile as envfile_lib  # noqa: E402 — sys.path mutated above
from lib import hookio  # noqa: E402 — sys.path mutated above
from lib import state as state_lib  # noqa: E402 — sys.path mutated above

# v0.18: lazy import only when auto-GC actually triggers (kept None
# until first use). Reason: SessionStart latency matters; the import
# tree pulls in `time` which is cheap, but the lookup itself only
# pays for users who opted into CC_ENFORCER_AUTO_GC_DAYS.
_gc_state_mod = None

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

# --------------------------------------------------------------------------- #
# Language switch (v0.15; skeleton-flipped v0.21).
#
# English is the DEFAULT and the "skeleton" (source-of-truth) language:
# the root prompts/*.md files are English. Set CC_ENFORCER_LANG=<code>
# to inject a translation from prompts/<code>/ (e.g. CC_ENFORCER_LANG=zh
# → prompts/zh/). ANY code is accepted — a new language ships by adding
# its prompts/<code>/ + rules/<code>/ dirs, no code change here. If the
# translation file is missing, load_prompt() falls back to the English
# skeleton — fail-safe to the source-of-truth language, never silently
# miss the injection.
# --------------------------------------------------------------------------- #
DEFAULT_LANG = "en"


def _resolved_lang() -> str:
    """Return the active language code.

    Defaults to the English skeleton (DEFAULT_LANG); any non-empty
    CC_ENFORCER_LANG value passes through verbatim (lower-cased). No
    membership gate — resolution + fallback happen in load_prompt() /
    edicts, so an unregistered code degrades gracefully to English.
    """
    return (os.environ.get("CC_ENFORCER_LANG") or "").strip().lower() or DEFAULT_LANG


def load_prompt(filename: str) -> str:
    """Read prompt content for the active language. Fail loudly on missing file.

    Failing loudly (rather than returning '') is itself a cc-enforcer
    measure: a silent empty injection would mask broken configuration.

    Skeleton-flipped (v0.21): the English skeleton lives at
    prompts/<filename> (root). When CC_ENFORCER_LANG names a non-default
    language, read prompts/<lang>/<filename> first; if that translation
    is missing, fall back to the root English skeleton with a stderr
    warning. The fallback prevents a missing / partial translation from
    blanking the injection.
    """
    lang = _resolved_lang()
    if lang != DEFAULT_LANG:
        translated = PROMPTS_DIR / lang / filename
        if translated.is_file():
            return translated.read_text(encoding="utf-8")
        sys.stderr.write(
            f"[cc-enforcer] CC_ENFORCER_LANG={lang} but missing {translated}; "
            f"falling back to English skeleton.\n"
        )
    path = PROMPTS_DIR / filename
    if not path.is_file():
        # Surface the misconfiguration to Claude Code's error stream.
        # We still exit 0 with an empty additionalContext so the hook
        # does not block the user; but the diagnostic goes to stderr.
        sys.stderr.write(
            f"[cc-enforcer] missing prompt file: {path}\n"
            f"  expected one of: {sorted(EVENT_TO_PROMPT.values())}\n"
        )
        return ""
    return path.read_text(encoding="utf-8")


# --------------------------------------------------------------------------- #
# v0.29 — self-locating header.
#
# Claude Code caps hook output (additionalContext included) at 10,000
# CHARACTERS; anything longer is written to a file and replaced inline
# by a short preview plus that path
# (https://code.claude.com/docs/en/hooks#json-output). A contract the
# agent can only see the first ~2 KB of is not a contract: the field
# failure was a session where §3 (the mandatory reply schema) sat past
# the preview boundary and went unread for the whole session.
#
# The prompts are now budgeted to stay under the cap, but a budget is
# not a guarantee — edicts grow, translations differ in length. This
# header is the fail-safe: it is the FIRST thing in every injection, so
# it survives any truncation, and it carries the absolute plugin root
# (which the static markdown cannot know) so the agent can Read the
# full contract instead of working from a fragment.
# --------------------------------------------------------------------------- #
_HEADER = (
    "<!-- cc-enforcer root: {root} -->\n"
    "Truncated (a `<persisted-output>` preview)? Read "
    "`{root}/prompts/{fname}` in full before replying.\n\n"
)

# Claude Code's documented cap on hook output, in CHARACTERS (not bytes;
# UTF-8 multi-byte content counts one per character):
# https://code.claude.com/docs/en/hooks#json-output
# Public because the test suite asserts the live injections fit under it,
# and a private copy of the number in the tests is a second source of
# truth that drifts the moment Claude Code changes the limit.
OUTPUT_CAP = 10000

_EDICTS_ELIDED = (
    "\n\n<!-- {n} edict(s) elided to stay under the {cap}-char hook cap; "
    "run `/cc-enforcer:edict list` or read the project's "
    "`.claude/cc-enforcer/edicts.toml` for the full text. -->\n"
)


def build_context(prompt_filename: str, body: str, edict_block: str = "") -> str:
    """Assemble the injection, guaranteeing it stays under the output cap.

    The contract body is fixed-size and budgeted; the edict block is not —
    it grows with every edict the user adds, and it was what pushed this
    injection past the cap in the first place (16 project edicts ≈ 5.6k
    characters on top of a 13.2k contract, so the whole thing was written
    to a file and replaced inline by a ~2 KB preview).

    Trimming the two parts is therefore not symmetric. The contract is
    what the cap exists to protect: losing its tail silently disables the
    reply-schema and enforcement tables. The edict block is recoverable —
    it lives in a file the agent can read on demand — so when the budget
    is tight the edicts are elided down to a pointer and the contract
    survives whole. A fixed budget would go stale the moment either side
    changes length, so the split is computed from the actual strings.
    """
    header = _HEADER.format(root=PLUGIN_ROOT, fname=prompt_filename)
    if len(header) + len(body) + len(edict_block) <= OUTPUT_CAP:
        return header + body + edict_block
    room = OUTPUT_CAP - len(header) - len(body) - len(_EDICTS_ELIDED)
    if room <= 0:
        # The contract alone fills the budget: emit it without edicts
        # rather than emit a truncated contract. Over-cap here is the
        # lesser failure — the harness persists it and the header (first
        # thing in the payload) still says where to read the full text.
        return header + body
    kept, dropped = _clip_edicts(edict_block, room)
    return header + body + kept + _EDICTS_ELIDED.format(
        n=dropped, cap=OUTPUT_CAP,
    )


def _clip_edicts(block: str, room: int) -> tuple[str, int]:
    """Keep as many whole edicts as `room` allows; report how many were cut.

    Entries are cut at table-row boundaries — `render_injection` emits one
    markdown row per edict, each starting ``| `<id>` |`` (lib/edicts.py) —
    never mid-row: half an edict reads as a complete instruction and would
    be obeyed as one. Keeping ``lines[:kept_upto]`` preserves the block
    preamble (title / intro / table header) ahead of the first kept row.

    v0.34.1 — the original boundary pattern matched the ``[Exx]`` line
    shape that ``manage_edicts list`` PRINTS, which the injected block
    never contains (it is a markdown table), so any over-cap injection
    silently dropped EVERY edict while the elision notice reported 0 cut —
    exactly the unfounded-claim shape this plugin exists to block.
    """
    lines = block.splitlines(keepends=True)
    starts = [i for i, line in enumerate(lines) if _EDICT_ENTRY.match(line)]
    total = len(starts)
    if not total:
        return ("", 0)
    kept_upto = 0
    for idx, start in enumerate(starts):
        end = starts[idx + 1] if idx + 1 < total else len(lines)
        if len("".join(lines[:end])) > room:
            break
        kept_upto = end
    return ("".join(lines[:kept_upto]), total - sum(
        1 for start in starts if start < kept_upto
    ))


# A rendered edict row: first cell is the backticked id (lib/edicts.py
# render_injection). The table header row (`| ID |`) and the separator
# (`|----|`) carry no backtick, so neither counts as an entry.
_EDICT_ENTRY = re.compile(r"^\|\s*`")


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
        description="cc-enforcer context injection hook",
    )
    parser.add_argument(
        "--event",
        required=True,
        choices=sorted(EVENT_TO_PROMPT.keys()),
        help="Which hook event this invocation corresponds to.",
    )
    args = parser.parse_args()

    # Drain stdin if Claude Code piped hook input to us; reading prevents
    # a SIGPIPE on the parent side. v0.25.1: the payload is also where the
    # live session id lives, and auto-GC needs it so it can never prune
    # the state file of the session that is starting (see _maybe_auto_gc).
    raw_payload = ""
    try:
        # v0.37 — bytes + explicit UTF-8 (lib/hookio). Text-mode stdin
        # decodes with the host codepage under `surrogateescape`, which
        # can pull the byte after a multi-byte sequence into the previous
        # character — enough to break the `session_id` key out of a
        # payload whose earlier fields carry any non-ASCII text.
        raw_payload = hookio.read_payload_text()
    except Exception:
        # Draining stdin is best-effort; losing it only costs auto-GC its
        # exclusion hint.
        # Rationale: a read failure must never block the injection.
        pass
    session_id = _session_id_from(raw_payload)

    prompt_filename = EVENT_TO_PROMPT[args.event]
    additional_context = load_prompt(prompt_filename)

    # Append 圣旨 / Imperial Edicts (user-defined edicts) to BOTH
    # SessionStart and UserPromptSubmit injections. SessionStart
    # establishes the edicts at boot; UserPromptSubmit re-injects them
    # every turn so they survive context compaction (the failure mode
    # that motivated v0.12's prompt thinning + edict system).
    #
    # v0.17: pass the already-resolved language so the edict block and
    # the base prompt always speak the same language (CC_ENFORCER_LANG
    # is the single switch the user toggles — the base prompt (English
    # skeleton at prompts/*.md, or a translation at prompts/<lang>/*.md)
    # and the edict block flip together).
    #
    # v0.29: the block is kept SEPARATE from the contract body rather
    # than concatenated here, because build_context must be able to trim
    # the two asymmetrically — the contract is protected, the edicts are
    # elided to a pointer when the 10,000-char output cap is tight.
    edict_block = ""
    try:
        loaded = edicts_lib.load()
        block = edicts_lib.render_injection(loaded, lang=_resolved_lang())
        if block:
            edict_block = "\n" + block
            additional_context = additional_context.rstrip()
    except Exception as e:
        # Never let an edicts bug brick the injection.
        sys.stderr.write(f"[cc-enforcer] edicts injection failed: {e}\n")

    # v0.18 auto-GC on SessionStart (opt-in via CC_ENFORCER_AUTO_GC_DAYS).
    # Runs after the main injection so even if GC blows up, the prompt
    # injection already landed. Rate-limited by a marker file so we don't
    # re-scan on every rapid session restart.
    #
    # v0.34 env-file hygiene rides the same slot and cadence: SessionStart
    # is exactly the event on which a non-idempotent plugin re-appends its
    # exports (it fires per compact/resume), so deduping here bounds the
    # accumulation at one generation regardless of hook ordering. Both
    # maintenance passes are failing-open and never touch the payload.
    if args.event == "SessionStart":
        _maybe_auto_gc(session_id)
        envfile_lib.maybe_dedupe()

    emit(args.event, build_context(
        prompt_filename, additional_context, edict_block,
    ))
    return 0


def _session_id_from(raw: str) -> str | None:
    """Best-effort session id from the drained hook payload.

    Returns None on anything unexpected — a missing id costs auto-GC its
    self-exclusion hint, which is strictly better than raising here and
    losing the whole injection.
    """
    if not raw.strip():
        return None
    try:
        payload = json.loads(raw)
    except Exception:
        return None
    if not isinstance(payload, dict):
        return None
    sid = payload.get("session_id")
    return sid if isinstance(sid, str) and sid.strip() else None


# --------------------------------------------------------------------------- #
# v0.18 — opt-in auto-GC on SessionStart.
#
# Trigger: env var CC_ENFORCER_AUTO_GC_DAYS=N (positive int, default
# disabled). When set, on every SessionStart we prune session-state
# files older than N days. Rate-limited via a marker file at
# state_dir / _auto_gc.json so we run at most once per 24h regardless
# of how many sessions open. Failures are silent stderr — never block
# the injection.
# --------------------------------------------------------------------------- #
_AUTO_GC_MARKER = "_auto_gc.json"
_AUTO_GC_MIN_INTERVAL_SECONDS = 86400  # once per day


def _maybe_auto_gc(session_id: str | None = None) -> None:
    """Run garbage collection if the user opted in and we're not rate-limited.

    All failure modes log to stderr and return silently — auto-GC must
    never affect the injection payload or block session startup.

    `session_id` (v0.25.1) is the live session, excluded from pruning.
    """
    raw = os.environ.get("CC_ENFORCER_AUTO_GC_DAYS", "").strip()
    if not raw:
        return  # default off

    try:
        threshold_days = int(raw)
    except ValueError:
        sys.stderr.write(
            f"[cc-enforcer] CC_ENFORCER_AUTO_GC_DAYS={raw!r} is not an "
            f"integer; auto-GC skipped.\n"
        )
        return

    if threshold_days < 1:
        return  # 0 or negative explicitly disables

    # Rate limit: skip if we ran within the last 24h.
    import json as _json
    import time as _time
    try:
        marker_path = state_lib.state_dir() / _AUTO_GC_MARKER
    except Exception as exc:
        sys.stderr.write(
            f"[cc-enforcer] auto-GC could not resolve state_dir: {exc}\n"
        )
        return

    now = _time.time()
    if marker_path.is_file():
        try:
            marker = _json.loads(marker_path.read_text(encoding="utf-8"))
            last_ts = marker.get("ts", 0) if isinstance(marker, dict) else 0
        except Exception:
            # Rationale: a corrupt marker file shouldn't prevent GC;
            # treat as "never ran" and proceed (the GC itself will
            # rewrite the marker on success below).
            last_ts = 0
        if not isinstance(last_ts, (int, float)) or isinstance(last_ts, bool):
            # v0.25.1 — a marker that PARSES but carries a non-numeric
            # `ts` (e.g. {"ts": "yesterday"}) used to raise TypeError on
            # the subtraction below, OUTSIDE the try. That escaped
            # _maybe_auto_gc, which main() calls before emit() — so one
            # mistyped marker file silently suppressed the ENTIRE
            # SessionStart injection, edicts included.
            last_ts = 0
        if now - last_ts < _AUTO_GC_MIN_INTERVAL_SECONDS:
            return  # rate-limited

    # Lazy import gc_state on first real GC pass.
    global _gc_state_mod
    if _gc_state_mod is None:
        try:
            from . import gc_state as _gc  # type: ignore[import-not-found]  # because relative import inside script; falls through
        except Exception:
            try:
                import gc_state as _gc  # because we sys.path.inserted scripts dir
            except Exception as exc:
                sys.stderr.write(
                    f"[cc-enforcer] auto-GC could not import gc_state: {exc}\n"
                )
                return
        _gc_state_mod = _gc

    # Exclude the live session's own state file. v0.25.1 — this used to
    # pass None with the reasoning "the live session's file should be too
    # new to cross the threshold anyway". That holds only for a session
    # that started now: a RESUMED session carries an old state file, and
    # auto-GC would delete its reads, baselines, rolling counters and
    # sync acknowledgements out from under it. The id now comes from the
    # hook payload main() drains (see _session_id_from).
    try:
        summary = _gc_state_mod.prune_old_sessions(
            threshold_days=threshold_days,
            dry_run=False,
            exclude_session=session_id,
        )
    except Exception as exc:
        sys.stderr.write(f"[cc-enforcer] auto-GC failed: {exc}\n")
        return

    # Always update the marker after a real attempt — even if 0 files
    # were eligible. This is what makes the 24h rate limit work.
    try:
        marker_path.write_text(
            _json.dumps({"ts": now, "deleted": summary["deleted"]}),
            encoding="utf-8",
        )
    except Exception as exc:
        sys.stderr.write(
            f"[cc-enforcer] auto-GC could not update marker: {exc}\n"
        )

    if summary["deleted"] > 0 or summary["failures"]:
        sys.stderr.write(
            f"[cc-enforcer] auto-GC: deleted {summary['deleted']} "
            f"session(s) older than {threshold_days}d "
            f"({summary['bytes_freed']} bytes freed)"
            f"{'; failures: ' + str(summary['failures']) if summary['failures'] else ''}\n"
        )


if __name__ == "__main__":
    sys.exit(main())
