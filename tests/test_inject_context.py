"""Tests for hooks/scripts/inject_context.py.

The script is purely additive (always exits 0, only emits
hookSpecificOutput.additionalContext). These tests verify:
  - The output JSON shape matches Claude Code's hook spec.
  - The injected content is non-empty and references the rule pack.
  - Non-ASCII (CJK) content survives the UTF-8 stdout pipeline on
    Windows (where Python's default stdout encoding would otherwise
    mangle it).

v0.21 — language architecture inverted: **English is the skeleton
(source of truth) and the runtime default**; Chinese is a first-class
translation reached via ``CC_ENFORCER_LANG=zh`` (``prompts/zh/*.md``).
The tests are organised by language path:
  - ``TestInjectContextDefault``  — no env var → English skeleton.
  - ``TestInjectContextEnglish``  — explicit ``en`` + unknown-lang fallback.
  - ``TestInjectContextChinese``  — ``zh`` translation (granular per-rule
    coverage; every rule's Chinese content must still be present).
"""

from __future__ import annotations

import sys
from pathlib import Path

# The sys.path.insert must precede importing _helpers, so the import
# cannot sit at module top — E402 is silenced because the path bootstrap
# is a precondition of the import, not misplaced code.
sys.path.insert(0, str(Path(__file__).resolve().parent))
import re  # noqa: E402 -- kept after the path bootstrap for import grouping
import unittest  # noqa: E402 -- kept after the path bootstrap for import grouping

from _helpers import SCRIPTS_DIR, run_hook  # noqa: E402 -- see path-bootstrap note

INJECT = str(SCRIPTS_DIR / "inject_context.py")
PLUGIN_ROOT = SCRIPTS_DIR.parent.parent

# TestOutputCap calls build_context directly (the cap arithmetic is a pure
# function; driving it through the subprocess would only let us observe
# the final size, not which half yielded).
sys.path.insert(0, str(SCRIPTS_DIR))
import inject_context as ic  # noqa: E402 -- see path-bootstrap note


class TestInjectContextDefault(unittest.TestCase):
    """No CC_ENFORCER_LANG → the English skeleton (``prompts/*.md``).

    English is the source-of-truth 'skeleton' language (v0.21). These
    cover the JSON hook shape, the language-neutral 01-11 structural
    contract, and that the *default* (no env var) resolves to English.
    """

    def test_returns_valid_hook_output(self) -> None:
        rc, out, err = run_hook(
            [INJECT, "--event", "SessionStart"],
            stdin_payload={
                "session_id": "test-session",
                "hook_event_name": "SessionStart",
            },
        )
        self.assertEqual(rc, 0, msg=err)
        self.assertIsNotNone(out)
        self.assertIn("hookSpecificOutput", out)
        self.assertEqual(out["hookSpecificOutput"]["hookEventName"], "SessionStart")
        self.assertIn("additionalContext", out["hookSpecificOutput"])

    def test_content_references_rules(self) -> None:
        _, out, _ = run_hook(
            [INJECT, "--event", "SessionStart"],
            stdin_payload={"session_id": "t", "hook_event_name": "SessionStart"},
        )
        ctx = out["hookSpecificOutput"]["additionalContext"]
        # v0.22: 11 numbered rules now, all must appear in the session-
        # start injection. These tokens are language-neutral (rule
        # numbers + the rules/ path), so they hold for the English
        # skeleton default and every translation alike.
        for label in ("01", "02", "03", "04", "05", "06", "07", "08", "09",
                      "10", "11", "rules/"):
            self.assertIn(label, ctx, msg=f"context missing {label!r}")

    def test_no_lang_env_var_uses_english(self) -> None:
        # v0.21 — with no CC_ENFORCER_LANG the default is now the English
        # skeleton (was Chinese pre-v0.21). Assert English content is
        # present and the Chinese-canonical headers do NOT bleed in.
        _, out, _ = run_hook(
            [INJECT, "--event", "SessionStart"],
            stdin_payload={"session_id": "t", "hook_event_name": "SessionStart"},
            # No CC_ENFORCER_LANG in env.
        )
        ctx = out["hookSpecificOutput"]["additionalContext"]
        self.assertIn("Session Discipline Contract", ctx)
        self.assertIn("Verify, don't guess", ctx)
        self.assertNotIn("会话纪律合约", ctx)
        self.assertNotIn("强制注入", ctx)


