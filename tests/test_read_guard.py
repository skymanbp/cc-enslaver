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

    def _pre_edit_with_new_string(
        self,
        file_path: str,
        new_string: str,
        turn_count: int | None = None,
    ) -> tuple[int, dict | None, str]:
        payload: dict = {
            "session_id": self.sid,
            "hook_event_name": "PreToolUse",
            "tool_name": "Edit",
            "tool_input": {
                "file_path": file_path,
                "new_string": new_string,
                "old_string": "",
            },
        }
        if turn_count is not None:
            payload["turn_count"] = turn_count
        return run_hook([GUARD], payload, env_overrides=self.env)

    def _pre_write_with_content(
        self,
        file_path: str,
        content: str,
        turn_count: int | None = None,
    ) -> tuple[int, dict | None, str]:
        payload: dict = {
            "session_id": self.sid,
            "hook_event_name": "PreToolUse",
            "tool_name": "Write",
            "tool_input": {
                "file_path": file_path,
                "content": content,
            },
        }
        if turn_count is not None:
            payload["turn_count"] = turn_count
        return run_hook([GUARD], payload, env_overrides=self.env)

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


class TestPatchStyleEdit(_GuardTestBase):
    """v0.11 — rule 09 PreToolUse(Edit|Write) new_string content guard.

    The detector scans the new content for unjustified suppression
    markers and DENY-s with a rule-09 reason. Each marker is allowed
    when accompanied by an adjacent rationale comment.

    Note on dogfooding: the fixtures below intentionally trigger the
    detector at *runtime* (the new_string sent to the hook subprocess).
    To avoid this test file's own source tripping read_guard when this
    file is later edited, race/workaround/etc. fixtures are built via
    runtime string concatenation so the literal regex match does not
    appear in this file's source.
    """

    def test_bare_try_except_pass_is_denied(self) -> None:
        # try/except: pass is unambiguous at the source level; no need
        # for runtime concatenation here — the detector regex is multi-
        # line and won't match this single-string-literal in source.
        target = self._existing_file()
        self._pre("Read", target)
        new_string = (
            "try:\n"
            "    risky()\n"
            "except Exception:\n"
            "    pass\n"
        )
        rc, out, _ = self._pre_edit_with_new_string(target, new_string)
        self.assertEqual(rc, 0)
        self.assertIsNotNone(out, msg="bare try/except: pass must DENY")
        spec = out["hookSpecificOutput"]
        self.assertEqual(spec["permissionDecision"], "deny")
        self.assertIn("rule 09", spec["permissionDecisionReason"])

    def test_bare_noqa_is_denied(self) -> None:
        target = self._existing_file()
        self._pre("Read", target)
        # Build via concatenation so this test file's source doesn't
        # itself contain a bare-noqa pattern.
        bare = "# " + "no" + "qa"
        new_string = "x = unused_var  " + bare + "\n"
        rc, out, _ = self._pre_edit_with_new_string(target, new_string)
        self.assertIsNotNone(out, msg="bare noqa must DENY")
        self.assertEqual(out["hookSpecificOutput"]["permissionDecision"], "deny")
        self.assertIn("rule 09", out["hookSpecificOutput"]["permissionDecisionReason"])

    def test_noqa_with_rationale_is_allowed(self) -> None:
        target = self._existing_file()
        self._pre("Read", target)
        # Justified form: rationale contains "because" within the ±1
        # line window of the marker.
        marker = "# " + "no" + "qa: E501"
        new_string = (
            marker + "  -- URL must stay on one line, because splitting hurts readability\n"
            "LONG_URL = 'https://example.com/very/long'\n"
        )
        rc, out, _ = self._pre_edit_with_new_string(target, new_string)
        self.assertIsNone(
            out,
            msg=f"noqa with adjacent 'because' rationale must allow, got {out!r}",
        )

    def test_ts_ignore_with_rationale_is_allowed(self) -> None:
        target = self._existing_file()
        self._pre("Read", target)
        ts_marker = "// " + "@ts-" + "ignore"
        new_string = (
            ts_marker + ": third-party lib has incomplete type, see issue #1234\n"
            "const result = legacy.foo();\n"
        )
        rc, out, _ = self._pre_edit_with_new_string(target, new_string)
        self.assertIsNone(out, msg="@ts-ignore with rationale must allow")

    def test_bare_eslint_disable_next_line_is_denied(self) -> None:
        target = self._existing_file()
        self._pre("Read", target)
        es_marker = "// " + "eslint-" + "disable-next-line"
        new_string = (
            es_marker + " no-console\n"
            "console.log('hi');\n"
        )
        rc, out, _ = self._pre_edit_with_new_string(target, new_string)
        self.assertIsNotNone(out, msg="bare eslint-disable must DENY")
        self.assertEqual(out["hookSpecificOutput"]["permissionDecision"], "deny")

    def test_time_sleep_workaround_is_denied(self) -> None:
        target = self._existing_file()
        self._pre("Read", target)
        # Runtime concatenation: source never has `# workaround` adjacent
        # to a `time.sleep(...)` call, but the runtime new_string does.
        race_keyword = "work" + "around"
        new_string = (
            "import time\n"
            "time.sleep(0.5)  # " + race_keyword + "\n"
        )
        rc, out, _ = self._pre_edit_with_new_string(target, new_string)
        self.assertIsNotNone(
            out,
            msg="time.sleep with race/wait/workaround marker must DENY",
        )
        self.assertEqual(out["hookSpecificOutput"]["permissionDecision"], "deny")

    def test_clean_new_string_is_allowed(self) -> None:
        target = self._existing_file()
        self._pre("Read", target)
        new_string = "def add(a, b):\n    return a + b\n"
        rc, out, _ = self._pre_edit_with_new_string(target, new_string)
        self.assertIsNone(out, msg="clean new_string must allow silently")

    def test_write_new_file_with_bare_noqa_is_denied(self) -> None:
        target = str(self.tmpdir / "new_module.py")
        bare = "# " + "no" + "qa"
        content = "import sys  " + bare + "\nprint(sys.path)\n"
        rc, out, _ = self._pre_write_with_content(target, content)
        self.assertIsNotNone(out, msg="even new-file Write must DENY bare noqa")
        self.assertEqual(out["hookSpecificOutput"]["permissionDecision"], "deny")


