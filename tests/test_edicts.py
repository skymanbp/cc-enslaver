"""Tests for hooks/scripts/lib/edicts.py and its integration with the
three hook scripts that consume it (inject_context, read_guard,
bash_guard).

Edicts are user-defined per-project hard rules (`severity = "must"`)
or soft reminders (`severity = "should"`). The tests cover:

  - Loading: missing file, malformed TOML, malformed entries, bad regex
  - Soft layer: injection rendering (table content)
  - Hard layer (Edit/Write): must + matching pattern → DENY
  - Hard layer (Bash): must + matching pattern → DENY
  - Severity gating: should + matching pattern → ALLOW (no DENY)
  - Multiple edicts: first match wins
  - Built-in patterns still run before edicts (no whitelist bypass)
"""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _helpers import SCRIPTS_DIR, run_hook  # noqa: E402

# Library is importable directly for unit tests.
sys.path.insert(0, str(SCRIPTS_DIR))
from lib import edicts as edicts_lib  # noqa: E402

INJECT = str(SCRIPTS_DIR / "inject_context.py")
READ_GUARD = str(SCRIPTS_DIR / "read_guard.py")
BASH_GUARD = str(SCRIPTS_DIR / "bash_guard.py")


class _EdictsBase(unittest.TestCase):
    """Provides an isolated project dir + edicts.toml writer."""

    def setUp(self) -> None:
        self.proj = Path(tempfile.mkdtemp(prefix="ccens-edict-proj-"))
        self.plugin_data = Path(tempfile.mkdtemp(prefix="ccens-edict-data-"))
        self.env = {
            "CLAUDE_PROJECT_DIR": str(self.proj),
            "CLAUDE_PLUGIN_DATA": str(self.plugin_data),
            # Hide ~/.claude fallback during tests by re-pointing HOME.
            "HOME": str(self.proj),
            "USERPROFILE": str(self.proj),
        }
        self.edicts_path = self.proj / ".claude" / "cc-enslaver" / "edicts.toml"

    def tearDown(self) -> None:
        shutil.rmtree(self.proj, ignore_errors=True)
        shutil.rmtree(self.plugin_data, ignore_errors=True)

    def write_edicts(self, content: str) -> None:
        self.edicts_path.parent.mkdir(parents=True, exist_ok=True)
        self.edicts_path.write_text(textwrap.dedent(content), encoding="utf-8")