class TestInjectContextEnglish(unittest.TestCase):
    """Explicit ``CC_ENFORCER_LANG=en`` + unknown-lang fallback.

    ``en`` reads the root skeleton (same files the default resolves to);
    an unrecognised code falls back to that same English skeleton.
    """

    def test_lang_en_uses_english_session_start(self) -> None:
        _, out, _ = run_hook(
            [INJECT, "--event", "SessionStart"],
            stdin_payload={"session_id": "t", "hook_event_name": "SessionStart"},
            env_overrides={"CC_ENFORCER_LANG": "en"},
        )
        ctx = out["hookSpecificOutput"]["additionalContext"]
        # English skeleton keyword contract — must include the rule
        # numbers + the English disciplinary phrases.
        for needle in (
            "Session Discipline Contract",
            "Verify, don't guess",
            "Systematic, not reactive",
            "Read-before-edit",
            "think-before-write",
            "Did this really solve the problem",
            "Is there a better solution",
            "Has the change been verified",
            "Is the verification reasonable",
            "Task fidelity",
            "rule 08",
            "rule 09",
            "layer (e)",
            "layer (f)",
            # v0.20 — YAML schema + tldr / layer (h) must surface too.
            "cc-enforcer:",
            "tldr",
            "layer (h)",
        ):
            self.assertIn(needle, ctx, msg=f"english session-start missing {needle!r}")
        # And critically: the Chinese headers must NOT bleed into the
        # English injection (proves we're actually reading the skeleton).
        self.assertNotIn("会话纪律合约", ctx)
        self.assertNotIn("强制注入", ctx)

    def test_lang_en_uses_english_user_prompt(self) -> None:
        _, out, _ = run_hook(
            [INJECT, "--event", "UserPromptSubmit"],
            stdin_payload={"session_id": "t", "hook_event_name": "UserPromptSubmit"},
            env_overrides={"CC_ENFORCER_LANG": "en"},
        )
        ctx = out["hookSpecificOutput"]["additionalContext"]
        for needle in (
            "Decision-time triggers",
            "convergence",
            "fidelity",
            "read-before-edit",
            "think-before-write",
            "systematic",
        ):
            self.assertIn(needle, ctx, msg=f"english user-prompt missing {needle!r}")

    def test_unknown_lang_falls_back_to_english(self) -> None:
        # v0.21 — English is the skeleton, so an unsupported / typo'd
        # language must fall back to English (was Chinese pre-v0.21). The
        # injection must not silently drop.
        _, out, _ = run_hook(
            [INJECT, "--event", "SessionStart"],
            stdin_payload={"session_id": "t", "hook_event_name": "SessionStart"},
            env_overrides={"CC_ENFORCER_LANG": "fr"},
        )
        ctx = out["hookSpecificOutput"]["additionalContext"]
        self.assertIn("Session Discipline Contract", ctx)
        self.assertNotIn("会话纪律合约", ctx)