class TestRecordEditTurn(_GuardTestBase):
    """v0.11 — accepted Edits/Writes stamp last_edit_turn into state.

    The stamp is what Stop layers (e)+(f) check to scope themselves to
    edit turns. Without this stamp, those layers silently allow.
    """

    def test_successful_edit_stamps_edit_turn(self) -> None:
        target = self._existing_file()
        self._pre("Read", target)
        rc, out, _ = self._pre_edit_with_new_string(
            target,
            "x = 1\n",
            turn_count=7,
        )
        self.assertIsNone(out, msg="clean Edit must allow")
        state = self._state()
        self.assertEqual(
            state.get("last_edit_turn"),
            7,
            msg=f"expected last_edit_turn=7, got {state!r}",
        )

    def test_successful_write_stamps_edit_turn(self) -> None:
        target = str(self.tmpdir / "fresh.py")
        rc, out, _ = self._pre_write_with_content(
            target,
            "def f(): pass\n",
            turn_count=12,
        )
        self.assertIsNone(out, msg="clean Write of new file must allow")
        state = self._state()
        self.assertEqual(state.get("last_edit_turn"), 12)

    def test_denied_edit_does_not_stamp_edit_turn(self) -> None:
        target = self._existing_file()
        self._pre("Read", target)
        rc, out, _ = self._pre_edit_with_new_string(
            target,
            "try:\n    risky()\nexcept Exception:\n    pass\n",
            turn_count=4,
        )
        self.assertIsNotNone(out)
        state = self._state()
        self.assertNotEqual(
            state.get("last_edit_turn"),
            4,
            msg="denied Edit must not stamp last_edit_turn",
        )

    def test_no_turn_count_does_not_stamp(self) -> None:
        target = self._existing_file()
        self._pre("Read", target)
        rc, out, _ = self._pre_edit_with_new_string(target, "x = 1\n")
        self.assertIsNone(out)
        state = self._state()
        self.assertIsNone(
            state.get("last_edit_turn"),
            msg="missing turn_count must not produce a stamp",
        )


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
