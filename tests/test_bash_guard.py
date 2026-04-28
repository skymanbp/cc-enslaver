"""Tests for hooks/scripts/bash_guard.py.

Each row in the matrix below specifies the bypass pattern (or absence
thereof), the bash command, and the expected hook decision. A driver
test runs every row through the guard and asserts on the decision.

This is the regression suite for the bypass-pattern catalog: any new
pattern added to bash_guard.py must come with a positive case (deny)
and at least one nearby negative case (allow) in this file.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _helpers import SCRIPTS_DIR, run_hook  # noqa: E402

GUARD = str(SCRIPTS_DIR / "bash_guard.py")


def _invoke(command: str) -> tuple[int, dict | None, str]:
    return run_hook(
        [GUARD],
        {
            "session_id": "test",
            "hook_event_name": "PreToolUse",
            "tool_name": "Bash",
            "tool_input": {"command": command},
        },
    )


# Each case: (description, command, expected_decision, expected_substring_in_reason)
# expected_decision in {"allow", "deny"}; substring is None for allow.
CASES: list[tuple[str, str, str, str | None]] = [
    # ----- ALLOW: ordinary commands -----
    ("plain echo", "echo hello", "allow", None),
    ("git status", "git status", "allow", None),
    ("git push origin main", "git push origin main", "allow", None),
    ("git push --force-with-lease", "git push --force-with-lease origin main", "allow", None),
    ("git push --force-with-lease=refspec", "git push --force-with-lease=refs/heads/main", "allow", None),
    ("chmod 755", "chmod 755 file.txt", "allow", None),
    ("chmod symbolic mode", "chmod u+rwx file.txt", "allow", None),
    ("rm -rf node_modules", "rm -rf node_modules", "allow", None),
    ("flag superstring of --no-verify", "git commit --no-verify-extra", "allow", None),
    ("force outside git push context", "echo --force >> notes.txt", "allow", None),

    # ----- DENY: --no-verify -----
    ("git commit --no-verify", 'git commit -m "x" --no-verify', "deny", "no-verify"),
    ("--no-verify at end", "git commit -am foo --no-verify", "deny", "no-verify"),

    # ----- DENY: --no-gpg-sign -----
    ("git commit --no-gpg-sign", 'git commit -m "x" --no-gpg-sign', "deny", "no-gpg-sign"),

    # ----- DENY: git push --force / -f -----
    ("git push --force", "git push --force origin main", "deny", "force"),
    ("git push -f short flag", "git push -f origin main", "deny", "force"),
    ("git push --force at end", "git push origin main --force", "deny", "force"),

    # ----- DENY: chmod 777 variants -----
    ("chmod 777 file", "chmod 777 file.txt", "deny", "777"),
    ("chmod -R 777 dir", "chmod -R 777 dir/", "deny", "777"),
    ("chmod 0777", "chmod 0777 file.txt", "deny", "777"),
    ("chmod -R 0777", "chmod -R 0777 dir/", "deny", "777"),
]


class TestBashGuardMatrix(unittest.TestCase):
    """One assertion per matrix row — each gets its own .subTest scope."""

    def test_all_cases(self) -> None:
        for desc, cmd, expected, substring in CASES:
            with self.subTest(case=desc, cmd=cmd):
                rc, out, err = _invoke(cmd)
                self.assertEqual(rc, 0, msg=err)

                if expected == "allow":
                    self.assertIsNone(
                        out,
                        msg=f"expected silent allow, got {out!r}",
                    )
                else:  # deny
                    self.assertIsNotNone(out, msg="expected deny output")
                    spec = out["hookSpecificOutput"]
                    self.assertEqual(spec["hookEventName"], "PreToolUse")
                    self.assertEqual(spec["permissionDecision"], "deny")
                    if substring is not None:
                        self.assertIn(
                            substring,
                            spec["permissionDecisionReason"],
                            msg=f"reason missing expected substring {substring!r}",
                        )


class TestBashGuardEventGating(unittest.TestCase):
    """The guard must ignore non-PreToolUse / non-Bash payloads silently."""

    def test_post_tool_use_is_ignored(self) -> None:
        # A force-push command via PostToolUse must not produce a deny.
        rc, out, _ = run_hook(
            [GUARD],
            {
                "session_id": "test",
                "hook_event_name": "PostToolUse",
                "tool_name": "Bash",
                "tool_input": {"command": "git push --force"},
            },
        )
        self.assertEqual(rc, 0)
        self.assertIsNone(out)

    def test_non_bash_tool_is_ignored(self) -> None:
        # PreToolUse for a different tool with bypass-looking input
        # should not trigger this guard. (read_guard handles Edit/Write.)
        rc, out, _ = run_hook(
            [GUARD],
            {
                "session_id": "test",
                "hook_event_name": "PreToolUse",
                "tool_name": "Edit",
                "tool_input": {"file_path": "x.py", "old_string": "--no-verify", "new_string": ""},
            },
        )
        self.assertEqual(rc, 0)
        self.assertIsNone(out)


class TestBashGuardFailOpen(unittest.TestCase):
    def test_malformed_stdin_does_not_block(self) -> None:
        import subprocess

        proc = subprocess.run(
            [sys.executable, GUARD],
            input=b"not json",
            capture_output=True,
        )
        self.assertEqual(proc.returncode, 0)
        self.assertEqual(proc.stdout.strip(), b"")
        self.assertIn(b"bash_guard exception", proc.stderr)


class TestBashGuardRegisterFlow(unittest.TestCase):
    """v0.4.0 read-cache escape hatch: bash_guard intercepts register_read.py
    invocations, validates --hash against on-disk content, and either
    registers the file in session state (ALLOW) or denies with diagnostic."""

    def setUp(self) -> None:
        import hashlib
        import shutil
        import tempfile

        self.tmpdir = Path(tempfile.mkdtemp(prefix="alaz-bg-reg-"))
        self.fpath = self.tmpdir / "fixture.bin"
        self.content = b"bash_guard register-flow fixture content\n"
        self.fpath.write_bytes(self.content)
        self.correct = hashlib.sha256(self.content).hexdigest()
        self.state_dir = self.tmpdir / "data"
        self.env = {"CLAUDE_PLUGIN_DATA": str(self.state_dir)}
        self.sid = "bg-reg-test-session"
        self._shutil = shutil

    def tearDown(self) -> None:
        self._shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _call(self, command: str):
        return run_hook(
            [GUARD],
            {
                "session_id": self.sid,
                "hook_event_name": "PreToolUse",
                "tool_name": "Bash",
                "tool_input": {"command": command},
            },
            env_overrides=self.env,
        )

    def _reg_cmd(self, file_path, hash_val) -> str:
        return (
            'python "/path/to/register_read.py" '
            '--file "%s" --hash %s' % (file_path, hash_val)
        )

    def test_correct_hash_allows_and_records(self) -> None:
        rc, out, err = self._call(self._reg_cmd(self.fpath, self.correct))
        self.assertEqual(rc, 0, msg=err)
        self.assertIsNone(out, msg="expected silent allow on valid registration")
        sessions = list((self.state_dir / "sessions").glob("*.json"))
        self.assertEqual(len(sessions), 1)
        import json

        state = json.loads(sessions[0].read_text(encoding="utf-8"))
        self.assertTrue(any("fixture.bin" in p for p in state["read_files"]))

    def test_wrong_hash_denies(self) -> None:
        rc, out, _ = self._call(self._reg_cmd(self.fpath, "0" * 64))
        self.assertEqual(rc, 0)
        self.assertEqual(out["hookSpecificOutput"]["permissionDecision"], "deny")
        self.assertIn(
            "hash mismatch",
            out["hookSpecificOutput"]["permissionDecisionReason"],
        )
        # State must not contain the file (deny means not registered).
        sessions = list((self.state_dir / "sessions").glob("*.json"))
        if sessions:
            import json

            state = json.loads(sessions[0].read_text(encoding="utf-8"))
            self.assertFalse(any("fixture.bin" in p for p in state["read_files"]))

    def test_missing_file_denies(self) -> None:
        ghost = self.tmpdir / "ghost.txt"
        rc, out, _ = self._call(self._reg_cmd(ghost, self.correct))
        self.assertEqual(out["hookSpecificOutput"]["permissionDecision"], "deny")
        self.assertIn(
            "does not exist",
            out["hookSpecificOutput"]["permissionDecisionReason"],
        )

    def test_relative_path_denies(self) -> None:
        rc, out, _ = self._call(self._reg_cmd("relative/foo.txt", self.correct))
        self.assertEqual(out["hookSpecificOutput"]["permissionDecision"], "deny")
        self.assertIn(
            "absolute", out["hookSpecificOutput"]["permissionDecisionReason"]
        )

    def test_bad_hash_format_denies(self) -> None:
        rc, out, _ = self._call(self._reg_cmd(self.fpath, "NOT-HEX"))
        self.assertEqual(out["hookSpecificOutput"]["permissionDecision"], "deny")
        self.assertIn(
            "64 lowercase hex",
            out["hookSpecificOutput"]["permissionDecisionReason"],
        )

    def test_non_register_command_falls_through(self) -> None:
        # A command that has nothing to do with register_read.py should
        # fall through to bypass-pattern checks and return allow if clean.
        rc, out, _ = self._call("echo hello")
        self.assertEqual(rc, 0)
        self.assertIsNone(out)


if __name__ == "__main__":
    unittest.main()
