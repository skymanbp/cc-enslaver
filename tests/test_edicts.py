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


# --------------------------------------------------------------------------- #
# manage_edicts.py CLI subprocess tests (v0.14).
#
# Tests the actual subprocess invocation surface that /cc-enslaver:edict
# and shell users hit. Catches integration bugs (argparse drift, file
# layout, write-then-read round-trip) that the lib-level tests miss.
# --------------------------------------------------------------------------- #
MANAGE = str(SCRIPTS_DIR / "manage_edicts.py")


class _ManageCLIBase(unittest.TestCase):
    """Sandbox both CLAUDE_PROJECT_DIR and HOME so --global writes
    land inside our tmp dir, not the real user's ~/.claude."""

    def setUp(self) -> None:
        self.proj = Path(tempfile.mkdtemp(prefix="ccens-cli-proj-"))
        self.home = Path(tempfile.mkdtemp(prefix="ccens-cli-home-"))
        self.env = {
            "CLAUDE_PROJECT_DIR": str(self.proj),
            "HOME": str(self.home),
            "USERPROFILE": str(self.home),
        }

    def tearDown(self) -> None:
        shutil.rmtree(self.proj, ignore_errors=True)
        shutil.rmtree(self.home, ignore_errors=True)

    def _run(self, *args: str):
        import os
        env = {**os.environ, **self.env}
        # PATH may have weird things; force just-this-python to avoid
        # surprises in shebang resolution.
        import subprocess
        proc = subprocess.run(
            [sys.executable, MANAGE, *args],
            capture_output=True,
            env=env,
        )
        return (
            proc.returncode,
            proc.stdout.decode("utf-8", errors="replace"),
            proc.stderr.decode("utf-8", errors="replace"),
        )


class TestManageCLI(_ManageCLIBase):

    def test_path_when_no_file_prints_intended_location(self) -> None:
        rc, out, _ = self._run("path")
        self.assertEqual(rc, 0)
        self.assertIn("does not exist yet", out)
        self.assertIn(str(self.proj), out)

    def test_add_creates_file_and_list_shows_it(self) -> None:
        rc, out, err = self._run(
            "add", "E01", "禁止 mongoose",
            "--must", "--deny-bash", r"npm\s+i\s+mongoose",
        )
        self.assertEqual(rc, 0, msg=f"add failed: {err}")
        # File written into project-level location.
        f = self.proj / ".claude" / "cc-enslaver" / "edicts.toml"
        self.assertTrue(f.is_file())
        # list reflects the new edict.
        rc, out, _ = self._run("list")
        self.assertEqual(rc, 0)
        self.assertIn("[E01]", out)
        self.assertIn("must", out)
        self.assertIn("deny_bash×1", out)

    def test_add_then_remove_round_trip(self) -> None:
        self._run("add", "E01", "x", "--deny-bash", "foo")
        rc, out, _ = self._run("remove", "E01")
        self.assertEqual(rc, 0)
        self.assertIn("Removed", out)
        rc, out, _ = self._run("list")
        self.assertIn("empty", out.lower())

    def test_duplicate_add_rejected(self) -> None:
        self._run("add", "E01", "first")
        rc, _, err = self._run("add", "E01", "second")
        self.assertNotEqual(rc, 0)
        self.assertIn("already exists", err)

    def test_remove_nonexistent_rejected(self) -> None:
        rc, _, err = self._run("remove", "E99")
        self.assertNotEqual(rc, 0)
        self.assertIn("No edict", err)

    def test_should_severity_persists(self) -> None:
        self._run("add", "E01", "soft", "--should", "--deny-bash", "x")
        rc, out, _ = self._run("list")
        self.assertIn("should", out)
        # And the file actually says severity = "should".
        f = self.proj / ".claude" / "cc-enslaver" / "edicts.toml"
        self.assertIn('severity = "should"', f.read_text(encoding="utf-8"))


