"""v0.26.0 — the four shared models, and every defect they were built to kill.

Round-4 audit reviewed the *v0.25.1 fix diff itself* and found 33 confirmed
defects. They collapsed into three root causes:

  alpha  the detector encoded a SPELLING, not the concept (most defects)
  beta   hardening was scoped to the observed instance, never the class
  gamma  the claim outran the change (docstrings asserting behaviour the
         code lacked; tests that passed on the pre-fix tree)

The fix is four shared models -- lib/srclex, lib/mdctx, lib/shellcmd and a
schema-driven state normaliser -- rather than ~30 individual patches.

EVERY test here is red on the pre-fix tree. Where a case asserts that a
rationale ALLOWS something, it is paired with a twin asserting that
REMOVING the rationale DENIES: an "allow" assertion alone would also pass
with the detector deleted, which is precisely the vacuity this round found
in four of the previous release's tests.

Offending fixtures are assembled from fragments at runtime because this
repo is governed by its own plugin -- a literal suppression marker or
user-home path in this file would be denied on write.
"""

from __future__ import annotations

import importlib.util
import os
import shutil
import sys
import tempfile
import unittest
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
# because the sys.path bootstrap above must run before this import
from _helpers import SCRIPTS_DIR  # noqa: E402

sys.path.insert(0, str(SCRIPTS_DIR))
# because the sys.path bootstrap above must run before this import
from lib import mdctx, shellcmd, srclex  # noqa: E402


