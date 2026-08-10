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

    # ----- v0.14 new patterns: git rebase --skip -----
    ("git rebase --skip", "git rebase --skip", "deny", "git rebase"),
    ("git rebase mid-cmd --skip", "git rebase --onto main HEAD~3 --skip", "deny", "--skip"),
    ("git rebase plain (no --skip)", "git rebase main", "allow", None),
    # Note: echo "git rebase --skip" inside a string would false-positive
    # here, same as `echo "--no-verify"` does for the --no-verify pattern.
    # Accepted trade-off: rare false-positive < agents actually running --skip.

    # ----- v0.14 new patterns: --break-system-packages -----
    ("pip install --break-system-packages", "pip install requests --break-system-packages", "deny", "break-system-packages"),
    ("pip3 install --break-system-packages mid", "pip3 install --break-system-packages requests", "deny", "break-system-packages"),
    ("pip install normal", "pip install requests", "allow", None),
    ("python -m pip with venv", "python -m pip install requests", "allow", None),

    # ----- v0.14 new patterns: rm -rf on root / $HOME / ~ -----
    ("rm -rf /", "rm -rf /", "deny", "rm -rf"),
    ("rm -rf / with trailing args", "rm -rf / --no-preserve-root", "deny", "rm -rf"),
    ("rm -rf /etc", "rm -rf /etc", "deny", "rm -rf"),
    ("rm -rf /usr", "rm -rf /usr/local/share", "deny", "rm -rf"),
    ("rm -rf $HOME", "rm -rf $HOME", "deny", "rm -rf"),
    ("rm -rf $HOME/.config", "rm -rf $HOME/.config", "deny", "rm -rf"),
    ("rm -rf ~", "rm -rf ~", "deny", "rm -rf"),
    ("rm -rf ~/", "rm -rf ~/", "deny", "rm -rf"),
    ("rm -rf ./node_modules (allow)", "rm -rf ./node_modules", "allow", None),
    ("rm -rf /tmp/foo (allow)", "rm -rf /tmp/foo", "allow", None),
    ("rm -rf relative path (allow)", "rm -rf build/", "allow", None),
    ("rm without -r (allow)", "rm /etc/myfile", "allow", None),
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

        self.tmpdir = Path(tempfile.mkdtemp(prefix="ccens-bg-reg-"))
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


class TestRegisterChainingBypass(unittest.TestCase):
    """v0.25 — a register_read invocation must not shield the rest of a
    compound command from the bypass-pattern catalog.

    Root cause (v0.4.0-v0.24.0): `main()` returned 0 the moment a
    registration succeeded, so every static pattern, the force-push
    detector, and the edict scan were skipped for the WHOLE command
    string. Any bypass chained after a valid registration rode through:

        python .../register_read.py --file F --hash H && git push --force

    was ALLOWED. Registration and bypass-scanning are orthogonal concerns
    and both must run; the deny checks now run FIRST, and the file is
    registered only when the command is otherwise clean (same ordering
    principle as v0.24's read_guard fix, where a DENIED Write must not
    grant read-before-edit authorization).
    """

    def setUp(self) -> None:
        import hashlib
        import shutil
        import tempfile

        self.tmpdir = Path(tempfile.mkdtemp(prefix="ccens-bg-chain-"))
        self.fpath = self.tmpdir / "fixture.bin"
        content = b"chaining-bypass fixture content\n"
        self.fpath.write_bytes(content)
        self.correct = hashlib.sha256(content).hexdigest()
        self.state_dir = self.tmpdir / "data"
        self.env = {"CLAUDE_PLUGIN_DATA": str(self.state_dir)}
        self._shutil = shutil

    def tearDown(self) -> None:
        self._shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _call(self, command: str, sid: str):
        return run_hook(
            [GUARD],
            {
                "session_id": sid,
                "hook_event_name": "PreToolUse",
                "tool_name": "Bash",
                "tool_input": {"command": command},
            },
            env_overrides=self.env,
        )

    def _reg_cmd(self) -> str:
        return (
            'python "/path/to/register_read.py" '
            '--file "%s" --hash %s' % (self.fpath, self.correct)
        )

    def _recorded_paths(self) -> list[str]:
        import json

        out: list[str] = []
        sessions_dir = self.state_dir / "sessions"
        if not sessions_dir.is_dir():
            return out
        for f in sessions_dir.glob("*.json"):
            try:
                out.extend(json.loads(f.read_text(encoding="utf-8"))
                           .get("read_files", []))
            except (OSError, json.JSONDecodeError):
                continue
        return out

    def test_chained_bypasses_are_denied(self) -> None:
        chained = [
            ("force-push", " && git push --force origin main", "force"),
            ("no-verify", ' && git commit -m x --no-verify', "no-verify"),
            ("chmod 777", " ; chmod 777 /tmp/x", "777"),
            ("no-gpg-sign", " && git commit -m x --no-gpg-sign", "no-gpg-sign"),
            ("rebase --skip", " && git rebase --skip", "--skip"),
        ]
        for i, (label, tail, substring) in enumerate(chained):
            with self.subTest(bypass=label):
                sid = f"chain-deny-{i}"
                rc, out, err = self._call(self._reg_cmd() + tail, sid)
                self.assertEqual(rc, 0, msg=err)
                self.assertIsNotNone(
                    out,
                    msg=f"{label} chained after a registration was ALLOWED "
                        f"— the bypass catalog was skipped",
                )
                spec = out["hookSpecificOutput"]
                self.assertEqual(spec["permissionDecision"], "deny")
                self.assertIn(substring, spec["permissionDecisionReason"])

    def test_denied_chain_does_not_register(self) -> None:
        # Ordering contract: the deny checks run BEFORE registration, so a
        # command that is going to be denied never mutates session state.
        self._call(self._reg_cmd() + " && git push --force", "chain-noreg")
        self.assertFalse(
            any("fixture.bin" in p for p in self._recorded_paths()),
            msg="a DENIED compound command still registered its file as read",
        )

    def test_clean_registration_still_allows_and_records(self) -> None:
        # Guard against over-fixing: a bare, clean registration must keep
        # working exactly as before.
        rc, out, err = self._call(self._reg_cmd(), "chain-clean")
        self.assertEqual(rc, 0, msg=err)
        self.assertIsNone(out, msg="clean registration must still ALLOW")
        self.assertTrue(
            any("fixture.bin" in p for p in self._recorded_paths()),
            msg="clean registration failed to record the file",
        )


