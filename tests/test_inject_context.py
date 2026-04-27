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
        # Should mention all 5 numbered rules and the rules/ directory.
        for label in ("01", "02", "03", "04", "05", "rules/"):
            self.assertIn(label, ctx, msg=f"context missing {label!r}")

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
