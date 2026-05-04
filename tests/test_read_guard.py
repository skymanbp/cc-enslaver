"""Tests for hooks/scripts/read_guard.py.

As of v0.3.2 the guard is a single PreToolUse handler covering Read /
Write / Edit. Every record-or-deny decision happens in PreToolUse so
that the recording side has the same scope as the gating side
(Claude Code does not always fire PostToolUse for files outside the
project working directory; relying on it broke v0.3.1 in production).

Covered:
  - PreToolUse(Read) records the file and allows.
  - PreToolUse(Write) on non-existent path: records and allows
    (new file creation).
  - PreToolUse(Write) on existing tracked target: allows (no deny).
  - PreToolUse(Write) on existing untracked target: denies.
  - PreToolUse(Edit) on existing tracked target: allows.
  - PreToolUse(Edit) on existing untracked target: denies.
  - PreToolUse(Edit) on non-existent path: allows (Claude Code itself
    will reject the bad input downstream).
  - Path normalization: forward/back slash equivalence on Windows.
  - Fail-open: malformed stdin or empty stdin must not block.
  - Event gating: non-PreToolUse events (e.g., a stray PostToolUse) are
    no-ops and do not record.
"""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
import unittest
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _helpers import SCRIPTS_DIR, run_hook  # noqa: E402

GUARD = str(SCRIPTS_DIR / "read_guard.py")


class _GuardTestBase(unittest.TestCase):
    """Each test class gets its own tmp CLAUDE_PLUGIN_DATA + session id.

    State isolation per test class so a recording in one test does not
    bleed into another's allow/deny check.
    """

    def setUp(self) -> None:
        self.tmpdir = Path(tempfile.mkdtemp(prefix="ccens-test-"))
        self.env = {"CLAUDE_PLUGIN_DATA": str(self.tmpdir)}
        self.sid = f"test-{uuid.uuid4().hex[:8]}"

    def tearDown(self) -> None:
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _existing_file(self) -> str:
        # The test file itself is a guaranteed-existing target.
        return str(Path(__file__).resolve())

    def _pre(self, tool: str, file_path: str) -> tuple[int, dict | None, str]:
        return run_hook(
            [GUARD],
            {
                "session_id": self.sid,
                "hook_event_name": "PreToolUse",
                "tool_name": tool,
                "tool_input": {"file_path": file_path},
            },
            env_overrides=self.env,
        )

    def _state_files(self) -> list[Path]:
        return list((self.tmpdir / "sessions").glob("*.json"))

    def _state(self) -> dict | None:
        files = self._state_files()
        if not files:
            return None
        return json.loads(files[0].read_text(encoding="utf-8"))


class TestPreReadRecords(_GuardTestBase):
    def test_read_records_file_and_allows(self) -> None:
        rc, out, err = self._pre("Read", self._existing_file())
        self.assertEqual(rc, 0, msg=err)
        self.assertIsNone(out, msg="Read must always allow silently")

        state = self._state()
        self.assertIsNotNone(state)
        self.assertEqual(state["session_id"], self.sid)
        self.assertEqual(len(state["read_files"]), 1)

    def test_read_then_edit_is_allowed(self) -> None:
        target = self._existing_file()
        self._pre("Read", target)
        rc, out, _ = self._pre("Edit", target)
        self.assertEqual(rc, 0)
        self.assertIsNone(out, msg="Edit after Read should allow silently")


class TestPreWrite(_GuardTestBase):
    def test_write_on_new_file_records_and_allows(self) -> None:
        target = str(self.tmpdir / "brand-new.txt")
        self.assertFalse(Path(target).exists())
        rc, out, _ = self._pre("Write", target)
        self.assertEqual(rc, 0)
        self.assertIsNone(out, msg="new file creation must not be blocked")
        # Recorded for subsequent Edit.
        state = self._state()
        self.assertEqual(len(state["read_files"]), 1)

    def test_write_on_existing_untracked_is_denied(self) -> None:
        target = self._existing_file()
        rc, out, _ = self._pre("Write", target)
        self.assertEqual(rc, 0)
        self.assertIsNotNone(out, msg="overwriting unknown file must be denied")
        self.assertEqual(out["hookSpecificOutput"]["permissionDecision"], "deny")

    def test_write_on_existing_tracked_is_allowed(self) -> None:
        target = self._existing_file()
        self._pre("Read", target)  # mark as known
        rc, out, _ = self._pre("Write", target)
        self.assertEqual(rc, 0)
        self.assertIsNone(out)


