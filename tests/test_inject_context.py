"""Tests for hooks/scripts/inject_context.py.

The script is purely additive (always exits 0, only emits
hookSpecificOutput.additionalContext). These tests verify:
  - The output JSON shape matches Claude Code's hook spec.
  - The injected content is non-empty and references the rule pack.
  - Non-ASCII (CJK) content survives the UTF-8 stdout pipeline on
    Windows (where Python's default stdout encoding would otherwise
    mangle it).
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _helpers import SCRIPTS_DIR, run_hook  # noqa: E402

INJECT = str(SCRIPTS_DIR / "inject_context.py")


class TestInjectContextSessionStart(unittest.TestCase):
    def test_returns_valid_hook_output(self) -> None:
        rc, out, err = run_hook(
            [INJECT, "--event", "SessionStart"],
            stdin_payload={
                "session_id": "test-session",
                "hook_event_name": "SessionStart",
            },
        )
        self.assertEqual(rc, 0, msg=err)
        self.assertIsNotNone(out)
        self.assertIn("hookSpecificOutput", out)
        self.assertEqual(out["hookSpecificOutput"]["hookEventName"], "SessionStart")
        self.assertIn("additionalContext", out["hookSpecificOutput"])

    def test_content_references_rules(self) -> None:
        _, out, _ = run_hook(
            [INJECT, "--event", "SessionStart"],
            stdin_payload={"session_id": "t", "hook_event_name": "SessionStart"},
        )
        ctx = out["hookSpecificOutput"]["additionalContext"]
        # v0.11: 9 numbered rules now, all must appear in the session-
        # start injection.
        for label in ("01", "02", "03", "04", "05", "06", "07", "08", "09", "rules/"):
            self.assertIn(label, ctx, msg=f"context missing {label!r}")

    def test_content_references_rule_06_convergence(self) -> None:
        # Rule 06 is the post-fix verify-and-converge rule (v0.5.0). The
        # session-start prompt must surface its 4-question self-quiz so
        # the agent sees them on every cold start.
        _, out, _ = run_hook(
            [INJECT, "--event", "SessionStart"],
            stdin_payload={"session_id": "t", "hook_event_name": "SessionStart"},
        )
        ctx = out["hookSpecificOutput"]["additionalContext"]
        # The 4 self-questions phrased in Chinese (matching session-start.md):
        for needle in (
            "验证收敛",
            "重触发原症状",
            "是不是真的解决了问题",
            "有没有更好的解决方法",
            "改动是否经过验证",
            "验证是否合理",
        ):
            self.assertIn(needle, ctx, msg=f"session-start prompt missing {needle!r}")

    def test_user_prompt_includes_convergence_check(self) -> None:
        # The per-turn reminder should also nudge the agent toward
        # convergence checks before declaring done.
        _, out, _ = run_hook(
            [INJECT, "--event", "UserPromptSubmit"],
            stdin_payload={"session_id": "t", "hook_event_name": "UserPromptSubmit"},
        )
        ctx = out["hookSpecificOutput"]["additionalContext"]
        self.assertIn("收敛", ctx, msg="user-prompt missing convergence reminder")

    def test_content_references_rule_07_fidelity(self) -> None:
        # Rule 07 is the post-fix request-coverage / no-degrade rule
        # (v0.8.0). The session-start prompt must surface its three
        # self-questions and the "modifier word" warning.
        _, out, _ = run_hook(
            [INJECT, "--event", "SessionStart"],
            stdin_payload={"session_id": "t", "hook_event_name": "SessionStart"},
        )
        ctx = out["hookSpecificOutput"]["additionalContext"]
        for needle in (
            "任务忠实",
            "覆盖性",
            "标准性",
            "忠实性",
            "原始请求",
        ):
            self.assertIn(needle, ctx, msg=f"session-start prompt missing {needle!r}")

    def test_user_prompt_includes_fidelity_check(self) -> None:
        # Per-turn reminder must also include rule-07 fidelity nudge.
        _, out, _ = run_hook(
            [INJECT, "--event", "UserPromptSubmit"],
            stdin_payload={"session_id": "t", "hook_event_name": "UserPromptSubmit"},
        )
        ctx = out["hookSpecificOutput"]["additionalContext"]
        self.assertIn("忠实", ctx, msg="user-prompt missing fidelity reminder")

    def test_content_references_rule_08_read_before_edit(self) -> None:
        # v0.11 — rule 08 (read-before-edit / think-before-write) must
        # appear in the session-start injection with both halves named.
        _, out, _ = run_hook(
            [INJECT, "--event", "SessionStart"],
            stdin_payload={"session_id": "t", "hook_event_name": "SessionStart"},
        )
        ctx = out["hookSpecificOutput"]["additionalContext"]
        for needle in (
            "改前必读",
            "写前必想",
            "rule 08",
            # The Stop-hook layer (e) reference confirms physical-
            # enforcement disclosure in the injection.
            "layer (e)",
        ):
            self.assertIn(needle, ctx, msg=f"session-start prompt missing {needle!r}")

    def test_content_references_rule_09_systematic_modification(self) -> None:
        # v0.11 — rule 09 (systematic modification, no patch-style) must
        # appear in the session-start injection with the anti-patch
        # vocabulary and the physical-enforcement callout.
        _, out, _ = run_hook(
            [INJECT, "--event", "SessionStart"],
            stdin_payload={"session_id": "t", "hook_event_name": "SessionStart"},
        )
        ctx = out["hookSpecificOutput"]["additionalContext"]
        for needle in (
            "系统式修改",
            "禁止打补丁",
            "rule 09",
            "layer (f)",
        ):
            self.assertIn(needle, ctx, msg=f"session-start prompt missing {needle!r}")

    def test_user_prompt_includes_rule_08_and_09_reminders(self) -> None:
        # The per-turn reminder must surface rule-08 + rule-09 nudges
        # since they govern the "during this turn" workflow.
        _, out, _ = run_hook(
            [INJECT, "--event", "UserPromptSubmit"],
            stdin_payload={"session_id": "t", "hook_event_name": "UserPromptSubmit"},
        )
        ctx = out["hookSpecificOutput"]["additionalContext"]
        for needle in (
            "改前必读",
            "写前必想",
            "系统式",
        ):
            self.assertIn(needle, ctx, msg=f"user-prompt missing {needle!r}")

    def test_content_is_utf8_intact(self) -> None:
        # Smoke test for the Windows cp936 stdout regression: the prompt
        # file is Chinese, and if we did not write sys.stdout.buffer as
        # UTF-8 the CJK chars would mojibake before reaching us.
        _, out, _ = run_hook(
            [INJECT, "--event", "SessionStart"],
            stdin_payload={"session_id": "t", "hook_event_name": "SessionStart"},
        )
        ctx = out["hookSpecificOutput"]["additionalContext"]
        # Pick a known CJK substring from prompts/session-start.md.
        self.assertIn("会话", ctx)
        self.assertIn("规则", ctx)


class TestInjectContextUserPromptSubmit(unittest.TestCase):
    def test_returns_valid_hook_output(self) -> None:
        rc, out, err = run_hook(
            [INJECT, "--event", "UserPromptSubmit"],
            stdin_payload={
                "session_id": "test-session",
                "hook_event_name": "UserPromptSubmit",
            },
        )
        self.assertEqual(rc, 0, msg=err)
        self.assertEqual(
            out["hookSpecificOutput"]["hookEventName"],
            "UserPromptSubmit",
        )
        self.assertGreater(
            len(out["hookSpecificOutput"]["additionalContext"]),
            50,
            msg="user-prompt reminder is suspiciously short",
        )


if __name__ == "__main__":
    unittest.main()