class TestInjectContextChinese(unittest.TestCase):
    """``CC_ENFORCER_LANG=zh`` → ``prompts/zh/*.md`` (Chinese translation).

    v0.21 — Chinese is now a first-class *translation* (was canonical).
    Every rule's Chinese content must still be present in the zh
    injection; these preserve the granular per-rule coverage under the
    zh path so the flip does not silently degrade Chinese support.
    """

    ZH = {"CC_ENFORCER_LANG": "zh"}

    def test_content_references_rule_06_convergence(self) -> None:
        # Rule 06 is the post-fix verify-and-converge rule (v0.5.0). The
        # session-start prompt must surface its 4-question self-quiz so
        # the agent sees them on every cold start.
        _, out, _ = run_hook(
            [INJECT, "--event", "SessionStart"],
            stdin_payload={"session_id": "t", "hook_event_name": "SessionStart"},
            env_overrides=self.ZH,
        )
        ctx = out["hookSpecificOutput"]["additionalContext"]
        # The 4 self-questions phrased in Chinese (matching zh/session-start.md):
        for needle in (
            "验证收敛",
            "重触发原症状",
            "是不是真的解决了问题",
            "有没有更好的解决方法",
            "改动是否经过验证",
            "验证是否合理",
        ):
            self.assertIn(needle, ctx, msg=f"session-start prompt missing {needle!r}")

    def test_user_prompt_includes_convergence_check(self) -> None:
        # The per-turn reminder should also nudge the agent toward
        # convergence checks before declaring done.
        _, out, _ = run_hook(
            [INJECT, "--event", "UserPromptSubmit"],
            stdin_payload={"session_id": "t", "hook_event_name": "UserPromptSubmit"},
            env_overrides=self.ZH,
        )
        ctx = out["hookSpecificOutput"]["additionalContext"]
        self.assertIn("收敛", ctx, msg="user-prompt missing convergence reminder")

    def test_content_references_rule_07_fidelity(self) -> None:
        # Rule 07 is the post-fix request-coverage / no-degrade rule
        # (v0.8.0). The session-start prompt must surface its three
        # self-questions and the "modifier word" warning.
        _, out, _ = run_hook(
            [INJECT, "--event", "SessionStart"],
            stdin_payload={"session_id": "t", "hook_event_name": "SessionStart"},
            env_overrides=self.ZH,
        )
        ctx = out["hookSpecificOutput"]["additionalContext"]
        for needle in (
            "任务忠实",
            "覆盖性",
            "标准性",
            "忠实性",
            "原始请求",
        ):
            self.assertIn(needle, ctx, msg=f"session-start prompt missing {needle!r}")

    def test_user_prompt_includes_fidelity_check(self) -> None:
        # Per-turn reminder must also include rule-07 fidelity nudge.
        _, out, _ = run_hook(
            [INJECT, "--event", "UserPromptSubmit"],
            stdin_payload={"session_id": "t", "hook_event_name": "UserPromptSubmit"},
            env_overrides=self.ZH,
        )
        ctx = out["hookSpecificOutput"]["additionalContext"]
        self.assertIn("忠实", ctx, msg="user-prompt missing fidelity reminder")

    def test_content_references_rule_08_read_before_edit(self) -> None:
        # v0.11 — rule 08 (read-before-edit / think-before-write) must
        # appear in the session-start injection with both halves named.
        _, out, _ = run_hook(
            [INJECT, "--event", "SessionStart"],
            stdin_payload={"session_id": "t", "hook_event_name": "SessionStart"},
            env_overrides=self.ZH,
        )
        ctx = out["hookSpecificOutput"]["additionalContext"]
        for needle in (
            "改前必读",
            "写前必想",
            "rule 08",
            # The Stop-hook layer (e) reference confirms physical-
            # enforcement disclosure in the injection.
            "layer (e)",
        ):
            self.assertIn(needle, ctx, msg=f"session-start prompt missing {needle!r}")

    def test_content_references_rule_09_systematic_modification(self) -> None:
        # v0.11 — rule 09 (systematic modification, no patch-style) must
        # appear in the session-start injection with the anti-patch
        # vocabulary and the physical-enforcement callout.
        _, out, _ = run_hook(
            [INJECT, "--event", "SessionStart"],
            stdin_payload={"session_id": "t", "hook_event_name": "SessionStart"},
            env_overrides=self.ZH,
        )
        ctx = out["hookSpecificOutput"]["additionalContext"]
        for needle in (
            "系统式修改",
            "禁止打补丁",
            "rule 09",
            "layer (f)",
        ):
            self.assertIn(needle, ctx, msg=f"session-start prompt missing {needle!r}")

    def test_user_prompt_includes_rule_08_and_09_reminders(self) -> None:
        # The per-turn reminder must surface rule-08 + rule-09 nudges
        # since they govern the "during this turn" workflow.
        _, out, _ = run_hook(
            [INJECT, "--event", "UserPromptSubmit"],
            stdin_payload={"session_id": "t", "hook_event_name": "UserPromptSubmit"},
            env_overrides=self.ZH,
        )
        ctx = out["hookSpecificOutput"]["additionalContext"]
        for needle in (
            "改前必读",
            "写前必想",
            "系统式",
        ):
            self.assertIn(needle, ctx, msg=f"user-prompt missing {needle!r}")

    def test_content_references_yaml_schema_and_tldr(self) -> None:
        # v0.20 — the session-start injection must teach the canonical
        # YAML reply schema and the mandatory tldr / layer (h) closing.
        _, out, _ = run_hook(
            [INJECT, "--event", "SessionStart"],
            stdin_payload={"session_id": "t", "hook_event_name": "SessionStart"},
            env_overrides=self.ZH,
        )
        ctx = out["hookSpecificOutput"]["additionalContext"]
        for needle in (
            "cc-enforcer:",   # the YAML block root key
            "tldr",
            "大白话",
            "layer (h)",
        ):
            self.assertIn(needle, ctx, msg=f"session-start prompt missing {needle!r}")

    def test_user_prompt_includes_tldr_reminder(self) -> None:
        _, out, _ = run_hook(
            [INJECT, "--event", "UserPromptSubmit"],
            stdin_payload={"session_id": "t", "hook_event_name": "UserPromptSubmit"},
            env_overrides=self.ZH,
        )
        ctx = out["hookSpecificOutput"]["additionalContext"]
        self.assertIn("tldr", ctx, msg="user-prompt missing tldr reminder")
        self.assertIn("layer (h)", ctx, msg="user-prompt missing layer (h)")

    def test_content_is_utf8_intact(self) -> None:
        # Smoke test for the Windows cp936 stdout regression: the zh
        # prompt file is Chinese, and if we did not write
        # sys.stdout.buffer as UTF-8 the CJK chars would mojibake before
        # reaching us. Pinned to zh so it keeps exercising CJK now that
        # the default injection is English.
        _, out, _ = run_hook(
            [INJECT, "--event", "SessionStart"],
            stdin_payload={"session_id": "t", "hook_event_name": "SessionStart"},
            env_overrides=self.ZH,
        )
        ctx = out["hookSpecificOutput"]["additionalContext"]
        # Pick a known CJK substring from prompts/zh/session-start.md.
        self.assertIn("会话", ctx)
        self.assertIn("规则", ctx)


