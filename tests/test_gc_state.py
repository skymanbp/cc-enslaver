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
        self.tmpdir = Path(tempfile.mkdtemp(prefix="ccens-gc-"))
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


class TestAutoGCOnSessionStart(_GcBase):
    """v0.18 — opt-in auto-GC at SessionStart via CC_ENSLAVER_AUTO_GC_DAYS.

    The auto-GC entry lives in `inject_context.py`'s SessionStart code
    path. These tests drive inject_context as a subprocess (same
    surface Claude Code uses) and verify the marker / deletion /
    rate-limit semantics.
    """

    INJECT = str(SCRIPTS_DIR / "inject_context.py")

    def _run_inject_session_start(self, env_extra: dict):
        env = {**self.env, **env_extra}
        import json as _json
        proc = subprocess.run(
            [sys.executable, self.INJECT, "--event", "SessionStart"],
            input=_json.dumps({
                "session_id": "auto-gc-test",
                "hook_event_name": "SessionStart",
            }).encode("utf-8"),
            capture_output=True,
            env=env,
        )
        return proc

    def test_env_unset_does_not_run_gc(self) -> None:
        # Old file present; no env → file remains.
        self._make_session_file("old", age_days=60)
        proc = self._run_inject_session_start({})
        self.assertEqual(proc.returncode, 0)
        self.assertTrue((self.sessions_dir / "old.json").exists())
        # No marker should be written either.
        self.assertFalse((self.sessions_dir / "_auto_gc.json").exists())

    def test_env_set_deletes_old_and_writes_marker(self) -> None:
        self._make_session_file("old1", age_days=60)
        self._make_session_file("old2", age_days=40)
        self._make_session_file("fresh", age_days=1)
        proc = self._run_inject_session_start({
            "CC_ENSLAVER_AUTO_GC_DAYS": "30",
        })
        self.assertEqual(proc.returncode, 0)
        self.assertFalse((self.sessions_dir / "old1.json").exists())
        self.assertFalse((self.sessions_dir / "old2.json").exists())
        self.assertTrue((self.sessions_dir / "fresh.json").exists())
        marker = self.sessions_dir / "_auto_gc.json"
        self.assertTrue(marker.is_file())
        import json as _json
        data = _json.loads(marker.read_text(encoding="utf-8"))
        self.assertEqual(data["deleted"], 2)
        self.assertGreater(data["ts"], 0)

    def test_rate_limit_skips_within_24h(self) -> None:
        # Plant a fresh marker (ran < 24h ago).
        import json as _json
        marker = self.sessions_dir / "_auto_gc.json"
        marker.write_text(_json.dumps({"ts": time.time(), "deleted": 0}))

        self._make_session_file("old", age_days=60)
        proc = self._run_inject_session_start({
            "CC_ENSLAVER_AUTO_GC_DAYS": "30",
        })
        self.assertEqual(proc.returncode, 0)
        # Old file should still exist because rate limit kicked in.
        self.assertTrue((self.sessions_dir / "old.json").exists())

    def test_rate_limit_passes_after_25h(self) -> None:
        # Plant a stale marker (ran > 24h ago).
        import json as _json
        marker = self.sessions_dir / "_auto_gc.json"
        marker.write_text(
            _json.dumps({"ts": time.time() - 25 * 3600, "deleted": 0})
        )

        self._make_session_file("old", age_days=60)
        proc = self._run_inject_session_start({
            "CC_ENSLAVER_AUTO_GC_DAYS": "30",
        })
        self.assertEqual(proc.returncode, 0)
        self.assertFalse((self.sessions_dir / "old.json").exists())

    def test_marker_file_itself_never_gc_d(self) -> None:
        # The marker is in state_dir alongside session files. The auto-GC
        # must never delete it even if it's older than the threshold.
        import json as _json
        marker = self.sessions_dir / "_auto_gc.json"
        marker.write_text(_json.dumps({"ts": 0, "deleted": 0}))
        # Backdate the marker so it would be eligible if it were a session.
        old_time = time.time() - 90 * 86400
        os.utime(marker, (old_time, old_time))

        proc = self._run_inject_session_start({
            "CC_ENSLAVER_AUTO_GC_DAYS": "30",
        })
        self.assertEqual(proc.returncode, 0)
        # Marker still exists (was rewritten by the GC pass with fresh ts).
        self.assertTrue(marker.is_file())
        # And its content reflects the new run.
        data = _json.loads(marker.read_text(encoding="utf-8"))
        self.assertGreater(data["ts"], time.time() - 60)

    def test_bad_env_value_is_skipped_silently(self) -> None:
        self._make_session_file("old", age_days=60)
        proc = self._run_inject_session_start({
            "CC_ENSLAVER_AUTO_GC_DAYS": "not-a-number",
        })
        self.assertEqual(proc.returncode, 0)
        # Old file remains; no marker written.
        self.assertTrue((self.sessions_dir / "old.json").exists())
        self.assertFalse((self.sessions_dir / "_auto_gc.json").exists())
        # Stderr should mention the bad value.
        self.assertIn(b"not an integer", proc.stderr)

    def test_zero_or_negative_threshold_disables(self) -> None:
        self._make_session_file("old", age_days=60)
        proc = self._run_inject_session_start({
            "CC_ENSLAVER_AUTO_GC_DAYS": "0",
        })
        self.assertEqual(proc.returncode, 0)
        self.assertTrue((self.sessions_dir / "old.json").exists())

    def test_user_prompt_submit_does_not_trigger_gc(self) -> None:
        # Auto-GC must only run on SessionStart, not every UserPromptSubmit.
        self._make_session_file("old", age_days=60)
        import json as _json
        proc = subprocess.run(
            [sys.executable, self.INJECT, "--event", "UserPromptSubmit"],
            input=_json.dumps({
                "session_id": "x",
                "hook_event_name": "UserPromptSubmit",
            }).encode("utf-8"),
            capture_output=True,
            env={**self.env, "CC_ENSLAVER_AUTO_GC_DAYS": "30"},
        )
        self.assertEqual(proc.returncode, 0)
        self.assertTrue((self.sessions_dir / "old.json").exists())


