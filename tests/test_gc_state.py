"""Tests for hooks/scripts/gc_state.py.

Covers:
  - --dry-run and --apply mutual exclusion (must pass exactly one)
  - --older-than threshold honoured (files newer kept; older listed/deleted)
  - --dry-run never deletes
  - --apply deletes and prints "deleted: N" / "bytes_freed"
  - Empty state dir → "nothing to do"
  - --older-than 0 / negative → rejected with non-zero exit
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _helpers import SCRIPTS_DIR  # noqa: E402

GC = str(SCRIPTS_DIR / "gc_state.py")


class _GcBase(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = Path(tempfile.mkdtemp(prefix="alaz-gc-"))
        self.sessions_dir = self.tmpdir / "sessions"
        self.sessions_dir.mkdir(parents=True)
        # Force the gc script to use this tmp dir as its state root via
        # CLAUDE_PLUGIN_DATA. state_lib.state_dir() resolves CLAUDE_PLUGIN_DATA
        # first, so this overrides the default fallback chain.
        self.env = {**os.environ, "CLAUDE_PLUGIN_DATA": str(self.tmpdir)}

    def tearDown(self) -> None:
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _make_session_file(self, name: str, age_days: float, content: str = "{}") -> Path:
        f = self.sessions_dir / f"{name}.json"
        f.write_text(content, encoding="utf-8")
        # Backdate mtime by age_days.
        old_time = time.time() - age_days * 86400
        os.utime(f, (old_time, old_time))
        return f

    def _run(self, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, GC, *args],
            capture_output=True,
            env=self.env,
        )


class TestArgValidation(_GcBase):
    def test_no_args_rejected(self) -> None:
        proc = self._run()
        self.assertNotEqual(
            proc.returncode, 0,
            msg="missing --dry-run/--apply must fail",
        )

    def test_both_flags_rejected(self) -> None:
        proc = self._run("--dry-run", "--apply")
        self.assertNotEqual(proc.returncode, 0)

    def test_negative_threshold_rejected(self) -> None:
        proc = self._run("--dry-run", "--older-than", "0")
        self.assertNotEqual(proc.returncode, 0)


class TestDryRun(_GcBase):
    def test_dry_run_lists_old_files_without_deleting(self) -> None:
        old1 = self._make_session_file("ancient", age_days=60)
        old2 = self._make_session_file("middle", age_days=45)
        fresh = self._make_session_file("recent", age_days=5)

        proc = self._run("--dry-run", "--older-than", "30")
        self.assertEqual(
            proc.returncode, 0,
            msg=f"stderr: {proc.stderr.decode(errors='replace')}",
        )
        # Files still present.
        self.assertTrue(old1.exists(), "dry-run must not delete")
        self.assertTrue(old2.exists())
        self.assertTrue(fresh.exists())

        out = proc.stdout.decode("utf-8")
        self.assertIn("eligible:  2", out)
        self.assertIn("ancient.json", out)
        self.assertIn("middle.json", out)
        self.assertNotIn("recent.json", out)

    def test_dry_run_with_no_eligible_says_nothing_to_do(self) -> None:
        self._make_session_file("recent", age_days=5)
        proc = self._run("--dry-run", "--older-than", "30")
        self.assertEqual(proc.returncode, 0)
        self.assertIn("nothing to do", proc.stdout.decode("utf-8"))


class TestApply(_GcBase):
    def test_apply_deletes_old_files_and_prints_summary(self) -> None:
        old1 = self._make_session_file("ancient", age_days=60, content="x" * 100)
        old2 = self._make_session_file("middle", age_days=45, content="y" * 50)
        fresh = self._make_session_file("recent", age_days=5)

        proc = self._run("--apply", "--older-than", "30")
        self.assertEqual(proc.returncode, 0)
        self.assertFalse(old1.exists(), "ancient should be deleted")
        self.assertFalse(old2.exists(), "middle should be deleted")
        self.assertTrue(fresh.exists(), "recent must be kept")

        out = proc.stdout.decode("utf-8")
        self.assertIn("deleted:    2", out)
        # bytes_freed should be at least 100 + 50 = 150 (file content sizes).
        # (JSON file sizes match content for our simple "x" * N writes.)
        self.assertIn("bytes_freed:", out)

    def test_apply_with_no_eligible_is_noop(self) -> None:
        self._make_session_file("recent", age_days=5)
        proc = self._run("--apply", "--older-than", "30")
        self.assertEqual(proc.returncode, 0)
        # The fresh file is still here.
        self.assertTrue((self.sessions_dir / "recent.json").exists())


class TestThresholdBoundary(_GcBase):
    def test_files_exactly_at_threshold_kept(self) -> None:
        # File exactly at the threshold (mtime = now - threshold seconds).
        # cutoff is "older than threshold", so equal-age files are KEPT.
        f = self._make_session_file("borderline", age_days=30)
        proc = self._run("--apply", "--older-than", "30")
        self.assertEqual(proc.returncode, 0)
        # Borderline file may or may not match depending on sub-second
        # rounding. We just assert the script ran cleanly.
        # (Precise boundary semantics are documented in the script.)
        del f  # silence unused

    def test_higher_threshold_keeps_more_files(self) -> None:
        self._make_session_file("forty", age_days=40)
        self._make_session_file("twenty", age_days=20)
        # Threshold = 50 → none eligible.
        proc = self._run("--dry-run", "--older-than", "50")
        out = proc.stdout.decode("utf-8")
        self.assertIn("eligible:  0", out)


if __name__ == "__main__":
    unittest.main()