class TestManageCLIGlobalFlag(_ManageCLIBase):
    """v0.14 --global writes to ~/.claude/cc-enslaver/edicts.toml."""

    def test_global_add_writes_to_home(self) -> None:
        rc, out, err = self._run(
            "add", "E01", "global edict", "--global", "--deny-bash", "x",
        )
        self.assertEqual(rc, 0, msg=err)
        self.assertIn("global", out.lower())
        # File goes under HOME, not under CLAUDE_PROJECT_DIR.
        global_f = self.home / ".claude" / "cc-enslaver" / "edicts.toml"
        proj_f = self.proj / ".claude" / "cc-enslaver" / "edicts.toml"
        self.assertTrue(global_f.is_file())
        self.assertFalse(proj_f.is_file())

    def test_global_add_then_list_finds_it_via_fallback(self) -> None:
        # No project file → loader's HOME fallback picks up the global file.
        self._run("add", "E01", "g", "--global", "--deny-bash", "x")
        rc, out, _ = self._run("list")
        self.assertIn("[E01]", out)

    def test_project_add_takes_precedence_over_global_in_list(self) -> None:
        # Both files exist → project wins (loader's documented order).
        self._run("add", "E01", "global", "--global", "--deny-bash", "x")
        self._run("add", "E02", "project", "--deny-bash", "y")
        rc, out, _ = self._run("list")
        # E02 is in project file; E01 is in global. list uses load() which
        # returns the first-found file, so we should see project's E02 but
        # NOT global's E01.
        self.assertIn("[E02]", out)
        self.assertNotIn("[E01]", out)

    def test_remove_falls_back_from_project_to_global(self) -> None:
        # Add to global only; remove without --global should still find it.
        self._run("add", "E01", "g", "--global", "--deny-bash", "x")
        rc, out, _ = self._run("remove", "E01")
        self.assertEqual(rc, 0)
        self.assertIn("Removed", out)

    def test_global_remove_restricted_to_global_file(self) -> None:
        # E01 exists only in project; remove --global should fail.
        self._run("add", "E01", "p", "--deny-bash", "x")
        rc, _, err = self._run("remove", "E01", "--global")
        self.assertNotEqual(rc, 0)
        self.assertIn("No edict", err)


