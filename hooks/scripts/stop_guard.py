#!/usr/bin/env python3
"""anti-laziness — Stop hook enforcing rule 06 (verify-convergence).

At every Stop event, this hook inspects the agent's last assistant
message and refuses to let the agent finish the turn if both:

  (a) the message contains a "done" claim (`已解决` / `完成` / `修好了`
      / `fixed` / `done` / `completed` / etc.); AND
  (b) the message contains no convergence evidence (a `$ ` shell
      prompt, command output, "重触发", "test passed", etc.).

When both conditions hold, the hook returns
`{"decision": "block", "reason": <rule 06 reminder>}`, forcing the
agent to spend one more turn supplying actual verification evidence.

# One-shot guard — why we never block twice in a row

A Stop hook that always blocks would loop forever: block → continue →
block → continue → … . We record `last_blocked_turn` in the
session state file. If the *current* `turn_count` is within 3 turns
of the last block, we skip the heuristic and allow the Stop. The
agent gets one (well, up to three) chances to recover before we
fire again.

# Heuristic vs deep verification

A v0.7.0+ candidate is to parse "I edited <path>" / "我修改了 <path>"
claims and verify each against `git diff` / file mtime. v0.6.0 ships
the simpler done-without-evidence heuristic because:
  - The deep version requires natural-language extraction of file
    paths from arbitrary phrasings — fragile and high false-positive.
  - The simple version is robust: even a careful agent should always
    cite some evidence (per rule 05) when claiming done.
  - One-shot guard means a single false positive costs the user one
    extra turn, not a stuck session.

# Output contract (Stop event, verified against
# https://code.claude.com/docs/en/hooks.md):
#
#   Block:  {"decision": "block", "reason": "<text>"}   (top-level)
#   Allow:  exit 0 with no stdout
#
# Note this differs from PreToolUse, which uses
# `hookSpecificOutput.permissionDecision`.

# Failing-open contract: any exception → log to stderr + exit 0
# (allow). A bug in the guard cannot be permitted to brick the agent.
"""

from __future__ import annotations

import json
import re
import sys
import traceback
from pathlib import Path

# Make `lib/` importable when run as a script.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib import state as state_lib  # noqa: E402


# --------------------------------------------------------------------------- #
# Heuristic patterns.
#
# DONE_PATTERNS: phrasings that signal the agent claims completion.
# EVIDENCE_PATTERNS: phrasings that signal the agent supplied verification
#                    evidence per rule 06.
#
# Both pattern lists are intentionally loose. False positives (block when
# work was actually done) cost one extra turn each; false negatives (no
# block when work is sloppy) cost the discipline. The one-shot guard
# bounds the false-positive damage.
# --------------------------------------------------------------------------- #
DONE_PATTERNS = [
    # Chinese — explicit completion
    re.compile(r"已解决"),
    re.compile(r"已修复"),
    re.compile(r"完成了"),
    re.compile(r"完工"),
    re.compile(r"搞定"),
    # Chinese — natural "fixed it" phrasings (V + 好了 idiom).
    # Caught the test failure where "我把 bug 改好了" was overlooked
    # because we had only 修好了 but not 改好了 / 弄好了 / 搞好了 etc.
    re.compile(r"[修改弄搞]好了"),
    # English — explicit completion
    re.compile(r"\bfixed\b", re.IGNORECASE),
    re.compile(r"\bdone\b", re.IGNORECASE),
    re.compile(r"\bcompleted\b", re.IGNORECASE),
    re.compile(r"\bresolved\b", re.IGNORECASE),
    # English — soft "should be done" phrasings (also red flags)
    re.compile(r"all set", re.IGNORECASE),
    re.compile(r"should\s+work\s+now", re.IGNORECASE),
    re.compile(r"that\s+should\s+do\s+it", re.IGNORECASE),
]

EVIDENCE_PATTERNS = [
    # Shell prompts and command-output markers
    re.compile(r"^\s*\$\s+\S", re.MULTILINE),
    re.compile(r"^\s*>\s+\S", re.MULTILINE),
    # Test-runner output snippets
    re.compile(r"\b\d+\s+(passed|failed|errors?)\b", re.IGNORECASE),
    re.compile(r"Ran\s+\d+\s+tests?", re.IGNORECASE),
    re.compile(r"\bpytest\b", re.IGNORECASE),
    re.compile(r"\bunittest\b", re.IGNORECASE),
    # Convergence keywords from rule 06 itself
    re.compile(r"重触发"),
    re.compile(r"边界用例"),
    re.compile(r"反向用例"),
    re.compile(r"收敛"),
    # Generic verification language
    re.compile(r"\bverified\b", re.IGNORECASE),
    re.compile(r"\bre-?ran\b", re.IGNORECASE),
    re.compile(r"\bvalidated\b", re.IGNORECASE),
    # Evidence formatting cues — fenced code blocks of output
    re.compile(r"```\n[^`]{20,}", re.MULTILINE),
]