class TestRegisterPathSpellings(unittest.TestCase):
    """v0.25 — `shlex.split(..., posix=True)` destroys unquoted Windows
    backslash paths, making the read-cache escape hatch unusable with the
    path spelling this plugin's own primary platform produces.

    `C:\\Users\\me\\note.txt` came back out of shlex as
    `C:Usersmenote.txt`, so `_handle_register_invocation` denied with
    "file does not exist on disk" — the recovery mechanism for a false
    rule-04 DENY was itself broken. The existing register tests all quote
    the path (`--file "%s"`), and quoting happens to survive posix
    splitting, which is why this went unnoticed for 21 releases.
    """

    def setUp(self) -> None:
        import hashlib
        import shutil
        import tempfile

        self.tmpdir = Path(tempfile.mkdtemp(prefix="ccens-bg-spell-"))
        self.fpath = self.tmpdir / "fixture.bin"
        content = b"path-spelling fixture content\n"
        self.fpath.write_bytes(content)
        self.correct = hashlib.sha256(content).hexdigest()
        self.state_dir = self.tmpdir / "data"
        self.env = {"CLAUDE_PLUGIN_DATA": str(self.state_dir)}
        self._shutil = shutil

    def tearDown(self) -> None:
        self._shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _call(self, command: str, sid: str):
        return run_hook(
            [GUARD],
            {
                "session_id": sid,
                "hook_event_name": "PreToolUse",
                "tool_name": "Bash",
                "tool_input": {"command": command},
            },
            env_overrides=self.env,
        )

    def _registered(self) -> bool:
        import json

        sessions_dir = self.state_dir / "sessions"
        if not sessions_dir.is_dir():
            return False
        for f in sessions_dir.glob("*.json"):
            try:
                paths = json.loads(f.read_text(encoding="utf-8")).get(
                    "read_files", [])
            except (OSError, json.JSONDecodeError):
                continue
            if any("fixture.bin" in p for p in paths):
                return True
        return False

    def test_all_four_spellings_register(self) -> None:
        native = str(self.fpath)
        forward = native.replace("\\", "/")
        spellings = [
            ("native unquoted", f"--file {native}"),
            ("native quoted", f'--file "{native}"'),
            ("forward unquoted", f"--file {forward}"),
            ("forward quoted", f'--file "{forward}"'),
        ]
        for i, (label, file_arg) in enumerate(spellings):
            with self.subTest(spelling=label):
                self._shutil.rmtree(self.state_dir, ignore_errors=True)
                cmd = (
                    'python "/path/to/register_read.py" '
                    f"{file_arg} --hash {self.correct}"
                )
                rc, out, err = self._call(cmd, f"spell-{i}")
                self.assertEqual(rc, 0, msg=err)
                self.assertIsNone(
                    out,
                    msg=f"{label} path was rejected: "
                        f"{(out or {}).get('hookSpecificOutput', {}).get('permissionDecisionReason', '')[:200]}",
                )
                self.assertTrue(
                    self._registered(),
                    msg=f"{label} path did not land in session state",
                )


if __name__ == "__main__":
    unittest.main()
