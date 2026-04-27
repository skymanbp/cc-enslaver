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


if __name__ == "__main__":
    unittest.main()