# --------------------------------------------------------------------------- #
# Loader unit tests.
# --------------------------------------------------------------------------- #
class TestLoader(_EdictsBase):

    def _load_in_env(self):
        # The loader reads env vars at call time; we patch via env in
        # subprocess for hook integration, but for direct unit tests
        # we temporarily set os.environ.
        import os
        old = dict(os.environ)
        try:
            os.environ.update(self.env)
            return edicts_lib.load()
        finally:
            os.environ.clear()
            os.environ.update(old)

    def test_no_file_returns_empty(self) -> None:
        self.assertEqual(self._load_in_env(), [])

    def test_empty_file_returns_empty(self) -> None:
        self.write_edicts("")
        self.assertEqual(self._load_in_env(), [])

    def test_well_formed_must_edict_loads(self) -> None:
        self.write_edicts("""
            [[edicts]]
            id = "E01"
            text = "禁止使用 mongoose"
            severity = "must"
            deny_edit = ['''from ["']mongoose["']''']
            deny_bash = ['''npm (i|install) mongoose''']
        """)
        es = self._load_in_env()
        self.assertEqual(len(es), 1)
        self.assertEqual(es[0].id, "E01")
        self.assertEqual(es[0].severity, "must")
        self.assertTrue(es[0].is_hard)
        self.assertEqual(len(es[0]._compiled_edit), 1)
        self.assertEqual(len(es[0]._compiled_bash), 1)

    def test_should_severity_loads_but_not_hard(self) -> None:
        self.write_edicts("""
            [[edicts]]
            id = "E02"
            text = "建议使用 prisma"
            severity = "should"
            deny_edit = ['''from ["']mongoose["']''']
        """)
        es = self._load_in_env()
        self.assertEqual(len(es), 1)
        self.assertEqual(es[0].severity, "should")
        # should + patterns → NOT hard (patterns won't DENY).
        self.assertFalse(es[0].is_hard)

    def test_malformed_toml_returns_empty(self) -> None:
        self.write_edicts("[[edicts\nid = unclosed")
        self.assertEqual(self._load_in_env(), [])

    def test_missing_id_skipped(self) -> None:
        self.write_edicts("""
            [[edicts]]
            text = "without id"
        """)
        self.assertEqual(self._load_in_env(), [])

    def test_missing_text_skipped(self) -> None:
        self.write_edicts("""
            [[edicts]]
            id = "E01"
        """)
        self.assertEqual(self._load_in_env(), [])

    def test_invalid_regex_is_dropped_but_edict_kept(self) -> None:
        # Edict has one good and one bad regex; the bad one is dropped
        # with a warning and the good one still applies.
        self.write_edicts("""
            [[edicts]]
            id = "E01"
            text = "test"
            deny_edit = ["valid_pattern", "[broken_unclosed"]
        """)
        es = self._load_in_env()
        self.assertEqual(len(es), 1)
        self.assertEqual(len(es[0]._compiled_edit), 1)  # bad one dropped

    def test_duplicate_id_first_wins(self) -> None:
        self.write_edicts("""
            [[edicts]]
            id = "E01"
            text = "first"

            [[edicts]]
            id = "E01"
            text = "second"
        """)
        es = self._load_in_env()
        self.assertEqual(len(es), 1)
        self.assertEqual(es[0].text, "first")

    def test_unknown_severity_defaults_to_must(self) -> None:
        self.write_edicts("""
            [[edicts]]
            id = "E01"
            text = "test"
            severity = "blocker"
        """)
        es = self._load_in_env()
        self.assertEqual(es[0].severity, "must")


# --------------------------------------------------------------------------- #
# Soft-layer injection rendering.
# --------------------------------------------------------------------------- #
class TestSoftInjection(_EdictsBase):

    def test_no_edicts_yields_empty_injection(self) -> None:
        rc, out, _ = run_hook(
            [INJECT, "--event", "SessionStart"],
            stdin_payload={"session_id": "t", "hook_event_name": "SessionStart"},
            env_overrides=self.env,
        )
        ctx = out["hookSpecificOutput"]["additionalContext"]
        self.assertNotIn("圣旨", ctx, msg="no edicts → no 圣旨 block")

    def test_edicts_appear_in_session_start_injection(self) -> None:
        self.write_edicts("""
            [[edicts]]
            id = "E01"
            text = "禁止使用 mongoose"
            severity = "must"
            deny_edit = ["mongoose"]

            [[edicts]]
            id = "E02"
            text = "API 必须经过 src/api/client.ts"
            severity = "should"
        """)
        rc, out, _ = run_hook(
            [INJECT, "--event", "SessionStart"],
            stdin_payload={"session_id": "t", "hook_event_name": "SessionStart"},
            env_overrides=self.env,
        )
        ctx = out["hookSpecificOutput"]["additionalContext"]
        self.assertIn("圣旨", ctx)
        self.assertIn("`E01`", ctx)
        self.assertIn("`E02`", ctx)
        self.assertIn("禁止使用 mongoose", ctx)
        self.assertIn("must", ctx)
        self.assertIn("should", ctx)

    def test_edicts_also_injected_on_user_prompt_submit(self) -> None:
        # Per-turn re-injection survives context compaction.
        self.write_edicts("""
            [[edicts]]
            id = "E01"
            text = "test edict"
        """)
        rc, out, _ = run_hook(
            [INJECT, "--event", "UserPromptSubmit"],
            stdin_payload={"session_id": "t", "hook_event_name": "UserPromptSubmit"},
            env_overrides=self.env,
        )
        ctx = out["hookSpecificOutput"]["additionalContext"]
        self.assertIn("圣旨", ctx)
        self.assertIn("`E01`", ctx)