class TestBilingualRendering(_EdictsBase):
    """v0.17 — CC_ENSLAVER_LANG=en switches edict injection + deny reason
    to English. Default (zh / unset) keeps the Chinese 圣旨 wording.

    Tests cover:
      - Default (no env) → Chinese 圣旨 banner in injection + deny reason
      - lang=en          → English "Imperial Edicts" banner in injection
                           + "Imperial Edict {ID} violation" in deny
      - Unknown lang     → fail-safe back to Chinese
    """

    def test_injection_default_is_chinese(self) -> None:
        self.write_edicts("""
            [[edicts]]
            id = "E01"
            text = "test edict"
            severity = "must"
            deny_bash = ["x"]
        """)
        rc, out, _ = run_hook(
            [INJECT, "--event", "SessionStart"],
            stdin_payload={"session_id": "t", "hook_event_name": "SessionStart"},
            env_overrides=self.env,  # no CC_ENSLAVER_LANG
        )
        ctx = out["hookSpecificOutput"]["additionalContext"]
        self.assertIn("圣旨", ctx)
        self.assertIn("项目自定义硬规则", ctx)
        self.assertNotIn("Imperial Edicts", ctx)

    def test_injection_lang_en_is_english(self) -> None:
        self.write_edicts("""
            [[edicts]]
            id = "E01"
            text = "no mongoose"
            severity = "must"
            deny_bash = ["x"]
        """)
        env_en = {**self.env, "CC_ENSLAVER_LANG": "en"}
        rc, out, _ = run_hook(
            [INJECT, "--event", "SessionStart"],
            stdin_payload={"session_id": "t", "hook_event_name": "SessionStart"},
            env_overrides=env_en,
        )
        ctx = out["hookSpecificOutput"]["additionalContext"]
        self.assertIn("Imperial Edicts", ctx)
        self.assertIn("project hard rules", ctx)
        self.assertIn("User-defined, hot-reloadable", ctx)
        self.assertIn("`E01`", ctx)
        # The literal Chinese 圣旨 banner must not appear in English mode.
        self.assertNotIn("项目自定义硬规则", ctx)
        self.assertNotIn("用户自定义、可热更新", ctx)

    def test_injection_unknown_lang_falls_back_to_chinese(self) -> None:
        self.write_edicts("""
            [[edicts]]
            id = "E01"
            text = "test"
        """)
        env_fr = {**self.env, "CC_ENSLAVER_LANG": "fr"}
        rc, out, _ = run_hook(
            [INJECT, "--event", "SessionStart"],
            stdin_payload={"session_id": "t", "hook_event_name": "SessionStart"},
            env_overrides=env_fr,
        )
        ctx = out["hookSpecificOutput"]["additionalContext"]
        self.assertIn("圣旨", ctx)
        self.assertNotIn("Imperial Edicts", ctx)

    def test_bash_deny_reason_default_is_chinese(self) -> None:
        self.write_edicts(r"""
            [[edicts]]
            id = "E01"
            text = "ban mongoose"
            severity = "must"
            deny_bash = ['''npm\s+install\s+mongoose''']
        """)
        rc, out, _ = run_hook(
            [BASH_GUARD],
            stdin_payload={
                "session_id": "t",
                "hook_event_name": "PreToolUse",
                "tool_name": "Bash",
                "tool_input": {"command": "npm install mongoose"},
            },
            env_overrides=self.env,
        )
        reason = out["hookSpecificOutput"]["permissionDecisionReason"]
        # Chinese term "圣旨" preserved in headline (default mode).
        self.assertIn("圣旨 E01 violation", reason)

    def test_bash_deny_reason_lang_en_is_english(self) -> None:
        self.write_edicts(r"""
            [[edicts]]
            id = "E01"
            text = "ban mongoose"
            severity = "must"
            deny_bash = ['''npm\s+install\s+mongoose''']
        """)
        env_en = {**self.env, "CC_ENSLAVER_LANG": "en"}
        rc, out, _ = run_hook(
            [BASH_GUARD],
            stdin_payload={
                "session_id": "t",
                "hook_event_name": "PreToolUse",
                "tool_name": "Bash",
                "tool_input": {"command": "npm install mongoose"},
            },
            env_overrides=env_en,
        )
        reason = out["hookSpecificOutput"]["permissionDecisionReason"]
        self.assertIn("Imperial Edict E01 violation", reason)
        # The literal Chinese 圣旨 must not appear in the English headline.
        self.assertNotIn("圣旨", reason)


