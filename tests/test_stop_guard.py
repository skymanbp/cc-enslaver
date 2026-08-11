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
  - Layer (h) TL;DR (v0.20)   → done-claim without 大白话 / tldr → BLOCK

Note (v0.20): layer (h) requires every done-claim reply to surface a
plain-language TL;DR marker (`tldr:` / `大白话` / `TL;DR`). Every
"expects allow" fixture below therefore carries a tldr line; without it
the reply would (correctly) block at (h).
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
# because the sys.path bootstrap above must run before this import
from _helpers import SCRIPTS_DIR, run_hook  # noqa: E402

GUARD = str(SCRIPTS_DIR / "stop_guard.py")


class _StopBase(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = Path(tempfile.mkdtemp(prefix="ccens-stop-"))
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


class TestDoneClaimWithEvidenceAndQuiz(_StopBase):
    """v0.7.0 — evidence alone is no longer sufficient. Must also surface
    a rule-06 marker OR >= 2 of the 4 self-questions."""

    def test_done_with_evidence_and_convergence_marker_allows(self) -> None:
        # 重触发 is both an evidence pattern AND a convergence marker.
        # v0.8.0: also needs rule-07 fidelity marker.
        # v0.20: also needs a tldr (layer h).
        msg = (
            "已修复并验证：\n\n"
            "$ pytest tests/\n"
            "Ran 35 tests in 4.5s\n"
            "OK\n\n"
            "重触发原症状: 已通过。\n"
            "任务忠实: 用户原始请求只有'修复 X'，已完成，无降级、无超范围。\n"
            "tldr: 修了 X，测试全过，可直接 ship。"
        )
        rc, out, _ = self._stop(msg)
        self.assertEqual(rc, 0)
        self.assertIsNone(out, msg=f"expected silent allow, got {out!r}")

    def test_done_with_re_triggered_keyword_allows(self) -> None:
        # 重触发 alone is a convergence marker.
        # v0.8.0: also needs rule-07 fidelity marker.
        # v0.20: also needs a tldr (layer h).
        msg = (
            "完成了。重触发原症状后异常消失。无遗漏。\n"
            "tldr: 改完了，异常没了。"
        )
        rc, out, _ = self._stop(msg)
        self.assertIsNone(out)

    def test_evidence_only_without_quiz_or_marker_is_blocked_v07(self) -> None:
        # v0.6.0 would have allowed this; v0.7.0 blocks because no rule-06
        # marker and no self-quiz questions are present.
        msg = "fixed. 22 passed, 0 failed."
        rc, out, _ = self._stop(msg)
        self.assertEqual(rc, 0)
        self.assertIsNotNone(out, msg="v0.7 must block evidence-only completion")
        self.assertEqual(out["decision"], "block")
        self.assertIn("self-quiz", out["reason"])

    def test_done_with_two_self_questions_allows(self) -> None:
        # Agent answered Q1 (真解决) + Q2 (更好方案) → quiz threshold met.
        # v0.8.0: also needs rule-07 fidelity coverage.
        # v0.20: also needs a tldr (layer h).
        msg = (
            "fixed.\n\n"
            "$ pytest -v\nRan 22 tests, 22 passed.\n\n"
            "**真的解决了吗?** Yes — the failing input now returns 200.\n"
            "**有没有更好的方案?** Considered using a thread lock instead, "
            "but the existing async lock is already part of the architecture.\n"
            "Task fidelity: covered all requested items, no degradation.\n"
            "tldr: race fixed via the existing async lock, all green."
        )
        rc, out, _ = self._stop(msg)
        self.assertEqual(rc, 0)
        self.assertIsNone(out, msg="2 of 4 self-questions should pass quiz gate")

    def test_done_with_explicit_rule06_mention_allows(self) -> None:
        # Explicit "rule 06" + evidence is enough (single marker hit).
        # v0.8.0: also needs rule-07 fidelity marker.
        # v0.20: also needs a tldr (layer h).
        msg = (
            "Done.\n$ pytest passed (60/60)\n"
            "Ran rule 06 self-check; all 5 steps verified.\n"
            "Rule 07 task fidelity: covered all requested items, no degradation.\n"
            "tldr: all 60 tests pass, shipped."
        )
        rc, out, _ = self._stop(msg)
        self.assertIsNone(out)


class TestHedgedCompletion(_StopBase):
    """v0.7.0 — hedge near done-claim → block (rule 01 cross-enforcement)."""

    def test_chinese_hedge_then_done_is_blocked(self) -> None:
        msg = "我觉得 bug 修好了。"
        rc, out, _ = self._stop(msg)
        self.assertEqual(rc, 0)
        self.assertIsNotNone(out, msg="hedge-then-done must block")
        self.assertEqual(out["decision"], "block")
        self.assertIn("rule 01", out["reason"])

    def test_english_i_think_fixed_is_blocked(self) -> None:
        msg = "I think it's fixed now."
        rc, out, _ = self._stop(msg)
        self.assertEqual(out["decision"], "block")
        self.assertIn("hedge", out["reason"].lower())

    def test_probably_done_is_blocked(self) -> None:
        msg = "probably done. $ pytest passed (35/35). 重触发: ok"
        # Even with evidence + marker, hedging undermines the claim.
        rc, out, _ = self._stop(msg)
        self.assertEqual(out["decision"], "block")

    def test_done_then_hedge_is_blocked(self) -> None:
        # Reverse order: completion first, hedge after, still within window.
        msg = "已解决，应该是这样。$ pytest passed."
        rc, out, _ = self._stop(msg)
        self.assertEqual(out["decision"], "block")

    def test_hedge_far_from_done_is_allowed(self) -> None:
        # Hedge in unrelated paragraph, far from the done-claim, with proper
        # evidence + quiz markers nearby. Should not trip the proximity check.
        # v0.8.0: also needs rule-07 fidelity marker.
        # v0.20: also needs a tldr (layer h), kept far from the hedge.
        msg = (
            "I think this race condition usually doesn't reproduce — "
            "hard to test in isolation.\n\n"
            "But anyway, $ pytest passed (35/35), 重触发原症状 confirms "
            "the lock fixes the race, **真解决** confirmed via the new "
            "concurrent test, and the existing tests still pass. "
            "Task fidelity: covered all requested items. fixed.\n"
            "tldr: lock fixes the race, all tests pass."
        )
        rc, out, _ = self._stop(msg)
        # The hedge "I think" is more than 50 chars away from "fixed".
        # Should pass.
        self.assertIsNone(out, msg=f"distant hedge should not block, got {out!r}")


class TestFidelityLayer(_StopBase):
    """v0.8.0 — rule 07 task-fidelity Stop-hook layer (Layer d).

    Layer (d) fires only after (a)(b)(c) all pass. It checks that the
    agent surfaced a rule-07 fidelity marker OR answered >=2 of the 3
    fidelity self-questions (coverage / standard / fidelity).
    """

    def test_passes_a_b_c_but_no_fidelity_marker_or_quiz_blocks(self) -> None:
        # Done + evidence + rule-06 marker (`重触发`) BUT no fidelity
        # marker and no fidelity quiz answers → must block with rule-07
        # reason.
        msg = (
            "已修复。\n\n"
            "$ pytest tests/\nRan 35 tests in 4.5s\nOK\n\n"
            "重触发原症状: 已通过。"
        )
        rc, out, _ = self._stop(msg)
        self.assertEqual(rc, 0)
        self.assertIsNotNone(out, msg="Layer (d) must block when fidelity absent")
        self.assertEqual(out["decision"], "block")
        self.assertIn("rule 07", out["reason"])

    def test_explicit_rule07_marker_passes(self) -> None:
        # Single 'rule 07' mention is enough.
        # v0.20: also needs a tldr (layer h).
        msg = (
            "Fixed.\n$ pytest passed.\n重触发: ok.\n"
            "rule 07: covered all sub-items, no scope creep.\n"
            "tldr: all sub-items done, nothing extra."
        )
        rc, out, _ = self._stop(msg)
        self.assertIsNone(out, msg=f"single rule-07 marker must pass, got {out!r}")

    def test_chinese_task_fidelity_marker_passes(self) -> None:
        # v0.20: also needs a tldr (layer h).
        msg = (
            "已解决。\n$ pytest passed (35/35).\n重触发原症状: ok.\n"
            "任务忠实自答: 用户原始请求只有'修 X'一项，已完成。\n"
            "tldr: 修了 X，没别的。"
        )
        rc, out, _ = self._stop(msg)
        self.assertIsNone(out)

    def test_no_degradation_english_passes(self) -> None:
        # v0.20: also needs a tldr (layer h).
        msg = (
            "Done.\n$ pytest passed.\nRan rule 06 self-check.\n"
            "Reviewed against the original request: no degradation, "
            "no omission, no scope creep.\n"
            "tldr: did exactly what was asked, nothing degraded."
        )
        rc, out, _ = self._stop(msg)
        self.assertIsNone(out)

    def test_two_fidelity_questions_pass(self) -> None:
        # Coverage Q + standard Q answered → 2 of 3 quiz threshold met.
        # v0.20: also needs a tldr (layer h).
        msg = (
            "Fixed.\n\n"
            "$ pytest -v\nRan 22 tests, 22 passed.\n\n"
            "重触发: ok。\n\n"
            "**覆盖性**: 用户原始请求拆成两项 (修 X / 加测试)，均完成。\n"
            "**标准性**: 用户用了'强制'一词，已落实为钩子拦截 (file:line)，"
            "不是文档建议。\n"
            "tldr: 两项都做了，'强制'落地为硬钩子。"
        )
        rc, out, _ = self._stop(msg)
        self.assertIsNone(out, msg="2 of 3 fidelity questions should pass Layer (d)")

    def test_no_fidelity_signal_at_all_with_full_06_blocks(self) -> None:
        # Even a thoroughly answered rule-06 self-quiz is not enough;
        # rule-07 axis is independent and must surface.
        msg = (
            "fixed.\n\n"
            "$ pytest -v\nRan 22 tests, 22 passed.\n\n"
            "**真的解决了吗?** Yes — the failing input now returns 200.\n"
            "**有没有更好的方案?** Considered async lock, picked sync.\n"
            "**哪些没验?** None — full path covered.\n"
            "**验证合理?** Yes, exercises the original failure mechanism."
        )
        rc, out, _ = self._stop(msg)
        self.assertIsNotNone(out, msg="rule-06 self-quiz alone must not pass Layer (d)")
        self.assertEqual(out["decision"], "block")
        self.assertIn("rule 07", out["reason"])

    def test_checklist_emoji_form_passes(self) -> None:
        # The agent enumerated original-request items with ✅ check
        # marks — that's the per-item form rule 07 endorses.
        # v0.20: also needs a tldr (layer h).
        msg = (
            "完成了。\n$ pytest passed.\n重触发: ok.\n\n"
            "原始请求逐项核对:\n"
            "- ✅ 完成: 修复 X (auth.py:42)\n"
            "- ✅ 完成: 加测试 (test_auth.py)\n"
            "tldr: 两项都打勾完成。"
        )
        rc, out, _ = self._stop(msg)
        self.assertIsNone(out, msg=f"emoji checklist should pass, got {out!r}")


class TestRule08Layer(_StopBase):
    """v0.11 — Layer (e) rule 08 (read-before-edit / think-before-write).

    Layer (e) fires **only on edit turns** (state.last_edit_turn ==
    turn_count). On non-edit turns it silently allows.

    Pass condition (either):
      (1) any explicit rule-08 marker, OR
      (2) at least 3 of the six rule-02 keywords.
    """

    def _seed_edit_turn(self, turn_count: int) -> None:
        """Plant `last_edit_turn = turn_count` in this session's state
        file so the Stop hook sees this as an edit turn."""
        sessions = self.tmpdir / "sessions"
        sessions.mkdir(parents=True, exist_ok=True)
        state_path = sessions / f"{self.sid}.json"
        state_path.write_text(
            json.dumps({
                "session_id": self.sid,
                "read_files": [],
                "last_edit_turn": turn_count,
            }),
            encoding="utf-8",
        )

    def test_non_edit_turn_passes_silently(self) -> None:
        # No edit this turn — layer (e) MUST silently allow even if the
        # message would otherwise lack rule-08 markers. Message includes
        # rule 06 + 07 markers so it survives layers (a-d).
        # v0.20: also needs a tldr (layer h, which is NOT edit-gated).
        msg = (
            "已修复并验证。\n"
            "$ pytest passed (35/35).\n"
            "重触发原症状: 已通过。\n"
            "任务忠实: 用户原始请求只有一项，已完成，无降级、无超范围。\n"
            "tldr: 一项需求修完了。"
        )
        rc, out, _ = self._stop(msg, turn_count=5)
        self.assertIsNone(
            out,
            msg=f"non-edit turn must not trigger layer (e), got {out!r}",
        )

    def test_edit_turn_without_rule08_marker_blocks(self) -> None:
        # Plant an edit turn. Message passes (a-d) but contains NO
        # rule-08 markers and fewer than 3 of 6 rule-02 keywords. Must
        # block with rule-08 reason.
        self._seed_edit_turn(turn_count=5)
        msg = (
            "已修复。\n"
            "$ pytest passed (35/35).\n"
            "重触发原症状: 已通过。\n"
            "rule 07: 用户原始请求 1 项，无降级、无超范围。"
        )
        rc, out, _ = self._stop(msg, turn_count=5)
        self.assertIsNotNone(out, msg="edit turn without rule-08 marker must block")
        self.assertEqual(out["decision"], "block")
        self.assertIn("rule 08", out["reason"])

    def test_edit_turn_with_explicit_rule08_marker_passes(self) -> None:
        # v0.20: also needs a tldr (layer h).
        self._seed_edit_turn(turn_count=5)
        msg = (
            "已修复。\n"
            "$ pytest passed (35/35).\n"
            "重触发原症状: 已通过。\n"
            "rule 07: 无降级、无遗漏。\n"
            "rule 08: 改前必读 (auth.py 第 3 次工具调用 Read 完整) + 写前必想 "
            "(根因 / 影响 / 方案 三件套见下).\n"
            "rule 09: 根因 = 缺锁 (auth.py:142); 影响 = routes/login.py:88 调用链; "
            "方案 = 复用 session._pending_lock。\n"
            "tldr: 缺锁导致的并发 bug，复用现有锁修好了。"
        )
        rc, out, _ = self._stop(msg, turn_count=5)
        self.assertIsNone(out, msg=f"explicit rule-08 marker must pass, got {out!r}")

    def test_edit_turn_with_three_rule02_keywords_passes(self) -> None:
        # 3 of 6 rule-02 keywords: 架构 + 根源 + 方案. Plus rule 09
        # triplet (because layer (f) also checks).
        # v0.20: also needs a tldr (layer h).
        self._seed_edit_turn(turn_count=5)
        msg = (
            "已修复。\n"
            "$ pytest passed (35/35).\n"
            "重触发原症状: 已通过。\n"
            "rule 07: 无降级。\n"
            "**架构定位**: auth.py 是登录链路第 3 步; "
            "**根源**: auth.py:142 缺锁; "
            "**方案**: 复用 session._pending_lock (覆盖 connected impact)。\n"
            "tldr: 登录链路缺锁，复用现有锁修复。"
        )
        rc, out, _ = self._stop(msg, turn_count=5)
        self.assertIsNone(
            out,
            msg=f"3 rule-02 keywords + rule-09 triplet must pass, got {out!r}",
        )

    def test_edit_turn_with_only_two_rule02_keywords_blocks_at_e(self) -> None:
        # 2 of 6 rule-02 keywords (root cause + solution but not the
        # third) → fewer than threshold → layer (e) blocks.
        self._seed_edit_turn(turn_count=5)
        msg = (
            "已修复。\n"
            "$ pytest passed (35/35).\n"
            "重触发原症状: 已通过。\n"
            "rule 07: 无降级。\n"
            "**根源**: 缺锁; **方案**: 加锁。"
        )
        rc, out, _ = self._stop(msg, turn_count=5)
        self.assertIsNotNone(out, msg="2 keywords < threshold must block")
        self.assertEqual(out["decision"], "block")
        self.assertIn("rule 08", out["reason"])


class TestRule09Layer(_StopBase):
    """v0.11 — Layer (f) rule 09 (systematic modification, no patch-style).

    Layer (f) fires **only on edit turns** AND only after (a)-(e) pass.
    Pass condition (either):
      (1) any explicit rule-09 marker, OR
      (2) ALL THREE of the triplet keywords (root-cause + impact +
          solution).
    """

    def _seed_edit_turn(self, turn_count: int) -> None:
        sessions = self.tmpdir / "sessions"
        sessions.mkdir(parents=True, exist_ok=True)
        state_path = sessions / f"{self.sid}.json"
        state_path.write_text(
            json.dumps({
                "session_id": self.sid,
                "read_files": [],
                "last_edit_turn": turn_count,
            }),
            encoding="utf-8",
        )

    def test_edit_turn_passes_e_but_lacks_rule09_triplet_blocks(self) -> None:
        # Passes (a-e) with rule-08 marker but never names rule-09 / no
        # complete triplet (only root cause present, missing impact +
        # solution at the triplet level).
        self._seed_edit_turn(turn_count=5)
        msg = (
            "已修复。\n"
            "$ pytest passed (35/35).\n"
            "重触发原症状: 已通过。\n"
            "rule 07: 无降级、无遗漏。\n"
            "rule 08: 改前必读 + 写前必想 (架构 / 职责 / 风险 三件套)。"
        )
        rc, out, _ = self._stop(msg, turn_count=5)
        self.assertIsNotNone(out, msg="edit turn without rule-09 triplet must block")
        self.assertEqual(out["decision"], "block")
        self.assertIn("rule 09", out["reason"])

    def test_edit_turn_with_explicit_rule09_marker_passes(self) -> None:
        # v0.20: also needs a tldr (layer h).
        self._seed_edit_turn(turn_count=5)
        msg = (
            "已修复。\n"
            "$ pytest passed (35/35).\n"
            "重触发原症状: 已通过。\n"
            "rule 07: 无降级。\n"
            "rule 08: 改前必读完毕。\n"
            "rule 09: 系统式修改完成。\n"
            "tldr: 系统式改完，测试全过。"
        )
        rc, out, _ = self._stop(msg, turn_count=5)
        self.assertIsNone(
            out,
            msg=f"explicit rule-09 marker must pass, got {out!r}",
        )

    def test_edit_turn_with_complete_triplet_passes(self) -> None:
        # All three triplet axes present without explicit rule 09 marker.
        # Also has rule 08 markers so layer (e) passes.
        # v0.20: also needs a tldr (layer h).
        self._seed_edit_turn(turn_count=5)
        msg = (
            "已修复。\n"
            "$ pytest passed (35/35).\n"
            "重触发原症状: 已通过。\n"
            "rule 07: 无降级。\n"
            "rule 08: 改前必读完毕。\n"
            "**根源**: auth.py:142 缺锁。\n"
            "**影响范围**: routes/login.py:88, tests/test_auth.py:55。\n"
            "**方案**: 复用 session._pending_lock（与方案 B 锁全表对比，A 更轻量）。\n"
            "tldr: 缺锁的并发 bug，复用轻量锁修复。"
        )
        rc, out, _ = self._stop(msg, turn_count=5)
        self.assertIsNone(
            out,
            msg=f"complete rule-09 triplet must pass, got {out!r}",
        )

    def test_edit_turn_with_only_two_triplet_axes_blocks(self) -> None:
        # 根源 + 方案 but no 影响/impact → triplet incomplete → block.
        # rule 08 satisfied so (e) passes.
        self._seed_edit_turn(turn_count=5)
        msg = (
            "已修复。\n"
            "$ pytest passed (35/35).\n"
            "重触发原症状: 已通过。\n"
            "rule 07: 无降级。\n"
            "rule 08: 改前必读完毕。\n"
            "**根源**: 缺锁。\n"
            "**方案**: 加锁。"
        )
        rc, out, _ = self._stop(msg, turn_count=5)
        self.assertIsNotNone(out)
        self.assertEqual(out["decision"], "block")
        self.assertIn("rule 09", out["reason"])

    def test_non_edit_turn_silently_passes_f(self) -> None:
        # No edit this turn — layer (f) must not fire even with no
        # rule-09 marker / no triplet.
        # v0.20: also needs a tldr (layer h, which is NOT edit-gated).
        msg = (
            "已修复。\n"
            "$ pytest passed (35/35).\n"
            "重触发原症状: 已通过。\n"
            "rule 07: 无降级、无遗漏。\n"
            "tldr: 修好了。"
        )
        rc, out, _ = self._stop(msg, turn_count=5)
        self.assertIsNone(out)


class TestRule10FileClaimVerification(_StopBase):
    """v0.16 — Layer (g) file-claim verification.

    The agent's done-claim message is parsed for "I edited X" / "我修改了 X"
    style claims; each claimed path is verified against the baseline
    captured by read_guard. Definitively contradicted claims → BLOCK.

    Pass conditions for layer (g):
      - no file claims in the message → pass silently
      - file claim but no baseline for that file → pass (can't verify)
      - file claim AND baseline AND on-disk state shows actual change →
        pass (claim is true)
      - CC_ENSLAVER_DISABLE_LAYER_G is set → pass (escape hatch)

    Fail (BLOCK) condition:
      - file claim with verb "edited" / "modified" AND baseline mtime
        exists AND current mtime == baseline mtime, OR
      - file claim with verb "created" AND baseline showed file didn't
        exist AND file still doesn't exist.

    v0.20: `_full_compliance_message()` now carries a tldr so the
    pass-case tests reach (g)/allow rather than tripping layer (h). The
    block-case tests still block at (g), which precedes (h).
    """

    def _seed_edit_turn_and_baseline(
        self, turn_count: int, baselines: dict[str, float | None],
    ) -> None:
        """Plant `last_edit_turn` + `baseline_mtimes` in the session state.

        baselines is {abs_path: mtime_or_None}.
        """
        import os
        sessions = self.tmpdir / "sessions"
        sessions.mkdir(parents=True, exist_ok=True)
        state_path = sessions / f"{self.sid}.json"
        # normalize_path for the JSON keys (must match what read_guard
        # would write).
        normalised = {
            os.path.normcase(os.path.realpath(p)): v for p, v in baselines.items()
        }
        state_path.write_text(
            json.dumps({
                "session_id": self.sid,
                "read_files": list(normalised.keys()),
                "last_edit_turn": turn_count,
                "baseline_mtimes": normalised,
            }),
            encoding="utf-8",
        )

    def _writable(self, name: str, content: str = "# initial\n") -> str:
        f = self.tmpdir / name
        f.write_text(content, encoding="utf-8")
        return str(f)

    def _full_compliance_message(self) -> str:
        """A message that passes layers (a)-(f) AND (h) so we test only (g)."""
        return (
            "已修复。\n$ pytest passed (35/35).\n"
            "重触发原症状: 已通过。\n"
            "rule 07: 无降级。\n"
            "rule 08: 改前必读完毕。\n"
            "rule 09: 系统式修改完成。\n"
            "tldr: 改完了，测试全过。"
        )

    def test_no_claim_passes_silently(self) -> None:
        # All earlier-layer markers present but no "I edited X" claim.
        self._seed_edit_turn_and_baseline(5, {})
        rc, out, _ = self._stop(self._full_compliance_message(), turn_count=5)
        self.assertIsNone(out, msg=f"no claim should pass, got {out!r}")

    def test_unverifiable_claim_passes(self) -> None:
        # Claim about a file we never tracked → can't verify → pass.
        self._seed_edit_turn_and_baseline(5, {})  # no baselines
        msg = self._full_compliance_message() + "\nI edited unknown.py."
        rc, out, _ = self._stop(msg, turn_count=5)
        self.assertIsNone(out, msg=f"unverifiable should pass, got {out!r}")

    def test_edit_claim_with_unchanged_mtime_blocks(self) -> None:
        # Baseline says file existed with mtime M; current mtime is M;
        # claim says "I edited X" → contradicted → block.
        import os
        target = self._writable("x.py")
        baseline_mtime = os.path.getmtime(target)
        self._seed_edit_turn_and_baseline(5, {target: baseline_mtime})
        msg = self._full_compliance_message() + f"\nI edited {target}."
        rc, out, _ = self._stop(msg, turn_count=5)
        self.assertIsNotNone(out, msg="contradicted edit claim must block")
        self.assertEqual(out["decision"], "block")
        self.assertIn("rule 01", out["reason"])
        self.assertIn("file-claim", out["reason"])

    def test_edit_claim_with_changed_mtime_passes(self) -> None:
        # Baseline mtime != current mtime → claim verified → pass.
        target = self._writable("x.py")
        old_mtime = 0.0  # forced "different from current"
        self._seed_edit_turn_and_baseline(5, {target: old_mtime})
        msg = self._full_compliance_message() + f"\nI edited {target}."
        rc, out, _ = self._stop(msg, turn_count=5)
        self.assertIsNone(out, msg=f"changed mtime should pass, got {out!r}")

    def test_create_claim_when_file_missing_blocks(self) -> None:
        # Baseline says file didn't exist; file still doesn't exist;
        # claim says "I created Y" → contradicted → block.
        missing_target = str(self.tmpdir / "never_created.py")
        self._seed_edit_turn_and_baseline(5, {missing_target: None})
        msg = self._full_compliance_message() + f"\nI created {missing_target}."
        rc, out, _ = self._stop(msg, turn_count=5)
        self.assertIsNotNone(out, msg="phantom create must block")
        self.assertEqual(out["decision"], "block")
        self.assertIn("rule 01", out["reason"])

    def test_create_claim_when_file_exists_passes(self) -> None:
        # Baseline = None (file didn't exist), current = exists → pass.
        target = self._writable("created.py")
        self._seed_edit_turn_and_baseline(5, {target: None})
        msg = self._full_compliance_message() + f"\nI created {target}."
        rc, out, _ = self._stop(msg, turn_count=5)
        self.assertIsNone(out, msg=f"verified create should pass, got {out!r}")

    def test_chinese_claim_extraction_blocks(self) -> None:
        import os
        target = self._writable("y.py")
        baseline_mtime = os.path.getmtime(target)
        self._seed_edit_turn_and_baseline(5, {target: baseline_mtime})
        msg = self._full_compliance_message() + f"\n我修改了 `{target}`。"
        rc, out, _ = self._stop(msg, turn_count=5)
        self.assertIsNotNone(out, msg="Chinese claim must be parsed and blocked")
        self.assertEqual(out["decision"], "block")

    def test_negated_claim_does_not_extract(self) -> None:
        # "I did not edit X" / "没修改 X" — negation guard must filter.
        import os
        target = self._writable("z.py")
        baseline_mtime = os.path.getmtime(target)
        self._seed_edit_turn_and_baseline(5, {target: baseline_mtime})
        msg = self._full_compliance_message() + f"\nI did not edit {target}."
        rc, out, _ = self._stop(msg, turn_count=5)
        self.assertIsNone(out, msg=f"negated claim must not block, got {out!r}")

    def test_no_extension_in_path_not_extracted(self) -> None:
        # "I edited the project" — no extension, not a file claim.
        self._seed_edit_turn_and_baseline(5, {})
        msg = self._full_compliance_message() + "\nI edited the project structure."
        rc, out, _ = self._stop(msg, turn_count=5)
        self.assertIsNone(out)

    def test_escape_hatch_disables_layer(self) -> None:
        # Set CC_ENSLAVER_DISABLE_LAYER_G; even a contradicted claim
        # should pass.
        import os
        target = self._writable("x.py")
        baseline_mtime = os.path.getmtime(target)
        self._seed_edit_turn_and_baseline(5, {target: baseline_mtime})
        msg = self._full_compliance_message() + f"\nI edited {target}."
        env = {**self.env, "CC_ENSLAVER_DISABLE_LAYER_G": "1"}
        rc, out, _ = run_hook(
            [GUARD],
            {
                "session_id": self.sid,
                "hook_event_name": "Stop",
                "cwd": str(self.tmpdir),
                "turn_count": 5,
                "assistant_message": msg,
            },
            env_overrides=env,
        )
        self.assertIsNone(out, msg=f"escape hatch must disable layer, got {out!r}")

    def test_non_edit_turn_does_not_fire_g(self) -> None:
        # No edit turn seeded → layer (g) must not fire (n/a).
        msg = (
            self._full_compliance_message() + "\nI edited /nonexistent/x.py."
        )
        rc, out, _ = self._stop(msg, turn_count=5)
        self.assertIsNone(out, msg=f"non-edit turn must not trip (g), got {out!r}")


class TestTildePathClaimRegression(unittest.TestCase):
    """v0.21.1 — 8.3 short-name (tilde) paths must extract as file claims.

    Every user-home path in this class is an example / fixture: the path
    SHAPE is the subject under test, and nothing depends on a real layout.

    Root cause of the pre-existing windows-latest CI red: the GitHub
    Windows runner's TEMP is a DOS 8.3 short path whose user segment
    carries a tilde — an example only:
    C:\\Users\\RUNNER~1\\AppData\\Local\\Temp\\... — and the
    _PATH_TOKEN character class did not include the tilde, so any claim
    whose path contained one produced ZERO extractions. Layer (g) then
    silently no-op'd, so the three TestRule10 block-cases returned None
    (no block) and failed — but only on the runner. Developer machines
    with a tilde-free temp (an example only:
    C:\\Users\\skyma\\...) extracted fine and
    passed, masking the bug.

    These call _extract_file_claims directly with a hardcoded tilde path
    so the regression reproduces deterministically on ANY machine,
    independent of what the local TEMP happens to be.
    """

    def _claims(self, message):
        sys.path.insert(0, str(SCRIPTS_DIR))
        import stop_guard
        return stop_guard._extract_file_claims(message)

    def test_tilde_english_edit_claim_extracts(self) -> None:
        claims = self._claims(
            # fixture: the tilde path shape IS the subject under test
            r"I edited C:\Users\RUNNER~1\AppData\Local\Temp\t\x.py."
        )
        self.assertTrue(
            claims, "8.3 short-name (tilde) path must extract — GH runner temp",
        )
        verb, path, ctype = claims[0]
        self.assertIn("~", path, "the tilde must be preserved in the path")
        self.assertTrue(path.endswith("x.py"))
        self.assertEqual(ctype, "edit")

    def test_tilde_create_claim_extracts(self) -> None:
        claims = self._claims(
            # fixture: the tilde path shape IS the subject under test
            r"I created C:\Users\RUNNER~1\AppData\Local\Temp\t\new.py."
        )
        self.assertTrue(claims, "tilde create claim must extract")
        self.assertEqual(claims[0][2], "create")

    def test_tilde_chinese_edit_claim_extracts(self) -> None:
        # fixture: the tilde path shape IS the subject under test
        claims = self._claims("我修改了 `C:\\Users\\RUNNER~1\\Temp\\y.py`。")
        self.assertTrue(claims, "tilde path (zh) must extract")
        self.assertIn("~", claims[0][1])

    def test_non_tilde_path_still_extracts(self) -> None:
        # Guard against over-narrowing: ordinary paths keep working.
        # fixture: an example of the ordinary tilde-free user-home shape,
        # spelled out because the SHAPE is exactly what is under test here
        claims = self._claims(r"I edited C:\Users\skyma\Temp\t\x.py.")
        self.assertTrue(claims)
        self.assertNotIn("~", claims[0][1])


class TestTldrLayerH(_StopBase):
    """v0.20 — Layer (h): plain-language TL;DR (大白话) closing requirement.

    Fires on EVERY done-claim turn (edit or not), as the final gate after
    all discipline checks pass. The reply must surface a tldr / 大白话 /
    TL;DR marker, else block. Replies with no done-claim are untouched.
    """

    def _seed_edit_turn(self, turn_count: int) -> None:
        sessions = self.tmpdir / "sessions"
        sessions.mkdir(parents=True, exist_ok=True)
        (sessions / f"{self.sid}.json").write_text(
            json.dumps({
                "session_id": self.sid,
                "read_files": [],
                "last_edit_turn": turn_count,
            }),
            encoding="utf-8",
        )

    def _compliant_non_edit(self) -> str:
        # Passes layers (a)-(d) on a non-edit turn; (e)(f)(g) are n/a.
        return (
            "已修复并验证。\n$ pytest passed (35/35).\n"
            "重触发原症状: 已通过。\n"
            "任务忠实: 用户原始请求一项，已完成，无降级、无遗漏。"
        )

    def test_done_compliant_but_no_tldr_blocks(self) -> None:
        rc, out, _ = self._stop(self._compliant_non_edit(), turn_count=5)
        self.assertIsNotNone(out, msg="missing tldr must block at (h)")
        self.assertEqual(out["decision"], "block")
        self.assertIn("(h)", out["reason"])
        self.assertIn("tldr", out["reason"].lower())

    def test_done_with_tldr_field_allows(self) -> None:
        msg = self._compliant_non_edit() + '\ntldr: "修了 X，全绿，可 ship。"'
        rc, out, _ = self._stop(msg, turn_count=5)
        self.assertIsNone(out, msg=f"tldr field must pass (h), got {out!r}")

    def test_dabaihua_marker_allows(self) -> None:
        msg = self._compliant_non_edit() + "\n大白话: 修了 X，可以 ship。"
        rc, out, _ = self._stop(msg, turn_count=5)
        self.assertIsNone(out, msg=f"大白话 marker must pass (h), got {out!r}")

    def test_tldr_caps_marker_allows(self) -> None:
        msg = self._compliant_non_edit() + "\nTL;DR: fixed X, all green."
        rc, out, _ = self._stop(msg, turn_count=5)
        self.assertIsNone(out, msg=f"TL;DR marker must pass (h), got {out!r}")

    def test_non_edit_turn_still_requires_tldr(self) -> None:
        # Explicit contrast with (e)(f)(g): layer (h) is NOT edit-gated.
        rc, out, _ = self._stop(self._compliant_non_edit(), turn_count=5)
        self.assertIsNotNone(out, msg="(h) must fire even on a non-edit turn")
        self.assertIn("FAILED at Layer (h)", out["reason"])

    def test_no_done_claim_does_not_require_tldr(self) -> None:
        # No done-claim → the whole hook is a no-op, so (h) never fires.
        msg = "Looking at auth.py:142, the lock is missing — needs a fix."
        rc, out, _ = self._stop(msg, turn_count=5)
        self.assertIsNone(out, msg="no done-claim → (h) must not fire")

    def test_block_reason_carries_plain_language_line(self) -> None:
        # cc-enslaver's OWN block output also ends with a 大白话 line.
        rc, out, _ = self._stop(self._compliant_non_edit(), turn_count=5)
        self.assertIn("大白话:", out["reason"])

    def test_edit_turn_missing_tldr_blocks_at_h(self) -> None:
        # Full a-g compliance on an edit turn, but no tldr → (h) blocks.
        self._seed_edit_turn(5)
        msg = (
            "已修复。\n$ pytest passed (35/35).\n"
            "重触发原症状: 已通过。\n"
            "rule 07: 无降级。\n"
            "rule 08: 改前必读完毕。\n"
            "rule 09: 系统式修改完成。"
        )
        rc, out, _ = self._stop(msg, turn_count=5)
        self.assertIsNotNone(out, msg="edit turn missing tldr must block at (h)")
        self.assertIn("FAILED at Layer (h)", out["reason"])


class TestTldrLengthLayerH(_StopBase):
    """v0.23 — layer (h) part 2: each tldr item must stay within
    TLDR_MAX_ITEM_CHARS (160). Presence alone no longer suffices; a
    paragraph-length "tldr" blocks with a dedicated overlong recovery.
    Multiple items are fine when each line stays within the cap.
    """

    def _compliant_non_edit(self) -> str:
        return (
            "已修复并验证。\n$ pytest passed (35/35).\n"
            "重触发原症状: 已通过。\n"
            "任务忠实: 用户原始请求一项，已完成，无降级、无遗漏。"
        )

    def test_overlong_single_line_tldr_blocks(self) -> None:
        msg = self._compliant_non_edit() + "\ntldr: " + "改" * 200
        rc, out, _ = self._stop(msg, turn_count=5)
        self.assertIsNotNone(out, msg="200-char tldr item must block at (h)")
        self.assertEqual(out["decision"], "block")
        self.assertIn("FAILED at Layer (h)", out["reason"])
        self.assertIn("overlong", out["reason"])

    def test_tldr_within_cap_allows(self) -> None:
        msg = self._compliant_non_edit() + "\ntldr: " + "x" * 150
        rc, out, _ = self._stop(msg, turn_count=5)
        self.assertIsNone(out, msg=f"150-char tldr must pass, got {out!r}")

    def test_tldr_exactly_at_cap_allows(self) -> None:
        # Boundary: len == 160 is allowed; only len > 160 blocks.
        msg = self._compliant_non_edit() + "\ntldr: " + "y" * 160
        rc, out, _ = self._stop(msg, turn_count=5)
        self.assertIsNone(out, msg=f"exactly-160-char tldr must pass, got {out!r}")

    def test_multi_item_list_all_short_allows(self) -> None:
        msg = (
            self._compliant_non_edit()
            + "\ntldr:\n"
            + '  - "修了 X：根因是缺锁，现在测试全绿。"\n'
            + '  - "顺带同步了 B 的引用，无行为变化。"'
        )
        rc, out, _ = self._stop(msg, turn_count=5)
        self.assertIsNone(out, msg=f"short multi-item tldr must pass, got {out!r}")

    def test_multi_item_with_one_long_item_blocks(self) -> None:
        msg = (
            self._compliant_non_edit()
            + "\ntldr:\n"
            + '  - "短的一条，没问题。"\n'
            + '  - "' + "长" * 200 + '"'
        )
        rc, out, _ = self._stop(msg, turn_count=5)
        self.assertIsNotNone(out, msg="one overlong item in a list must block")
        self.assertIn("overlong", out["reason"])

    def test_dabaihua_overlong_line_blocks(self) -> None:
        # The natural 大白话 marker is measured the same way.
        msg = self._compliant_non_edit() + "\n大白话: " + "话" * 200
        rc, out, _ = self._stop(msg, turn_count=5)
        self.assertIsNotNone(out, msg="overlong 大白话 line must block at (h)")
        self.assertIn("FAILED at Layer (h)", out["reason"])

    def test_overlong_block_reason_names_the_cap(self) -> None:
        msg = self._compliant_non_edit() + "\ntldr: " + "z" * 300
        rc, out, _ = self._stop(msg, turn_count=5)
        self.assertIn("160", out["reason"])

    # -- v0.23.1 extraction hardening (adversarial-review findings) ------- #

    def test_heading_form_overlong_paragraph_blocks(self) -> None:
        # `## TL;DR` + a 400-char paragraph line — the colon-less heading
        # form must be measured, not silently skipped.
        msg = self._compliant_non_edit() + "\n## TL;DR\n\n" + "内" * 200
        rc, out, _ = self._stop(msg, turn_count=5)
        self.assertIsNotNone(out, msg="overlong `## TL;DR` paragraph must block")
        self.assertIn("overlong", out["reason"])

    def test_bold_marker_form_overlong_blocks(self) -> None:
        # `**tldr:** <long>` — the emphasised markdown-label form.
        msg = self._compliant_non_edit() + "\n**tldr:** " + "w" * 300
        rc, out, _ = self._stop(msg, turn_count=5)
        self.assertIsNotNone(out, msg="overlong **tldr:** form must block")
        self.assertIn("overlong", out["reason"])

    def test_same_indent_yaml_list_is_measured(self) -> None:
        # Legal YAML block sequence: `tldr:` + same-column `- ` items.
        msg = (
            self._compliant_non_edit()
            + "\ntldr:\n"
            + '- "短的一条。"\n'
            + '- "' + "长" * 200 + '"'
        )
        rc, out, _ = self._stop(msg, turn_count=5)
        self.assertIsNotNone(out, msg="same-indent YAML list items must be measured")
        self.assertIn("overlong", out["reason"])

    def test_canonical_yaml_fence_is_still_measured(self) -> None:
        # The canonical reply schema lives in a ```yaml fence — the fence
        # skip must NOT exempt it.
        msg = (
            self._compliant_non_edit()
            + "\n```yaml\ncc-enslaver:\n  tldr: \"" + "超" * 200 + "\"\n```"
        )
        rc, out, _ = self._stop(msg, turn_count=5)
        self.assertIsNotNone(out, msg="overlong tldr inside ```yaml must block")
        self.assertIn("overlong", out["reason"])

    def test_non_yaml_fence_fixture_is_not_measured(self) -> None:
        # A quoted fixture in a bare fence is someone else's tldr — the
        # reply's own short tldr should pass.
        msg = (
            self._compliant_non_edit()
            + "\n反面例子：\n```\ntldr: " + "坏" * 200 + "\n```\n"
            + "tldr: 修好了，测试全绿。"
        )
        rc, out, _ = self._stop(msg, turn_count=5)
        self.assertIsNone(out, msg=f"fenced fixture must not be measured, got {out!r}")

    def test_blockquoted_tldr_is_not_measured(self) -> None:
        # Quoting a user's overlong line as evidence must not self-trip.
        msg = (
            self._compliant_non_edit()
            + "\n> tldr: " + "引" * 200 + "\n"
            + "tldr: 修好了，测试全绿。"
        )
        rc, out, _ = self._stop(msg, turn_count=5)
        self.assertIsNone(out, msg=f"blockquoted tldr must not be measured, got {out!r}")

    def test_heading_with_colon_paragraph_is_measured(self) -> None:
        # `## TL;DR:` (value-less heading marker WITH a colon) — the
        # following paragraph is the content and must be measured; an
        # indent-based continuation scan alone would never collect it.
        msg = self._compliant_non_edit() + "\n## TL;DR:\n\n" + "容" * 200
        rc, out, _ = self._stop(msg, turn_count=5)
        self.assertIsNotNone(out, msg="overlong `## TL;DR:` paragraph must block")
        self.assertIn("overlong", out["reason"])

    def test_tilde_line_inside_backtick_fence_does_not_toggle(self) -> None:
        # A `~~~` line INSIDE a ``` fence is content, not a fence close.
        # Before the fence-marker pairing fix this flipped the state and
        # the fixture tldr got measured → false-positive block.
        msg = (
            self._compliant_non_edit()
            + "\n```text\n~~~ some inner line\ntldr: " + "假" * 200 + "\n```\n"
            + "tldr: 修好了，测试全绿。"
        )
        rc, out, _ = self._stop(msg, turn_count=5)
        self.assertIsNone(
            out, msg=f"mixed fence markers must not mis-toggle, got {out!r}",
        )

    def test_nested_list_under_short_dabaihua_is_not_swallowed(self) -> None:
        # A nested markdown list under a short, compliant 大白话 bullet is
        # detail, not more tldr — must not be measured as an item.
        msg = (
            self._compliant_non_edit()
            + "\n- 大白话: 修好了，一句话说清。\n"
            + "  - " + "细" * 200
        )
        rc, out, _ = self._stop(msg, turn_count=5)
        self.assertIsNone(
            out, msg=f"nested detail bullet must not be measured, got {out!r}",
        )


class TestSyncGateLayerI(_StopBase):
    """v0.23 — layer (i): rule 12 repo-wide sync gate.

    Edit-turns only, per-project opt-in via
    .claude/cc-enslaver/sync-gate.toml. Block condition: a group's `when`
    glob matched an edited file, no edited file matched any `require`
    glob, and the reply carries no sync marker. Failing-open on missing /
    malformed config.
    """

    GATE_TOML = (
        '[[groups]]\n'
        'name = "rules-fanout"\n'
        'when = ["rules/*.md"]\n'
        'require = ["prompts/*.md"]\n'
        'note = "rules fan out to prompts"\n'
    )

    def setUp(self) -> None:
        super().setUp()
        # Pin project-dir resolution to the tmpdir so the surrounding
        # environment (this repo has its own sync-gate.toml) can't leak in.
        self.env["CLAUDE_PROJECT_DIR"] = str(self.tmpdir)

    def _write_gate(self, toml_text: str) -> None:
        gate_dir = self.tmpdir / ".claude" / "cc-enslaver"
        gate_dir.mkdir(parents=True, exist_ok=True)
        (gate_dir / "sync-gate.toml").write_text(toml_text, encoding="utf-8")

    def _project_file(self, rel: str) -> str:
        p = self.tmpdir / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("# x\n", encoding="utf-8")
        return str(p)

    def _seed_edit_turn_and_edited(
        self, turn_count: int, edited: list[str],
    ) -> None:
        import os
        sessions = self.tmpdir / "sessions"
        sessions.mkdir(parents=True, exist_ok=True)
        (sessions / f"{self.sid}.json").write_text(
            json.dumps({
                "session_id": self.sid,
                "read_files": [],
                "last_edit_turn": turn_count,
                "edited_files": [
                    os.path.normcase(os.path.realpath(p)) for p in edited
                ],
            }),
            encoding="utf-8",
        )

    def _full_compliance_message(self) -> str:
        # Passes (a)-(h); deliberately contains NO sync marker.
        return (
            "已修复。\n$ pytest passed (35/35).\n"
            "重触发原症状: 已通过。\n"
            "rule 07: 无降级。\n"
            "rule 08: 改前必读完毕。\n"
            "rule 09: 系统式修改完成。\n"
            "tldr: 改完了，测试全过。"
        )

    def test_unmet_group_blocks_at_i(self) -> None:
        self._write_gate(self.GATE_TOML)
        edited = [self._project_file("rules/06-verify.md")]
        self._seed_edit_turn_and_edited(5, edited)
        rc, out, _ = self._stop(self._full_compliance_message(), turn_count=5)
        self.assertIsNotNone(out, msg="unmet sync-gate group must block at (i)")
        self.assertEqual(out["decision"], "block")
        self.assertIn("FAILED at Layer (i)", out["reason"])
        self.assertIn("rule 12", out["reason"])
        self.assertIn("rules-fanout", out["reason"])

    def test_require_side_edited_passes(self) -> None:
        self._write_gate(self.GATE_TOML)
        edited = [
            self._project_file("rules/06-verify.md"),
            self._project_file("prompts/session-start.md"),
        ]
        self._seed_edit_turn_and_edited(5, edited)
        rc, out, _ = self._stop(self._full_compliance_message(), turn_count=5)
        self.assertIsNone(out, msg=f"require-side edit must pass (i), got {out!r}")

    def test_sync_marker_escape_passes(self) -> None:
        self._write_gate(self.GATE_TOML)
        edited = [self._project_file("rules/06-verify.md")]
        self._seed_edit_turn_and_edited(5, edited)
        msg = (
            self._full_compliance_message()
            + "\n同步核对: prompts 侧核对过，本次改动不影响注入文案。"
        )
        rc, out, _ = self._stop(msg, turn_count=5)
        self.assertIsNone(out, msg=f"sync marker must pass (i), got {out!r}")

    def test_no_config_never_fires(self) -> None:
        # No sync-gate.toml in the project → layer (i) is off.
        edited = [self._project_file("rules/06-verify.md")]
        self._seed_edit_turn_and_edited(5, edited)
        rc, out, _ = self._stop(self._full_compliance_message(), turn_count=5)
        self.assertIsNone(out, msg=f"no config must never fire (i), got {out!r}")

    def test_non_edit_turn_does_not_fire(self) -> None:
        # Config + edited history present, but this turn had no edit.
        self._write_gate(self.GATE_TOML)
        edited = [self._project_file("rules/06-verify.md")]
        import os
        sessions = self.tmpdir / "sessions"
        sessions.mkdir(parents=True, exist_ok=True)
        (sessions / f"{self.sid}.json").write_text(
            json.dumps({
                "session_id": self.sid,
                "read_files": [],
                "edited_files": [
                    os.path.normcase(os.path.realpath(p)) for p in edited
                ],
            }),
            encoding="utf-8",
        )
        msg = (
            "已修复并验证。\n$ pytest passed (35/35).\n"
            "重触发原症状: 已通过。\n"
            "任务忠实: 用户原始请求一项，已完成，无降级、无遗漏。\n"
            "tldr: 修好了。"
        )
        rc, out, _ = self._stop(msg, turn_count=5)
        self.assertIsNone(out, msg=f"non-edit turn must not fire (i), got {out!r}")

    def test_malformed_config_fails_open(self) -> None:
        self._write_gate("this is [[ not valid toml\n")
        edited = [self._project_file("rules/06-verify.md")]
        self._seed_edit_turn_and_edited(5, edited)
        rc, out, _ = self._stop(self._full_compliance_message(), turn_count=5)
        self.assertIsNone(out, msg=f"malformed config must fail open, got {out!r}")

    def test_edits_outside_project_are_ignored(self) -> None:
        self._write_gate(self.GATE_TOML)
        # An edited file OUTSIDE the project root can't match any group.
        import tempfile
        outside = Path(tempfile.mkdtemp(prefix="ccens-outside-"))
        try:
            f = outside / "rules" / "06-verify.md"
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text("# x\n", encoding="utf-8")
            self._seed_edit_turn_and_edited(5, [str(f)])
            rc, out, _ = self._stop(
                self._full_compliance_message(), turn_count=5,
            )
            self.assertIsNone(
                out, msg=f"out-of-project edit must not trip (i), got {out!r}",
            )
        finally:
            shutil.rmtree(outside, ignore_errors=True)

    def test_block_reason_lists_require_globs(self) -> None:
        self._write_gate(self.GATE_TOML)
        edited = [self._project_file("rules/06-verify.md")]
        self._seed_edit_turn_and_edited(5, edited)
        rc, out, _ = self._stop(self._full_compliance_message(), turn_count=5)
        self.assertIn("prompts/*.md", out["reason"])
        self.assertIn("同步核对", out["reason"])

    # -- v0.23.1 hardening (adversarial-review findings) ------------------ #

    def test_english_sync_check_marker_escapes(self) -> None:
        self._write_gate(self.GATE_TOML)
        edited = [self._project_file("rules/06-verify.md")]
        self._seed_edit_turn_and_edited(5, edited)
        msg = (
            self._full_compliance_message()
            + "\nsync-check: prompts need no change for this edit."
        )
        rc, out, _ = self._stop(msg, turn_count=5)
        self.assertIsNone(out, msg=f"sync-check marker must pass (i), got {out!r}")

    def test_sync_gate_filename_mention_does_not_escape(self) -> None:
        # `sync-gate` is the config file's NAME, not a claim — merely
        # mentioning sync-gate.toml must not pass the gate.
        self._write_gate(self.GATE_TOML)
        edited = [self._project_file("rules/06-verify.md")]
        self._seed_edit_turn_and_edited(5, edited)
        msg = (
            self._full_compliance_message()
            + "\n另外我看了一眼 sync-gate.toml 的配置格式。"
        )
        rc, out, _ = self._stop(msg, turn_count=5)
        self.assertIsNotNone(
            out, msg="mentioning the config filename must NOT escape (i)",
        )
        self.assertIn("FAILED at Layer (i)", out["reason"])

    def test_marker_escape_acks_group_for_the_session(self) -> None:
        # Sticky-violation regression: after one marker escape, the same
        # unmet group must not re-block a later, unrelated edit turn.
        self._write_gate(self.GATE_TOML)
        edited = [self._project_file("rules/06-verify.md")]
        self._seed_edit_turn_and_edited(5, edited)
        msg = (
            self._full_compliance_message()
            + "\n同步核对: prompts 侧核对过，无需变更。"
        )
        rc, out, _ = self._stop(msg, turn_count=5)
        self.assertIsNone(out, msg=f"marker escape must pass, got {out!r}")
        state_path = self.tmpdir / "sessions" / f"{self.sid}.json"
        state = json.loads(state_path.read_text(encoding="utf-8"))
        self.assertIn(
            "rules-fanout", state.get("sync_acked_groups", []),
            msg="marker escape must persist the group acknowledgement",
        )
        # A later edit turn WITHOUT the marker must now pass too.
        state["last_edit_turn"] = 9
        state_path.write_text(json.dumps(state), encoding="utf-8")
        rc, out, _ = self._stop(self._full_compliance_message(), turn_count=9)
        self.assertIsNone(
            out,
            msg=f"acked group must not re-block later turns, got {out!r}",
        )

    def test_marker_in_grace_window_recovery_acks_group(self) -> None:
        # v0.24 regression (the PRIMARY real-world flow): block at (i) →
        # the recovery reply carries the sync marker but lands INSIDE the
        # one-shot grace window. v0.23 returned from the grace path before
        # reading the message, so the ack was silently lost and the same
        # group re-blocked the next post-grace edit turn — the exact
        # sticky-violation the sync_acked_groups contract promises to
        # prevent ("one explicit answer per group per session").
        self._write_gate(self.GATE_TOML)
        edited = [self._project_file("rules/06-verify.md")]
        self._seed_edit_turn_and_edited(5, edited)
        rc, out, _ = self._stop(self._full_compliance_message(), turn_count=5)
        self.assertIsNotNone(out, msg="unmet group must first block at (i)")
        self.assertIn("FAILED at Layer (i)", out["reason"])
        # Recovery reply one turn later (inside grace), WITH the marker.
        # Merge-update the state (a fresh seed would wipe last_blocked_turn
        # and defeat the grace window this test is about).
        state_path = self.tmpdir / "sessions" / f"{self.sid}.json"
        state = json.loads(state_path.read_text(encoding="utf-8"))
        state["last_edit_turn"] = 6
        state_path.write_text(json.dumps(state), encoding="utf-8")
        msg = (
            self._full_compliance_message()
            + "\n同步核对: prompts 侧核对过，无需变更。"
        )
        rc, out, _ = self._stop(msg, turn_count=6)
        self.assertIsNone(out, msg=f"grace window must allow, got {out!r}")
        state = json.loads(state_path.read_text(encoding="utf-8"))
        self.assertIn(
            "rules-fanout", state.get("sync_acked_groups", []),
            msg="the grace-path recovery marker must persist the ack",
        )
        # Post-grace edit turn WITHOUT the marker → must NOT re-block.
        state["last_edit_turn"] = 9
        state_path.write_text(json.dumps(state), encoding="utf-8")
        rc, out, _ = self._stop(self._full_compliance_message(), turn_count=9)
        self.assertIsNone(
            out,
            msg=f"group answered in grace window re-blocked later: {out!r}",
        )

    def test_grace_marker_after_non_i_block_does_not_ack(self) -> None:
        # v0.24 adversarial-review finding: the grace-path ack must be
        # scoped to recoveries from a layer-(i) block. A reply that
        # merely QUOTES a sync marker while recovering from an
        # unrelated layer (here: (a), no evidence) must NOT silently
        # acknowledge the pending group — the gate still owes the agent
        # a real layer-(i) confrontation later.
        self._write_gate(self.GATE_TOML)
        edited = [self._project_file("rules/06-verify.md")]
        self._seed_edit_turn_and_edited(5, edited)
        rc, out, _ = self._stop("已解决。", turn_count=5)
        self.assertIsNotNone(out)
        self.assertIn("FAILED at Layer (a)", out["reason"])
        # Recovery inside grace, incidentally containing a marker string.
        state_path = self.tmpdir / "sessions" / f"{self.sid}.json"
        state = json.loads(state_path.read_text(encoding="utf-8"))
        state["last_edit_turn"] = 6
        state_path.write_text(json.dumps(state), encoding="utf-8")
        msg = "补充证据中；顺带提一句，日志里出现过 sync-check 这个词。"
        rc, out, _ = self._stop(msg, turn_count=6)
        self.assertIsNone(out, msg=f"grace must still allow, got {out!r}")
        state = json.loads(state_path.read_text(encoding="utf-8"))
        self.assertNotIn(
            "rules-fanout", state.get("sync_acked_groups", []),
            msg="a non-(i) recovery must not ack the sync group",
        )
        # Post-grace, the group must still be enforceable at (i).
        state["last_edit_turn"] = 9
        state_path.write_text(json.dumps(state), encoding="utf-8")
        rc, out, _ = self._stop(self._full_compliance_message(), turn_count=9)
        self.assertIsNotNone(out, msg="un-acked group must still block at (i)")
        self.assertIn("FAILED at Layer (i)", out["reason"])

    def test_mode_all_requires_every_glob(self) -> None:
        gate = (
            '[[groups]]\n'
            'name = "version-manifests"\n'
            'when = ["plugin.json"]\n'
            'require = ["marketplace.json", "CHANGELOG.md"]\n'
            'mode = "all"\n'
        )
        self._write_gate(gate)
        # when + only ONE require edited → still a violation under all-of.
        edited = [
            self._project_file("plugin.json"),
            self._project_file("CHANGELOG.md"),
        ]
        self._seed_edit_turn_and_edited(5, edited)
        rc, out, _ = self._stop(self._full_compliance_message(), turn_count=5)
        self.assertIsNotNone(
            out, msg="mode=all with one stale sibling must block",
        )
        self.assertIn("FAILED at Layer (i)", out["reason"])
        # All require globs edited → satisfied.
        edited.append(self._project_file("marketplace.json"))
        self._seed_edit_turn_and_edited(5, edited)
        rc, out, _ = self._stop(self._full_compliance_message(), turn_count=5)
        self.assertIsNone(out, msg=f"mode=all fully satisfied must pass, got {out!r}")


class TestProductionShapePayloads(_StopBase):
    """v0.23 E2E finding — production hook payloads carry NO turn_count.

    Verified live: a real session with 27 recorded edits had no
    `last_edit_turn` key at all (every stamp had silently no-op'd), so
    the edit-gated layers (e)/(f)/(g)/(i) and the one-shot grace window
    had NEVER fired in production — only in the test suite, which always
    passed a turn_count. These tests replay the production shape: no
    turn_count, message via transcript_path, edit signal via the
    `edited_since_last_stop` flag that read_guard now always records.
    """

    def _seed_flag(self, value: bool = True) -> None:
        sessions = self.tmpdir / "sessions"
        sessions.mkdir(parents=True, exist_ok=True)
        (sessions / f"{self.sid}.json").write_text(
            json.dumps({
                "session_id": self.sid,
                "read_files": [],
                "edited_since_last_stop": value,
            }),
            encoding="utf-8",
        )

    def _stop_prod(self, reply: str) -> tuple[int, dict | None, str]:
        """Stop with NO turn_count and the message in a transcript."""
        tpath = self.tmpdir / f"transcript-{uuid.uuid4().hex[:6]}.jsonl"
        entries = [
            {"type": "user", "message": {"content": "do it"}},
            {"type": "assistant", "message": {"content": [
                {"type": "text", "text": reply}]}},
        ]
        tpath.write_text(
            "\n".join(json.dumps(e) for e in entries), encoding="utf-8",
        )
        return run_hook([GUARD], {
            "session_id": self.sid,
            "hook_event_name": "Stop",
            "cwd": str(self.tmpdir),
            "transcript_path": str(tpath),
        }, env_overrides=self.env)

    MISSING_RULE08 = (
        "已修复。\n$ pytest passed (35/35).\n重触发原症状: 已通过。\n"
        "rule 07: 无降级、无遗漏。\ntldr: 修好了。"
    )
    COMPLIANT = (
        "已修复。\n$ pytest passed (35/35).\n重触发原症状: 已通过。\n"
        "rule 07: 无降级。\nrule 08: 改前必读完毕。\n"
        "rule 09: 系统式修改完成。\ntldr: 改完了，测试全过。"
    )

    def _state_dict(self) -> dict:
        f = self.tmpdir / "sessions" / f"{self.sid}.json"
        return json.loads(f.read_text(encoding="utf-8"))

    def test_edit_flag_triggers_layer_e_without_turn_count(self) -> None:
        self._seed_flag(True)
        rc, out, _ = self._stop_prod(self.MISSING_RULE08)
        self.assertIsNotNone(
            out, msg="production-shape edit turn must block at (e)",
        )
        self.assertIn("FAILED at Layer (e)", out["reason"])

    def test_synthetic_grace_window_after_block(self) -> None:
        self._seed_flag(True)
        self._stop_prod(self.MISSING_RULE08)  # blocks, synthetic turn 1
        rc, out, _ = self._stop_prod(self.MISSING_RULE08)
        self.assertIsNone(
            out,
            msg=f"synthetic-turn grace must allow the recovery turn, got {out!r}",
        )

    def test_allowed_stop_clears_edit_flag(self) -> None:
        self._seed_flag(True)
        rc, out, _ = self._stop_prod(self.COMPLIANT)
        self.assertIsNone(out, msg=f"compliant reply must pass, got {out!r}")
        self.assertFalse(
            self._state_dict().get("edited_since_last_stop"),
            msg="an ALLOWED Stop is a turn boundary — flag must clear",
        )

    def test_blocked_stop_keeps_edit_flag(self) -> None:
        self._seed_flag(True)
        rc, out, _ = self._stop_prod(self.MISSING_RULE08)
        self.assertIsNotNone(out)
        self.assertTrue(
            self._state_dict().get("edited_since_last_stop"),
            msg="a BLOCKED Stop keeps the flag — recovery is the same turn",
        )

    def test_no_done_claim_clears_flag(self) -> None:
        self._seed_flag(True)
        rc, out, _ = self._stop_prod("看了一下 auth.py:42，问题在缺锁，下一步加锁。")
        self.assertIsNone(out)
        self.assertFalse(self._state_dict().get("edited_since_last_stop"))

    def test_stop_counter_increments_per_production_stop(self) -> None:
        self._seed_flag(False)
        self._stop_prod("分析中，尚无结论。")
        self._stop_prod("继续分析。")
        self.assertEqual(self._state_dict().get("stop_counter"), 2)


class TestCanonicalYamlSchema(_StopBase):
    """v0.20 — the canonical YAML reply schema must pass all layers a-h.

    Locks the "field names ARE the markers" contract: the schema field
    names (重触发 / 自答 / 请求覆盖 / 根因 / 影响范围 / 方案 / tldr ...) are
    exactly the substrings the layer detectors match. If a future edit
    renames a field, this test catches the drift before it ships.
    """

    def _seed_edit_turn(self, turn_count: int) -> None:
        sessions = self.tmpdir / "sessions"
        sessions.mkdir(parents=True, exist_ok=True)
        (sessions / f"{self.sid}.json").write_text(
            json.dumps({
                "session_id": self.sid,
                "read_files": [],
                "last_edit_turn": turn_count,
            }),
            encoding="utf-8",
        )

    CANONICAL = (
        "已修复。\n\n"
        "```yaml\n"
        "cc-enslaver:\n"
        "  改前:\n"
        "    架构定位: auth 链路第 3 步\n"
        "    根因: auth.py:142 缺锁\n"
        "    方案: 复用 session._pending_lock\n"
        "  改中:\n"
        '    - {file: "auth.py:142", what: "加锁"}\n'
        "  收敛:\n"
        '    重触发: "$ pytest -> 35 passed"\n'
        "    边界用例: 并发 100 线程无重入\n"
        "    连带不破: 既有测试全过\n"
        "    自答: {真解决: 是, 更好方案: 已比较锁全表方案, 哪些没验: 无, 验证合理: 是}\n"
        "  忠实:\n"
        "    请求覆盖: [修 X: OK]\n"
        "    标准性: '强制' -> 钩子拦截\n"
        "    忠实性: 无降级 无遗漏 无范围溢出\n"
        "  收尾:\n"
        "    根因: 缺锁\n"
        "    影响范围: routes/login.py:88\n"
        "    方案: 复用现有锁\n"
        '  tldr: "加锁修了并发 bug，测试全过，可直接 ship。"\n'
        "```"
    )

    # English schema: YAML plain-scalar keys CAN contain spaces, so the
    # field names match the space-separated English markers exactly
    # (root cause / self-quiz / request coverage / no degradation / impact).
    CANONICAL_EN = (
        "Fixed.\n\n"
        "```yaml\n"
        "cc-enslaver:\n"
        "  before:\n"
        "    architecture: auth chain step 3\n"
        "    root cause: auth.py:142 missing lock\n"
        "    solution: reuse session._pending_lock\n"
        "  edits:\n"
        '    - {file: "auth.py:142", what: "add lock"}\n'
        "  convergence:\n"
        '    re-trigger: "$ pytest -> 35 passed"\n'
        "    boundary case: 100 concurrent threads\n"
        "    existing tests: all pass\n"
        "    self-quiz: {really solved: yes, better solution: compared, "
        "unverified: none, verification reasonable: yes}\n"
        "  fidelity:\n"
        "    request coverage: [fix X: OK]\n"
        "    standard: mandatory -> hook\n"
        "    no degradation: no omission / no scope creep\n"
        "  closing:\n"
        "    root cause: missing lock\n"
        "    impact: routes/login.py:88\n"
        "    solution: reuse lock\n"
        '  tldr: "added a lock to fix the concurrency bug, all tests pass."\n'
        "```"
    )

    def test_full_yaml_schema_reply_passes_all_layers(self) -> None:
        # Strictest path: edit turn, so a-h are all active.
        self._seed_edit_turn(5)
        rc, out, _ = self._stop(self.CANONICAL, turn_count=5)
        self.assertIsNone(
            out, msg=f"canonical YAML schema must pass a-h, got {out!r}",
        )

    def test_full_english_yaml_schema_reply_passes_all_layers(self) -> None:
        self._seed_edit_turn(5)
        rc, out, _ = self._stop(self.CANONICAL_EN, turn_count=5)
        self.assertIsNone(
            out, msg=f"canonical EN YAML schema must pass a-h, got {out!r}",
        )


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
    """Claude Code's actual Stop hook payload usually omits
    `assistant_message` and only ships `transcript_path`. The fallback
    parser is therefore the *primary* code path on Claude Code 2.x, not
    a backup. v0.9.1 fixed a bug where the parser read the wrong field
    path (top-level `entry.content`) instead of the nested
    `entry.message.content` that Claude Code 2.x actually writes —
    which made the whole Stop hook a silent no-op for v0.6.0–v0.9.0.

    These tests cover both the real Claude Code 2.x schema (nested) and
    a generic legacy schema (top-level), so a future format flip in
    either direction can't silently regress the parser again.
    """

    def test_falls_back_to_transcript_claude_code_2x_schema(self) -> None:
        # Real Claude Code 2.x JSONL: `type` + nested `message.content`.
        tpath = self.tmpdir / "transcript.jsonl"
        entries = [
            {"type": "user", "message": {"content": "Fix the bug"}},
            {
                "type": "assistant",
                "message": {
                    "content": [
                        {"type": "text", "text": "已解决，无需进一步处理。"},
                    ],
                },
            },
        ]
        tpath.write_text(
            "\n".join(json.dumps(e) for e in entries),
            encoding="utf-8",
        )
        rc, out, _ = self._stop(message="", transcript_path=str(tpath))
        self.assertIsNotNone(
            out,
            msg="real Claude Code 2.x transcript schema must be parsed",
        )
        self.assertEqual(out["decision"], "block")

    def test_falls_back_to_transcript_legacy_top_level_schema(self) -> None:
        # Backwards-compat: generic / older schema with top-level content.
        # The parser tries nested first then falls back to top-level so
        # both formats keep working.
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
        self.assertIsNotNone(out, msg="legacy top-level schema must still parse")
        self.assertEqual(out["decision"], "block")

    def test_falls_back_to_transcript_string_content(self) -> None:
        # Some schemas use a plain string instead of a content array.
        # The parser handles both list-of-blocks and bare-string content.
        tpath = self.tmpdir / "transcript.jsonl"
        entries = [
            {"type": "assistant", "message": {"content": "已修复"}},
        ]
        tpath.write_text(
            "\n".join(json.dumps(e) for e in entries),
            encoding="utf-8",
        )
        rc, out, _ = self._stop(message="", transcript_path=str(tpath))
        self.assertIsNotNone(out, msg="string-content schema must parse")
        self.assertEqual(out["decision"], "block")

    def test_text_reply_wins_over_later_tool_use_entry(self) -> None:
        # In Claude Code 2.x a single agent turn may emit multiple
        # assistant entries: text reply, then one or more tool_use
        # entries (or vice versa). The Stop hook fires after the whole
        # turn completes. The parser must pull the *last text-bearing*
        # entry, not blindly the last assistant entry — otherwise a
        # trailing tool_use with no text blocks wipes out the actual
        # done-claim reply (regression bug fixed in v0.9.1).
        tpath = self.tmpdir / "transcript.jsonl"
        entries = [
            {"type": "user", "message": {"content": "fix bug"}},
            {
                "type": "assistant",
                "message": {
                    "content": [
                        {"type": "text", "text": "已修复，准备 ship。"},
                    ],
                },
            },
            # Trailing tool_use entry with no text blocks — this used to
            # overwrite the prior text reply with "" and silently allow.
            {
                "type": "assistant",
                "message": {
                    "content": [
                        {
                            "type": "tool_use",
                            "id": "toolu_x",
                            "name": "Bash",
                            "input": {"command": "echo verifying"},
                        },
                    ],
                },
            },
        ]
        tpath.write_text(
            "\n".join(json.dumps(e) for e in entries),
            encoding="utf-8",
        )
        rc, out, _ = self._stop(message="", transcript_path=str(tpath))
        self.assertIsNotNone(
            out,
            msg="text reply must survive a trailing tool_use entry",
        )
        self.assertEqual(out["decision"], "block")


class TestV012StatusTableFormat(_StopBase):
    """v0.12 — every block reason must render a uniform status table.

    The table is what users (and the agent) see at a glance: which gate
    failed, which gates passed, which were not evaluated. This format is
    contractual; we test it explicitly so accidental refactors of the
    builder don't silently revert to the v0.11 monolithic prose form.
    (v0.20 added an 8th row, layer (h).)
    """

    def _seed_edit_turn(self, turn_count: int) -> None:
        sessions = self.tmpdir / "sessions"
        sessions.mkdir(parents=True, exist_ok=True)
        state_path = sessions / f"{self.sid}.json"
        state_path.write_text(
            json.dumps({
                "session_id": self.sid,
                "read_files": [],
                "last_edit_turn": turn_count,
            }),
            encoding="utf-8",
        )

    def test_table_header_present_on_every_block(self) -> None:
        # Layer (a) failure path: no evidence.
        rc, out, _ = self._stop("已解决")
        self.assertEqual(out["decision"], "block")
        self.assertIn("| Layer | Rule | Status", out["reason"])
        self.assertIn("|-------|------|", out["reason"])

    def test_layer_a_failure_table_shape(self) -> None:
        rc, out, _ = self._stop("已解决")
        r = out["reason"]
        # Headline names the failed layer and its rule.
        self.assertIn("FAILED at Layer (a)", r)
        self.assertIn("rule 06", r)
        # (a) is the failing row; later layers are pending or n/a.
        self.assertIn("| (a)   | 06   | ❌", r)
        # Later layers must not be marked ✅ — they were never evaluated.
        for later in ["(b)", "(c)", "(d)", "(e)", "(f)", "(h)", "(i)"]:
            # Each later row should be either pending or n/a, never Pass.
            row = [line for line in r.splitlines() if line.startswith(f"| {later}")]
            self.assertEqual(len(row), 1, msg=f"missing row for {later}")
            self.assertNotIn("✅", row[0])

    def test_layer_c_failure_marks_earlier_layers_pass(self) -> None:
        # Done + evidence but no quiz → (a)(b) pass, (c) FAIL.
        rc, out, _ = self._stop("fixed. 22 passed, 0 failed.")
        r = out["reason"]
        self.assertIn("FAILED at Layer (c)", r)
        # (a) and (b) must show Pass; (c) must show FAIL.
        a_row = next(l for l in r.splitlines() if l.startswith("| (a)"))
        b_row = next(l for l in r.splitlines() if l.startswith("| (b)"))
        c_row = next(l for l in r.splitlines() if l.startswith("| (c)"))
        self.assertIn("✅ Pass", a_row)
        self.assertIn("✅ Pass", b_row)
        self.assertIn("❌", c_row)
        # `self-quiz` keyword preserved for downstream consumers.
        self.assertIn("self-quiz", r)

    def test_non_edit_turn_marks_ef_as_na(self) -> None:
        # No edit turn seeded → (e) and (f) must render as "n/a", not pending.
        rc, out, _ = self._stop("已解决")  # layer (a) fail, non-edit turn
        r = out["reason"]
        e_row = next(l for l in r.splitlines() if l.startswith("| (e)"))
        f_row = next(l for l in r.splitlines() if l.startswith("| (f)"))
        self.assertIn("n/a", e_row)
        self.assertIn("n/a", f_row)
        self.assertIn("non-edit", e_row)

    def test_edit_turn_marks_ef_pending_on_earlier_fail(self) -> None:
        # Edit turn + layer (a) fail → (e)(f) "pending", not "n/a".
        self._seed_edit_turn(5)
        rc, out, _ = self._stop("已解决", turn_count=5)
        r = out["reason"]
        e_row = next(l for l in r.splitlines() if l.startswith("| (e)"))
        f_row = next(l for l in r.splitlines() if l.startswith("| (f)"))
        self.assertIn("pending", e_row)
        self.assertIn("pending", f_row)
        # And NOT n/a — that would lie about applicability.
        self.assertNotIn("n/a", e_row)

    def test_recovery_section_present_and_named(self) -> None:
        rc, out, _ = self._stop("fixed. 22 passed.")  # layer (c)
        self.assertIn("[Recovery —", out["reason"])
        self.assertIn("rule 06 self-quiz", out["reason"])

    def test_one_shot_footer_present(self) -> None:
        rc, out, _ = self._stop("已解决")
        self.assertIn("One-shot guard", out["reason"])

    def test_layer_e_failure_marks_d_pass_and_f_pending(self) -> None:
        # Pass (a)(b)(c)(d), fail (e) — edit turn, missing rule-08 marker.
        self._seed_edit_turn(5)
        msg = (
            "已修复。\n$ pytest passed (35/35).\n"
            "重触发原症状: 已通过。\nrule 07: 无降级。"
        )
        rc, out, _ = self._stop(msg, turn_count=5)
        r = out["reason"]
        self.assertIn("FAILED at Layer (e)", r)
        d_row = next(l for l in r.splitlines() if l.startswith("| (d)"))
        e_row = next(l for l in r.splitlines() if l.startswith("| (e)"))
        f_row = next(l for l in r.splitlines() if l.startswith("| (f)"))
        self.assertIn("✅ Pass", d_row)
        self.assertIn("❌", e_row)
        self.assertIn("pending", f_row)

    def test_layer_h_row_present_and_is_final(self) -> None:
        # v0.20: the status table must include an (h) row in every block.
        rc, out, _ = self._stop("已解决")
        r = out["reason"]
        h_row = [l for l in r.splitlines() if l.startswith("| (h)")]
        self.assertEqual(len(h_row), 1, msg="status table must have an (h) row")

    def test_layer_i_row_present_and_na_on_non_edit_turn(self) -> None:
        # v0.23: the status table must include an (i) row; on a non-edit
        # turn it renders n/a like the other edit-gated layers.
        rc, out, _ = self._stop("已解决")  # layer (a) fail, non-edit turn
        r = out["reason"]
        i_rows = [l for l in r.splitlines() if l.startswith("| (i)")]
        self.assertEqual(len(i_rows), 1, msg="status table must have an (i) row")
        self.assertIn("n/a", i_rows[0])

    def test_layer_i_row_pending_on_edit_turn_earlier_fail(self) -> None:
        self._seed_edit_turn(5)
        rc, out, _ = self._stop("已解决", turn_count=5)
        i_row = next(
            l for l in out["reason"].splitlines() if l.startswith("| (i)")
        )
        self.assertIn("pending", i_row)


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


class TestChineseFileClaimAnchoring(unittest.TestCase):
    """v0.25 — layer (g) must not read a third-party attribution as a
    self-claim, and must honour Chinese negation.

    `_FILE_CLAIMS_EN` requires the subject `I`, so "The previous commit
    modified state.py" is correctly ignored. The Chinese pattern had NO
    subject constraint, so "上一版修改了 lib/state.py，本次没动" became a
    claim that THIS agent edited the file — and since read_guard records a
    baseline mtime for every file merely READ this session, layer (g)
    could then "disprove" it and BLOCK, accusing the agent of lying about
    an edit in the very sentence where it correctly said it had not
    touched the file.

    The negation guard was independently broken for CJK: it required
    whitespace after the negator, and Chinese does not put a space
    between 没有 and the verb, so "我没有修改了 X" still produced a claim.

    This repo's primary language is Chinese and version attributions
    ("v0.23 修改了 X") are pervasive in its own docs and replies, so both
    were live false-block generators.
    """

    def setUp(self) -> None:
        sys.path.insert(0, str(SCRIPTS_DIR))
        import stop_guard

        self.sg = stop_guard

    def _paths(self, message: str) -> list[str]:
        return [c[1] for c in self.sg._extract_file_claims(message)]

    def test_third_person_attribution_is_not_a_self_claim(self) -> None:
        for msg in [
            "上一版修改了 lib/state.py ，本次没动",
            "v0.23 修改了 stop_guard.py，这里不再赘述",
            "那个 PR 新增了 docs/RULES.md",
        ]:
            with self.subTest(msg=msg):
                self.assertEqual(
                    self._paths(msg), [],
                    msg="third-party attribution parsed as a self-claim",
                )

    def test_chinese_negation_is_honoured(self) -> None:
        for msg in [
            "我没有修改了 lib/state.py",
            "我没修改了 lib/state.py",
            "本次未修改了 lib/state.py",
        ]:
            with self.subTest(msg=msg):
                self.assertEqual(
                    self._paths(msg), [],
                    msg="negated Chinese claim still extracted",
                )

    def test_genuine_first_person_claims_still_extracted(self) -> None:
        # The layer must keep catching what it exists to catch.
        for msg, expected in [
            ("我修改了 lib/state.py", "lib/state.py"),
            ("我创建了 docs/NEW.md", "docs/NEW.md"),
            ("本次修改了 hooks/scripts/read_guard.py",
             "hooks/scripts/read_guard.py"),
        ]:
            with self.subTest(msg=msg):
                self.assertIn(expected, self._paths(msg))

    def test_english_behaviour_unchanged(self) -> None:
        self.assertIn("state.py", self._paths("I edited state.py"))
        self.assertEqual(
            self._paths("The previous commit modified state.py"), [])
        self.assertEqual(self._paths("I did not edit state.py"), [])


class TestNestedFenceTldrExtraction(unittest.TestCase):
    """v0.25 — a nested code fence must not close its parent.

    Fence markers were truncated to 3 characters, so an inner ``` fence
    inside an outer ```` fence compared equal to the opener and closed
    it. CommonMark requires a closing fence to be at least as long as the
    opening one; a shorter run is content. Once the outer fence was
    spuriously closed, its remaining body was scanned as prose — and a
    `tldr:` line inside quoted fixture text got measured, blocking layer
    (h) with "tldr item overlong" on text the reply merely quoted.
    Quoting nested markdown/YAML examples is routine in this repo.
    """

    def setUp(self) -> None:
        sys.path.insert(0, str(SCRIPTS_DIR))
        import stop_guard

        self.sg = stop_guard

    def test_nested_fence_content_is_not_measured(self) -> None:
        nl = chr(10)
        tick3, tick4 = "`" * 3, "`" * 4
        reply = (
            "Fixed." + nl * 2
            + tick4 + "markdown" + nl
            + tick3 + "text" + nl
            + 'tldr: "' + "A" * 300 + '"' + nl
            + tick3 + nl
            + tick4 + nl * 2
            + 'tldr: "the real one, short"' + nl
        )
        items = self.sg._tldr_items(reply)
        self.assertNotIn(
            300, [len(i) for i in items],
            msg="quoted fixture inside a nested fence was measured",
        )
        self.assertIsNone(
            self.sg._find_overlong_tldr(reply),
            msg="layer (h) would block on quoted text the agent did not "
                "author as its tldr",
        )

    def test_canonical_yaml_fence_still_measured(self) -> None:
        # Guard against over-fixing: the reply schema lives in a ```yaml
        # fence and its tldr MUST stay length-checked.
        nl = chr(10)
        tick3 = "`" * 3
        reply = (
            "Done." + nl * 2 + tick3 + "yaml" + nl
            + "cc-enslaver:" + nl
            + '  tldr: "' + "B" * 300 + '"' + nl
            + tick3 + nl
        )
        self.assertIsNotNone(
            self.sg._find_overlong_tldr(reply),
            msg="the canonical yaml schema block must remain measurable",
        )


class TestDoneClaimCoverageV0251(_StopBase):
    """v0.25.1 — `_has_done_claim` gates ALL nine layers.

    A completion phrased outside DONE_PATTERNS did not merely skip one
    check: stop_guard returned immediately, so evidence, convergence,
    fidelity, rule 08, rule 09, file-claims, TL;DR and the sync gate
    were all bypassed and the edit flag was cleared on the way out.
    """

    def _blocked(self, message: str) -> bool:
        _, out, _ = self._stop(message)
        return out is not None

    def test_previously_missed_wordings_now_claim_completion(self) -> None:
        # No evidence in any of these → layer (a) must block, which is
        # only reachable once the wording registers as a done-claim.
        for label, msg in [
            ("implemented", "Implemented the fix; ship it."),
            ("finished", "Finished the refactor."),
            ("is complete", "The migration is complete."),
            ("chinese 已完成", "已完成。可以直接发布了。"),
        ]:
            with self.subTest(case=label):
                self.assertTrue(self._blocked(msg), msg=label)

    def test_negated_statements_are_not_done_claims(self) -> None:
        """An honest report of failure must not be treated as a claim."""
        for label, msg in [
            ("not done", "Not done; tests failed and I need more input."),
            ("is not fixed", "This is not fixed. The parser still crashes."),
            ("all settings substring",
             "Not all settings are loaded, so I stopped here."),
            ("chinese 尚未", "尚未完成了修复，等你确认方案。"),
        ]:
            with self.subTest(case=label):
                self.assertFalse(self._blocked(msg), msg=label)

    def test_windows_transcript_counts_as_evidence(self) -> None:
        """This plugin's primary platform emits PowerShell prompts.

        Neither `PS C:\\repo>` nor `C:\\repo>` matched the POSIX-only
        prompt patterns, so a Windows user pasting a genuine transcript
        was still told they had produced no evidence.
        """
        bs = chr(92)
        for label, transcript in [
            ("powershell", "PS C:" + bs + "repo> checker.exe\nOK\n"),
            ("cmd", "C:" + bs + "repo> checker.exe\nOK\n"),
        ]:
            with self.subTest(case=label):
                _, out, _ = self._stop("Fixed.\n" + transcript)
                # Scoped to layer (a): this test is about evidence
                # detection, not the whole stack. A reply this bare
                # correctly fails a later layer.
                reason = "" if out is None else out.get("reason", "")
                self.assertNotIn(
                    "FAILED at Layer (a)", reason,
                    msg=f"{label}: a real transcript was called no-evidence",
                )

    def test_prose_without_a_transcript_still_lacks_evidence(self) -> None:
        """Reverse twin: the Windows patterns must not match prose."""
        _, out, _ = self._stop("Fixed. Everything works on C: drive now.")
        self.assertIsNotNone(out)
        self.assertIn("FAILED at Layer (a)", out.get("reason", ""))


class TestTldrMustCarryContentV0251(_StopBase):
    """v0.25.1 — layer (h) presence must mean an actual takeaway.

    A bare `tldr:` satisfied the presence half while the LENGTH half
    then measured nothing, so the emptiest possible summary passed both.
    """

    BODY = (
        "Fixed.\n\n$ python -m unittest\nRan 12 tests\nOK\n\n"
        "收敛: 真解决了吗 / 更好方案 / 哪些没验 / 验证是否合理\n"
        "忠实: 请求覆盖 / 无降级 / 无遗漏\n"
    )

    def _blocked_for_tldr(self, tail: str) -> bool:
        _, out, _ = self._stop(self.BODY + tail)
        if out is None:
            return False
        # The status table lists EVERY layer, so a bare "(h)" substring
        # would match on any block; assert on the failing-layer header.
        return "FAILED at Layer (h)" in out.get("reason", "")

    def test_empty_and_quoted_markers_are_rejected(self) -> None:
        for label, tail in [
            ("bare marker", "tldr:\n"),
            ("empty string value", 'tldr: ""\n'),
            ("blockquoted only", "> tldr: quoted from the spec\n"),
        ]:
            with self.subTest(case=label):
                self.assertTrue(self._blocked_for_tldr(tail), msg=label)

    def test_real_tldr_still_passes(self) -> None:
        for label, tail in [
            ("inline value", "tldr: 修好了检测器，测试全过。\n"),
            ("list under marker", "tldr:\n  - 修好了检测器，测试全过。\n"),
        ]:
            with self.subTest(case=label):
                self.assertFalse(self._blocked_for_tldr(tail), msg=label)

    def test_twin_layer_h_actually_fires_on_these_shapes(self) -> None:
        """v0.26.0 — the twin the PASS-only test above was missing.

        Round-4 audit found `test_real_tldr_still_passes` vacuous: it can
        succeed whenever layer (h) never fires at all, and it passes on
        the pre-fix tree, so it does not show the content detector
        recognised either form. Each shape below is the same form with its
        CONTENT removed or requoted, and must block.
        """
        for label, tail in [
            ("no tldr at all", "所有测试通过。\n"),
            ("value-less marker", "tldr:\n"),
            ("punctuation only", "tldr: ！！！\n"),
            ("quoted from elsewhere", "> tldr: 别人说的\n"),
            ("non-canonical fence", "```text\ntldr: 引用的示例\n```\n"),
        ]:
            with self.subTest(case=label):
                self.assertTrue(self._blocked_for_tldr(tail), msg=label)


class TestGraceAckScopeV0251(_StopBase):
    """v0.25.1 — a grace-window ack covers only the groups it was shown.

    The recovery turn is still an editing turn. If it touches files that
    violate a DIFFERENT group, that group became pending AFTER the
    block, was never presented, and was never answered — yet the ack
    used to silence it for the rest of the session.
    """

    def _write_config(self) -> None:
        cfg_dir = self.tmpdir / ".claude" / "cc-enslaver"
        cfg_dir.mkdir(parents=True, exist_ok=True)
        (self.tmpdir / ".git").mkdir(exist_ok=True)
        (cfg_dir / "sync-gate.toml").write_text(
            '[[groups]]\nname = "alpha"\nwhen = ["a/*"]\nrequire = ["ax/*"]\n'
            '\n[[groups]]\nname = "beta"\nwhen = ["b/*"]\nrequire = ["bx/*"]\n',
            encoding="utf-8",
        )

    def _edit(self, rel: str) -> None:
        """Record an edited file via the real read_guard Write path.

        The target must NOT pre-exist: an existing-but-unread file takes
        read_guard's read-before-edit branch and is DENIED, so nothing
        would be recorded and the sync gate would never see it.
        """
        target = self.tmpdir / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        run_hook(
            [str(SCRIPTS_DIR / "read_guard.py")],
            {"session_id": self.sid, "hook_event_name": "PreToolUse",
             "tool_name": "Write",
             "tool_input": {"file_path": str(target), "content": "x\n"}},
            env_overrides=self.env,
        )

    def test_ack_does_not_swallow_a_group_never_presented(self) -> None:
        self._write_config()
        body = (
            "Fixed.\n\n$ python -m unittest\nRan 3 tests\nOK\n\n"
            "收敛: 真解决了吗 / 更好方案 / 哪些没验 / 验证是否合理\n"
            "忠实: 请求覆盖 / 无降级 / 无遗漏\n"
            "根因: x / 影响范围: y / 方案: z\n"
            "架构定位: x / 风险: y\n"
            "tldr: 修好了。\n"
        )
        # Turn 5: only group alpha is violated → layer (i) blocks on it.
        self._edit("a/one.py")
        _, out, _ = self._stop(body, turn_count=5)
        self.assertIsNotNone(out, msg="layer (i) should have blocked")
        self.assertIn("alpha", out.get("reason", ""))

        # Turn 6 (grace window): the recovery reply answers alpha, but
        # this turn also edited a file that newly violates beta.
        self._edit("b/one.py")
        self._stop(body + "\n同步核对: alpha 已核对，prompts 无需改。\n",
                   turn_count=6)

        # Turn 9 (past the [last+1, last+3] grace window, which the
        # turn-5 block opened over turns 6-8): beta was never presented,
        # so it must still be able to block — while alpha, which WAS
        # presented and answered, must stay silent.
        self._edit("b/two.py")
        _, out, _ = self._stop(body, turn_count=9)
        self.assertIsNotNone(
            out, msg="beta was acked without ever being presented",
        )
        reason = out.get("reason", "")
        self.assertIn("beta", reason)
        self.assertNotIn(
            "group 'alpha'", reason,
            msg="an answered group must not re-block (v0.24 contract)",
        )


if __name__ == "__main__":
    unittest.main()