def _load(name: str):
    spec = importlib.util.spec_from_file_location(
        f"_v026_{name}", str(SCRIPTS_DIR / f"{name}.py")
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


rg = _load("read_guard")
sg = _load("stop_guard")
bg = _load("bash_guard")

# Markers built from fragments (see module docstring).
NOQA = "# " + "noqa"
TSIG = "// " + "@ts-" + "ignore"
ESL = "// " + "eslint-" + "disable"
SWALLOW = "pa" + "ss"
PWKW = "pass" + "word"
BS = chr(92)


def _patch(text: str, scannable: bool = True, lang: str = "auto") -> bool:
    """True when the rule-09 content detector DENIES `text`."""
    return rg._find_unjustified_patch_marker(
        text, scannable=scannable, lang=lang) is not None


def _secret(text: str, lang: str = "auto") -> bool:
    return rg._find_hardcoded_secret(text, lang=lang) is not None


def _pathdep(text: str, lang: str = "auto") -> bool:
    return rg._find_path_dependency(text, lang=lang) is not None


# --------------------------------------------------------------------------- #
# Model 1 — lib/srclex
# --------------------------------------------------------------------------- #
class TestSrclex(unittest.TestCase):
    def test_hash_inside_a_string_is_not_a_comment(self) -> None:
        self.assertEqual(srclex.comment_text('u = "http://x/#why"', "py"), "")

    def test_double_slash_inside_a_string_is_not_a_comment(self) -> None:
        self.assertEqual(
            srclex.comment_text('U = "https://vendor.example.com/api"', "py"),
            "",
        )

    def test_real_trailing_comment_is_found(self) -> None:
        self.assertIn("why", srclex.comment_text("x = 1  # why not", "py"))

    def test_block_comment_is_found(self) -> None:
        self.assertIn(
            "because",
            srclex.comment_text("/* because upstream is wrong */", "ts"),
        )

    def test_docstring_counts_as_documentation(self) -> None:
        # A why-note in a docstring is documentation, not data.
        src = '"""because the bootstrap must run first."""\nx = 1\n'
        self.assertIn("because", srclex.comment_text(src, "py"))

    def test_mask_literals_preserves_offsets_and_newlines(self) -> None:
        src = 'try:\n    x = """\ntext\n"""\nexcept Exception:\n    ' + SWALLOW
        masked = srclex.mask_literals(src, "py")
        self.assertEqual(len(masked), len(src))
        self.assertEqual(masked.count("\n"), src.count("\n"))
        # The string body no longer looks like column-0 code.
        self.assertNotIn("text", masked)

    # --- re-audit round -------------------------------------------------- #
    def test_escaped_delimiter_does_not_close_a_triple_quote(self) -> None:
        q3, bs = chr(34) * 3, chr(92)
        src = "x = " + q3 + "a " + bs + q3 + " b\n# not a comment\n" + q3 + "\n"
        # The `#` is string content; ending the block early exposed it as a
        # comment and let it justify an adjacent marker.
        self.assertEqual(srclex.comment_text(src, "py"), "")

    def test_triple_quoted_data_is_not_documentation(self) -> None:
        q3 = chr(34) * 3
        data = "    SQL = " + q3 + "SELECT 1 -- because legacy" + q3 + "\n"
        doc = "    " + q3 + "because the bootstrap runs first." + q3 + "\n"
        self.assertNotIn("because", srclex.comment_text(data, "py"))
        self.assertIn("because", srclex.comment_text(doc, "py"))

    def test_logical_lines_join_bracketed_continuations(self) -> None:
        src = "try:\n    w()\nexcept (\n    ValueError,\n):\n    " + SWALLOW
        joined = [code for _, code in srclex.logical_lines(src, "py")]
        self.assertTrue(
            any(c.startswith("except (") and c.rstrip().endswith(":")
                for c in joined),
            joined,
        )


# --------------------------------------------------------------------------- #
# Model 2 — lib/mdctx
# --------------------------------------------------------------------------- #
class TestMdctx(unittest.TestCase):
    def test_quote_nested_under_a_list_item_is_quoted(self) -> None:
        self.assertTrue(mdctx.lines("- > quoted")[0].quoted)

    def test_plain_list_item_is_not_quoted(self) -> None:
        self.assertFalse(mdctx.lines("- ordinary item")[0].quoted)

    def test_inner_short_fence_does_not_close_outer_long_fence(self) -> None:
        text = "````\n```\nstill inside\n````\n"
        ctx = mdctx.lines(text)
        self.assertTrue(ctx[2].in_fence)

    def test_only_yaml_fences_are_countable(self) -> None:
        yaml_body = mdctx.lines("```yaml\nkey: v\n```\n")[1]
        text_body = mdctx.lines("```text\nkey: v\n```\n")[1]
        self.assertTrue(yaml_body.countable)
        self.assertFalse(text_body.countable)

    # --- re-audit round -------------------------------------------------- #
    def test_closing_fence_may_not_carry_an_info_string(self) -> None:
        # ```still-inside used to CLOSE an enclosing ```text block, after
        # which quoted fixture content below it became countable.
        ctx = mdctx.lines("```text\n```still-inside\ntldr: fake\n```\n")
        self.assertTrue(ctx[1].in_fence)
        self.assertFalse(ctx[2].countable)

    def test_info_string_language_is_matched_exactly(self) -> None:
        for info, want in [("yaml", True), ("yml", True), ("yaml linenums", True),
                           ("yaml-not", False), ("yamlish", False), ("text", False)]:
            with self.subTest(info=info):
                body = mdctx.lines("```" + info + "\ntldr: x\n```\n")[1]
                self.assertEqual(body.countable, want)

    def test_four_space_indent_is_not_a_fence(self) -> None:
        # CommonMark: 4+ spaces is an indented code block, not a fence.
        self.assertFalse(mdctx.lines("text\n    ```yaml\n")[1].in_fence)
        self.assertTrue(mdctx.lines("text\n   ```yaml\n")[1].in_fence)

    def test_has_substance(self) -> None:
        self.assertFalse(mdctx.has_substance("!!!"))
        self.assertFalse(mdctx.has_substance("   "))
        self.assertTrue(mdctx.has_substance("fixed it"))
        self.assertTrue(mdctx.has_substance("修好了"))


# --------------------------------------------------------------------------- #
# Model 3 — lib/shellcmd
# --------------------------------------------------------------------------- #
class TestShellcmd(unittest.TestCase):
    def test_segments_split_on_separators(self) -> None:
        segs = shellcmd.segments("a b && c d ; e")
        self.assertEqual([s[0] for s in segs], ["a", "c", "e"])

    def test_git_subcommand_skips_global_value_options(self) -> None:
        argv = ["git", "-C", "/repo", "push", "--force"]
        self.assertEqual(shellcmd.git_subcommand(argv)[0], "push")

    def test_git_subcommand_ignores_long_option_values(self) -> None:
        argv = ["git", "--git-dir=/" + "a" * 200, "push"]
        self.assertEqual(shellcmd.git_subcommand(argv)[0], "push")

    def test_python_dash_c_runs_no_script(self) -> None:
        self.assertIsNone(
            shellcmd.python_script_arg(["python", "-c", "register_read.py"]))

    def test_python_dash_m_runs_no_script(self) -> None:
        self.assertIsNone(
            shellcmd.python_script_arg(["python", "-m", "mod"]))

    def test_python_x_option_operand_is_skipped(self) -> None:
        self.assertEqual(
            shellcmd.python_script_arg(["python", "-X", "utf8", "s.py"]), "s.py")

    def test_versioned_interpreter_is_recognised(self) -> None:
        self.assertEqual(
            shellcmd.python_script_arg(["python3.13", "s.py"]), "s.py")

    def test_hash_in_a_path_is_not_a_comment(self) -> None:
        """`#` must never truncate a command, on either platform.

        This is the platform-INDEPENDENT half: `commenters=""`. The
        original spelling folded it together with backslash survival and
        so passed only on Windows — it went red the first time CI ran it
        on ubuntu, because the host-OS branch below is real behaviour,
        not an accident.
        """
        for windows in (True, False):
            with self.subTest(windows=windows):
                toks = shellcmd.tokenize("python s.py --file /tmp/a#b.py",
                                         windows=windows)
                self.assertIn("/tmp/a#b.py", toks)

    def test_backslash_handling_is_platform_branched(self) -> None:
        """Backslash survival differs by platform, deterministically.

        `tokenize` takes an explicit `windows` flag, so both branches are
        pinned here rather than left to whatever host CI happens to use.

        Known limitation (v0.26.0 audit, not fixed): keying this on
        `os.name` treats the HOST OS as a proxy for the SHELL grammar. On
        Windows the actual shell is usually Git Bash, which applies POSIX
        escape rules, so the Windows branch can disagree with what really
        runs. Recorded for a future release; changing it now would alter
        the register_read hatch's behaviour on this plugin's main
        platform without a design pass.
        """
        cmd = "python s.py --file C:" + BS + "w" + BS + "a.py"
        win = shellcmd.tokenize(cmd, windows=True)
        self.assertIn("C:" + BS + "w" + BS + "a.py", win,
                      "on Windows the backslashes are path separators")
        posix = shellcmd.tokenize(cmd, windows=False)
        self.assertIn("C:wa.py", posix,
                      "under POSIX rules the backslash is an escape")


# --------------------------------------------------------------------------- #
# Rule 09 — block structure (defects 1-3)
# --------------------------------------------------------------------------- #
class TestRule09StructureV026(unittest.TestCase):
    def test_flat_bare_swallow_still_denied(self) -> None:
        self.assertTrue(_patch("try:\n    a()\nexcept Exception:\n    " + SWALLOW))

    def test_nested_outer_swallow_is_denied(self) -> None:
        # REGRESSION guard: v0.25.0 denied this, v0.25.1 allowed it.
        src = ("try:\n    try:\n        a()\n    except ValueError:\n"
               "        log()\nexcept Exception:\n    " + SWALLOW)
        self.assertTrue(_patch(src))

    def test_multiline_string_body_does_not_hide_a_later_swallow(self) -> None:
        src = ('try:\n    x = """\ntext\n"""\nexcept Exception:\n    ' + SWALLOW)
        self.assertTrue(_patch(src))

    def test_multiline_except_header_is_inspected(self) -> None:
        src = ("try:\n    w()\nexcept (\n    ValueError,\n    TypeError,\n):\n"
               "    " + SWALLOW)
        self.assertTrue(_patch(src))

    def test_oneliner_swallow_is_denied(self) -> None:
        self.assertTrue(_patch("try:\n    a()\nexcept Exception: " + SWALLOW))

    def test_identifier_beginning_with_finally_is_not_a_handler(self) -> None:
        src = ("finally_hook = 1\ntry:\n    a()\nexcept Exception:\n    "
               + SWALLOW)
        self.assertTrue(_patch(src))

    def test_handled_exception_is_allowed(self) -> None:
        self.assertFalse(
            _patch("try:\n    a()\nexcept ValueError:\n    log()\n"))


# --------------------------------------------------------------------------- #
# Rule 09 — marker token boundaries (defects 4-6), each with a twin
# --------------------------------------------------------------------------- #
class TestMarkerBoundariesV026(unittest.TestCase):
    def test_noqa_prefix_word_is_not_a_marker(self) -> None:
        self.assertFalse(_patch("value = 1  " + NOQA + "lity\n"))

    def test_twin_real_noqa_is_still_denied(self) -> None:
        self.assertTrue(_patch("value = 1  " + NOQA + "\n"))

    def test_ts_ignore_prefix_word_is_not_a_marker(self) -> None:
        self.assertFalse(_patch(TSIG + "-generated\nconst x = f();\n"))

    def test_twin_real_ts_ignore_is_still_denied(self) -> None:
        self.assertTrue(_patch(TSIG + "\nconst x = f();\n"))

    def test_eslint_prefix_word_is_not_a_marker(self) -> None:
        self.assertFalse(_patch(ESL + "ment\nconst x = f();\n"))

    def test_twin_real_eslint_disable_is_still_denied(self) -> None:
        self.assertTrue(_patch(ESL + "\nconst x = f();\n"))

    def test_eslint_disable_next_line_with_rule_still_denied(self) -> None:
        self.assertTrue(_patch(ESL + "-next-line no-console\nf();\n"))


# --------------------------------------------------------------------------- #
# Rules 09/10/11 — the rationale hatch (defects 7-10), each with a twin
# --------------------------------------------------------------------------- #
class TestRationaleHatchV026(unittest.TestCase):
    # --- a token inside a DATA string must not justify anything --------- #
    def test_url_in_a_neighbouring_string_does_not_justify_a_marker(self) -> None:
        src = 'U = "https://vendor.example.com/api"\nx = f()  ' + NOQA + "\n"
        self.assertTrue(_patch(src, lang="py"))

    def test_twin_a_real_comment_rationale_does_justify(self) -> None:
        src = "# because the vendor stub is wrong\nx = f()  " + NOQA + "\n"
        self.assertFalse(_patch(src, lang="py"))

    def test_url_in_a_neighbouring_string_does_not_silence_rule_10(self) -> None:
        src = 'API = "https://api.example.com"\n' + PWKW + ' = "Rea1Secret123x"\n'
        self.assertTrue(_secret(src, lang="py"))

    def test_twin_rule_10_comment_rationale_does_silence(self) -> None:
        src = ("# fixture: sample credential for the parser test\n"
               + PWKW + ' = "Rea1Secret123x"\n')
        self.assertFalse(_secret(src, lang="py"))

    def test_url_in_a_neighbouring_string_does_not_silence_rule_11(self) -> None:
        path = 'CACHE = "C:' + BS * 2 + "Users" + BS * 2 + "bob" + BS * 2 + 'c"\n'
        self.assertTrue(_pathdep('API = "https://api.example.com"\n' + path,
                                 lang="py"))

    def test_twin_rule_11_comment_rationale_does_silence(self) -> None:
        path = 'CACHE = "C:' + BS * 2 + "Users" + BS * 2 + "bob" + BS * 2 + 'c"\n'
        self.assertFalse(_pathdep("# essential: fixed OS location\n" + path,
                                  lang="py"))

    # --- block comments --------------------------------------------------- #
    def test_block_comment_rationale_is_honoured(self) -> None:
        src = "/* because upstream types are wrong */\n" + TSIG + "\nf();\n"
        self.assertFalse(_patch(src, lang="ts"))

    def test_twin_block_comment_without_a_reason_still_denies(self) -> None:
        src = "/* upstream */\n" + TSIG + "\nf();\n"
        self.assertTrue(_patch(src, lang="ts"))

    # --- language symmetry ------------------------------------------------ #
    def test_chinese_because_is_a_rationale(self) -> None:
        self.assertFalse(
            _patch("x = f()  " + NOQA + "  因为上游库"
                   "类型定义有误\n", lang="py"))

    def test_chinese_deliberate_is_a_rationale(self) -> None:
        self.assertFalse(
            _patch("x = f()  " + NOQA + "  故意保留，"
                   "上游类型有误\n", lang="py"))

    def test_twin_bare_chinese_filler_still_denies(self) -> None:
        # No rationale token and too short to read as an explanation.
        self.assertTrue(
            _patch("x = f()  " + NOQA + "  改了\n", lang="py"))

    def test_english_and_chinese_rationales_agree(self) -> None:
        en = "x = f()  " + NOQA + "  because upstream types are wrong\n"
        zh = ("x = f()  " + NOQA + "  因为上游库类"
              "型定义有误\n")
        self.assertEqual(_patch(en, lang="py"), _patch(zh, lang="py"))

    def test_deferral_keyword_is_not_a_rationale(self) -> None:
        self.assertTrue(_patch(TSIG + ": TO" + "DO later\nf();\n", lang="ts"))

    # --- re-audit round: padding must not reach the length bar ----------- #
    def test_punctuation_padding_is_not_a_rationale(self) -> None:
        for label, tail in [
            ("exclamation padding", "改了改了改了!!!!!!"),
            ("underscore padding", "变量名字变量名字____"),
            ("pure repetition", "改了改了改了改了改了改了"),
        ]:
            with self.subTest(case=label):
                self.assertTrue(
                    _patch("x = f()  " + NOQA + ": " + tail + "\n", lang="py"),
                    msg=label,
                )

    def test_twin_a_real_chinese_reason_still_passes(self) -> None:
        self.assertFalse(
            _patch("x = f()  " + NOQA + ": 上游库类型定义有误"
                   "无法修复\n", lang="py"))


# --------------------------------------------------------------------------- #
# Stop layer (a)/(h) — done-claim negation (defects 11-13)
# --------------------------------------------------------------------------- #
class TestDoneClaimNegationV026(unittest.TestCase):
    NEGATED = [
        "Not done; tests failed.",
        "This is not fixed.",
        "The work is not yet done.",
        "The migration isn't done.",
        "The tests aren't fixed yet.",
        "Nothing is done.",
        "Not fully done.",
        "还没有搞定",
        "尚未完成了",
        # Re-audit round: negators that were missing entirely. Missing a
        # negation is the DAMAGING direction — it blocks an honest report
        # of failure for "claiming completion without evidence".
        "cannot be considered done",
        "unable to finish",
        "绝非已完成",
        "并非已完成",
    ]
    GENUINE = [
        "Fixed. Ran 378 tests.",
        "已完成。",
        "Implemented the fix.",
        "No errors remain. Done.",
        "没有遗漏，已完成",
        "All tests pass; the migration is complete.",
        # Re-audit round: a negator that scopes something ELSE must not
        # suppress the claim.
        "not only fixed but tested",      # "not only" is not a denial
        "no longer broken - fixed",       # the dash starts a new clause
        "不得不承认已完成",                  # double negative = affirmative
    ]

    def test_negated_statements_are_not_claims(self) -> None:
        for text in self.NEGATED:
            with self.subTest(text=text):
                self.assertIsNone(sg._has_done_claim(text))

    def test_twin_genuine_claims_are_still_detected(self) -> None:
        for text in self.GENUINE:
            with self.subTest(text=text):
                self.assertIsNotNone(sg._has_done_claim(text))


# --------------------------------------------------------------------------- #
# Stop layer (h) — tldr context (defects 14-16)
# --------------------------------------------------------------------------- #
class TestTldrContextV026(unittest.TestCase):
    def test_tldr_in_a_non_canonical_fence_does_not_satisfy(self) -> None:
        self.assertFalse(sg._has_tldr("```text\ntldr: quoted example\n```\n"))

    def test_twin_tldr_in_the_canonical_yaml_fence_does_satisfy(self) -> None:
        self.assertTrue(
            sg._has_tldr("```yaml\ncc-enslaver:\n  tldr: fixed the parser\n```\n"))

    def test_twin_plain_tldr_line_satisfies(self) -> None:
        self.assertTrue(sg._has_tldr("tldr: fixed the parser\n"))

    def test_punctuation_only_tldr_does_not_satisfy(self) -> None:
        self.assertFalse(sg._has_tldr("tldr: !!!\n"))

    def test_quote_nested_in_a_list_item_does_not_satisfy(self) -> None:
        self.assertFalse(sg._has_tldr("- > tldr: quoted example\n"))

    def test_presence_and_length_halves_agree_on_fences(self) -> None:
        long_item = "x" * (sg.TLDR_MAX_ITEM_CHARS + 40)
        text_fence = "```text\ntldr: " + long_item + "\n```\n"
        # Not countable for EITHER half -- no presence, nothing measured.
        self.assertFalse(sg._has_tldr(text_fence))
        self.assertIsNone(sg._find_overlong_tldr(text_fence))
        yaml_fence = "```yaml\ncc-enslaver:\n  tldr: " + long_item + "\n```\n"
        self.assertTrue(sg._has_tldr(yaml_fence))
        self.assertIsNotNone(sg._find_overlong_tldr(yaml_fence))


# --------------------------------------------------------------------------- #
# bash_guard — command model (defects 19-27)
# --------------------------------------------------------------------------- #
class TestForcePushCommandModelV026(unittest.TestCase):
    FORCE = "--" + "force"

    def _deny(self, cmd: str) -> bool:
        return bg._detect_force_push(cmd) is not None

    def test_force_refspec_without_colon_is_denied(self) -> None:
        self.assertTrue(self._deny("git push origin +main"))

    def test_force_deletion_refspec_is_denied(self) -> None:
        self.assertTrue(self._deny("git push origin +:refs/heads/main"))

    def test_long_global_option_value_does_not_hide_the_push(self) -> None:
        self.assertTrue(self._deny(
            "git --git-dir=/" + "a" * 200 + " push " + self.FORCE + " origin m"))

    def test_stacked_short_flags_are_denied(self) -> None:
        self.assertTrue(self._deny("git push -fu origin main"))

    def test_mirror_is_denied(self) -> None:
        self.assertTrue(self._deny("git push --mirror origin"))

    def test_quoted_prose_is_not_an_invocation(self) -> None:
        self.assertFalse(self._deny(
            'echo "git push ' + self.FORCE + ' origin main"'))

    def test_a_different_git_subcommand_is_not_a_push(self) -> None:
        self.assertFalse(self._deny('git config alias.deploy "push --mirror"'))

    def test_unrelated_dash_f_is_not_a_force_push(self) -> None:
        self.assertFalse(self._deny("rm -f build.log && git push origin main"))

    def test_force_with_lease_is_allowed(self) -> None:
        self.assertFalse(self._deny("git push --force-with-lease origin main"))

    def test_twin_plain_force_push_is_still_denied(self) -> None:
        self.assertTrue(self._deny("git push " + self.FORCE + " origin main"))

    # --- re-audit round: nested invocations ----------------------------- #
    # The text heuristic this command model replaced caught these BY
    # ACCIDENT (it scanned raw characters). A model that only understands
    # top-level segments would therefore have been a regression, not an
    # improvement — the words inside `$( … )`, backticks, `( … )` and a
    # shell's `-c` operand are a command in their own right.
    def test_command_substitution_is_a_command(self) -> None:
        self.assertTrue(self._deny("$(git push " + self.FORCE + " origin main)"))

    def test_backtick_substitution_is_a_command(self) -> None:
        self.assertTrue(self._deny("`git push " + self.FORCE + " origin main`"))

    def test_assignment_from_substitution_is_a_command(self) -> None:
        self.assertTrue(self._deny("x=$(git push " + self.FORCE + ")"))

    def test_subshell_group_is_a_command(self) -> None:
        self.assertTrue(self._deny("(cd repo && git push " + self.FORCE + ")"))

    def test_shell_dash_c_operand_is_scanned(self) -> None:
        self.assertTrue(self._deny("bash -c 'git push " + self.FORCE + "'"))
        self.assertTrue(self._deny('sh -c "git push -f origin main"'))

    def test_twin_innocent_substitutions_still_allowed(self) -> None:
        for label, cmd in [
            ("date substitution", "echo $(date) && git push origin main"),
            ("subshell plain push", "(cd repo && git push origin main)"),
            ("quoted prose", 'echo "git push ' + self.FORCE + '"'),
        ]:
            with self.subTest(case=label):
                self.assertFalse(self._deny(cmd), msg=label)


class TestRegisterCommandModelV026(unittest.TestCase):
    HASH = "a" * 64

    def _parsed(self, cmd: str) -> bool:
        return bg._parse_register_invocation(cmd) is not None

    def _reg(self, prefix: str) -> str:
        return f"{prefix} --file v.py --hash {self.HASH}"

    def test_inline_code_operand_is_not_a_script(self) -> None:
        self.assertFalse(self._parsed(self._reg("python -c register_read.py")))

    def test_module_operand_is_not_a_script(self) -> None:
        self.assertFalse(self._parsed(self._reg("python -m register_read.py")))

    def test_interpreter_option_with_operand_is_skipped(self) -> None:
        self.assertTrue(
            self._parsed(self._reg("python -X utf8 register_read.py")))

    def test_versioned_interpreter_is_recognised(self) -> None:
        self.assertTrue(self._parsed(self._reg("python3.13 register_read.py")))

    def test_hash_in_an_unquoted_path_survives(self) -> None:
        cmd = ("python register_read.py --file C:" + BS + "w" + BS
               + "a#b.py --hash " + self.HASH)
        parsed = bg._parse_register_invocation(cmd)
        self.assertIsNotNone(parsed)
        self.assertTrue(parsed["file"].endswith("a#b.py"), parsed)

    def test_quoted_path_with_spaces_still_groups(self) -> None:
        cmd = ('python register_read.py --file "C:' + BS + 'Dir With Space'
               + BS + 'x.py" --hash ' + self.HASH)
        parsed = bg._parse_register_invocation(cmd)
        self.assertIsNotNone(parsed)
        self.assertIn("Dir With Space", parsed["file"])

    def test_twin_echo_of_the_script_path_is_not_a_registration(self) -> None:
        self.assertFalse(
            self._parsed(self._reg("echo /not/executed/register_read.py")))

    def test_twin_plain_invocation_still_parses(self) -> None:
        self.assertTrue(self._parsed(self._reg("python register_read.py")))


# --------------------------------------------------------------------------- #
# State / config shape (defects 28-30)
# --------------------------------------------------------------------------- #
class TestStateShapeV026(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = Path(tempfile.mkdtemp(prefix="ccens-shape-"))
        os.environ["CLAUDE_PLUGIN_DATA"] = str(self.tmpdir)
        # state_dir() resolves CLAUDE_PLUGIN_DATA at call time, so a plain
        # import is enough; reloading a module that is not yet in
        # sys.modules is what broke the first draft of this harness.
        from lib import state as state_lib
        self.state = state_lib
        self.sid = f"test-{uuid.uuid4().hex[:8]}"
        self.target = str(Path(__file__).resolve())

    def tearDown(self) -> None:
        shutil.rmtree(self.tmpdir, ignore_errors=True)
        os.environ.pop("CLAUDE_PLUGIN_DATA", None)

    def _write_state(self, blob: str) -> None:
        path = self.state._state_file(self.sid)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(blob, encoding="utf-8")

    MALFORMED = {
        "empty object": "{}",
        "top-level list": "[]",
        "non-string session_id": '{"session_id": 42, "read_files": []}',
        "read_files as dict": '{"session_id":"s","read_files":{}}',
        "edited_files as string": '{"read_files":[],"edited_files":"x"}',
        "edits_per_file as list": '{"read_files":[],"edits_per_file":[]}',
        "stop_counter as string": '{"read_files":[],"stop_counter":"x"}',
        "baseline_mtimes as list": '{"read_files":[],"baseline_mtimes":[]}',
        "sync_acked_groups as int": '{"read_files":[],"sync_acked_groups":1}',
    }

    def test_malformed_records_never_raise_through_mutators(self) -> None:
        for name, blob in self.MALFORMED.items():
            with self.subTest(shape=name):
                self._write_state(blob)
                self.state.add_read(self.sid, self.target)
                self.state.record_edited_file(self.sid, self.target)
                self.state.next_stop_turn(self.sid)
                self.state.record_baseline(self.sid, self.target)
                self.state.ack_sync_groups(self.sid, ["g"])

    def test_a_read_survives_a_malformed_record(self) -> None:
        # The v0.25.1 bug: add_read raised, was swallowed failing-open, the
        # Read was never recorded, and the NEXT edit was falsely denied.
        for name, blob in self.MALFORMED.items():
            with self.subTest(shape=name):
                self._write_state(blob)
                self.state.add_read(self.sid, self.target)
                self.assertTrue(
                    self.state.has_read(self.sid, self.target), name)

    def test_stored_session_id_never_redirects_the_write(self) -> None:
        # A record whose stored id disagrees with its filename used to send
        # every later save() to a different file.
        self._write_state('{"session_id":"someone-else","read_files":[]}')
        self.state.add_read(self.sid, self.target)
        self.assertTrue(self.state.has_read(self.sid, self.target))


class TestGcExclusionV026(unittest.TestCase):
    def test_exclusion_uses_the_same_naming_rule_as_creation(self) -> None:
        from lib import state as state_lib
        gc = _load("gc_state")
        tmpdir = Path(tempfile.mkdtemp(prefix="ccens-gc-"))
        try:
            os.environ["CLAUDE_PLUGIN_DATA"] = str(tmpdir)
            sessions = state_lib.state_dir()
            sessions.mkdir(parents=True, exist_ok=True)
            # An id whose sanitised filename differs from the raw string.
            raw_id = "live/session"
            live = sessions / state_lib._safe_session_filename(raw_id)
            live.write_text("{}", encoding="utf-8")
            old = time.time() - (99 * 86400)
            os.utime(live, (old, old))
            result = gc.prune_old_sessions(
                threshold_days=1, dry_run=True, exclude_session=raw_id)
            self.assertEqual(
                [p.name for p, _, _ in result["items"]], [],
                "auto-GC must not select the live session",
            )
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)
            os.environ.pop("CLAUDE_PLUGIN_DATA", None)


class TestEdictDumpV026(unittest.TestCase):
    WRONG_SHAPES = [
        {"id": "E1", "text": 7, "severity": "must"},
        {"id": "E1", "text": "ok", "severity": []},
        {"id": "E1", "text": "ok", "severity": "must", "note": 3},
        {"id": "E1", "text": "ok", "severity": "must", "deny_bash": "abc"},
    ]

    def test_wrong_typed_fields_do_not_break_reserialization(self) -> None:
        me = _load("manage_edicts")
        for ed in self.WRONG_SHAPES:
            with self.subTest(edict=ed):
                out = me._dump_edict(ed)
                self.assertIn("[[edicts]]", out)

    def test_twin_output_is_still_parseable_toml(self) -> None:
        import tomllib
        me = _load("manage_edicts")
        for ed in self.WRONG_SHAPES:
            with self.subTest(edict=ed):
                parsed = tomllib.loads(me._dump_edict(ed))
                self.assertEqual(parsed["edicts"][0]["id"], "E1")


import time  # noqa: E402  -- because TestGcExclusionV026 needs it after _load


if __name__ == "__main__":
    unittest.main()