# --------------------------------------------------------------------------- #
# v0.19.0 — cwd fallback for edicts path resolution.
#
# When `CLAUDE_PROJECT_DIR` is unset (which happens on Windows when
# Claude Code's Bash tool subprocess doesn't propagate the env var
# to hook subprocesses), the loader / writer falls back to cwd if
# cwd looks like a project root (has `.git/` or `.claude/`). Without
# that fallback, the project-level edicts.toml was silently invisible
# whenever the hook subprocess lost the env var, and edicts only
# worked from `~/.claude` even when the user had a project-level
# edicts.toml sitting right next to them.
#
# The tests below pin each surface area of the fallback:
#   - `_looks_like_project_root` marker semantics (.git / .claude)
#   - `edicts_path()` (loader) precedence ordering
#   - `default_project_path()` (writer) precedence ordering
#   - manage_edicts.py CLI subprocess uses cwd when env unset
# --------------------------------------------------------------------------- #
class TestCwdFallback(unittest.TestCase):
    """v0.19.0 — cwd fallback semantics for edicts path resolution."""

    def setUp(self) -> None:
        self.proj = Path(tempfile.mkdtemp(prefix="ccens-cwd-proj-"))
        self.fake_home = Path(tempfile.mkdtemp(prefix="ccens-cwd-home-"))
        # Build minimal env that explicitly *omits* CLAUDE_PROJECT_DIR
        # so the cwd fallback path is the one under test. HOME is
        # redirected so the loader doesn't pick up the real user's
        # ~/.claude during the personal-global fallback step.
        self.env_no_proj = {
            "HOME": str(self.fake_home),
            "USERPROFILE": str(self.fake_home),
        }

    def tearDown(self) -> None:
        shutil.rmtree(self.proj, ignore_errors=True)
        shutil.rmtree(self.fake_home, ignore_errors=True)

    def _mark_project_root(self, kind: str) -> None:
        """Create the project-root marker on self.proj. `kind` is
        "git", "claude", or "both"."""
        if kind in ("git", "both"):
            (self.proj / ".git").mkdir(exist_ok=True)
        if kind in ("claude", "both"):
            (self.proj / ".claude").mkdir(exist_ok=True)

    def _write_edicts_in(self, root: Path, body: str) -> Path:
        p = root / ".claude" / "cc-enslaver" / "edicts.toml"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(textwrap.dedent(body), encoding="utf-8")
        return p

    def _with_env_and_cwd(self, fn, *, cwd: Path, extra_env: dict | None = None):
        """Call `fn` with self.env_no_proj applied (+ optional extras)
        and the working dir temporarily set to `cwd`. Restores both
        on exit. Necessary because the loader reads cwd via
        `Path.cwd()` and the env via `os.environ` at call time.
        """
        import os
        old_env = dict(os.environ)
        old_cwd = os.getcwd()
        env = dict(self.env_no_proj)
        if extra_env:
            env.update(extra_env)
        try:
            os.environ.clear()
            os.environ.update(env)
            os.chdir(cwd)
            return fn()
        finally:
            os.chdir(old_cwd)
            os.environ.clear()
            os.environ.update(old_env)

    # ---------------- marker semantics ---------------- #

    def test_looks_like_project_root_with_git_marker(self) -> None:
        self._mark_project_root("git")
        self.assertTrue(edicts_lib._looks_like_project_root(self.proj))

    def test_looks_like_project_root_with_claude_dir_marker(self) -> None:
        self._mark_project_root("claude")
        self.assertTrue(edicts_lib._looks_like_project_root(self.proj))

    def test_looks_like_project_root_without_any_marker(self) -> None:
        # Empty tmp dir — no .git, no .claude.
        self.assertFalse(edicts_lib._looks_like_project_root(self.proj))

    def test_looks_like_project_root_with_git_file_worktree(self) -> None:
        # Git worktrees use a `.git` *file* (not directory). The
        # marker check uses `.exists()` so this still counts.
        (self.proj / ".git").write_text(
            "gitdir: /elsewhere/.git/worktrees/x\n", encoding="utf-8",
        )
        self.assertTrue(edicts_lib._looks_like_project_root(self.proj))

    # ---------------- loader (edicts_path) ---------------- #

    def test_loader_uses_cwd_when_env_unset_and_marker_present(self) -> None:
        self._mark_project_root("git")
        wanted = self._write_edicts_in(self.proj, """
            [[edicts]]
            id = "E01"
            text = "discovered via cwd fallback"
        """)
        found = self._with_env_and_cwd(edicts_lib.edicts_path, cwd=self.proj)
        self.assertEqual(found, wanted)

    def test_loader_uses_cwd_when_env_unset_and_dotclaude_alone_is_marker(self) -> None:
        # The act of writing edicts.toml under .claude/ creates the
        # .claude/ directory, which is itself a valid project-root
        # marker. This is intentional: a project that has a
        # cc-enslaver config dir is by definition a project Claude
        # Code has touched, so cwd is a safe fallback even without .git.
        wanted = self._write_edicts_in(self.proj, """
            [[edicts]]
            id = "E01"
            text = "marker comes from .claude/ itself"
        """)
        found = self._with_env_and_cwd(edicts_lib.edicts_path, cwd=self.proj)
        self.assertEqual(found, wanted)

    def test_loader_returns_none_when_env_unset_and_no_marker(self) -> None:
        # cwd is just a random tmp dir — no .git, no .claude. The
        # loader must NOT silently start reading edicts.toml from
        # cwd; the marker requirement is what prevents accidental
        # discovery in `~/Downloads` etc.
        # (No edicts written anywhere reachable.)
        found = self._with_env_and_cwd(edicts_lib.edicts_path, cwd=self.proj)
        self.assertIsNone(found)

    def test_loader_env_var_takes_precedence_over_cwd(self) -> None:
        # Put a different edicts.toml under CLAUDE_PROJECT_DIR vs the
        # cwd; verify the env-var location wins.
        env_proj = Path(tempfile.mkdtemp(prefix="ccens-cwd-env-"))
        try:
            (env_proj / ".git").mkdir()
            env_file = self._write_edicts_in(env_proj, """
                [[edicts]]
                id = "ENV"
                text = "env wins"
            """)
            self._mark_project_root("git")
            self._write_edicts_in(self.proj, """
                [[edicts]]
                id = "CWD"
                text = "cwd loses"
            """)
            found = self._with_env_and_cwd(
                edicts_lib.edicts_path,
                cwd=self.proj,
                extra_env={"CLAUDE_PROJECT_DIR": str(env_proj)},
            )
            self.assertEqual(found, env_file)
        finally:
            shutil.rmtree(env_proj, ignore_errors=True)

    def test_loader_falls_through_to_home_when_cwd_marker_present_but_no_file(self) -> None:
        # cwd is a valid project root but has no edicts.toml; loader
        # should continue to the personal-global fallback rather than
        # synthesising a path that doesn't exist.
        self._mark_project_root("git")
        home_file = self._write_edicts_in(self.fake_home, """
            [[edicts]]
            id = "HOME"
            text = "fallback hit"
        """)
        found = self._with_env_and_cwd(edicts_lib.edicts_path, cwd=self.proj)
        self.assertEqual(found, home_file)

    # ---------------- writer (default_project_path) ---------------- #

    def test_writer_uses_cwd_when_env_unset_and_marker_present(self) -> None:
        self._mark_project_root("claude")
        wanted = self.proj / ".claude" / "cc-enslaver" / "edicts.toml"
        got = self._with_env_and_cwd(
            edicts_lib.default_project_path, cwd=self.proj,
        )
        self.assertEqual(got, wanted)

    def test_writer_returns_none_when_env_unset_and_no_marker(self) -> None:
        # Without env var AND without a cwd marker, the writer must
        # return None so callers can surface an actionable error
        # (manage_edicts.py exits 2 with a diagnostic).
        got = self._with_env_and_cwd(
            edicts_lib.default_project_path, cwd=self.proj,
        )
        self.assertIsNone(got)

    def test_writer_env_var_takes_precedence_over_cwd(self) -> None:
        env_proj = Path(tempfile.mkdtemp(prefix="ccens-cwd-env-"))
        try:
            self._mark_project_root("git")
            got = self._with_env_and_cwd(
                edicts_lib.default_project_path,
                cwd=self.proj,
                extra_env={"CLAUDE_PROJECT_DIR": str(env_proj)},
            )
            self.assertEqual(
                got,
                env_proj / ".claude" / "cc-enslaver" / "edicts.toml",
            )
        finally:
            shutil.rmtree(env_proj, ignore_errors=True)


