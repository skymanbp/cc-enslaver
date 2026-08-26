"""Tests for lib/messages.py and the guard message catalogs (v0.38).

Until v0.38 the guards' user-facing text was bilingual — an English body
with a Chinese plain-language line appended and Chinese phrasings offered
inline. Both READMEs quoted real samples of it, so both READMEs mixed
languages, and neither could be cleaned without either fabricating output
or dropping the samples. The mixing was the product's, not the docs'.

The catalog fixes that at the source. What these tests hold it to:

  * the English catalog is **actually English** — zero CJK, asserted on
    every value, which is the user-visible requirement and the one thing
    a reviewer cannot eyeball across 27 KB of prose;
  * the Chinese catalog is **actually translated** — not the English
    strings copied across, which would satisfy a key-set check while
    leaving the output in English;
  * switching `CC_ENFORCER_LANG` really switches what a guard PRINTS,
    end to end through the hook, not just what a dict returns;
  * and the fallbacks degrade to English rather than to a blank deny.

Parity of key sets and placeholder fields is enforced by
`i18n_check.check_message_catalogs`, exercised in `test_i18n_sync.py`
against the real repo; it is not duplicated here.
"""

from __future__ import annotations

import importlib.util
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from _helpers import SCRIPTS_DIR, run_hook

LIB = SCRIPTS_DIR / "lib"
CJK = re.compile(r"[㐀-䶿一-鿿぀-ヿ가-힯]")


def _load(name: str):
    """Import `lib.<name>` the way a hook script does.

    Not `spec_from_file_location`: `messages.py` resolves its catalogs
    with relative imports, which only work when the module is loaded as
    part of the `lib` package. Loading it standalone raises — and the
    difference is exactly the kind of thing a test should exercise in the
    production shape rather than route around.
    """
    if str(SCRIPTS_DIR) not in sys.path:
        sys.path.insert(0, str(SCRIPTS_DIR))
    return importlib.import_module(f"lib.{name}")


class TestEnglishCatalogIsEnglish(unittest.TestCase):
    """The requirement, stated as an assertion instead of a review pass."""

    def setUp(self) -> None:
        self.en = _load("messages_en").MESSAGES

    def test_no_value_contains_cjk(self) -> None:
        offenders = {k: CJK.findall(v)[:6]
                     for k, v in self.en.items() if CJK.search(v)}
        self.assertEqual(
            offenders, {},
            "the English catalog still carries CJK — an English session "
            "would print mixed-language guard output, which is what v0.38 "
            "exists to end:\n" + "\n".join(
                f"  {k}: {chars}" for k, chars in sorted(offenders.items())),
        )

    def test_catalog_is_not_empty(self) -> None:
        # Vacuity guard: an empty dict passes the CJK check trivially.
        self.assertGreater(len(self.en), 50)
        self.assertTrue(all(v.strip() for v in self.en.values()))


class TestChineseCatalogIsTranslated(unittest.TestCase):
    """Key parity is not translation. This checks the values moved."""

    def setUp(self) -> None:
        self.en = _load("messages_en").MESSAGES
        self.zh = _load("messages_zh").MESSAGES

    def test_prose_values_are_actually_in_chinese(self) -> None:
        # Only the long-form values: short ones are legitimately
        # identifiers (`rule 09`, `TL;DR`, layer keywords) and translating
        # them would break the markers they name.
        untranslated = sorted(
            k for k, v in self.zh.items()
            if len(self.en[k]) > 120 and not CJK.search(v)
        )
        self.assertEqual(
            untranslated, [],
            "these long messages are byte-identical English in the zh "
            "catalog — a key-set check would pass and the user would still "
            f"read English: {untranslated}",
        )

    def test_no_long_value_was_left_byte_identical(self) -> None:
        copied = sorted(k for k, v in self.zh.items()
                        if len(self.en[k]) > 120 and v == self.en[k])
        self.assertEqual(copied, [], f"copied verbatim from English: {copied}")


class TestCatalogResolution(unittest.TestCase):
    """The loader: default, switch, per-key fallback, unknown key."""

    def setUp(self) -> None:
        self.messages = _load("messages")
        self.en = _load("messages_en").MESSAGES
        self._saved = os.environ.get("CC_ENFORCER_LANG")
        self.addCleanup(self._restore)

    def _restore(self) -> None:
        if self._saved is None:
            os.environ.pop("CC_ENFORCER_LANG", None)
        else:
            os.environ["CC_ENFORCER_LANG"] = self._saved

    def _with_lang(self, lang: str | None):
        if lang is None:
            os.environ.pop("CC_ENFORCER_LANG", None)
        else:
            os.environ["CC_ENFORCER_LANG"] = lang
        self.messages.reset_cache()
        return self.messages.catalog()

    def test_unset_language_resolves_to_the_skeleton(self) -> None:
        self.assertEqual(self._with_lang(None), self.en)

    def test_empty_language_is_treated_as_unset(self) -> None:
        self.assertEqual(self._with_lang("   "), self.en)

    def test_zh_overrides_every_key(self) -> None:
        zh = self._with_lang("zh")
        self.assertEqual(set(zh), set(self.en))
        self.assertIn("大白话", zh["stop.tldr_prefix"])

    def test_unknown_language_falls_back_to_english(self) -> None:
        # A code with no catalog must degrade to the skeleton, not blank
        # every guard message for the session.
        self.assertEqual(self._with_lang("qq"), self.en)

    def test_partial_translation_falls_back_per_key(self) -> None:
        # The property that makes a half-finished translation safe: it is
        # degraded, never broken. Simulated at the loader seam rather than
        # by shipping a broken catalog.
        original = self.messages._load
        try:
            self.messages._load = lambda lang: {"stop.tldr_prefix": "白话"}
            os.environ["CC_ENFORCER_LANG"] = "xx"
            self.messages.reset_cache()
            cat = self.messages.catalog()
        finally:
            self.messages._load = original
        self.assertEqual(cat["stop.tldr_prefix"], "白话")
        self.assertEqual(cat["stop.recovery.a"], self.en["stop.recovery.a"])

    def test_blank_translation_value_does_not_win(self) -> None:
        original = self.messages._load
        try:
            self.messages._load = lambda lang: {"stop.tldr_prefix": "   "}
            os.environ["CC_ENFORCER_LANG"] = "xx"
            self.messages.reset_cache()
            cat = self.messages.catalog()
        finally:
            self.messages._load = original
        self.assertEqual(cat["stop.tldr_prefix"],
                         self.en["stop.tldr_prefix"])

    def test_unknown_key_is_loud_not_blank(self) -> None:
        self._with_lang(None)
        got = self.messages.text("no.such.key")
        self.assertIn("missing message", got)
        self.assertIn("no.such.key", got)


