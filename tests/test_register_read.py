"""Tests for hooks/scripts/register_read.py (the user-facing stub).

The stub itself only verifies that the agent's claimed --hash matches
the on-disk SHA-256. The actual state mutation is performed by
`bash_guard.py` in the PreToolUse hook (covered by test_bash_guard.py).

These tests verify:
  - Correct hash → exit 0
  - Wrong hash → exit 3 (reserved for hash mismatch)
  - Missing file → exit 2
  - Non-absolute path → exit 1 (bad-args)
  - Bad hash format → handled by argparse / first check
"""

from __future__ import annotations

import hashlib
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _helpers import SCRIPTS_DIR  # noqa: E402

STUB = str(SCRIPTS_DIR / "register_read.py")


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class TestRegisterReadStub(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = Path(tempfile.mkdtemp(prefix="ccens-reg-"))
        self.fpath = self.tmpdir / "fixture.bin"
        self.content = b"register_read stub test fixture\nline2\n"
        self.fpath.write_bytes(self.content)
        self.correct_hash = _sha256(self.content)

    def tearDown(self) -> None:
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _run(self, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, STUB, *args],
            capture_output=True,
        )

    def test_correct_hash_returns_zero(self) -> None:
        proc = self._run("--file", str(self.fpath), "--hash", self.correct_hash)
        self.assertEqual(
            proc.returncode,
            0,
            msg=f"stderr: {proc.stderr.decode(errors='replace')}",
        )
        # Stdout should mention "ok"
        self.assertIn(b"ok", proc.stdout)

    def test_hash_mismatch_returns_three(self) -> None:
        wrong = "0" * 64
        proc = self._run("--file", str(self.fpath), "--hash", wrong)
        self.assertEqual(proc.returncode, 3)
        self.assertIn(b"hash mismatch", proc.stderr)

    def test_missing_file_returns_two(self) -> None:
        ghost = self.tmpdir / "ghost.txt"
        proc = self._run("--file", str(ghost), "--hash", self.correct_hash)
        self.assertEqual(proc.returncode, 2)
        self.assertIn(b"not found", proc.stderr)

    def test_relative_path_returns_one(self) -> None:
        # --file must be absolute.
        proc = self._run("--file", "relative/file.txt", "--hash", self.correct_hash)
        self.assertEqual(proc.returncode, 1)
        self.assertIn(b"absolute", proc.stderr)

    def test_uppercase_hash_is_normalized(self) -> None:
        # Hex case shouldn't matter; the stub lowercases internally.
        proc = self._run(
            "--file", str(self.fpath), "--hash", self.correct_hash.upper()
        )
        self.assertEqual(proc.returncode, 0, msg=proc.stderr.decode(errors="replace"))


if __name__ == "__main__":
    unittest.main()