def _has_done_claim(text: str) -> str | None:
    """Return the matched done-claim phrase, or None."""
    for p in DONE_PATTERNS:
        m = p.search(text)
        if m:
            return m.group(0)
    return None


def _has_evidence(text: str) -> bool:
    return any(p.search(text) for p in EVIDENCE_PATTERNS)


# --------------------------------------------------------------------------- #
# Block reason template.
# --------------------------------------------------------------------------- #
BLOCK_REASON = """anti-laziness · rule 06 enforcement (Stop hook)

You appear to be claiming completion ({matched_phrase!r}) but your
message contains no convergence evidence — no shell command output,
no test results, no "重触发原症状" demonstration, no quantitative
comparison.

Per rule 06 (rules/06-verify-convergence.md), before declaring done
you must:

  1. 重触发原症状 — Re-run the exact failing input and show output.
  2. 边界 + 反向用例 — Cover at least 1 edge + 1 negative case.
  3. 连带不破坏 — Run the relevant test/lint/typecheck pass.
  4. 自答 4 题 — Is it really solved? Is there a better solution?
                 Which changes are unverified? Is the verification
                 actually meaningful?
  5. 量化优于定性 — For perf/race/compat: numbers, repeat counts,
                    matrix outputs.

Continue your response with the actual verification evidence. If you
have already done the verification mentally but did not include it in
the message, repeat with the concrete commands and outputs.

(One-shot guard: this is the only time you'll be blocked for this
sequence. The next Stop will be allowed even if evidence is still
weak. Use the next turn well.)
"""


def _emit_block(matched_phrase: str) -> None:
    """Write a `decision: block` response and exit 0.

    Stop hook output uses top-level `decision`/`reason`, NOT the
    `hookSpecificOutput` envelope used by PreToolUse.
    """
    payload = {
        "decision": "block",
        "reason": BLOCK_REASON.format(matched_phrase=matched_phrase),
    }
    encoded = (json.dumps(payload, ensure_ascii=False) + "\n").encode("utf-8")
    sys.stdout.buffer.write(encoded)
    sys.stdout.buffer.flush()


# --------------------------------------------------------------------------- #
# Transcript fallback.
#
# The Stop payload normally includes `assistant_message`. If a future
# version of Claude Code drops that field (or if our payload-shape
# assumption is wrong), we fall back to reading the last assistant
# entry from `transcript_path` (a JSONL file).
# --------------------------------------------------------------------------- #
def _last_assistant_message_from_transcript(transcript_path: str) -> str:
    p = Path(transcript_path)
    if not p.is_file():
        return ""
    try:
        # Read the last few lines; the last assistant message will be
        # near the end. We read the whole file because JSONL lines can
        # be long and a tail-based approach is fiddlier.
        text = p.read_text(encoding="utf-8")
    except OSError:
        return ""
    last_assistant = ""
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        # Common transcript schemas use 'role' or 'type'; tolerate either.
        role = entry.get("role") or entry.get("type") or ""
        if role == "assistant":
            content = entry.get("content")
            if isinstance(content, list):
                # content array of {type, text} blocks
                parts = []
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "text":
                        parts.append(block.get("text", ""))
                last_assistant = "\n".join(parts)
            elif isinstance(content, str):
                last_assistant = content
    return last_assistant


# --------------------------------------------------------------------------- #
# Entry point.
# --------------------------------------------------------------------------- #
def main() -> int:
    try:
        raw = sys.stdin.read()
        if not raw.strip():
            return 0  # nothing to inspect, fail open
        payload = json.loads(raw)
        if payload.get("hook_event_name") != "Stop":
            return 0  # SubagentStop and others: no-op

        session_id = payload.get("session_id") or "default"
        turn_count = payload.get("turn_count")

        # One-shot guard: if we just blocked, allow this Stop unconditionally.
        if state_lib.was_just_blocked(session_id, turn_count):
            return 0

        # Get the message text, preferring the direct payload field.
        message = payload.get("assistant_message") or ""
        if not message and payload.get("transcript_path"):
            message = _last_assistant_message_from_transcript(
                payload["transcript_path"]
            )
        if not message:
            return 0  # nothing to inspect

        matched = _has_done_claim(message)
        if matched is None:
            return 0  # no done-claim → don't block
        if _has_evidence(message):
            return 0  # claim is supported by evidence → don't block

        # Done-claim without evidence: block once, record the block.
        state_lib.record_stop_block(session_id, turn_count)
        _emit_block(matched)
    except Exception:
        # Failing open: log to stderr but never block by accident.
        sys.stderr.write("[anti-laziness] stop_guard exception:\n")
        sys.stderr.write(traceback.format_exc())
    return 0


if __name__ == "__main__":
    sys.exit(main())