class TestCatalogChineseOutput(unittest.TestCase):
    """End to end: `CC_ENFORCER_LANG=zh` changes what a guard PRINTS.

    The unit tests above prove a dict resolves. This proves the resolved
    dict reaches the user through a real hook subprocess — and each case
    ships its English twin, because "the output is Chinese" is only
    meaningful next to "and the default is not".
    """

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.work = Path(self.tmp.name) / "w"
        self.work.mkdir()
        self.addCleanup(self.tmp.cleanup)

    def _env(self, lang: str | None) -> dict:
        env = {"CLAUDE_PLUGIN_DATA": self.tmp.name}
        env["CC_ENFORCER_LANG"] = lang if lang else ""
        return env

    def _stop(self, lang: str | None, sid: str):
        _, out, _ = run_hook(
            [str(SCRIPTS_DIR / "stop_guard.py")],
            {"session_id": sid, "hook_event_name": "Stop",
             "assistant_message": "All done, everything is fixed."},
            self._env(lang),
        )
        self.assertIsNotNone(out, "a bare done-claim must block at (a)")
        return out["reason"]

    def test_stop_block_reason_is_chinese_under_zh(self) -> None:
        reason = self._stop("zh", "msg-zh")
        self.assertGreater(len(CJK.findall(reason)), 100)
        self.assertIn("大白话:", reason)
        self.assertIn("未通过", reason)

    def test_stop_block_reason_has_no_cjk_by_default(self) -> None:
        # The twin. Without it, a catalog that returned Chinese for every
        # language would pass the test above.
        reason = self._stop(None, "msg-en")
        self.assertEqual(
            CJK.findall(reason), [],
            f"default output must be pure English, found CJK: {reason[:200]}",
        )
        self.assertIn("In plain words:", reason)

    def _bash_deny(self, lang: str | None, sid: str) -> str:
        _, out, _ = run_hook(
            [str(SCRIPTS_DIR / "bash_guard.py")],
            {"session_id": sid, "hook_event_name": "PreToolUse",
             "tool_name": "Bash",
             "tool_input": {"command": "git commit -m x --no-verify"}},
            self._env(lang),
        )
        self.assertIsNotNone(out, "--no-verify must be denied")
        return out["hookSpecificOutput"]["permissionDecisionReason"]

    def test_bash_deny_switches_language(self) -> None:
        zh = self._bash_deny("zh", "bash-zh")
        self.assertIn("跳过提交钩子", zh)
        en = self._bash_deny(None, "bash-en")
        self.assertIn("skipping commit hooks", en)
        self.assertEqual(CJK.findall(en), [])

    def _read_deny(self, lang: str | None, sid: str, name: str) -> str:
        target = self.work / name
        target.write_text("x = 1\n", encoding="utf-8")
        _, out, _ = run_hook(
            [str(SCRIPTS_DIR / "read_guard.py")],
            {"session_id": sid, "hook_event_name": "PreToolUse",
             "tool_name": "Edit", "cwd": str(self.work),
             "tool_input": {"file_path": str(target),
                            "old_string": "x = 1", "new_string": "x = 2"}},
            self._env(lang),
        )
        self.assertIsNotNone(out, "an unread target must be denied")
        return out["hookSpecificOutput"]["permissionDecisionReason"]

    def test_read_deny_switches_language(self) -> None:
        zh = self._read_deny("zh", "read-zh", "a.py")
        self.assertIn("改前必读", zh)
        en = self._read_deny(None, "read-en", "b.py")
        self.assertIn("read-before-edit", en)
        self.assertEqual(CJK.findall(en), [])

    def test_an_unknown_language_still_prints_english(self) -> None:
        reason = self._stop("qq", "msg-qq")
        self.assertEqual(CJK.findall(reason), [])
        self.assertIn("In plain words:", reason)


class TestPlaceholdersSurviveFormatting(unittest.TestCase):
    """Every catalog value must survive `str.format` in both languages.

    `i18n_check` compares the field SETS; this renders them. A field the
    parity check accepts can still be malformed (`{0abc}`, an unbalanced
    brace), and that failure would land inside a hook, at the moment the
    user is already being denied.
    """

    def test_every_value_formats_in_every_catalog(self) -> None:
        import string
        for name in ("messages_en", "messages_zh"):
            cat = _load(name).MESSAGES
            for key, value in cat.items():
                fields = {f for _, f, _, _ in string.Formatter().parse(value)
                          if f}
                with self.subTest(catalog=name, key=key):
                    value.format(**{f: "X" for f in fields})


if __name__ == "__main__":
    unittest.main()