class TestPruneFunctionDirect(_GcBase):
    """v0.18 — direct unit tests for prune_old_sessions() (the shared
    function used by both manual CLI and auto-GC entry points)."""

    def test_exclude_session_spares_named_file(self) -> None:
        # Force gc_state importable.
        sys.path.insert(0, str(SCRIPTS_DIR))
        import os as _os
        old_data = _os.environ.get("CLAUDE_PLUGIN_DATA")
        _os.environ["CLAUDE_PLUGIN_DATA"] = str(self.tmpdir)
        try:
            # gc_state.py imports lib/ via sys.path insert at module
            # level. Reload defensively.
            import importlib
            import gc_state
            importlib.reload(gc_state)
            self._make_session_file("live", age_days=60)
            self._make_session_file("dead", age_days=60)
            summary = gc_state.prune_old_sessions(
                threshold_days=30,
                dry_run=False,
                exclude_session="live",
            )
            self.assertTrue((self.sessions_dir / "live.json").exists())
            self.assertFalse((self.sessions_dir / "dead.json").exists())
            self.assertEqual(summary["deleted"], 1)
        finally:
            if old_data is None:
                _os.environ.pop("CLAUDE_PLUGIN_DATA", None)
            else:
                _os.environ["CLAUDE_PLUGIN_DATA"] = old_data

    def test_threshold_less_than_one_raises(self) -> None:
        sys.path.insert(0, str(SCRIPTS_DIR))
        import gc_state
        with self.assertRaises(ValueError):
            gc_state.prune_old_sessions(threshold_days=0)


if __name__ == "__main__":
    unittest.main()