class TestInjectContextUserPromptSubmit(unittest.TestCase):
    def test_returns_valid_hook_output(self) -> None:
        rc, out, err = run_hook(
            [INJECT, "--event", "UserPromptSubmit"],
            stdin_payload={
                "session_id": "test-session",
                "hook_event_name": "UserPromptSubmit",
            },
        )
        self.assertEqual(rc, 0, msg=err)
        self.assertEqual(
            out["hookSpecificOutput"]["hookEventName"],
            "UserPromptSubmit",
        )
        self.assertGreater(
            len(out["hookSpecificOutput"]["additionalContext"]),
            50,
            msg="user-prompt reminder is suspiciously short",
        )


class TestOutputCap(unittest.TestCase):
    """v0.29 — the injection must never exceed the hook output cap.

    Claude Code caps hook output (additionalContext included) at 10,000
    CHARACTERS and replaces anything longer with a file path plus a short
    preview (https://code.claude.com/docs/en/hooks#json-output). The
    field failure this guards: 16 project edicts (~5.6k chars) on top of
    a 13.2k-char contract produced an 18.8k-char SessionStart injection,
    so §3 — the mandatory reply schema — sat past the preview boundary
    and went unread for a whole session. Both live injections must fit,
    and the edict block (the only unbounded part) must be what yields
    when the budget gets tight.
    """

    def _ctx(self, event: str) -> str:
        _, out, _ = run_hook(
            [INJECT, "--event", event],
            stdin_payload={"session_id": "t", "hook_event_name": event},
        )
        return out["hookSpecificOutput"]["additionalContext"]

    def test_live_injections_fit_under_the_cap(self) -> None:
        for event in ("SessionStart", "UserPromptSubmit"):
            with self.subTest(event=event):
                size = len(self._ctx(event))
                self.assertLessEqual(
                    size, ic.OUTPUT_CAP,
                    msg=f"{event} injection is {size} chars — it will be "
                        f"persisted to a file and only previewed inline",
                )

    def test_self_locating_header_leads_the_injection(self) -> None:
        # Defense in depth: if the cap is ever breached anyway, the
        # surviving preview must still say where the full text lives.
        #
        # v0.38.3 — measured against the header, not a fixed 200-character
        # slice. That slice encoded an assumption nobody stated: that the
        # install root is short. It is 23 characters here and 110 in a
        # clone under a temp path, where the filename fell outside the
        # window and this test failed on code that was working correctly.
        # A test that passes because of the maintainer's directory layout
        # is not testing the property it names.
        ctx = self._ctx("SessionStart")
        header = ctx.split("\n\n", 1)[0]
        self.assertIn("cc-enforcer root:", header)
        self.assertIn("prompts/session-start.md", header)

    def test_the_header_names_the_root_once(self) -> None:
        """The root is the header's only unbounded part — spend it once.

        It used to be printed twice, and the repeat came out of the same
        10,000-character budget the header exists to protect: a
        120-character install root cut the edict allowance from 386
        characters to 192 for nothing.
        """
        root = str(ic.PLUGIN_ROOT)
        header = self._ctx("SessionStart").split("\n\n", 1)[0]
        self.assertEqual(
            header.count(root), 1,
            f"the install root appears {header.count(root)} times in the "
            f"header; every repeat is subtracted from the edict budget",
        )

    def test_edicts_yield_before_the_contract(self) -> None:
        body = (PLUGIN_ROOT / "prompts" / "session-start.md").read_text(
            encoding="utf-8")
        edicts = "".join(
            f"\n  [E{i:02d}] must\n    " + "x" * 600 + "\n"
            for i in range(1, 201)
        )
        out = ic.build_context("session-start.md", body, edicts)
        self.assertLessEqual(len(out), ic.OUTPUT_CAP)
        self.assertIn(
            body.rstrip()[-80:], out,
            msg="the contract tail must survive; only edicts may be elided",
        )
        self.assertIn("elided to stay under", out)

    def test_a_total_elision_still_reports_the_count(self) -> None:
        """The no-room branch must say every edict was dropped.

        Found by running the suite from a clone at a long path, not by
        reading the function: when the contract alone fills the budget,
        `build_context` returned header + body and said nothing. A
        session on a deeply-nested install was then governed by rules it
        had never been shown, with no way to learn that. Same defect as
        v0.34.1 (all edicts elided, notice reporting 0), one branch over.

        The root is stretched rather than the body, because the body is
        the thing budgeted to fit — the trigger in the wild is an install
        path, and stating that keeps the test honest about what it
        reproduces.
        """
        body = (PLUGIN_ROOT / "prompts" / "session-start.md").read_text(
            encoding="utf-8")
        edicts = "".join(
            f"\n| `E{i:02d}` | must | rule number {i} |" for i in range(1, 9))
        original = ic.PLUGIN_ROOT
        try:
            ic.PLUGIN_ROOT = "C:" + "\\" + "x" * 700
            out = ic.build_context("session-start.md", body, edicts)
        finally:
            ic.PLUGIN_ROOT = original
        self.assertNotIn("E01", out, "premise: no edict survives this budget")
        self.assertIn(
            "8 edict(s) elided", out,
            "every edict was dropped and the injection did not say so",
        )

    def test_a_partial_elision_is_unaffected(self) -> None:
        """The twin: the branch that had room must still clip, not dump.

        Without this, the fix above could be 'always drop everything and
        report it', which would pass the assertion it was written for.
        """
        body = (PLUGIN_ROOT / "prompts" / "session-start.md").read_text(
            encoding="utf-8")
        edicts = "".join(
            f"\n| `E{i:02d}` | must | " + "x" * 120 + " |" for i in range(1, 9))
        out = ic.build_context("session-start.md", body, edicts)
        self.assertIn("E01", out, "the first edicts must still be kept")
        self.assertIn("elided", out, "and the cut ones still reported")

    def _rendered_edicts(self, n: int, payload: int = 300) -> str:
        """The REAL injected shape, via the real renderer.

        The first version of these tests hand-rolled the `[Exx]` line
        shape that `manage_edicts list` PRINTS — but the injected block is
        a markdown table whose data rows start "| `<id>` |" — so the tests
        stayed green while `_clip_edicts`, keyed to the wrong shape,
        dropped every edict on the over-cap path and reported 0 cut
        (fixed v0.34.1).
        """
        from lib import edicts as edicts_lib
        eds = [
            edicts_lib.Edict(id=f"E{i:02d}", text="x" * payload,
                             severity="must")
            for i in range(1, n + 1)
        ]
        return edicts_lib.render_injection(eds, lang="en")

    def test_whole_edicts_only_never_half_of_one(self) -> None:
        body = "B" * 8000
        out = ic.build_context(
            "session-start.md", body, self._rendered_edicts(19))
        self.assertLessEqual(len(out), ic.OUTPUT_CAP)
        kept_rows = [ln for ln in out.splitlines()
                     if ic._EDICT_ENTRY.match(ln)]
        # Non-vacuity guard: the pre-v0.34.1 defect dropped EVERY edict,
        # which would sail through a loop over zero retained rows.
        self.assertTrue(
            kept_rows,
            "no edict retained at all — the boundary pattern no longer "
            "matches the rendered rows",
        )
        # Every retained row must carry its full 300-char payload: a
        # half-rendered edict still reads as a complete instruction.
        for row in kept_rows:
            self.assertIn("x" * 300, row, msg=f"truncated row: {row[:60]}")

    def test_elision_notice_reports_the_true_count(self) -> None:
        # v0.34.1 regression pin: with the old `[Exx]`-shaped boundary
        # pattern the rendered table matched nothing, so the over-cap path
        # dropped EVERY edict while the notice claimed 0 cut — an
        # unfounded claim in the output of the plugin built to block them.
        total = 19
        out = ic.build_context(
            "session-start.md", "B" * 8000, self._rendered_edicts(total))
        kept = sum(1 for ln in out.splitlines()
                   if ic._EDICT_ENTRY.match(ln))
        m = re.search(r"<!-- (\d+) edict\(s\) elided", out)
        self.assertIsNotNone(
            m, "over-cap path must emit the elision notice")
        self.assertEqual(
            kept + int(m.group(1)), total,
            "kept + reported-elided must equal the total",
        )
        self.assertGreater(int(m.group(1)), 0)

    def test_entry_pattern_is_coupled_to_the_renderer(self) -> None:
        # If render_injection ever changes its row shape, this fails
        # before production silently reverts to drop-all-report-zero.
        rendered = self._rendered_edicts(2, payload=10)
        rows = [ln for ln in rendered.splitlines()
                if ic._EDICT_ENTRY.match(ln)]
        self.assertEqual(len(rows), 2)
        # Twin: the table header / separator rows are NOT entries.
        self.assertFalse(ic._EDICT_ENTRY.match("| ID | Severity | X |"))
        self.assertFalse(ic._EDICT_ENTRY.match("|----|----------|---|"))

    def test_body_alone_over_cap_keeps_body_drops_edicts(self) -> None:
        # Negative case: nothing can be salvaged by eliding edicts, so
        # the contract is emitted whole (degraded, harness-persisted)
        # rather than silently cut mid-sentence.
        out = ic.build_context(
            "session-start.md", "H" * (ic.OUTPUT_CAP + 5000),
            self._rendered_edicts(1, payload=10),
        )
        self.assertNotIn("`E01`", out)
        self.assertIn("H" * 100, out)


