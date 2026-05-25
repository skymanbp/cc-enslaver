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
        msg = (
            "已修复并验证：\n\n"
            "$ pytest tests/\n"
            "Ran 35 tests in 4.5s\n"
            "OK\n\n"
            "重触发原症状: 已通过。\n"
            "任务忠实: 用户原始请求只有'修复 X'，已完成，无降级、无超范围。"
        )
        rc, out, _ = self._stop(msg)
        self.assertEqual(rc, 0)
        self.assertIsNone(out, msg=f"expected silent allow, got {out!r}")

    def test_done_with_re_triggered_keyword_allows(self) -> None:
        # 重触发 alone is a convergence marker.
        # v0.8.0: also needs rule-07 fidelity marker.
        msg = "完成了。重触发原症状后异常消失。无遗漏。"
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
        msg = (
            "fixed.\n\n"
            "$ pytest -v\nRan 22 tests, 22 passed.\n\n"
            "**真的解决了吗?** Yes — the failing input now returns 200.\n"
            "**有没有更好的方案?** Considered using a thread lock instead, "
            "but the existing async lock is already part of the architecture.\n"
            "Task fidelity: covered all requested items, no degradation."
        )
        rc, out, _ = self._stop(msg)
        self.assertEqual(rc, 0)
        self.assertIsNone(out, msg="2 of 4 self-questions should pass quiz gate")

    def test_done_with_explicit_rule06_mention_allows(self) -> None:
        # Explicit "rule 06" + evidence is enough (single marker hit).
        # v0.8.0: also needs rule-07 fidelity marker.
        msg = (
            "Done.\n$ pytest passed (60/60)\n"
            "Ran rule 06 self-check; all 5 steps verified.\n"
            "Rule 07 task fidelity: covered all requested items, no degradation."
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
        msg = (
            "I think this race condition usually doesn't reproduce — "
            "hard to test in isolation.\n\n"
            "But anyway, $ pytest passed (35/35), 重触发原症状 confirms "
            "the lock fixes the race, **真解决** confirmed via the new "
            "concurrent test, and the existing tests still pass. "
            "Task fidelity: covered all requested items. fixed."
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
        msg = (
            "Fixed.\n$ pytest passed.\n重触发: ok.\n"
            "rule 07: covered all sub-items, no scope creep."
        )
        rc, out, _ = self._stop(msg)
        self.assertIsNone(out, msg=f"single rule-07 marker must pass, got {out!r}")

    def test_chinese_task_fidelity_marker_passes(self) -> None:
        msg = (
            "已解决。\n$ pytest passed (35/35).\n重触发原症状: ok.\n"
            "任务忠实自答: 用户原始请求只有'修 X'一项，已完成。"
        )
        rc, out, _ = self._stop(msg)
        self.assertIsNone(out)

    def test_no_degradation_english_passes(self) -> None:
        msg = (
            "Done.\n$ pytest passed.\nRan rule 06 self-check.\n"
            "Reviewed against the original request: no degradation, "
            "no omission, no scope creep."
        )
        rc, out, _ = self._stop(msg)
        self.assertIsNone(out)

    def test_two_fidelity_questions_pass(self) -> None:
        # Coverage Q + standard Q answered → 2 of 3 quiz threshold met.
        msg = (
            "Fixed.\n\n"
            "$ pytest -v\nRan 22 tests, 22 passed.\n\n"
            "重触发: ok。\n\n"
            "**覆盖性**: 用户原始请求拆成两项 (修 X / 加测试)，均完成。\n"
            "**标准性**: 用户用了'强制'一词，已落实为钩子拦截 (file:line)，"
            "不是文档建议。"
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
        msg = (
            "完成了。\n$ pytest passed.\n重触发: ok.\n\n"
            "原始请求逐项核对:\n"
            "- ✅ 完成: 修复 X (auth.py:42)\n"
            "- ✅ 完成: 加测试 (test_auth.py)"
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
        msg = (
            "已修复并验证。\n"
            "$ pytest passed (35/35).\n"
            "重触发原症状: 已通过。\n"
            "任务忠实: 用户原始请求只有一项，已完成，无降级、无超范围。"
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
        self._seed_edit_turn(turn_count=5)
        msg = (
            "已修复。\n"
            "$ pytest passed (35/35).\n"
            "重触发原症状: 已通过。\n"
            "rule 07: 无降级、无遗漏。\n"
            "rule 08: 改前必读 (auth.py 第 3 次工具调用 Read 完整) + 写前必想 "
            "(根因 / 影响 / 方案 三件套见下).\n"
            "rule 09: 根因 = 缺锁 (auth.py:142); 影响 = routes/login.py:88 调用链; "
            "方案 = 复用 session._pending_lock。"
        )
        rc, out, _ = self._stop(msg, turn_count=5)
        self.assertIsNone(out, msg=f"explicit rule-08 marker must pass, got {out!r}")

    def test_edit_turn_with_three_rule02_keywords_passes(self) -> None:
        # 3 of 6 rule-02 keywords: 架构 + 根源 + 方案. Plus rule 09
        # triplet (because layer (f) also checks).
        self._seed_edit_turn(turn_count=5)
        msg = (
            "已修复。\n"
            "$ pytest passed (35/35).\n"
            "重触发原症状: 已通过。\n"
            "rule 07: 无降级。\n"
            "**架构定位**: auth.py 是登录链路第 3 步; "
            "**根源**: auth.py:142 缺锁; "
            "**方案**: 复用 session._pending_lock (覆盖 connected impact)。"
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
        self._seed_edit_turn(turn_count=5)
        msg = (
            "已修复。\n"
            "$ pytest passed (35/35).\n"
            "重触发原症状: 已通过。\n"
            "rule 07: 无降级。\n"
            "rule 08: 改前必读完毕。\n"
            "rule 09: 系统式修改完成。"
        )
        rc, out, _ = self._stop(msg, turn_count=5)
        self.assertIsNone(
            out,
            msg=f"explicit rule-09 marker must pass, got {out!r}",
        )

    def test_edit_turn_with_complete_triplet_passes(self) -> None:
        # All three triplet axes present without explicit rule 09 marker.
        # Also has rule 08 markers so layer (e) passes.
        self._seed_edit_turn(turn_count=5)
        msg = (
            "已修复。\n"
            "$ pytest passed (35/35).\n"
            "重触发原症状: 已通过。\n"
            "rule 07: 无降级。\n"
            "rule 08: 改前必读完毕。\n"
            "**根源**: auth.py:142 缺锁。\n"
            "**影响范围**: routes/login.py:88, tests/test_auth.py:55。\n"
            "**方案**: 复用 session._pending_lock（与方案 B 锁全表对比，A 更轻量）。"
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
        msg = (
            "已修复。\n"
            "$ pytest passed (35/35).\n"
            "重触发原症状: 已通过。\n"
            "rule 07: 无降级、无遗漏。"
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
        """A message that passes layers (a)-(f) so we test only (g)."""
        return (
            "已修复。\n$ pytest passed (35/35).\n"
            "重触发原症状: 已通过。\n"
            "rule 07: 无降级。\n"
            "rule 08: 改前必读完毕。\n"
            "rule 09: 系统式修改完成。"
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
    """v0.12 — every block reason must render a uniform 6-row status table.

    The table is what users (and the agent) see at a glance: which gate
    failed, which gates passed, which were not evaluated. This format is
    contractual; we test it explicitly so accidental refactors of the
    builder don't silently revert to the v0.11 monolithic prose form.
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
        # (a) is the failing row; (b)-(f) are pending or n/a.
        self.assertIn("| (a)   | 06   | ❌", r)
        # Later layers must not be marked ✅ — they were never evaluated.
        for later in ["(b)", "(c)", "(d)", "(e)", "(f)"]:
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