class TestPreEdit(_GuardTestBase):
    def test_edit_after_read_is_allowed(self) -> None:
        target = self._existing_file()
        self._pre("Read", target)
        rc, out, err = self._pre("Edit", target)
        self.assertEqual(rc, 0, msg=err)
        self.assertIsNone(out, msg=f"expected silent allow, got {out!r}")

    def test_edit_after_write_creates_then_edits(self) -> None:
        # Agent's typical flow: Write a new file, then Edit it. The Write
        # records the new path; the subsequent Edit must therefore allow.
        target = str(self.tmpdir / "newly-written.txt")
        # Simulate the file actually being created on disk between Write
        # and Edit (Claude Code does this between hooks).
        rc, out, _ = self._pre("Write", target)
        self.assertEqual(rc, 0)
        self.assertIsNone(out, msg="Write of new file must allow")
        Path(target).write_text("hello", encoding="utf-8")
        rc, out, _ = self._pre("Edit", target)
        self.assertEqual(rc, 0)
        self.assertIsNone(out, msg="Edit after Write of same path must allow")

    def test_edit_on_existing_untracked_is_denied(self) -> None:
        target = self._existing_file()
        rc, out, err = self._pre("Edit", target)
        self.assertEqual(rc, 0, msg=err)
        self.assertIsNotNone(out)
        spec = out["hookSpecificOutput"]
        self.assertEqual(spec["hookEventName"], "PreToolUse")
        self.assertEqual(spec["permissionDecision"], "deny")
        reason = spec["permissionDecisionReason"]
        self.assertIn("rule 04", reason)
        self.assertIn(target.replace("\\", "/").rsplit("/", 1)[-1], reason)

    def test_edit_on_nonexistent_file_is_allowed(self) -> None:
        # Editing a non-existent file is the agent's bug; Claude Code
        # will reject it downstream. We don't second-guess.
        target = str(self.tmpdir / "does-not-exist.py")
        rc, out, _ = self._pre("Edit", target)
        self.assertEqual(rc, 0)
        self.assertIsNone(out)


class TestEventGating(_GuardTestBase):
    def test_post_tool_use_is_a_noop(self) -> None:
        # If a stray PostToolUse arrives (e.g., user manually re-added the
        # legacy event), the guard must not record or deny on it. The new
        # contract is: PreToolUse owns everything.
        rc, out, _ = run_hook(
            [GUARD],
            {
                "session_id": self.sid,
                "hook_event_name": "PostToolUse",
                "tool_name": "Read",
                "tool_input": {"file_path": self._existing_file()},
            },
            env_overrides=self.env,
        )
        self.assertEqual(rc, 0)
        self.assertIsNone(out)
        self.assertIsNone(self._state(), msg="PostToolUse must not write state")

    def test_unhandled_tool_is_ignored(self) -> None:
        # Bash and arbitrary other tools must not be touched by read_guard.
        rc, out, _ = self._pre("Bash", "ignored-arg")
        self.assertEqual(rc, 0)
        self.assertIsNone(out)
        self.assertIsNone(self._state())


class TestFailOpen(_GuardTestBase):
    def test_malformed_stdin_does_not_block(self) -> None:
        import subprocess

        proc = subprocess.run(
            [sys.executable, GUARD],
            input=b"this is not json at all",
            capture_output=True,
            env={**__import__("os").environ, **self.env},
        )
        self.assertEqual(proc.returncode, 0, msg=proc.stderr.decode())
        self.assertEqual(proc.stdout.strip(), b"", msg="malformed input must not deny")
        self.assertIn(b"read_guard exception", proc.stderr)

    def test_empty_stdin_returns_zero_silently(self) -> None:
        import subprocess

        proc = subprocess.run(
            [sys.executable, GUARD],
            input=b"",
            capture_output=True,
            env={**__import__("os").environ, **self.env},
        )
        self.assertEqual(proc.returncode, 0)
        self.assertEqual(proc.stdout, b"")


class TestPathNormalization(_GuardTestBase):
    def test_forward_and_backward_slash_match(self) -> None:
        target = self._existing_file()
        target_fwd = target.replace("\\", "/")
        target_bwd = target.replace("/", "\\")

        # Record using the forward-slash form via PreToolUse(Read).
        self._pre("Read", target_fwd)

        rc, out, _ = self._pre("Edit", target_fwd)
        self.assertEqual(rc, 0)
        self.assertIsNone(out, msg="forward-slash variant should be allowed")

        if sys.platform == "win32":
            rc, out, _ = self._pre("Edit", target_bwd)
            self.assertEqual(rc, 0)
            self.assertIsNone(
                out, msg="backslash variant should be allowed on Windows"
            )


if __name__ == "__main__":
    unittest.main()
