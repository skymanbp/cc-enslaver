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
# because the sys.path bootstrap above must run before this import
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
        # for runtime concatenation here — the detector is line-scan
        # based and won't match this single-string-literal in source.
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

    def test_bare_try_except_pass_with_rationale_is_allowed(self) -> None:
        """Adjacent 'because ...' rationale must suppress the DENY.

        Same allowance contract the noqa / ts-ignore branches use: the
        ±1-line window around the offending span is checked for
        RATIONALE_TOKENS. v0.18.1 routes the bare-pass check through a
        new linear scanner, so this test pins the rationale-window
        behaviour against the new code path.
        """
        target = self._existing_file()
        self._pre("Read", target)
        new_string = (
            "try:\n"
            "    risky()\n"
            "except Exception:\n"
            "    pass  # because upstream guarantees idempotency\n"
        )
        rc, out, _ = self._pre_edit_with_new_string(target, new_string)
        self.assertEqual(rc, 0)
        self.assertIsNone(
            out,
            msg=f"try/except/pass with adjacent rationale must allow, got {out!r}",
        )

    def test_redos_pathological_input_completes_fast(self) -> None:
        """Regression test for the v0.18.1 ReDoS fix.

        Before v0.18.1 the bare ``try/except/pass`` detector was a
        multi-line regex with non-greedy line repetition
        (``(?:[ \\t]+[^\\n]*\\n)+?``) followed by a later anchor. On a
        ``try:`` block that lacks the matching ``except:\\n    pass``
        closure — i.e. ordinary, healthy Python code — that regex
        exhibited catastrophic backtracking:

            N=10 body lines: ~0.07 s
            N=20 body lines: > 60 s (hung)
            N=50+:           > 10 minutes (user-reported)

        The whole hook process blocked, so every Edit/Write of a real
        ``.py`` file containing ``try:`` froze Claude Code for minutes
        to hours. The v0.18.1 linear scanner removes the regex; this
        test pins the worst case at well under 1 second so any future
        regression that re-introduces the regex fails loudly.

        Wall time bound is generous (1 s on a slow CI runner) but
        thousands of times faster than the broken version's runtime
        on the same input.
        """
        import time

        target = self._existing_file()
        self._pre("Read", target)

        # The pathological input: a ``try:`` header followed by 100
        # indented body lines with no matching ``except:\\n    pass``
        # ending. The old regex spent its time exploring every possible
        # backtracking assignment of body lines to the ``(?:...)+?``
        # group before the engine could conclude "no match".
        new_string = "try:\n" + ("    body_line = 1\n" * 100) + "y = 0\n"

        t0 = time.perf_counter()
        rc, out, _ = self._pre_edit_with_new_string(target, new_string)
        dt = time.perf_counter() - t0

        # Hook must complete promptly — generous 5 s cap on CI to
        # absorb Python-subprocess cold-start variance on Windows; the
        # actual scan is sub-millisecond. The broken version exceeded
        # 60 s on N=20 and minutes on N=100.
        self.assertLess(
            dt,
            5.0,
            msg=(
                f"read_guard took {dt:.3f}s on a 100-line try-without-except "
                "input — likely a ReDoS regression in the bare-pass detector"
            ),
        )
        # And the linear scanner must NOT raise a false-positive DENY
        # on this clean (no ``except: pass``) input.
        self.assertIsNone(
            out,
            msg=f"try block without bare-pass closure must allow, got {out!r}",
        )

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

    def test_denied_write_new_does_not_register_read(self) -> None:
        # v0.24 regression: the Write-new branch used to call add_read
        # BEFORE the content checks, so a DENIED Write still registered
        # the path as "read" — granting read-before-edit authorization
        # for a file whose content was never seen (if another process
        # later created it, a Write-existing would sail past has_read).
        import os
        target = str(self.tmpdir / "brand_new_denied.py")
        bare = "# " + "no" + "qa"
        rc, out, _ = self._pre_write_with_content(target, "x = 1  " + bare + "\n")
        self.assertIsNotNone(out, msg="the Write itself must DENY")
        state = self._state()
        if state is not None:
            norm = os.path.normcase(os.path.realpath(target))
            self.assertNotIn(
                norm, state.get("read_files", []),
                msg="a DENIED Write-new must NOT register the path as read",
            )


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

    def test_no_turn_count_still_sets_edit_flag(self) -> None:
        # v0.23 E2E finding: production payloads have no turn_count, so
        # the edit signal the Stop hook actually consumes is the
        # edited_since_last_stop flag — it must be set unconditionally
        # on every accepted Edit/Write.
        target = self._existing_file()
        self._pre("Read", target)
        rc, out, _ = self._pre_edit_with_new_string(target, "x = 1\n")
        self.assertIsNone(out)
        self.assertTrue(
            self._state().get("edited_since_last_stop"),
            msg="accepted Edit without turn_count must still set the flag",
        )


class TestEditedFilesRecording(_GuardTestBase):
    """v0.23 — accepted Edits/Writes land in the session's edited_files set.

    This set is what Stop layer (i) (rule 12 sync gate) matches against
    the project's co-update groups. Denied edits must NOT be recorded —
    a denied edit never landed, so it creates no co-update obligation.
    """

    def _edited(self) -> list[str]:
        state = self._state()
        if not state:
            return []
        return state.get("edited_files") or []

    def test_successful_edit_records_edited_file(self) -> None:
        import os
        target = self._existing_file()
        self._pre("Read", target)
        rc, out, _ = self._pre_edit_with_new_string(target, "x = 1\n")
        self.assertIsNone(out, msg="clean Edit must allow")
        norm = os.path.normcase(os.path.realpath(target))
        self.assertIn(norm, self._edited())

    def test_write_new_file_records_edited_file(self) -> None:
        import os
        target = str(self.tmpdir / "fresh_module.py")
        rc, out, _ = self._pre_write_with_content(target, "def f(): pass\n")
        self.assertIsNone(out, msg="clean Write of new file must allow")
        norm = os.path.normcase(os.path.realpath(target))
        self.assertIn(norm, self._edited())

    def test_denied_edit_is_not_recorded(self) -> None:
        target = self._existing_file()
        self._pre("Read", target)
        rc, out, _ = self._pre_edit_with_new_string(
            target,
            "try:\n    risky()\nexcept Exception:\n    pass\n",
        )
        self.assertIsNotNone(out, msg="patch-style edit must DENY")
        self.assertEqual(self._edited(), [])

    def test_read_alone_is_not_recorded(self) -> None:
        self._pre("Read", self._existing_file())
        self.assertEqual(self._edited(), [])