class TestSyncCheckIsASchemaField(unittest.TestCase):
    """v0.31.1 — rule 12's closing obligation joined the reply schema.

    Every other closing duty (before / edits / convergence / fidelity /
    closing / tldr) has been a schema FIELD since v0.20, and the v0.20
    design is that the field name IS the Stop-hook marker. Rule 12
    arrived three releases later and its acknowledgement stayed loose
    prose the agent had to remember to write — the one obligation with
    no slot to write it in.

    Two things must hold, and neither is implied by the other:
      1. the field is present in all four injected prompts, and
      2. its name still matches a real `SYNC_MARKERS` pattern.
    Renaming the field without (2) would produce a schema that looks
    complete and satisfies nothing.
    """

    def _prompt(self, rel: str) -> str:
        return (PLUGIN_ROOT / "prompts" / rel).read_text(encoding="utf-8")

    def test_every_injected_prompt_carries_the_field(self) -> None:
        for rel, key in (
            ("session-start.md", "sync-check:"),
            ("user-prompt.md", "sync-check:"),
            ("zh/session-start.md", "同步核对:"),
            ("zh/user-prompt.md", "同步核对:"),
        ):
            with self.subTest(prompt=rel):
                self.assertIn(key, self._prompt(rel))

    def test_the_field_name_is_a_real_stop_marker(self) -> None:
        """The v0.20 contract: field names ARE the detection markers."""
        sys.path.insert(0, str(SCRIPTS_DIR))
        import stop_guard  # noqa: E402 -- after the path bootstrap above
        for line in ('  sync-check: "co-files updated"',
                     '  同步核对: "require 侧无需变更"'):
            with self.subTest(line=line):
                self.assertTrue(stop_guard._has_sync_marker(line))

    def test_a_renamed_field_would_not_satisfy_the_gate(self) -> None:
        """Twin: proves the assertion above is not vacuously true."""
        sys.path.insert(0, str(SCRIPTS_DIR))
        import stop_guard  # noqa: E402 -- after the path bootstrap above
        self.assertFalse(stop_guard._has_sync_marker('  sync-sweep: "done"'))

    def test_both_languages_still_fit_under_the_cap(self) -> None:
        """Adding a field costs characters; SessionStart had ~1k spare."""
        for lang in ("", "zh"):
            for event, rel in (("SessionStart", "session-start.md"),
                               ("UserPromptSubmit", "user-prompt.md")):
                with self.subTest(lang=lang or "en", event=event):
                    _, out, _ = run_hook(
                        [INJECT, "--event", event],
                        stdin_payload={"session_id": "t",
                                       "hook_event_name": event},
                        env_overrides={"CC_ENFORCER_LANG": lang or "en"},
                    )
                    ctx = out["hookSpecificOutput"]["additionalContext"]
                    self.assertLessEqual(len(ctx), ic.OUTPUT_CAP)
                    self.assertIn(
                        "同步核对" if lang == "zh" else "sync-check", ctx)


if __name__ == "__main__":
    unittest.main()
