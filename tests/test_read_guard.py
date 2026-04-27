"""Tests for hooks/scripts/read_guard.py.

Covers all four code paths:
  - PostToolUse(Read|Write) records the file to per-session state.
  - PreToolUse(Edit|Write) on tracked target → silent allow.
  - PreToolUse(Edit|Write) on existing untracked target → deny.
  - PreToolUse(Edit|Write) on non-existing target → silent allow (new file).

Plus failure modes:
  - Malformed stdin → fail-open.
  - Path normalization (forward-slash vs backslash, case folding).
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
    """Each test class subclass gets its own tmp CLAUDE_PLUGIN_DATA + session id.

    We isolate state per test class so a recording in one test does not
    bleed into another's allow/deny check.
    """

    def setUp(self) -> None:
        self.tmpdir = Path(tempfile.mkdtemp(prefix="alaz-test-"))
        self.env = {"CLAUDE_PLUGIN_DATA": str(self.tmpdir)}
        self.sid = f"test-{uuid.uuid4().hex[:8]}"

    def tearDown(self) -> None:
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _existing_file(self) -> str:
        # The test file itself is a guaranteed-existing target.
        return str(Path(__file__).resolve())

    def _post(self, tool: str, file_path: str) -> tuple[int, dict | None, str]:
        return run_hook(
            [GUARD],
            {
                "session_id": self.sid,
                "hook_event_name": "PostToolUse",
                "tool_name": tool,
                "tool_input": {"file_path": file_path},
            },
            env_overrides=self.env,
        )

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


class TestPostToolUseRecord(_GuardTestBase):
    def test_post_read_records_file(self) -> None:
        rc, out, err = self._post("Read", self._existing_file())
        self.assertEqual(rc, 0, msg=err)
        self.assertIsNone(out, msg="record path should be silent")

        sessions = list((self.tmpdir / "sessions").glob("*.json"))
        self.assertEqual(len(sessions), 1)
        state = json.loads(sessions[0].read_text(encoding="utf-8"))
        self.assertEqual(state["session_id"], self.sid)
        self.assertEqual(len(state["read_files"]), 1)

    def test_post_write_records_file(self) -> None:
        rc, out, _ = self._post("Write", self._existing_file())
        self.assertEqual(rc, 0)
        self.assertIsNone(out)
        sessions = list((self.tmpdir / "sessions").glob("*.json"))
        state = json.loads(sessions[0].read_text(encoding="utf-8"))
        self.assertEqual(len(state["read_files"]), 1)


class TestPreToolUseAllowTracked(_GuardTestBase):
    def test_edit_after_read_is_allowed(self) -> None:
        target = self._existing_file()
        # Record first
        self._post("Read", target)
        # Then attempt edit
        rc, out, err = self._pre("Edit", target)
        self.assertEqual(rc, 0, msg=err)
        self.assertIsNone(out, msg=f"expected silent allow, got {out!r}")

    def test_edit_after_write_is_allowed(self) -> None:
        target = self._existing_file()
        self._post("Write", target)
        rc, out, _ = self._pre("Edit", target)
        self.assertEqual(rc, 0)
        self.assertIsNone(out)


class TestPreToolUseDenyUntracked(_GuardTestBase):
    def test_edit_on_existing_untracked_is_denied(self) -> None:
        target = self._existing_file()
        # No PostToolUse record beforehand
        rc, out, err = self._pre("Edit", target)
        self.assertEqual(rc, 0, msg=err)
        self.assertIsNotNone(out, msg="expected deny output, got none")
        spec = out["hookSpecificOutput"]
        self.assertEqual(spec["hookEventName"], "PreToolUse")
        self.assertEqual(spec["permissionDecision"], "deny")
        # Reason must mention rule 04 and the target path.
        reason = spec["permissionDecisionReason"]
        self.assertIn("rule 04", reason)
        self.assertIn(target.replace("\\", "/").rsplit("/", 1)[-1], reason)

    def test_write_on_existing_untracked_is_denied(self) -> None:
        target = self._existing_file()
        rc, out, _ = self._pre("Write", target)
        self.assertEqual(rc, 0)
        self.assertIsNotNone(out)
        self.assertEqual(out["hookSpecificOutput"]["permissionDecision"], "deny")


class TestPreToolUseAllowNewFile(_GuardTestBase):
    def test_edit_on_nonexistent_file_is_allowed(self) -> None:
        # Path under tmpdir that we have not created.
        target = str(self.tmpdir / "brand-new.txt")
        self.assertFalse(Path(target).exists())
        rc, out, _ = self._pre("Write", target)
        self.assertEqual(rc, 0)
        self.assertIsNone(out, msg="new-file creation must not be blocked")


class TestFailOpen(_GuardTestBase):
    def test_malformed_stdin_does_not_block(self) -> None:
        # Bypass _helpers.run_hook so we can pipe non-JSON.
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
        # Record using forward slashes; query using mixed/backslashes.
        target = self._existing_file()
        target_fwd = target.replace("\\", "/")
        target_bwd = target.replace("/", "\\")

        self._post("Read", target_fwd)

        # On Windows both should be allowed (case-folded + normalized).
        # On POSIX, backslashes are literal — so this assertion may not
        # hold there. Skip the back-slash variant if not on Windows.
        rc, out, _ = self._pre("Edit", target_fwd)
        self.assertEqual(rc, 0)
        self.assertIsNone(out, msg="forward-slash variant should be allowed")

        if sys.platform == "win32":
            rc, out, _ = self._pre("Edit", target_bwd)
            self.assertEqual(rc, 0)
            self.assertIsNone(out, msg="backslash variant should be allowed on Windows")


if __name__ == "__main__":
    unittest.main()
