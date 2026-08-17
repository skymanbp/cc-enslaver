"""Regressions for the second v0.26.0 audit (16 parallel read-only reviews).

Every test here pins a defect that was REPRODUCED against the real code
before anything was changed. The reviews returned roughly a hundred
observations; most were already-documented limitations or inherent to a
regex hook, and are not represented here. These are the ones that were
independently confirmed.

House rules followed throughout:

* Every "this is allowed" assertion has a twin that removes the reason and
  requires a DENY. An allow-only test cannot tell a working escape hatch
  from a dead detector — four such tests shipped in v0.25.1.
* Fixtures that contain suppression markers, credentials or home paths are
  ASSEMBLED AT RUNTIME. This plugin scans its own test files, so a literal
  fixture would make the module unwritable by any agent running it.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

# The sys.path bootstrap must precede these imports; E402 is silenced
# because the path setup is a precondition of the import, not dead code.
_SCRIPTS = Path(__file__).resolve().parents[1] / "hooks" / "scripts"
sys.path.insert(0, str(_SCRIPTS))
import bash_guard  # noqa: E402 -- because the path bootstrap must run first
import manage_edicts  # noqa: E402 -- because of the path bootstrap above
import read_guard  # noqa: E402 -- because of the path bootstrap above
import stop_guard  # noqa: E402 -- because of the path bootstrap above
# because of the sys.path bootstrap above, this import cannot sit at top
from lib import mdctx, srclex, state as state_lib  # noqa: E402

CR = chr(13)
TAB = chr(9)
BACKTICK = chr(96)
HOME_VAR = "$" + "HOME"
Q = chr(34)
# A credential-shaped literal, built so this file does not contain one.
SECRET_LINE = "password = " + Q + "RealSecret123!" + Q
SQ = chr(39)
SH_SECRET_LINE = "password=" + SQ + "RealSecret123!" + SQ  # fixture, not a secret
REASON = "# because upstream requires it"


class TestSrclexDocstringPosition(unittest.TestCase):
    """A triple-quoted block is documentation only in docstring position."""

    def test_bare_string_expression_is_not_a_rationale(self) -> None:
        src = "x = 1\n" + Q * 3 + "because upstream requires it" + Q * 3 \
            + "\n" + SECRET_LINE + "\n"
        self.assertIsNotNone(
            read_guard._find_hardcoded_secret(src, lang="py"),
            "a discarded string expression is not documentation; treating "
            "it as one silences the secret detector",
        )

    def test_module_docstring_is_a_rationale(self) -> None:
        src = Q * 3 + "because upstream requires it" + Q * 3 + "\n" \
            + SECRET_LINE + "\n"
        self.assertIsNone(read_guard._find_hardcoded_secret(src, lang="py"))

    def test_function_docstring_is_a_rationale(self) -> None:
        src = "def f():\n    " + Q * 3 + "because upstream requires it" \
            + Q * 3 + "\n    " + SECRET_LINE + "\n"
        self.assertIsNone(read_guard._find_hardcoded_secret(src, lang="py"))

    def test_raw_prefixed_docstring_is_a_rationale(self) -> None:
        src = "r" + Q * 3 + "because upstream requires it" + Q * 3 + "\n" \
            + SECRET_LINE + "\n"
        self.assertIsNone(
            read_guard._find_hardcoded_secret(src, lang="py"),
            "an r-prefixed docstring is still a docstring",
        )


class TestSrclexLineEndings(unittest.TestCase):
    """CR terminates a comment; it is not ordinary text."""

    def test_lone_cr_does_not_extend_a_comment_over_the_file(self) -> None:
        src = REASON + CR + "x = 1" + CR + "y = 2" + CR + SECRET_LINE + CR
        self.assertIsNotNone(
            read_guard._find_hardcoded_secret(src, lang="py"),
            "the rationale is three lines away; a CR-terminated comment "
            "must not swallow the credential into comment text",
        )

    def test_adjacent_rationale_still_allows_with_cr(self) -> None:
        src = "x = 1" + CR + REASON + CR + SECRET_LINE + CR
        self.assertIsNone(read_guard._find_hardcoded_secret(src, lang="py"))

    def test_cr_only_source_still_yields_logical_lines(self) -> None:
        joined = srclex.logical_lines("a = 1" + CR + "b = 2" + CR, "py")
        self.assertEqual(len(joined), 3, "CR must split logical lines")


class TestSrclexShellQuoting(unittest.TestCase):
    def test_single_quotes_take_no_escapes_in_sh(self) -> None:
        src = "x='a\\' " + REASON + "\n" + SH_SECRET_LINE + "\n"
        self.assertIsNone(
            read_guard._find_hardcoded_secret(src, lang="sh"),
            "POSIX single quotes end at the quote after a backslash, so "
            "the trailing comment is a real rationale",
        )

    def test_twin_without_reason_denies(self) -> None:
        src = "x='a\\' # unrelated note\n" + SH_SECRET_LINE + "\n"
        self.assertIsNotNone(read_guard._find_hardcoded_secret(src, lang="sh"))


class TestMdctxFenceGeometry(unittest.TestCase):
    def _countable(self, text: str) -> list[bool]:
        return [ln.countable for ln in mdctx.lines(text)]

    def test_tab_indented_fence_does_not_open(self) -> None:
        text = TAB + BACKTICK * 3 + "text\ntldr: measured\n"
        self.assertTrue(self._countable(text)[1],
                        "a tab is 4 columns: that line is indented code, "
                        "not a fence, so the tldr below is visible")

    def test_backtick_in_info_string_does_not_open(self) -> None:
        text = BACKTICK * 3 + "text" + BACKTICK + "bad\ntldr: measured\n"
        self.assertTrue(self._countable(text)[1])

    def test_list_nested_fence_does_open(self) -> None:
        text = "- " + BACKTICK * 3 + "text\n  quoted fixture\n  " \
            + BACKTICK * 3 + "\ntldr: mine\n"
        ctx = self._countable(text)
        self.assertFalse(ctx[1], "fixture inside a list-nested fence")
        self.assertTrue(ctx[3], "the agent's own tldr after it")

    def test_canonical_yaml_fence_still_measurable(self) -> None:
        text = BACKTICK * 3 + "yaml\ntldr: x\n" + BACKTICK * 3 + "\n"
        self.assertTrue(self._countable(text)[1])


class TestTldrContinuationAttribution(unittest.TestCase):
    """Both halves of layer (h) apply the same attribution test."""

    def test_blockquoted_continuation_is_not_measured(self) -> None:
        text = "tldr: short\n  > " + ("A" * 200)
        self.assertIsNone(
            stop_guard._find_overlong_tldr(text),
            "a quoted continuation line is not the agent's own tldr",
        )

    def test_real_overlong_continuation_is_measured(self) -> None:
        text = "tldr: short\n    " + ("A" * 200)
        self.assertIsNotNone(stop_guard._find_overlong_tldr(text))


class TestDoneClaimNegationV0262(unittest.TestCase):
    def _claims(self, text: str) -> bool:
        return stop_guard._has_done_claim(text) is not None

    def test_far_from_done_is_not_a_claim(self) -> None:
        self.assertFalse(self._claims("I am far from done. Tests failed."))

    def test_hardly_done_is_not_a_claim(self) -> None:
        self.assertFalse(self._claims("This is hardly done yet."))

    def test_double_negative_followed_by_real_negation(self) -> None:
        self.assertFalse(
            self._claims("不得不说明任务还没完成了"),
            "the nearer negator scopes the claim",
        )

    def test_true_double_negative_is_still_a_claim(self) -> None:
        self.assertTrue(self._claims("不得不承认已完成"))

    def test_chinese_connective_ends_the_negated_clause(self) -> None:
        self.assertTrue(
            self._claims("没有遗漏这部分工作所以这次已经完成了"),
            "所以 starts a new clause; the completion is genuine",
        )

    def test_plain_chinese_negation_still_negates(self) -> None:
        self.assertFalse(self._claims("任务还没完成了"))

    def test_predicative_complete_is_a_claim(self) -> None:
        self.assertTrue(self._claims("Work complete. Ready to ship."))

    def test_imperative_complete_is_not_a_claim(self) -> None:
        self.assertFalse(self._claims("Please complete the migration."))


class TestLayerGSubjectAnchoring(unittest.TestCase):
    def test_version_attribution_inside_first_person_is_not_a_self_claim(
        self,
    ) -> None:
        text = "我确认 v0.23 修改了 lib/state.py；本次没有修改该文件。"
        self.assertEqual(
            stop_guard._FILE_CLAIMS_ZH.findall(text), [],
            "the grammatical subject is v0.23, not the agent",
        )

    def test_plain_first_person_claim_still_parses(self) -> None:
        self.assertEqual(
            len(stop_guard._FILE_CLAIMS_ZH.findall("我修改了 lib/state.py")), 1)


class TestStateCorruptionRecovery(unittest.TestCase):
    def setUp(self) -> None:
        self._dir = tempfile.mkdtemp()
        self._prev = os.environ.get("CLAUDE_PLUGIN_DATA")
        os.environ["CLAUDE_PLUGIN_DATA"] = self._dir

    def tearDown(self) -> None:
        if self._prev is None:
            os.environ.pop("CLAUDE_PLUGIN_DATA", None)
        else:
            os.environ["CLAUDE_PLUGIN_DATA"] = self._prev

    def test_unparseable_state_is_quarantined_not_overwritten(self) -> None:
        sid = "audit2-corrupt"
        target = str(Path(__file__).resolve())
        self.assertTrue(state_lib.add_read(sid, target))
        f = state_lib._state_file(sid)
        f.write_text("{ not json", encoding="utf-8")
        # Fails OPEN on the gating path rather than falsely denying.
        self.assertTrue(state_lib.has_read(sid, target))
        self.assertTrue(f.with_name(f.name + ".corrupt").exists(),
                        "the damaged file must be preserved, not clobbered")
        # And the session can carry on.
        state_lib.add_read(sid, target)
        self.assertTrue(state_lib.has_read(sid, target))

    def test_add_read_reports_whether_it_persisted(self) -> None:
        self.assertIs(
            state_lib.add_read("audit2-ok", str(Path(__file__).resolve())),
            True,
            "callers must be able to distinguish a stored record from a "
            "lost one; register_read reports success from this value",
        )


class TestBashStaticPatternsUseArgv(unittest.TestCase):
    def _denies(self, command: str) -> bool:
        import lib.shellcmd as shellcmd
        for argv in shellcmd.segments(command):
            if not argv:
                continue
            if shellcmd.command_name(argv) in bash_guard._INERT_COMMANDS:
                continue
            for pat in bash_guard.STATIC_PATTERNS:
                if pat["match"](argv):
                    return True
        return False

    def test_chmod_with_an_unanticipated_option(self) -> None:
        self.assertTrue(self._denies("chmod -v 777 file"))

    def test_chmod_four_digit_mode(self) -> None:
        self.assertTrue(self._denies("chmod 7777 file"))

    def test_chmod_benign_mode_allowed(self) -> None:
        self.assertFalse(self._denies("chmod 644 file"))

    def test_git_global_option_before_rebase(self) -> None:
        self.assertTrue(self._denies("git -C . rebase --skip"))

    def test_rebase_continue_allowed(self) -> None:
        self.assertFalse(self._denies("git rebase --continue"))

    def test_rm_with_terminator_and_quoted_home(self) -> None:
        self.assertTrue(self._denies('rm -rf -- "' + HOME_VAR + '"'))

    def test_rm_long_options(self) -> None:
        self.assertTrue(self._denies("rm --recursive --force /"))

    def test_rm_under_system_root_still_denied(self) -> None:
        self.assertTrue(self._denies("rm -rf /usr/local/share"))

    def test_rm_scratch_subdirectory_allowed(self) -> None:
        self.assertFalse(self._denies("rm -rf /tmp/my-build"))

    def test_rm_project_directory_allowed(self) -> None:
        self.assertFalse(self._denies("rm -rf ./node_modules"))

    def test_quoted_flag_is_denied(self) -> None:
        self.assertTrue(self._denies("git commit '--no-verify'"))

    def test_longer_flag_is_not_a_match(self) -> None:
        self.assertFalse(self._denies("git commit --no-verify-extra"))

    def test_echoing_a_command_is_not_running_it(self) -> None:
        self.assertFalse(self._denies("echo git commit --no-verify"))
        self.assertFalse(self._denies("echo rm -rf /"))

    def test_unrelated_dash_f_is_not_a_force_push(self) -> None:
        self.assertFalse(self._denies("rm -f build.log && git status"))


class TestRegisterReadExecutionCertainty(unittest.TestCase):
    HASH = "a" * 64

    def test_plain_invocation_parses(self) -> None:
        self.assertIsNotNone(bash_guard._parse_register_invocation(
            "python register_read.py --file F --hash " + self.HASH))

    def test_equals_spelling_parses(self) -> None:
        self.assertIsNotNone(bash_guard._parse_register_invocation(
            "python register_read.py --file=F --hash=" + self.HASH))

    def test_interpreter_option_before_script_parses(self) -> None:
        self.assertIsNotNone(bash_guard._parse_register_invocation(
            "python -X utf8 register_read.py --file F --hash " + self.HASH))

    def test_conditional_invocation_earns_no_credit(self) -> None:
        self.assertIsNone(
            bash_guard._parse_register_invocation(
                "false && python register_read.py --file F --hash "
                + self.HASH),
            "the hook runs before execution and cannot know this branch "
            "is taken",
        )

    def test_compound_invocation_earns_no_credit(self) -> None:
        self.assertIsNone(bash_guard._parse_register_invocation(
            "python register_read.py --file F --hash " + self.HASH
            + " && git status"))

    def test_attached_inline_code_earns_no_credit(self) -> None:
        self.assertIsNone(
            bash_guard._parse_register_invocation(
                "python -cpass register_read.py --file F --hash "
                + self.HASH),
            "-cpass runs inline code; the script is only an argument",
        )

    def test_terminal_option_earns_no_credit(self) -> None:
        self.assertIsNone(bash_guard._parse_register_invocation(
            "python --version register_read.py --file F --hash " + self.HASH))


class TestEdictSerialisationRoundTrip(unittest.TestCase):
    """One hostile field must not take the whole edicts file down."""

    def _roundtrip(self, edict: dict) -> dict:
        import tomllib
        body = manage_edicts._HEADER + manage_edicts._dump_edict(edict)
        return tomllib.loads(body)["edicts"][0]

    def test_del_character_in_text(self) -> None:
        e = {"id": "E01", "text": "secrets" + chr(127), "severity": "must",
             "deny_bash": ["x"]}
        self.assertEqual(self._roundtrip(e)["text"], e["text"])

    def test_control_character_in_regex(self) -> None:
        e = {"id": "E01", "text": "t", "severity": "must",
             "deny_edit": ["foo" + chr(1) + "bar"]}
        self.assertEqual(self._roundtrip(e)["deny_edit"], e["deny_edit"])

    def test_triple_apostrophe_regex_survives(self) -> None:
        pattern = "foo" + ("'" * 3) + "bar"
        e = {"id": "E01", "text": "t", "severity": "must",
             "deny_edit": [pattern]}
        self.assertEqual(
            self._roundtrip(e)["deny_edit"], [pattern],
            "the literal form silently rewrote this pattern into "
            "something that no longer matched",
        )

    def test_backslash_regex_survives(self) -> None:
        pattern = chr(92) + "bmongoose" + chr(92) + "b"
        e = {"id": "E01", "text": "t", "severity": "must",
             "deny_edit": [pattern]}
        self.assertEqual(self._roundtrip(e)["deny_edit"], [pattern])

    def test_write_refuses_to_emit_unparseable_toml(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "edicts.toml"
            path.write_text("# seed\n", encoding="utf-8")
            before = path.read_text(encoding="utf-8")

            class Hostile:
                def __str__(self) -> str:
                    return Q + "\n[[edicts]]\nid = " + Q

            refused = False
            try:
                manage_edicts._write_edicts(path, [
                    {"id": Hostile(), "text": "t", "severity": "must"}])
            except manage_edicts.EdictWriteError:
                # Refusing to write is the other acceptable outcome. The
                # invariant under test is that the file on disk is never
                # left unparseable, not which branch produced that.
                refused = True
            self.assertIn(refused, (True, False))
            # Whatever happened, the file must still parse.
            import tomllib
            tomllib.loads(path.read_text(encoding="utf-8"))
            self.assertTrue(path.read_text(encoding="utf-8") == before
                            or "edicts" in path.read_text(encoding="utf-8"))


class TestHooksRegistrationIsPinned(unittest.TestCase):
    def test_hooks_json_registers_all_four_scripts(self) -> None:
        cfg = json.loads(
            (Path(__file__).resolve().parents[1] / "hooks" / "hooks.json")
            .read_text(encoding="utf-8"))
        blob = json.dumps(cfg)
        for script in ("inject_context.py", "read_guard.py",
                       "bash_guard.py", "stop_guard.py"):
            self.assertIn(script, blob,
                          f"{script} is not wired into hooks.json")


if __name__ == "__main__":
    unittest.main()
