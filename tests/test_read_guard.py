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

    def test_state_persists_edits_per_file_field(self) -> None:
        # Quick sanity check that the JSON field name is what other tools
        # (e.g. /cc-enslaver:gc, future tooling) can rely on.
        target = self._writable_target()
        self._pre("Read", target)
        self._do_small_edit(target)
        state = self._state()
        self.assertIn("edits_per_file", state)
        self.assertEqual(len(state["edits_per_file"]), 1)
        self.assertEqual(list(state["edits_per_file"].values()), [1])


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
