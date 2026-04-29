"""Tests for hooks/scripts/stop_guard.py.

Covers:
  - Done-claim + no evidence  → BLOCK (rule 06 enforcement)
  - Done-claim + evidence     → ALLOW
  - No done-claim             → ALLOW
  - One-shot guard            → second consecutive Stop allowed
  - Non-Stop event            → no-op
  - Empty payload / missing message → ALLOW (fail open)
  - Malformed stdin           → ALLOW (fail open, log to stderr)
  - Transcript fallback       → reads last assistant message from JSONL
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _helpers import SCRIPTS_DIR, run_hook  # noqa: E402

GUARD = str(SCRIPTS_DIR / "stop_guard.py")


class _StopBase(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = Path(tempfile.mkdtemp(prefix="alaz-stop-"))
        self.env = {"CLAUDE_PLUGIN_DATA": str(self.tmpdir)}
        self.sid = f"test-{uuid.uuid4().hex[:8]}"

    def tearDown(self) -> None:
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _stop(self, message: str, turn_count: int | None = 5,
              transcript_path: str | None = None) -> tuple[int, dict | None, str]:
        payload: dict = {
            "session_id": self.sid,
            "hook_event_name": "Stop",
            "cwd": str(self.tmpdir),
        }
        if message is not None:
            payload["assistant_message"] = message
        if turn_count is not None:
            payload["turn_count"] = turn_count
        if transcript_path is not None:
            payload["transcript_path"] = transcript_path
        return run_hook([GUARD], payload, env_overrides=self.env)


class TestDoneClaimWithoutEvidence(_StopBase):
    def test_chinese_done_claim_without_evidence_is_blocked(self) -> None:
        msg = "我把那个 bug 改好了。后续直接 ship 应该没问题。"
        rc, out, err = self._stop(msg)
        self.assertEqual(rc, 0, msg=err)
        self.assertIsNotNone(out, msg="expected block output")
        self.assertEqual(out["decision"], "block")
        self.assertIn("rule 06", out["reason"])

    def test_english_fixed_without_evidence_is_blocked(self) -> None:
        msg = "Done — that should fix the issue. Fixed."
        rc, out, _ = self._stop(msg)
        self.assertEqual(rc, 0)
        self.assertEqual(out["decision"], "block")

    def test_block_records_last_blocked_turn(self) -> None:
        msg = "已解决，可以 ship。"
        self._stop(msg, turn_count=7)
        # The state file should now record turn 7 as blocked.
        sessions = list((self.tmpdir / "sessions").glob("*.json"))
        self.assertEqual(len(sessions), 1)
        state = json.loads(sessions[0].read_text(encoding="utf-8"))
        self.assertEqual(state.get("last_blocked_turn"), 7)


class TestDoneClaimWithEvidence(_StopBase):
    def test_done_with_command_output_allows(self) -> None:
        msg = (
            "已修复并验证：\n\n"
            "$ pytest tests/\n"
            "Ran 35 tests in 4.5s\n"
            "OK\n\n"
            "重触发原症状: 已通过。"
        )
        rc, out, _ = self._stop(msg)
        self.assertEqual(rc, 0)
        self.assertIsNone(out, msg=f"expected silent allow, got {out!r}")

    def test_done_with_test_count_allows(self) -> None:
        msg = "fixed. 22 passed, 0 failed."
        rc, out, _ = self._stop(msg)
        self.assertIsNone(out)

    def test_done_with_re_triggered_keyword_allows(self) -> None:
        msg = "完成了。重触发原症状后异常消失。"
        rc, out, _ = self._stop(msg)
        self.assertIsNone(out)


class TestNoDoneClaim(_StopBase):
    def test_no_done_claim_allows(self) -> None:
        # Plain analysis with no completion claim.
        msg = "Looking at the code, the issue seems to be in auth.py:142."
        rc, out, _ = self._stop(msg)
        self.assertIsNone(out)

    def test_question_to_user_allows(self) -> None:
        msg = "Should I prefer approach A or B before I implement?"
        rc, out, _ = self._stop(msg)
        self.assertIsNone(out)


class TestOneShotGuard(_StopBase):
    def test_consecutive_stops_allowed_after_block(self) -> None:
        # Turn 5: claim done, no evidence → blocks.
        rc, out, _ = self._stop("已解决", turn_count=5)
        self.assertEqual(out["decision"], "block")
        # Turn 6: still claims done, still no evidence — but we just
        # blocked turn 5, so this should be ALLOWED (one-shot).
        rc, out, _ = self._stop("还是没修好其实，我先停一下", turn_count=6)
        self.assertIsNone(out, msg="one-shot guard must allow turn-after-block")

    def test_grace_window_extends_three_turns(self) -> None:
        self._stop("已解决", turn_count=5)
        # Turn 8 = last_blocked + 3. Still within grace.
        rc, out, _ = self._stop("done", turn_count=8)
        self.assertIsNone(out, msg="turn 8 (within +3 grace) must allow")

    def test_after_grace_blocks_again(self) -> None:
        self._stop("已解决", turn_count=5)
        # Turn 9 = last_blocked + 4. Outside grace window.
        rc, out, _ = self._stop("已解决", turn_count=9)
        self.assertEqual(
            out["decision"], "block",
            msg="after grace expires, fresh blocks should fire",
        )


class TestEventGating(_StopBase):
    def test_subagent_stop_event_is_noop(self) -> None:
        # Event gating: only Stop fires the heuristic. SubagentStop
        # (and any other event) is silently ignored.
        rc, out, _ = run_hook(
            [GUARD],
            {
                "session_id": self.sid,
                "hook_event_name": "SubagentStop",
                "assistant_message": "已解决",
                "turn_count": 5,
            },
            env_overrides=self.env,
        )
        self.assertEqual(rc, 0)
        self.assertIsNone(out)

    def test_pre_tool_use_event_is_noop(self) -> None:
        rc, out, _ = run_hook(
            [GUARD],
            {
                "session_id": self.sid,
                "hook_event_name": "PreToolUse",
                "tool_name": "Edit",
                "tool_input": {"file_path": "x.py"},
            },
            env_overrides=self.env,
        )
        self.assertEqual(rc, 0)
        self.assertIsNone(out)


class TestEmptyPayload(_StopBase):
    def test_missing_assistant_message_no_transcript_allows(self) -> None:
        rc, out, _ = self._stop(message=None, turn_count=1)
        self.assertIsNone(out, msg="empty message must not block")


class TestTranscriptFallback(_StopBase):
    def test_falls_back_to_transcript_when_message_absent(self) -> None:
        # Build a synthetic transcript JSONL with the agent claiming done.
        tpath = self.tmpdir / "transcript.jsonl"
        entries = [
            {"role": "user", "content": "Fix the bug"},
            {
                "role": "assistant",
                "content": [
                    {"type": "text", "text": "已解决，无需进一步处理。"},
                ],
            },
        ]
        tpath.write_text(
            "\n".join(json.dumps(e) for e in entries),
            encoding="utf-8",
        )
        rc, out, _ = self._stop(message="", transcript_path=str(tpath))
        self.assertIsNotNone(out, msg="should block via transcript fallback")
        self.assertEqual(out["decision"], "block")


class TestFailOpen(_StopBase):
    def test_malformed_stdin_does_not_block(self) -> None:
        proc = subprocess.run(
            [sys.executable, GUARD],
            input=b"not json",
            capture_output=True,
            env={**__import__("os").environ, **self.env},
        )
        self.assertEqual(proc.returncode, 0)
        self.assertEqual(proc.stdout.strip(), b"")
        self.assertIn(b"stop_guard exception", proc.stderr)


if __name__ == "__main__":
    unittest.main()