class TestRollingPatchInterception(_GuardTestBase):
    """v0.13 — rule 09 rolling-patch hard interception.

    The PreToolUse(Edit) guard classifies each change as small /
    systematic / medium and tracks a per-file counter. When the predicted
    next small-edit count reaches 4, the guard DENIES — without
    incrementing the counter, so subsequent attempts also DENY until a
    systematic edit (≥ 50 lines or ≥ 1500 chars) resets the counter.

    These tests intentionally pin the threshold (4) and the small/
    systematic boundaries (10 lines / 200 chars, 50 lines / 1500 chars)
    so accidental retuning of the constants doesn't silently degrade
    enforcement.
    """

    def _small_edit_payload(self, target: str) -> tuple[str, str]:
        # Both sides are well under (10 lines, 200 chars).
        return ("old line\n", "new line\n")

    def _systematic_edit_payload(self) -> tuple[str, str]:
        # ≥ 50 lines on new_string side triggers the systematic branch.
        new = "\n".join(f"line {i}" for i in range(60))
        return ("old\n", new)

    def _writable_target(self, name: str = "target.py") -> str:
        target = self.tmpdir / name
        target.write_text("# initial\n", encoding="utf-8")
        return str(target)

    def _do_small_edit(self, target: str):
        old, new = self._small_edit_payload(target)
        return run_hook(
            [GUARD],
            {
                "session_id": self.sid,
                "hook_event_name": "PreToolUse",
                "tool_name": "Edit",
                "tool_input": {
                    "file_path": target,
                    "old_string": old,
                    "new_string": new,
                },
            },
            env_overrides=self.env,
        )

    def _do_systematic_edit(self, target: str):
        old, new = self._systematic_edit_payload()
        return run_hook(
            [GUARD],
            {
                "session_id": self.sid,
                "hook_event_name": "PreToolUse",
                "tool_name": "Edit",
                "tool_input": {
                    "file_path": target,
                    "old_string": old,
                    "new_string": new,
                },
            },
            env_overrides=self.env,
        )

    def _counter(self, target: str) -> int:
        state = self._state()
        if not state:
            return 0
        counters = state.get("edits_per_file") or {}
        import os
        norm = os.path.normcase(os.path.realpath(target))
        return counters.get(norm, 0)

    def test_three_small_edits_allowed_fourth_denied(self) -> None:
        target = self._writable_target()
        self._pre("Read", target)
        # 1, 2, 3 — allow
        for i in range(3):
            rc, out, _ = self._do_small_edit(target)
            self.assertIsNone(
                out,
                msg=f"small edit #{i + 1} should be allowed, got {out!r}",
            )
        self.assertEqual(self._counter(target), 3)
        # 4 — DENY
        rc, out, _ = self._do_small_edit(target)
        self.assertIsNotNone(out, msg="4th small edit must DENY")
        self.assertEqual(out["hookSpecificOutput"]["permissionDecision"], "deny")
        reason = out["hookSpecificOutput"]["permissionDecisionReason"]
        self.assertIn("rule 09", reason)
        self.assertIn("rolling-patch", reason)
        # Counter must NOT advance on DENY (else next attempt is 5 not 4).
        self.assertEqual(self._counter(target), 3)

    def test_denied_attempt_does_not_increment_so_next_also_denies(self) -> None:
        target = self._writable_target()
        self._pre("Read", target)
        for _ in range(3):
            self._do_small_edit(target)
        self._do_small_edit(target)  # denied
        # Another attempt is also denied — counter stuck at 3.
        rc, out, _ = self._do_small_edit(target)
        self.assertIsNotNone(out)
        self.assertEqual(out["hookSpecificOutput"]["permissionDecision"], "deny")
        self.assertEqual(self._counter(target), 3)

    def test_systematic_edit_resets_counter(self) -> None:
        target = self._writable_target()
        self._pre("Read", target)
        for _ in range(3):
            self._do_small_edit(target)
        self.assertEqual(self._counter(target), 3)
        # Systematic Edit clears the counter.
        rc, out, _ = self._do_systematic_edit(target)
        self.assertIsNone(out, msg="systematic edit should be allowed")
        self.assertEqual(
            self._counter(target),
            0,
            msg="systematic edit must reset the counter",
        )
        # We can now do 3 more small edits.
        for i in range(3):
            rc, out, _ = self._do_small_edit(target)
            self.assertIsNone(
                out,
                msg=f"post-reset small edit #{i + 1} should be allowed",
            )

    def test_two_files_have_independent_counters(self) -> None:
        a = self._writable_target("a.py")
        b = self._writable_target("b.py")
        self._pre("Read", a)
        self._pre("Read", b)
        for _ in range(3):
            self._do_small_edit(a)
        # a is at the threshold; b has touched zero counter.
        self.assertEqual(self._counter(a), 3)
        self.assertEqual(self._counter(b), 0)
        rc, out, _ = self._do_small_edit(b)
        self.assertIsNone(
            out,
            msg="b's counter is 0, edit must be allowed even when a's is at limit",
        )

    def test_medium_edit_does_not_count_or_reset(self) -> None:
        target = self._writable_target()
        self._pre("Read", target)
        # Medium: between small (< 200 chars / ≤ 10 lines) and systematic
        # (≥ 1500 chars or ≥ 50 lines). 15 lines, ~150 chars: lines >
        # small-max but chars < small-max → medium because lines > 10
        # and lines < 50.
        medium_new = "\n".join(f"l{i}" for i in range(15))
        rc, out, _ = run_hook(
            [GUARD],
            {
                "session_id": self.sid,
                "hook_event_name": "PreToolUse",
                "tool_name": "Edit",
                "tool_input": {
                    "file_path": target,
                    "old_string": "a\n",
                    "new_string": medium_new,
                },
            },
            env_overrides=self.env,
        )
        self.assertIsNone(out, msg="medium edit should be allowed")
        self.assertEqual(
            self._counter(target),
            0,
            msg="medium edit should not increment the small-edit counter",
        )

    def test_systematic_write_resets_counter(self) -> None:
        target = self._writable_target()
        self._pre("Read", target)
        for _ in range(3):
            self._do_small_edit(target)
        self.assertEqual(self._counter(target), 3)
        # Systematic Write (60 lines of content) resets.
        big = "\n".join(f"line {i}" for i in range(60))
        rc, out, _ = self._pre_write_with_content(target, big)
        self.assertIsNone(out, msg="systematic Write should allow + reset")
        self.assertEqual(self._counter(target), 0)

    def test_write_new_file_does_not_increment_counter(self) -> None:
        # Writing a brand-new (non-existent) file is creation, not a
        # rolling patch. Counter must stay at 0.
        target = str(self.tmpdir / "brand-new.py")
        rc, out, _ = self._pre_write_with_content(
            target,
            "def f(): pass\n",  # small content
        )
        self.assertIsNone(out)
        self.assertEqual(self._counter(target), 0)

    def test_write_new_resets_stale_rolling_counter(self) -> None:
        # v0.24 regression: delete-and-recreate. A path accumulates small
        # edits, the file is deleted externally, then a Write creates a
        # fresh file at the same path. The stale counter used to survive,
        # so the fresh file's FIRST small edit was denied as attempt #4.
        # A new file is a fresh start — Write-new must clear the counter.
        import os
        target = str(self.tmpdir / "reborn.py")
        norm = os.path.normcase(os.path.realpath(target))
        sessions = self.tmpdir / "sessions"
        sessions.mkdir(parents=True, exist_ok=True)
        (sessions / f"{self.sid}.json").write_text(
            json.dumps({
                "session_id": self.sid,
                "read_files": [],
                "edits_per_file": {norm: 3},
            }),
            encoding="utf-8",
        )
        rc, out, _ = self._pre_write_with_content(target, "def f(): pass\n")
        self.assertIsNone(out, msg=f"Write-new must allow, got {out!r}")
        Path(target).write_text("def f(): pass\n", encoding="utf-8")
        rc, out, _ = self._do_small_edit(target)
        self.assertIsNone(
            out,
            msg=(
                "first small edit after recreation must be attempt #1, "
                f"not #4 from the stale counter — got {out!r}"
            ),
        )
        self.assertEqual(self._counter(target), 1)

    def test_state_persists_edits_per_file_field(self) -> None:
        # Quick sanity check that the JSON field name is what other tools
        # (e.g. /cc-enforcer:gc, future tooling) can rely on.
        target = self._writable_target()
        self._pre("Read", target)
        self._do_small_edit(target)
        state = self._state()
        self.assertIn("edits_per_file", state)
        self.assertEqual(len(state["edits_per_file"]), 1)
        self.assertEqual(list(state["edits_per_file"].values()), [1])


