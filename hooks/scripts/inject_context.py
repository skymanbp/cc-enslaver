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
import os
import sys
from pathlib import Path

# Make `lib/` importable when run directly as a script.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib import edicts as edicts_lib  # noqa: E402 — sys.path mutated above
from lib import state as state_lib  # noqa: E402 — sys.path mutated above

# v0.18: lazy import only when auto-GC actually triggers (kept None
# until first use). Reason: SessionStart latency matters; the import
# tree pulls in `time` which is cheap, but the lookup itself only
# pays for users who opted into CC_ENSLAVER_AUTO_GC_DAYS.
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
# Language switch (v0.15).
#
# Default prompts are Chinese (the user's primary language). Set
# CC_ENSLAVER_LANG=en to inject the English mirror under prompts/en/.
# Any other value falls back to Chinese — fail-safe to the canonical
# language, never silently miss the injection.
# --------------------------------------------------------------------------- #
SUPPORTED_LANGS = {"zh", "en"}


def _resolved_lang() -> str:
    """Return the active language. Defaults to 'zh'; 'en' if explicitly set."""
    lang = (os.environ.get("CC_ENSLAVER_LANG") or "").strip().lower()
    if lang in SUPPORTED_LANGS:
        return lang
    return "zh"


def load_prompt(filename: str) -> str:
    """Read prompt content from prompts/<filename>. Fail loudly on missing file.

    Failing loudly (rather than returning '') is itself a cc-enslaver
    measure: a silent empty injection would mask broken configuration.

    v0.15: when CC_ENSLAVER_LANG=en, reads from prompts/en/<filename>
    first; if missing, falls back to prompts/<filename> (Chinese
    canonical) with a stderr warning. The fallback prevents a missing
    English translation from blanking the injection.
    """
    lang = _resolved_lang()
    if lang == "en":
        en_path = PROMPTS_DIR / "en" / filename
        if en_path.is_file():
            return en_path.read_text(encoding="utf-8")
        sys.stderr.write(
            f"[cc-enslaver] CC_ENSLAVER_LANG=en but missing {en_path}; "
            f"falling back to Chinese canonical.\n"
        )
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

    # Append 圣旨 / Imperial Edicts (user-defined edicts) to BOTH
    # SessionStart and UserPromptSubmit injections. SessionStart
    # establishes the edicts at boot; UserPromptSubmit re-injects them
    # every turn so they survive context compaction (the failure mode
    # that motivated v0.12's prompt thinning + edict system).
    #
    # v0.17: pass the already-resolved language so the edict block and
    # the base prompt always speak the same language (CC_ENSLAVER_LANG
    # is the single switch the user toggles — base prompts/en/*.md and
    # the edict block flip together).
    try:
        loaded = edicts_lib.load()
        block = edicts_lib.render_injection(loaded, lang=_resolved_lang())
        if block:
            additional_context = additional_context.rstrip() + "\n" + block
    except Exception as e:
        # Never let an edicts bug brick the injection.
        sys.stderr.write(f"[cc-enslaver] edicts injection failed: {e}\n")

    # v0.18 auto-GC on SessionStart (opt-in via CC_ENSLAVER_AUTO_GC_DAYS).
    # Runs after the main injection so even if GC blows up, the prompt
    # injection already landed. Rate-limited by a marker file so we don't
    # re-scan on every rapid session restart.
    if args.event == "SessionStart":
        _maybe_auto_gc()

    emit(args.event, additional_context)
    return 0


# --------------------------------------------------------------------------- #
# v0.18 — opt-in auto-GC on SessionStart.
#
# Trigger: env var CC_ENSLAVER_AUTO_GC_DAYS=N (positive int, default
# disabled). When set, on every SessionStart we prune session-state
# files older than N days. Rate-limited via a marker file at
# state_dir / _auto_gc.json so we run at most once per 24h regardless
# of how many sessions open. Failures are silent stderr — never block
# the injection.
# --------------------------------------------------------------------------- #
_AUTO_GC_MARKER = "_auto_gc.json"
_AUTO_GC_MIN_INTERVAL_SECONDS = 86400  # once per day


def _maybe_auto_gc() -> None:
    """Run garbage collection if the user opted in and we're not rate-limited.

    All failure modes log to stderr and return silently — auto-GC must
    never affect the injection payload or block session startup.
    """
    raw = os.environ.get("CC_ENSLAVER_AUTO_GC_DAYS", "").strip()
    if not raw:
        return  # default off

    try:
        threshold_days = int(raw)
    except ValueError:
        sys.stderr.write(
            f"[cc-enslaver] CC_ENSLAVER_AUTO_GC_DAYS={raw!r} is not an "
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
            f"[cc-enslaver] auto-GC could not resolve state_dir: {exc}\n"
        )
        return

    now = _time.time()
    if marker_path.is_file():
        try:
            last_ts = _json.loads(marker_path.read_text(encoding="utf-8")).get("ts", 0)
        except Exception:
            # Rationale: a corrupt marker file shouldn't prevent GC;
            # treat as "never ran" and proceed (the GC itself will
            # rewrite the marker on success below).
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
                    f"[cc-enslaver] auto-GC could not import gc_state: {exc}\n"
                )
                return
        _gc_state_mod = _gc

    # Exclude the current session's own state file (defensive: usually
    # doesn't exist yet at SessionStart, but cheap safety).
    session_id: str | None = None
    # session_id is in the hook payload that we drained earlier. The
    # injection hook does not currently parse it; auto-GC works fine
    # without exclusion since the live session's file should be too
    # new to cross threshold anyway. Leaving exclude_session=None.

    try:
        summary = _gc_state_mod.prune_old_sessions(
            threshold_days=threshold_days,
            dry_run=False,
            exclude_session=session_id,
        )
    except Exception as exc:
        sys.stderr.write(f"[cc-enslaver] auto-GC failed: {exc}\n")
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
            f"[cc-enslaver] auto-GC could not update marker: {exc}\n"
        )

    if summary["deleted"] > 0 or summary["failures"]:
        sys.stderr.write(
            f"[cc-enslaver] auto-GC: deleted {summary['deleted']} "
            f"session(s) older than {threshold_days}d "
            f"({summary['bytes_freed']} bytes freed)"
            f"{'; failures: ' + str(summary['failures']) if summary['failures'] else ''}\n"
        )


if __name__ == "__main__":
    sys.exit(main())