# --------------------------------------------------------------------------- #
# Hard layer: Bash.
# --------------------------------------------------------------------------- #
class TestBashEdictDeny(_EdictsBase):

    def _run_bash(self, command: str):
        return run_hook(
            [BASH_GUARD],
            stdin_payload={
                "session_id": "t",
                "hook_event_name": "PreToolUse",
                "tool_name": "Bash",
                "tool_input": {"command": command},
                "cwd": str(self.proj),
            },
            env_overrides=self.env,
        )

    def test_must_edict_denies_matching_command(self) -> None:
        self.write_edicts(r"""
            [[edicts]]
            id = "E01"
            text = "禁止安装 mongoose"
            severity = "must"
            deny_bash = ['''npm\s+(i|install)\s+mongoose''']
        """)
        rc, out, _ = self._run_bash("npm install mongoose --save")
        self.assertEqual(rc, 0)
        self.assertIsNotNone(out, msg="must edict must DENY the matching command")
        self.assertEqual(out["hookSpecificOutput"]["permissionDecision"], "deny")
        self.assertIn("E01", out["hookSpecificOutput"]["permissionDecisionReason"])
        self.assertIn("圣旨", out["hookSpecificOutput"]["permissionDecisionReason"])

    def test_should_edict_does_not_deny(self) -> None:
        self.write_edicts(r"""
            [[edicts]]
            id = "E01"
            text = "建议不要装 mongoose"
            severity = "should"
            deny_bash = ['''npm\s+install\s+mongoose''']
        """)
        rc, out, _ = self._run_bash("npm install mongoose")
        self.assertIsNone(out, msg="should edict must not DENY")

    def test_non_matching_command_allowed(self) -> None:
        self.write_edicts(r"""
            [[edicts]]
            id = "E01"
            text = "no mongoose"
            severity = "must"
            deny_bash = ['''mongoose''']
        """)
        rc, out, _ = self._run_bash("npm install prisma")
        self.assertIsNone(out)

    def test_builtin_no_verify_still_denies_when_edicts_loaded(self) -> None:
        # Edicts must not preempt or override built-in disciplines.
        # Build a no-op edict and verify --no-verify is still rejected with
        # rule 03, not the edict.
        self.write_edicts("""
            [[edicts]]
            id = "E01"
            text = "irrelevant"
            severity = "must"
            deny_bash = ["never_matches_zzz"]
        """)
        rc, out, _ = self._run_bash("git commit -m foo --no-verify")
        self.assertIsNotNone(out)
        reason = out["hookSpecificOutput"]["permissionDecisionReason"]
        self.assertIn("rule 03", reason)
        self.assertNotIn("E01", reason)