class TestManageCLICwdFallback(unittest.TestCase):
    """v0.19.0 — manage_edicts.py CLI honours cwd fallback when
    `CLAUDE_PROJECT_DIR` is absent from the subprocess environment.

    The CLI is the surface users hit via /cc-enslaver:edict or
    direct invocation; the loader-level unit tests above pin the
    library semantics, but only an actual subprocess exercise
    catches argparse / env-propagation drift between the writer
    and the loader.
    """

    def setUp(self) -> None:
        self.proj = Path(tempfile.mkdtemp(prefix="ccens-cli-cwd-proj-"))
        self.fake_home = Path(tempfile.mkdtemp(prefix="ccens-cli-cwd-home-"))
        # Mark the tmp dir as a project root so cwd fallback elects it.
        (self.proj / ".git").mkdir()
        # Stripped-down env: deliberately omit CLAUDE_PROJECT_DIR. HOME
        # is redirected so --global / fallback writes land in our sandbox.
        self.env_no_proj = {
            "HOME": str(self.fake_home),
            "USERPROFILE": str(self.fake_home),
            "PATH": __import__("os").environ.get("PATH", ""),
            "SYSTEMROOT": __import__("os").environ.get("SYSTEMROOT", ""),
        }

    def tearDown(self) -> None:
        shutil.rmtree(self.proj, ignore_errors=True)
        shutil.rmtree(self.fake_home, ignore_errors=True)

    def _run(self, *args: str, cwd: Path | None = None, with_env_var: bool = False):
        """Invoke manage_edicts.py as a real subprocess.

        cwd: passed verbatim to subprocess.run (this is the lever the
             fallback tests use to control what `Path.cwd()` returns
             inside the child).
        with_env_var: when True, also injects CLAUDE_PROJECT_DIR=self.proj
                      so the env-var path wins (used for precedence test).
        """
        import subprocess
        env = dict(self.env_no_proj)
        if with_env_var:
            env["CLAUDE_PROJECT_DIR"] = str(self.proj)
        proc = subprocess.run(
            [sys.executable, MANAGE, *args],
            capture_output=True,
            env=env,
            cwd=str(cwd) if cwd else None,
        )
        return (
            proc.returncode,
            proc.stdout.decode("utf-8", errors="replace"),
            proc.stderr.decode("utf-8", errors="replace"),
        )

    def test_add_writes_to_cwd_when_env_unset_and_cwd_is_project_root(self) -> None:
        rc, out, err = self._run(
            "add", "E01", "via cwd fallback",
            "--must", "--deny-bash", "x",
            cwd=self.proj,
        )
        self.assertEqual(rc, 0, msg=f"stdout={out!r} stderr={err!r}")
        # File materialised under cwd, not under HOME.
        proj_f = self.proj / ".claude" / "cc-enslaver" / "edicts.toml"
        home_f = self.fake_home / ".claude" / "cc-enslaver" / "edicts.toml"
        self.assertTrue(proj_f.is_file(), msg="expected write at cwd path")
        self.assertFalse(home_f.is_file(), msg="must not have leaked to HOME")
        self.assertIn("E01", proj_f.read_text(encoding="utf-8"))

    def test_add_exits_with_diagnostic_when_env_unset_and_cwd_not_project_root(self) -> None:
        # Cwd lacks .git / .claude → writer cannot resolve a path →
        # exit 2 with an actionable diagnostic listing every attempted
        # fallback so the operator can fix it without guessing.
        non_root = Path(tempfile.mkdtemp(prefix="ccens-not-proj-"))
        try:
            rc, out, err = self._run(
                "add", "E01", "should fail",
                "--must", "--deny-bash", "x",
                cwd=non_root,
            )
            self.assertEqual(rc, 2, msg=f"stdout={out!r} stderr={err!r}")
            self.assertIn("CLAUDE_PROJECT_DIR", err)
            self.assertIn("cwd", err.lower())
            self.assertIn("--global", err)
        finally:
            shutil.rmtree(non_root, ignore_errors=True)

    def test_env_var_takes_precedence_over_cwd_in_cli(self) -> None:
        # Both CLAUDE_PROJECT_DIR and a project-root cwd point to *the
        # same* tmp dir here, which is fine for a precedence assertion:
        # the file lands once at that location, and we just check the
        # write succeeded without surprising errors.
        rc, out, err = self._run(
            "add", "E01", "env path takes precedence",
            "--must", "--deny-bash", "x",
            cwd=self.proj,
            with_env_var=True,
        )
        self.assertEqual(rc, 0, msg=f"stdout={out!r} stderr={err!r}")
        proj_f = self.proj / ".claude" / "cc-enslaver" / "edicts.toml"
        self.assertTrue(proj_f.is_file())

    def test_list_via_cwd_after_cwd_add(self) -> None:
        # Round-trip: add via cwd fallback, then list (also relying
        # on cwd fallback) should see the new edict.
        self._run("add", "E01", "round trip", "--must", "--deny-bash", "x",
                  cwd=self.proj)
        rc, out, _ = self._run("list", cwd=self.proj)
        self.assertEqual(rc, 0)
        self.assertIn("[E01]", out)
        self.assertIn("round trip", out)

    def test_path_subcommand_reports_cwd_location_when_env_unset(self) -> None:
        # `path` with no existing file should point at the cwd-derived
        # write target, not at $HOME, so the operator knows where the
        # writer would land.
        rc, out, _ = self._run("path", cwd=self.proj)
        self.assertEqual(rc, 0)
        self.assertIn("does not exist yet", out)
        self.assertIn(str(self.proj), out)


if __name__ == "__main__":
    unittest.main()