class TestConcurrentStateRecording(_GuardTestBase):
    """v0.23 — parallel hook processes must not lose state updates.

    Claude Code fires parallel tool calls as concurrent hook
    subprocesses sharing one session file. Before the v0.23 cross-
    process lock + atomic save, the unlocked load→mutate→save cycle
    lost 20-30% of recorded paths at 10-way parallelism (measured:
    2-3 of 10 per round), whose visible symptom was a false rule-04
    DENY right after the file WAS read — and, since v0.23, a corrupted
    layer-(i) edited_files verdict. This test launches 12 truly
    concurrent recorders and demands zero loss.
    """

    def test_parallel_reads_all_recorded(self) -> None:
        import subprocess
        n = 12
        targets = []
        for i in range(n):
            f = self.tmpdir / f"conc_{i}.py"
            f.write_text(f"# {i}\n", encoding="utf-8")
            targets.append(str(f))
        env = {**__import__("os").environ, **self.env}
        procs = []
        for t in targets:
            payload = json.dumps({
                "session_id": self.sid,
                "hook_event_name": "PreToolUse",
                "tool_name": "Read",
                "tool_input": {"file_path": t},
            }).encode("utf-8")
            p = subprocess.Popen(
                [sys.executable, GUARD],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=env,
            )
            procs.append((p, payload))
        # Feed stdin only after ALL processes exist, maximizing overlap.
        for p, payload in procs:
            p.stdin.write(payload)
            p.stdin.close()
        for p, _ in procs:
            p.wait(timeout=120)
        state = self._state()
        self.assertIsNotNone(state, msg="state file must exist")
        recorded = state.get("read_files", [])
        self.assertEqual(
            len(recorded), n,
            msg=(
                f"lost update: only {len(recorded)}/{n} parallel reads "
                f"survived — the session-lock / atomic-save fix regressed"
            ),
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


class _ContentDetectorBase(_GuardTestBase):
    """Shared fixtures for the rule 10 / 11 content detectors (v0.22).

    Dogfooding: read_guard.py is a .py file, so once the new detectors
    ship, editing *this* test file re-runs them on the new source. Every
    offending secret / path fixture below is therefore assembled via
    runtime string concatenation so no literal match ever appears in this
    file's own source (mirrors the TestPatchStyleEdit note above).
    """

    Q = '"'
    BS = chr(92)  # backslash

    # -- offending "code" lines, built so the source never matches -------- #
    def _secret_assign_line(self) -> str:
        # <keyword> = "<10-char non-placeholder value>"
        return ("api" + "_key") + " = " + self.Q + ("Zx9Q" + "7Lm2Kp") + self.Q

    def _aws_key_line(self) -> str:
        return "cred = " + self.Q + "AKIA" + ("Q" * 16) + self.Q

    def _pem_header_line(self) -> str:
        return "-----BEGIN " + "DSA " + "PRIVATE KEY-----"

    def _url_creds_line(self) -> str:
        return "dsn = " + self.Q + "mysql:" + "//" + "u:" + "p@" + "host/db" + self.Q

    def _placeholder_secret_line(self) -> str:
        # Real keyword+assignment, but a placeholder value → not flagged.
        return ("api" + "_key") + " = " + self.Q + "your-" + "key-here" + self.Q

    def _win_path_line(self) -> str:
        return "p = " + self.Q + "C:" + self.BS + "Users" + self.BS + "bob" + self.BS + "x.csv" + self.Q

    def _posix_path_line(self) -> str:
        return "p = " + self.Q + "/" + "home/" + "bob/proj/" + self.Q

    def _home_var_line(self) -> str:
        return "p = join(" + "$" + "HOME" + ", 'x')"

    def _userprofile_line(self) -> str:
        return "p = " + "%USER" + "PROFILE%" + self.BS + "x"

    def _tilde_line(self) -> str:
        return "p = " + self.Q + "~" + "/" + "proj/data" + self.Q

    def _read_py_target(self) -> str:
        target = self._existing_file()  # this test file, a .py → scannable
        self._pre("Read", target)
        return target

    def _assert_deny(self, out, rule_substr: str) -> None:
        self.assertIsNotNone(out, msg=f"expected DENY mentioning {rule_substr}")
        spec = out["hookSpecificOutput"]
        self.assertEqual(spec["permissionDecision"], "deny")
        self.assertIn(rule_substr, spec["permissionDecisionReason"])


class TestHardcodedSecretEdit(_ContentDetectorBase):
    """v0.22 — rule 10 hardcoded-secret content detector."""

    def test_secret_named_assignment_is_denied(self) -> None:
        target = self._read_py_target()
        _, out, _ = self._pre_edit_with_new_string(target, self._secret_assign_line() + "\n")
        self._assert_deny(out, "rule 10")

    def test_aws_key_literal_is_denied(self) -> None:
        target = self._read_py_target()
        _, out, _ = self._pre_edit_with_new_string(target, self._aws_key_line() + "\n")
        self._assert_deny(out, "rule 10")

    def test_private_key_header_is_denied(self) -> None:
        target = self._read_py_target()
        _, out, _ = self._pre_edit_with_new_string(target, self._pem_header_line() + "\n")
        self._assert_deny(out, "rule 10")

    def test_url_credentials_are_denied(self) -> None:
        target = self._read_py_target()
        _, out, _ = self._pre_edit_with_new_string(target, self._url_creds_line() + "\n")
        self._assert_deny(out, "rule 10")

    def test_placeholder_value_is_allowed(self) -> None:
        target = self._read_py_target()
        _, out, _ = self._pre_edit_with_new_string(target, self._placeholder_secret_line() + "\n")
        self.assertIsNone(out, msg=f"placeholder value must allow, got {out!r}")

    def test_env_read_is_allowed(self) -> None:
        target = self._read_py_target()
        # api_key = os.environ["API_KEY"] — RHS is not a quoted literal.
        new_string = ("api" + "_key") + " = os.environ[" + self.Q + "API_KEY" + self.Q + "]\n"
        _, out, _ = self._pre_edit_with_new_string(target, new_string)
        self.assertIsNone(out, msg=f"env-read must allow, got {out!r}")

    def test_secret_with_adjacent_rationale_is_allowed(self) -> None:
        target = self._read_py_target()
        # Same offending value, but an adjacent 'because' rationale in the
        # ±1-line window suppresses the DENY (the escape hatch operating
        # the user's "*非必须*" scoping).
        new_string = self._secret_assign_line() + "  # because documented test vector\n"
        _, out, _ = self._pre_edit_with_new_string(target, new_string)
        self.assertIsNone(out, msg=f"rationale must allow, got {out!r}")

    def test_clean_code_is_allowed(self) -> None:
        target = self._read_py_target()
        _, out, _ = self._pre_edit_with_new_string(target, "total = price * qty  # arithmetic\n")
        self.assertIsNone(out, msg=f"clean code must allow, got {out!r}")

    def test_new_file_write_with_secret_is_denied(self) -> None:
        target = str(self.tmpdir / "leak.py")
        _, out, _ = self._pre_write_with_content(target, self._aws_key_line() + "\n")
        self._assert_deny(out, "rule 10")

    def test_prose_doc_is_exempt(self) -> None:
        # A .md target legitimately carries example credentials → exempt.
        target = str(self.tmpdir / "notes.md")
        _, out, _ = self._pre_write_with_content(target, self._aws_key_line() + "\n")
        self.assertIsNone(out, msg=f".md must be exempt from rule 10, got {out!r}")

    def test_annotation_type_name_value_is_allowed(self) -> None:
        # v0.24: a Python forward-reference annotation like
        # `password: "SecretStr"` is a TYPE NAME, not a credential — the
        # pure-alpha CamelCase value shape must not be flagged (real
        # secrets carry digits / symbols). False positives violate the
        # repo's "prefer false negatives" detector philosophy.
        target = self._read_py_target()
        line = ("pass" + "word") + ": " + self.Q + "Secret" + "Str" + self.Q
        _, out, _ = self._pre_edit_with_new_string(target, line + "\n")
        self.assertIsNone(
            out, msg=f"type-annotation value must allow, got {out!r}",
        )

    def test_camel_case_value_with_digits_still_denied(self) -> None:
        # Guard against over-widening the v0.24 type-name allowance: a
        # value with digits is not a type name and must still DENY.
        target = self._read_py_target()
        line = ("pass" + "word") + " = " + self.Q + "Hunter" + "2Secret9" + self.Q
        _, out, _ = self._pre_edit_with_new_string(target, line + "\n")
        self._assert_deny(out, "rule 10")

    def test_requirements_txt_is_scannable(self) -> None:
        # v0.24: requirements*.txt is a dependency manifest, not prose —
        # an index URL with embedded credentials is a real leak vector
        # that the blanket .txt exemption used to wave through.
        target = str(self.tmpdir / "requirements.txt")
        line = (
            "--extra-index-url https:" + "//" + "build:" + "s3cr3t@"
            + "pkgs.host.test/simple"
        )
        _, out, _ = self._pre_write_with_content(target, line + "\n")
        self._assert_deny(out, "rule 10")

    def test_plain_txt_stays_exempt(self) -> None:
        # The v0.24 requirements carve-out must not shrink the general
        # .txt prose exemption.
        target = str(self.tmpdir / "notes.txt")
        _, out, _ = self._pre_write_with_content(target, self._aws_key_line() + "\n")
        self.assertIsNone(out, msg=f"plain .txt must stay exempt, got {out!r}")

    def test_asciidoc_long_extension_is_exempt(self) -> None:
        # v0.24: .asciidoc is the same format as the already-exempt
        # .adoc — both spellings must behave identically.
        target = str(self.tmpdir / "guide.asciidoc")
        _, out, _ = self._pre_write_with_content(target, self._pem_header_line() + "\n")
        self.assertIsNone(out, msg=f".asciidoc must be exempt, got {out!r}")


class TestPathDependencyEdit(_ContentDetectorBase):
    """v0.22 — rule 11 machine-specific path-dependency content detector."""

    def test_windows_user_home_path_is_denied(self) -> None:
        target = self._read_py_target()
        _, out, _ = self._pre_edit_with_new_string(target, self._win_path_line() + "\n")
        self._assert_deny(out, "rule 11")

    def test_posix_user_home_path_is_denied(self) -> None:
        target = self._read_py_target()
        _, out, _ = self._pre_edit_with_new_string(target, self._posix_path_line() + "\n")
        self._assert_deny(out, "rule 11")

    def test_shell_home_variable_is_denied(self) -> None:
        target = self._read_py_target()
        _, out, _ = self._pre_edit_with_new_string(target, self._home_var_line() + "\n")
        self._assert_deny(out, "rule 11")

    def test_userprofile_variable_is_denied(self) -> None:
        target = self._read_py_target()
        _, out, _ = self._pre_edit_with_new_string(target, self._userprofile_line() + "\n")
        self._assert_deny(out, "rule 11")

    def test_tilde_path_literal_is_denied(self) -> None:
        target = self._read_py_target()
        _, out, _ = self._pre_edit_with_new_string(target, self._tilde_line() + "\n")
        self._assert_deny(out, "rule 11")

    def test_path_with_adjacent_rationale_is_allowed(self) -> None:
        target = self._read_py_target()
        new_string = self._win_path_line() + "  # essential: fixed OS location\n"
        _, out, _ = self._pre_edit_with_new_string(target, new_string)
        self.assertIsNone(out, msg=f"path rationale must allow, got {out!r}")

    def test_relative_path_is_allowed(self) -> None:
        target = self._read_py_target()
        new_string = "p = base / " + self.Q + "sub" + self.Q + " / " + self.Q + "file.csv" + self.Q + "\n"
        _, out, _ = self._pre_edit_with_new_string(target, new_string)
        self.assertIsNone(out, msg=f"relative path must allow, got {out!r}")

    def test_new_file_write_with_path_is_denied(self) -> None:
        target = str(self.tmpdir / "cfg.py")
        _, out, _ = self._pre_write_with_content(target, self._posix_path_line() + "\n")
        self._assert_deny(out, "rule 11")

    def test_prose_doc_is_exempt(self) -> None:
        target = str(self.tmpdir / "README.md")
        _, out, _ = self._pre_write_with_content(target, self._win_path_line() + "\n")
        self.assertIsNone(out, msg=f".md must be exempt from rule 11, got {out!r}")

    def test_url_route_home_segment_is_allowed(self) -> None:
        # v0.24: `/home/<x>/` glued to a hostname is a URL route, not a
        # filesystem path — must not be flagged as a path dependency.
        target = self._read_py_target()
        line = (
            "URL = " + self.Q + "https:" + "//" + "host.test"
            + "/ho" + "me/" + "alice/dashboard/" + self.Q
        )
        _, out, _ = self._pre_edit_with_new_string(target, line + "\n")
        self.assertIsNone(out, msg=f"URL route must allow, got {out!r}")

    def test_file_scheme_home_path_still_denied(self) -> None:
        # Guard against over-widening the v0.24 URL allowance: a
        # file:///home/... URI IS a machine path and must still DENY
        # (the segment before /home/ is a slash, not a hostname char).
        target = self._read_py_target()
        line = (
            "p = " + self.Q + "file:" + "//" + "/ho" + "me/"
            + "bob/data/" + self.Q
        )
        _, out, _ = self._pre_edit_with_new_string(target, line + "\n")
        self._assert_deny(out, "rule 11")


class TestReaderWriterCollision(_GuardTestBase):
    """v0.24 — saves must survive concurrent readers (C8).

    The v0.23 session lock serialized writer-vs-writer only; every read
    path (has_read / was_just_blocked / get_edited_files / ...) called
    load() WITHOUT the lock. On Windows, os.replace against a file a
    reader currently holds open fails with PermissionError (CPython's
    open() does not pass FILE_SHARE_DELETE), the mutator raised, the
    hook failed open, and the mutation was silently lost — measured
    300/300 lost saves under 8 tight-loop readers, with orphan
    `<sid>.json.<pid>.tmp` files left behind (observed in live session
    state directories). The v0.24 fix routes the read accessors through
    the session lock (state._load_shared) so hook readers and writers
    serialize, plus a save()-side os.replace retry against
    non-cooperating external readers.

    The reader threads here call the real production read accessor
    (has_read), so this pins the end-to-end contract: with the v0.23
    lock-free accessor this test was red (192/200 saves lost); with the
    locked accessor every save must land. POSIX rename has no such
    restriction, so the Windows CI leg is the one that pins the
    regression.
    """

    def test_saves_survive_concurrent_lockfree_readers(self) -> None:
        import os
        import threading
        sys.path.insert(0, str(SCRIPTS_DIR))
        from lib import state as state_lib

        old_env = os.environ.get("CLAUDE_PLUGIN_DATA")
        os.environ["CLAUDE_PLUGIN_DATA"] = str(self.tmpdir)
        try:
            state_lib.add_read(self.sid, str(self.tmpdir / "seed.txt"))
            state_file = (
                self.tmpdir / "sessions" / f"{self.sid}.json"
            )
            stop = threading.Event()
            probe = str(self.tmpdir / "seed.txt")

            def reader() -> None:
                while not stop.is_set():
                    # The real production read path (locked since v0.24).
                    state_lib.has_read(self.sid, probe)

            threads = [
                threading.Thread(target=reader, daemon=True)
                for _ in range(4)
            ]
            for t in threads:
                t.start()
            n = 200
            for i in range(n):
                state_lib.add_read(self.sid, str(self.tmpdir / f"f_{i}.txt"))
            stop.set()
            for t in threads:
                t.join(timeout=5)

            state = json.loads(state_file.read_text(encoding="utf-8"))
            # Basename prefix, not full-path substring: the old `"f_" in p`
            # also matched the DIRECTORY part, so a mkdtemp suffix containing
            # "f_" (8 random chars from [a-z0-9_], ~0.5%/run) counted seed.txt
            # too — CI 2026-08-19 failed 201 != 200 exactly this way, and the
            # trap-dir reproduction (TMP=...\trap_f_dir) fails deterministically.
            # test_bash_guard's substring needles all contain ".", which the
            # suffix alphabet cannot produce, so this was the class's only member.
            recorded = sum(
                1 for p in state.get("read_files", [])
                if os.path.basename(p).startswith("f_")
            )
            self.assertEqual(
                recorded, n,
                msg=(
                    f"lost {n - recorded}/{n} saves to reader collisions — "
                    "the os.replace retry regressed"
                ),
            )
            leftovers = list((self.tmpdir / "sessions").glob("*.tmp"))
            self.assertEqual(
                leftovers, [],
                msg=f"orphan temp files left by failed saves: {leftovers}",
            )
        finally:
            if old_env is None:
                os.environ.pop("CLAUDE_PLUGIN_DATA", None)
            else:
                os.environ["CLAUDE_PLUGIN_DATA"] = old_env


class TestUnreadableStateMutation(_GuardTestBase):
    """v0.24 adversarial-review finding: a mutator that cannot read the
    existing state file must SKIP its mutation, not proceed with the
    empty fallback record — saving that record back would erase every
    recorded read, edit, baseline and counter of the session (full
    amnesia amplified through the lock). Losing one mutation is the
    strictly smaller failure.
    """

    def test_unreadable_state_skips_mutation_instead_of_wiping(self) -> None:
        import os
        from unittest import mock
        sys.path.insert(0, str(SCRIPTS_DIR))
        from lib import state as state_lib

        old_env = os.environ.get("CLAUDE_PLUGIN_DATA")
        os.environ["CLAUDE_PLUGIN_DATA"] = str(self.tmpdir)
        try:
            seeded = str(self.tmpdir / "seeded.txt")
            state_lib.add_read(self.sid, seeded)
            state_file = self.tmpdir / "sessions" / f"{self.sid}.json"
            before = state_file.read_text(encoding="utf-8")
            # Every read_text raises → _load_for_mutation returns None
            # (after its one retry) → the mutator must bail out.
            with mock.patch.object(
                Path, "read_text", side_effect=OSError("scanner holds file"),
            ):
                state_lib.add_read(self.sid, str(self.tmpdir / "other.txt"))
            after = state_file.read_text(encoding="utf-8")
            self.assertEqual(
                before, after,
                msg=(
                    "an unreadable state file must not be overwritten by "
                    "an empty-record save — the session would lose all "
                    "recorded reads/edits/baselines"
                ),
            )
        finally:
            if old_env is None:
                os.environ.pop("CLAUDE_PLUGIN_DATA", None)
            else:
                os.environ["CLAUDE_PLUGIN_DATA"] = old_env


class TestDetectorHardeningV025(unittest.TestCase):
    """v0.25 — three detector defects found by the round-2 audit."""

    def setUp(self) -> None:
        self.tmpdir = Path(tempfile.mkdtemp(prefix="ccens-v025-"))
        self.env = {"CLAUDE_PLUGIN_DATA": str(self.tmpdir / "data")}
        self.sid = f"v025-{uuid.uuid4().hex[:8]}"

    def tearDown(self) -> None:
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _seen(self, path: Path) -> None:
        run_hook(
            [GUARD],
            {"session_id": self.sid, "hook_event_name": "PreToolUse",
             "tool_name": "Read", "tool_input": {"file_path": str(path)}},
            env_overrides=self.env,
        )

    def _edit(self, path: Path, new_string: str, sid: str | None = None):
        return run_hook(
            [GUARD],
            {"session_id": sid or self.sid, "hook_event_name": "PreToolUse",
             "tool_name": "Edit",
             "tool_input": {"file_path": str(path), "old_string": "zzz",
                            "new_string": new_string}},
            env_overrides=self.env,
        )

    def _decision(self, out) -> str:
        if out is None:
            return "allow"
        return out["hookSpecificOutput"]["permissionDecision"]

    # --- rule 09: bare try/except: pass ------------------------------- #
    def test_try_except_pass_variants(self) -> None:
        """A trailing comment must not defeat the detector, and a later
        except clause must still be inspected.

        Requiring the swallow line to be exactly `pass` meant `pass  # TODO`
        was ALLOWED — and, worse, it made the documented why-comment escape
        hatch unreachable, because a rationale comment silenced the marker
        by changing the string instead of by being read. Clearing the
        try-watch after the first except clause hid the canonical shape:
        a narrow handler followed by a catch-all that swallows everything.
        """
        nl = chr(10)
        cases = [
            ("bare pass", "try:" + nl + "    r()" + nl
             + "except Exception:" + nl + "    pass" + nl, "deny"),
            ("pass + non-rationale comment", "try:" + nl + "    r()" + nl
             + "except Exception:" + nl + "    pass  # TODO later" + nl, "deny"),
            ("pass + trailing semicolon", "try:" + nl + "    r()" + nl
             + "except Exception:" + nl + "    pass ;" + nl, "deny"),
            ("bare pass in 2nd except clause", "try:" + nl + "    r()" + nl
             + "except ValueError:" + nl + "    log()" + nl
             + "except Exception:" + nl + "    pass" + nl, "deny"),
            # The escape hatch must now actually work — this is the case
            # that used to pass vacuously.
            ("pass + rationale comment", "try:" + nl + "    r()" + nl
             + "except Exception:" + nl
             + "    # because upstream guarantees idempotency" + nl
             + "    pass" + nl, "allow"),
            ("handled except (no pass)", "try:" + nl + "    r()" + nl
             + "except Exception:" + nl + "    log()" + nl, "allow"),
        ]
        # A fresh file AND session per case: several of these edits are
        # "small" by the rule-09 classifier, so sharing one session would
        # let the rolling-patch counter deny the 4th ALLOWED case and make
        # this test fail for a reason that has nothing to do with the
        # detector under test.
        for i, (label, src, expected) in enumerate(cases):
            with self.subTest(case=label):
                sid = f"{self.sid}-tep{i}"
                target = self.tmpdir / f"mod{i}.py"
                target.write_text("zzz\n", encoding="utf-8")
                run_hook(
                    [GUARD],
                    {"session_id": sid, "hook_event_name": "PreToolUse",
                     "tool_name": "Read",
                     "tool_input": {"file_path": str(target)}},
                    env_overrides=self.env,
                )
                _, out, _ = self._edit(target, src, sid=sid)
                self.assertEqual(self._decision(out), expected, msg=label)

    # --- rule 10: quoted-key secrets ---------------------------------- #
    def test_quoted_key_secret_is_detected(self) -> None:
        """`"api_key": "…"` (JSON / quoted-key YAML) must deny.

        The old pattern required the separator to follow the keyword with
        only spaces between, so the key's closing quote blocked every
        match — waving through the single most common way a credential
        gets committed, while catching the rarer bare-key spelling.
        """
        cfg = self.tmpdir / "config.json"
        cfg.write_text("zzz\n", encoding="utf-8")
        self._seen(cfg)
        secret = "Xk9" + "mQ2vLp7"
        for label, body in [
            ("quoted key", '  "api_key": "' + secret + '"'),
            ("quoted key, single quotes", "  'password': '" + secret + "'"),
            ("bare key (pre-existing behaviour)", '  api_key: "' + secret + '"'),
        ]:
            with self.subTest(case=label):
                _, out, _ = self._edit(cfg, body)
                self.assertEqual(self._decision(out), "deny", msg=label)

    def test_quoted_key_placeholder_still_allowed(self) -> None:
        # The placeholder escape must survive the pattern widening.
        cfg = self.tmpdir / "config.json"
        cfg.write_text("zzz\n", encoding="utf-8")
        self._seen(cfg)
        _, out, _ = self._edit(cfg, '  "api_key": "your-key-here"')
        self.assertEqual(self._decision(out), "allow")

    # --- rule 04: phantom read ---------------------------------------- #
    def test_read_of_missing_path_grants_no_authorization(self) -> None:
        """Reading a path before it exists must not authorize a later edit.

        The old code recorded unconditionally, justified by "Edit's
        os.path.exists short-circuit covers it" — but that only holds
        while the file is still absent. Read a generated artifact before
        generating it (an everyday flow), let a build step create it, and
        rule 04 was silently off for that path for the rest of the session.
        """
        ghost = self.tmpdir / "generated.py"
        self._seen(ghost)                      # phantom read: does not exist
        ghost.write_text("content never seen by the agent\n", encoding="utf-8")
        _, out, _ = self._edit(ghost, "x = 1")
        self.assertEqual(
            self._decision(out), "deny",
            msg="edit landed on content the session never read",
        )
        # A Write (whole-file replacement) must be gated too.
        _, out, _ = run_hook(
            [GUARD],
            {"session_id": self.sid, "hook_event_name": "PreToolUse",
             "tool_name": "Write",
             "tool_input": {"file_path": str(ghost), "content": "wiped"}},
            env_overrides=self.env,
        )
        self.assertEqual(self._decision(out), "deny")

    def test_read_of_existing_path_still_authorizes(self) -> None:
        real = self.tmpdir / "real.py"
        real.write_text("zzz\n", encoding="utf-8")
        self._seen(real)
        _, out, _ = self._edit(real, "x = 1")
        self.assertEqual(self._decision(out), "allow")


class TestRationaleWindowContract(unittest.TestCase):
    """v0.25.1 — the rationale window must be exactly ±1 line.

    Five PATCH_MARKERS regexes end in `(?:\\n|$)` and so consume the
    marker line's terminating newline; `_line_window` then measured the
    "next line" from a position that was already past it, silently
    widening the documented "same line or immediately adjacent line"
    contract to TWO lines below the marker. An unrelated `# because …`
    two lines away suppressed the DENY. (The window above, and the
    bare try/except scanner whose span carries no newline, were ±1 all
    along — pinned here as controls.)
    """

    def setUp(self) -> None:
        self.tmpdir = Path(tempfile.mkdtemp(prefix="ccens-window-"))
        self.env = {"CLAUDE_PLUGIN_DATA": str(self.tmpdir / "data")}
        self.sid = f"window-{uuid.uuid4().hex[:8]}"

    def tearDown(self) -> None:
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _decide(self, new_string: str, case: str) -> str:
        sid = f"{self.sid}-{case}"
        target = self.tmpdir / f"win_{case}.py"
        target.write_text("zzz\n", encoding="utf-8")
        run_hook(
            [GUARD],
            {"session_id": sid, "hook_event_name": "PreToolUse",
             "tool_name": "Read", "tool_input": {"file_path": str(target)}},
            env_overrides=self.env,
        )
        _, out, _ = run_hook(
            [GUARD],
            {"session_id": sid, "hook_event_name": "PreToolUse",
             "tool_name": "Edit",
             "tool_input": {"file_path": str(target), "old_string": "zzz",
                            "new_string": new_string}},
            env_overrides=self.env,
        )
        if out is None:
            return "allow"
        return out["hookSpecificOutput"]["permissionDecision"]

    def test_rationale_two_lines_below_is_out_of_window(self) -> None:
        nl, nq = chr(10), "# no" + "qa"
        src = "x = unused  " + nq + nl + "y = 1" + nl \
            + "z = 2  # because unrelated" + nl
        self.assertEqual(self._decide(src, "below2"), "deny")

    def test_rationale_one_line_below_is_in_window(self) -> None:
        nl, nq = chr(10), "# no" + "qa"
        src = "x = unused  " + nq + nl \
            + "# because third-party stub is wrong" + nl + "y = 1" + nl
        self.assertEqual(self._decide(src, "below1"), "allow")

    def test_twin_same_layout_without_the_rationale_denies(self) -> None:
        """v0.26.0 — the missing half of the test above.

        Round-4 audit found the two window tests vacuous: both assert only
        ALLOW, and both pass on the pre-fix tree, so neither shows the
        marker detector fired at all. Removing ONLY the rationale — same
        layout, same line count — is what proves the window decided.
        """
        nl, nq = chr(10), "# no" + "qa"
        # No rationale TOKEN anywhere -- "third-party" is itself one, so a
        # naive twin would still be allowed and stay just as vacuous.
        src = "x = unused  " + nq + nl \
            + "# stub" + nl + "y = 1" + nl
        self.assertEqual(self._decide(src, "below1-twin"), "deny")

    def test_rationale_one_line_above_is_in_window(self) -> None:
        nl, nq = chr(10), "# no" + "qa"
        src = "# because third-party stub is wrong" + nl \
            + "x = unused  " + nq + nl + "y = 1" + nl
        self.assertEqual(self._decide(src, "above1"), "allow")

    def test_twin_same_layout_above_without_the_rationale_denies(self) -> None:
        nl, nq = chr(10), "# no" + "qa"
        src = "# stub" + nl \
            + "x = unused  " + nq + nl + "y = 1" + nl
        self.assertEqual(self._decide(src, "above1-twin"), "deny")

    def test_rationale_two_lines_above_is_out_of_window(self) -> None:
        # Control: the upward direction was never over-extended.
        nl, nq = chr(10), "# no" + "qa"
        src = "# because unrelated" + nl + "y = 1" + nl \
            + "x = unused  " + nq + nl
        self.assertEqual(self._decide(src, "above2"), "deny")


class TestDetectorHardeningV0251(unittest.TestCase):
    """v0.25.1 — the round-3 audit's read_guard findings.

    Every "a rationale allows this" case is paired with a TWIN that
    strips the rationale and asserts DENY. Without the twin a test can
    pass because the detector never fired at all, which is exactly how
    `test_ts_ignore_with_rationale_is_allowed` and v0.25's own
    `pass + rationale comment` case passed for years while the escape
    hatch they claimed to pin was unreachable.
    """

    NOQA = "# no" + "qa"
    TSIG = "//" + " @ts-" + "ignore"
    NL = chr(10)
    BS = chr(92)

    def setUp(self) -> None:
        self.tmpdir = Path(tempfile.mkdtemp(prefix="ccens-v0251-"))
        self.env = {"CLAUDE_PLUGIN_DATA": str(self.tmpdir / "data")}
        self.counter = 0

    def tearDown(self) -> None:
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _decide(self, new_string: str, suffix: str = ".py") -> str:
        """Edit a fresh file in a fresh session; return allow/deny.

        A new file + session per call keeps the rolling-patch counter
        from denying the 4th small edit for reasons unrelated to the
        detector under test.
        """
        self.counter += 1
        sid = f"v0251-{uuid.uuid4().hex[:8]}"
        target = self.tmpdir / f"t{self.counter}{suffix}"
        target.write_text("zzz\n", encoding="utf-8")
        run_hook(
            [GUARD],
            {"session_id": sid, "hook_event_name": "PreToolUse",
             "tool_name": "Read", "tool_input": {"file_path": str(target)}},
            env_overrides=self.env,
        )
        _, out, _ = run_hook(
            [GUARD],
            {"session_id": sid, "hook_event_name": "PreToolUse",
             "tool_name": "Edit",
             "tool_input": {"file_path": str(target), "old_string": "zzz",
                            "new_string": new_string}},
            env_overrides=self.env,
        )
        if out is None:
            return "allow"
        return out["hookSpecificOutput"]["permissionDecision"]

    # --- rule 09: marker spellings ------------------------------------ #
    def test_crlf_does_not_defeat_markers(self) -> None:
        """CRLF is the norm on this plugin's primary platform.

        The five single-line markers anchored on `[ \\t]*\\n`, which
        cannot match `\\r\\n`, so every one of them was silently off for
        a CRLF file.
        """
        for label, eol in [("LF", self.NL), ("CRLF", chr(13) + self.NL)]:
            with self.subTest(eol=label):
                self.assertEqual(
                    self._decide("x = y  " + self.NOQA + eol), "deny",
                )

    def test_trailing_text_reaches_the_rationale_check(self) -> None:
        """A suffix must not make the marker invisible.

        A marker followed by a bare deferral keyword used to match
        nothing at all, so it was allowed without the rationale check
        ever running. A deferral is not a reason; an explanation is.
        """
        cases = [
            ("bare", self.TSIG, "deny"),
            ("deferral suffix", self.TSIG + ": TO" + "DO", "deny"),
            ("deferral suffix, wordy",
             self.TSIG + ": TO" + "DO fix this later", "deny"),
            ("explanation suffix",
             self.TSIG + ": upstream types are wrong for Node 20", "allow"),
        ]
        for label, marker, expected in cases:
            with self.subTest(case=label):
                self.assertEqual(
                    self._decide(marker + self.NL + "legacy();" + self.NL),
                    expected, msg=label,
                )

    def test_nested_call_in_sleep_still_detected(self) -> None:
        for label, call in [("flat", "time.sleep(0.5)"),
                            ("nested", "time.sleep(max(0, delay))"),
                            ("nested cast", "time.sleep(float(delay))")]:
            with self.subTest(case=label):
                self.assertEqual(
                    self._decide(call + "  # workaround" + self.NL), "deny",
                )

    # --- rule 09: try/except/pass layouts ----------------------------- #
    def _try_block(self, handler_body: str) -> str:
        return ("try:" + self.NL + "    risky()" + self.NL
                + "except Exception:" + self.NL + handler_body)

    def test_swallow_layouts_and_rationale_twins(self) -> None:
        """Layout must not decide the verdict; the rationale must.

        The own-line-rationale pair is the load-bearing one: before
        v0.25.1 the ALLOW half passed because a comment between the
        handler header and the swallow moved the swallow out of the
        scanner's sight, so `_has_rationale` was never consulted. The
        DENY twin (same layout, non-reason comment) is what proves the
        escape hatch is now genuinely reachable.
        """
        deferral = "# TO" + "DO revisit"
        reason = "# because upstream guarantees idempotency"
        cases = [
            ("bare pass", "    pass" + self.NL, "deny"),
            ("own-line rationale",
             "    " + reason + self.NL + "    pass" + self.NL, "allow"),
            ("own-line non-reason TWIN",
             "    " + deferral + self.NL + "    pass" + self.NL, "deny"),
            ("same-line rationale",
             "    pass  " + reason + self.NL, "allow"),
            ("same-line non-reason TWIN",
             "    pass  " + deferral + self.NL, "deny"),
            ("handled, no pass", "    log()" + self.NL, "allow"),
        ]
        for label, body, expected in cases:
            with self.subTest(case=label):
                self.assertEqual(
                    self._decide(self._try_block(body)), expected, msg=label,
                )

    def test_one_liner_handler_is_detected(self) -> None:
        src = ("try:" + self.NL + "    risky()" + self.NL
               + "except Exception: " + "pass" + self.NL)
        self.assertEqual(self._decide(src), "deny")

    def test_justified_swallow_does_not_hide_a_later_one(self) -> None:
        """Only the FIRST hit used to be inspected."""
        src = ("try:" + self.NL + "    a()" + self.NL
               + "except ValueError:" + self.NL
               + "    pass  # because a missing row is optional here" + self.NL
               + "try:" + self.NL + "    b()" + self.NL
               + "except Exception:" + self.NL + "    pass" + self.NL)
        self.assertEqual(self._decide(src), "deny")

    # --- rule 09: rationale must be a comment ------------------------- #
    def test_rationale_must_live_in_a_comment(self) -> None:
        code_token = ("reason = compute()" + self.NL
                      + "x = legacy()  " + self.NOQA + self.NL)
        comment_token = ("# reason: third-party stub is wrong" + self.NL
                         + "x = legacy()  " + self.NOQA + self.NL)
        self.assertEqual(self._decide(code_token), "deny",
                         msg="an identifier is not a why-comment")
        self.assertEqual(self._decide(comment_token), "allow")

    # --- prose docs keep their pre-v0.25.1 behaviour ------------------ #
    def test_prose_marker_behaviour_is_unchanged(self) -> None:
        """.md must not become a false-positive farm.

        This repo's own docs mention the marker spellings 54 times, all
        with trailing text. Prose therefore keeps matching only the BARE
        form — identical to the pre-v0.25.1 anchored patterns.
        """
        bare = "x = y  " + self.NOQA + self.NL
        # Short trailing text (a table cell / list item) is not an
        # explanation, so this is exactly where prose and code differ.
        tabulated = "| `" + self.NOQA + "` |" + self.NL
        explained = "- `" + self.NOQA + "` is a lint suppression" + self.NL
        self.assertEqual(self._decide(bare, suffix=".md"), "deny",
                         msg="the bare form is denied in prose, as before")
        self.assertEqual(self._decide(tabulated, suffix=".md"), "allow")
        self.assertEqual(self._decide(tabulated, suffix=".py"), "deny",
                         msg="code must not get the prose allowance")
        # A substantive trailing explanation justifies the marker in any
        # file type — that is the rationale contract, not an exemption.
        self.assertEqual(self._decide(explained, suffix=".py"), "allow")

    # --- rule 10 -------------------------------------------------------- #
    def test_type_annotation_relief_is_scoped_to_colon(self) -> None:
        pw = "pass" + "word"
        self.assertEqual(
            self._decide(pw + ': "SecretStr"' + self.NL), "allow",
            msg="forward-reference annotation is not a credential",
        )
        self.assertEqual(
            self._decide(pw + ' = "SuperSecret"' + self.NL), "deny",
            msg="an `=` assignment of the same shape IS a credential",
        )

    def test_provider_token_literals_are_detected(self) -> None:
        real = "gh" + "p_" + "A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q7r8"
        self.assertEqual(self._decide("t = " + '"' + real + '"' + self.NL),
                         "deny")

    def test_placeholder_url_is_allowed(self) -> None:
        """Placeholder filtering used to gate only the keyword branch."""
        url = "DSN = " + '"postgres://user:redacted@host/db"' + self.NL
        self.assertEqual(self._decide(url), "allow")

    # --- rule 11 -------------------------------------------------------- #
    def test_escaped_windows_path_is_detected(self) -> None:
        """A doubled separator is how the path appears in real source."""
        bs2 = self.BS * 2
        for label, sep in [("single backslash", self.BS),
                           ("escaped backslash", bs2),
                           ("forward slash", "/")]:
            with self.subTest(case=label):
                line = ('p = "C:' + sep + "Users" + sep + 'bob"' + self.NL)
                self.assertEqual(self._decide(line), "deny", msg=label)


class TestStateSchemaTolerance(unittest.TestCase):
    """v0.25.1 — valid JSON with the wrong shape must not break gating."""

    def setUp(self) -> None:
        self.tmpdir = Path(tempfile.mkdtemp(prefix="ccens-schema-"))
        self.data = self.tmpdir / "data"
        (self.data / "sessions").mkdir(parents=True)
        self.env = {"CLAUDE_PLUGIN_DATA": str(self.data)}
        self.target = self.tmpdir / "mod.py"
        self.target.write_text("zzz\n", encoding="utf-8")

    def tearDown(self) -> None:
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _edit_decision(self, sid: str) -> str:
        _, out, _ = run_hook(
            [GUARD],
            {"session_id": sid, "hook_event_name": "PreToolUse",
             "tool_name": "Edit",
             "tool_input": {"file_path": str(self.target),
                            "old_string": "zzz", "new_string": "x = 1"}},
            env_overrides=self.env,
        )
        if out is None:
            return "allow"
        return out["hookSpecificOutput"]["permissionDecision"]

    def test_list_shaped_state_does_not_bypass_the_gate(self) -> None:
        """A top-level `[]` raised AttributeError inside has_read.

        read_guard's outer handler swallowed it as failing-open, so an
        unread file became editable.
        """
        sid = "schema-list"
        (self.data / "sessions" / f"{sid}.json").write_text(
            "[]", encoding="utf-8")
        self.assertEqual(self._edit_decision(sid), "deny")

    def test_dict_without_read_files_still_records(self) -> None:
        """A top-level `{}` raised KeyError inside add_read.

        The Read was then never recorded and the next edit was falsely
        denied.
        """
        sid = "schema-empty"
        (self.data / "sessions" / f"{sid}.json").write_text(
            "{}", encoding="utf-8")
        run_hook(
            [GUARD],
            {"session_id": sid, "hook_event_name": "PreToolUse",
             "tool_name": "Read",
             "tool_input": {"file_path": str(self.target)}},
            env_overrides=self.env,
        )
        self.assertEqual(self._edit_decision(sid), "allow")


class TestStateUnreadableFailsOpen(unittest.TestCase):
    """v0.25 — an unreadable state file must not become a false DENY.

    `load()` degrades an unreadable record to an EMPTY one, and for
    `has_read` "empty" is a positive assertion of "never read" — which
    read_guard turns into a hard DENY. So a transient Windows sharing
    violation (the same cause `save()` already retries against) produced
    the exact false "you have not Read this file" DENY that v0.23/v0.24
    were chasing, while stderr simultaneously announced "failing open".
    """

    def setUp(self) -> None:
        self.tmpdir = Path(tempfile.mkdtemp(prefix="ccens-failopen-"))
        self.env = {"CLAUDE_PLUGIN_DATA": str(self.tmpdir / "data")}
        self.sid = f"failopen-{uuid.uuid4().hex[:8]}"

    def tearDown(self) -> None:
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_unreadable_state_allows_instead_of_denying(self) -> None:
        target = self.tmpdir / "mod.py"
        target.write_text("zzz\n", encoding="utf-8")
        edit_payload = {
            "session_id": self.sid, "hook_event_name": "PreToolUse",
            "tool_name": "Edit",
            "tool_input": {"file_path": str(target), "old_string": "zzz",
                           "new_string": "x = 1"},
        }
        # Control: never read -> deny (state file readable, simply empty).
        _, out, _ = run_hook([GUARD], edit_payload, env_overrides=self.env)
        self.assertIsNotNone(out, msg="control: unread file must deny")

        # Now make the state file exist-but-unreadable. A directory in its
        # place raises OSError on read_text exactly like a sharing
        # violation that outlives the single retry.
        state_file = self.tmpdir / "data" / "sessions" / f"{self.sid}.json"
        self.assertTrue(state_file.is_file(), msg="expected state to exist")
        state_file.unlink()
        state_file.mkdir()
        _, out, err = run_hook([GUARD], edit_payload, env_overrides=self.env)
        self.assertIsNone(
            out,
            msg="unreadable state produced a false read-before-edit DENY "
                "instead of failing open",
        )


class TestPluginIsSelfRewritable(unittest.TestCase):
    """v0.25 — every production hook script must survive its OWN detectors.

    A script containing a bare `# noqa` / `try: … except: pass` cannot be
    rewritten by any agent running this plugin: read_guard DENIES the
    Write. v0.23 recognised the failure mode and fixed exactly one file
    (lib/sync_gate.py's bare `# type: ignore`, whose commit message notes
    that otherwise "the plugin's own rule 09 guard would refuse to let
    anyone rewrite it") — but never swept the rest of the tree, which is
    the very repo-wide-sync omission rule 12 exists to catch. Five of the
    twelve scripts were still self-locked:

        bash_guard.py, gc_state.py, manage_edicts.py, read_guard.py
            → bare `# noqa: E402` on the sys.path-bootstrap imports
        inject_context.py
            → bare `try: sys.stdin.read() / except Exception: pass`

    The house pattern for a legitimate suppression is stop_guard.py's:
    the marker stays, and an adjacent line carries the rationale. This
    test pins the invariant for the whole tree so a new script cannot
    reintroduce the lock.
    """

    def setUp(self) -> None:
        self.tmpdir = Path(tempfile.mkdtemp(prefix="ccens-selfwrite-"))
        self.env = {"CLAUDE_PLUGIN_DATA": str(self.tmpdir)}

    def tearDown(self) -> None:
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _production_scripts(self) -> list[Path]:
        scripts = sorted(SCRIPTS_DIR.glob("*.py"))
        scripts += sorted((SCRIPTS_DIR / "lib").glob("*.py"))
        # v0.26.0 — the test tree is in scope too. The docstring above
        # already claimed this test "pins the invariant for the whole
        # tree", but the glob covered only hooks/scripts, and ALL SEVEN
        # test modules were in fact self-locked by the same bare lint
        # suppression on their own sys.path bootstrap — the identical
        # marker, in the identical position, that this class was created
        # to fix five scripts for. Fixing the observed instances and not
        # sweeping the rest is the audit's root cause beta; a claim
        # outrunning its glob is root cause gamma. Widening the glob
        # closes both. (The marker is not spelled out here: this file is
        # itself in scope now, and a bare mention would self-lock it.)
        scripts += sorted(Path(__file__).resolve().parent.glob("*.py"))
        return [p for p in scripts if p.name != "__init__.py"]

    def test_every_hook_script_can_be_rewritten(self) -> None:
        scripts = self._production_scripts()
        self.assertGreaterEqual(
            len(scripts), 10,
            msg="script discovery looks wrong — expected the full hook tree",
        )
        for script in scripts:
            with self.subTest(script=script.name):
                sid = f"selfwrite-{script.stem}-{uuid.uuid4().hex[:8]}"
                # Register the file as read so only the CONTENT detectors
                # (rule 09 / 10 / 11 + edicts) can produce a deny.
                rc, _, _ = run_hook(
                    [GUARD],
                    {
                        "session_id": sid,
                        "hook_event_name": "PreToolUse",
                        "tool_name": "Read",
                        "tool_input": {"file_path": str(script)},
                    },
                    env_overrides=self.env,
                )
                self.assertEqual(rc, 0)
                rc, out, err = run_hook(
                    [GUARD],
                    {
                        "session_id": sid,
                        "hook_event_name": "PreToolUse",
                        "tool_name": "Write",
                        "tool_input": {
                            "file_path": str(script),
                            "content": script.read_text(encoding="utf-8"),
                        },
                    },
                    env_overrides=self.env,
                )
                self.assertEqual(rc, 0, msg=err)
                if out is not None:
                    reason = out["hookSpecificOutput"]["permissionDecisionReason"]
                    label = next(
                        (ln for ln in reason.splitlines()
                         if ln.startswith("Pattern matched:")),
                        reason.splitlines()[0] if reason else "",
                    )
                    self.fail(
                        f"{script.name} is self-locked: rewriting it verbatim "
                        f"is DENIED by this plugin's own content detectors. "
                        f"{label}. Add an adjacent rationale comment (see "
                        f"stop_guard.py's `# noqa: E402 … because …` line)."
                    )


if __name__ == "__main__":
    unittest.main()