# --------------------------------------------------------------------------- #
# Hard layer: Edit / Write.
# --------------------------------------------------------------------------- #
class TestEditEdictDeny(_EdictsBase):

    def _run_write(self, file_path: str, content: str):
        return run_hook(
            [READ_GUARD],
            stdin_payload={
                "session_id": "t",
                "hook_event_name": "PreToolUse",
                "tool_name": "Write",
                "tool_input": {"file_path": file_path, "content": content},
            },
            env_overrides=self.env,
        )

    def _run_edit(self, file_path: str, new_string: str):
        return run_hook(
            [READ_GUARD],
            stdin_payload={
                "session_id": "t",
                "hook_event_name": "PreToolUse",
                "tool_name": "Edit",
                "tool_input": {
                    "file_path": file_path,
                    "old_string": "x",
                    "new_string": new_string,
                },
            },
            env_overrides=self.env,
        )

    def test_write_new_file_with_must_edict_violation_denies(self) -> None:
        self.write_edicts(r"""
            [[edicts]]
            id = "E01"
            text = "禁止使用 mongoose"
            severity = "must"
            deny_edit = ['''from ["']mongoose["']''']
        """)
        target = str(self.proj / "src" / "db.ts")
        rc, out, _ = self._run_write(target, "from 'mongoose'\nconst db = ...")
        self.assertIsNotNone(out)
        self.assertEqual(out["hookSpecificOutput"]["permissionDecision"], "deny")
        reason = out["hookSpecificOutput"]["permissionDecisionReason"]
        self.assertIn("E01", reason)
        self.assertIn("圣旨", reason)
        self.assertIn("禁止使用 mongoose", reason)

    def test_write_new_file_without_violation_allowed(self) -> None:
        self.write_edicts(r"""
            [[edicts]]
            id = "E01"
            text = "no mongoose"
            severity = "must"
            deny_edit = ['''mongoose''']
        """)
        target = str(self.proj / "src" / "db.ts")
        rc, out, _ = self._run_write(target, "import prisma from 'prisma'")
        self.assertIsNone(out)

    def test_edit_existing_file_with_violation_denies(self) -> None:
        # Pre-create the file and seed it as read.
        target = self.proj / "src" / "db.ts"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("// initial", encoding="utf-8")
        # Mark as read so the read-before-edit guard doesn't fire first.
        sessions = self.plugin_data / "sessions"
        sessions.mkdir(parents=True, exist_ok=True)
        import os
        norm = os.path.normcase(os.path.realpath(str(target)))
        (sessions / "t.json").write_text(
            json.dumps({"session_id": "t", "read_files": [norm]}),
            encoding="utf-8",
        )
        self.write_edicts(r"""
            [[edicts]]
            id = "E01"
            text = "禁 mongoose"
            severity = "must"
            deny_edit = ['''mongoose''']
        """)
        rc, out, _ = self._run_edit(str(target), "const x = require('mongoose')")
        self.assertIsNotNone(out)
        self.assertEqual(out["hookSpecificOutput"]["permissionDecision"], "deny")
        self.assertIn("E01", out["hookSpecificOutput"]["permissionDecisionReason"])

    def test_should_severity_does_not_deny_edits(self) -> None:
        self.write_edicts(r"""
            [[edicts]]
            id = "E01"
            text = "soft rec"
            severity = "should"
            deny_edit = ['''mongoose''']
        """)
        target = str(self.proj / "src" / "db.ts")
        rc, out, _ = self._run_write(target, "import mongoose from 'mongoose'")
        self.assertIsNone(out, msg="should edict must not DENY")

    def test_patch_marker_still_denied_when_edicts_loaded(self) -> None:
        # rule 09 patch-style check runs before edict check; both deny but
        # the order matters because the reason text and the failed rule
        # are different.
        self.write_edicts(r"""
            [[edicts]]
            id = "E01"
            text = "no mongoose"
            severity = "must"
            deny_edit = ['''never_match_zzz''']
        """)
        target = str(self.proj / "src" / "x.py")
        rc, out, _ = self._run_write(target, "def f():\n    try:\n        a()\n    except:\n        pass\n")
        self.assertIsNotNone(out)
        reason = out["hookSpecificOutput"]["permissionDecisionReason"]
        self.assertIn("rule 09", reason)
        self.assertNotIn("E01", reason)


# --------------------------------------------------------------------------- #
# Multi-edict ordering.
# --------------------------------------------------------------------------- #
class TestMultipleEdicts(_EdictsBase):

    def test_first_match_wins(self) -> None:
        self.write_edicts(r"""
            [[edicts]]
            id = "E01"
            text = "first"
            severity = "must"
            deny_bash = ["mongoose"]

            [[edicts]]
            id = "E02"
            text = "second"
            severity = "must"
            deny_bash = ["mongoose"]
        """)
        rc, out, _ = run_hook(
            [BASH_GUARD],
            stdin_payload={
                "session_id": "t",
                "hook_event_name": "PreToolUse",
                "tool_name": "Bash",
                "tool_input": {"command": "npm i mongoose"},
            },
            env_overrides=self.env,
        )
        reason = out["hookSpecificOutput"]["permissionDecisionReason"]
        self.assertIn("E01", reason)
        self.assertNotIn("E02", reason)


if __name__ == "__main__":
    unittest.main()
