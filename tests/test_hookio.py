"""Tests for lib/hookio.py and the encoding contract at every hook entry.

Why this file exists
--------------------
Claude Code writes hook payloads as raw UTF-8 bytes. Until v0.37 every
entry point read them with `sys.stdin.read()`, which decodes using the
*locale* codepage under the `surrogateescape` error handler — so a
payload not representable in that codepage came out silently rewritten,
and every guard scanned a string the agent never wrote. No exception, no
stderr, nothing to notice.

It survived 691 tests because the harness could not reach it:
`_helpers.run_hook` serialised with `json.dumps(...)`, whose
`ensure_ascii=True` default escaped every non-ASCII character to
`\\uXXXX` before the bytes were ever produced. The wire was pure ASCII,
so the decode step had nothing to get wrong. The fix is therefore two
things — the entry points read bytes and decode UTF-8 explicitly, and
the harness puts real UTF-8 on the wire — and `TestHarnessWireFormat`
pins the second, because restoring the default would re-hide the whole
class without failing anything else.

Why the codepage is forced
--------------------------
The defect only appears when the host codepage is not UTF-8. That is the
default on Windows (cp936 here, cp1252 on a US-English install) but NOT
on the ubuntu CI runner, whose locale is UTF-8 — so on half the matrix
these tests would pass no matter what the code did. A gate that can only
fail on one developer's laptop is not a gate.

So every subprocess below is launched with
`PYTHONIOENCODING=cp936:surrogateescape`, which reproduces the exact
production condition — wrong table, silent substitution — on any host.
`TestReproductionIsLive` asserts the reproduction still bites, so that a
future Python changing its stdin handling reports "the reproduction
broke", not "the bug is gone".

Which cases actually discriminate
---------------------------------
Measured against the pre-fix tree under this environment, five end-to-end
cases go RED — a Chinese done-claim with no evidence (layer (a)), a
Chinese hedge (layer (b)), an overlong Chinese tldr (layer (h)), the
em-dash `# noqa` (rule 09) and a `--no-verify` carrying a CJK commit
message. The rest are controls: they pass either way, and are here to
pin that the ASCII half never regressed and that the escape hatches keep
working. They are labelled as controls individually — an allow-only test
cannot tell a working hatch from a deleted detector, and calling one a
regression test it is not would be the same overstatement this plugin
blocks.
"""

from __future__ import annotations

import importlib.util
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from _helpers import REPO_ROOT, SCRIPTS_DIR, run_hook

READ_GUARD = str(SCRIPTS_DIR / "read_guard.py")
BASH_GUARD = str(SCRIPTS_DIR / "bash_guard.py")
STOP_GUARD = str(SCRIPTS_DIR / "stop_guard.py")
INJECT = str(SCRIPTS_DIR / "inject_context.py")

# The production condition, made portable. See the module docstring.
HOST_CODEPAGE_ENV = {"PYTHONIOENCODING": "cp936:surrogateescape"}

# Inherit the real environment so a probe subprocess can find its
# interpreter and libraries; only the codepage is overridden.
REPRO_BASE_ENV = os.environ.copy()


def _env(tmpdir: str) -> dict:
    return {"CLAUDE_PLUGIN_DATA": tmpdir, **HOST_CODEPAGE_ENV}


def _load_hookio():
    spec = importlib.util.spec_from_file_location(
        "cce_hookio", SCRIPTS_DIR / "lib" / "hookio.py",
    )
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


class _Bufferless:
    """A text stream with no `.buffer` — what a StringIO-based harness gives."""

    def __init__(self, text: str) -> None:
        self._text = text

    def read(self) -> str:
        return self._text


class _WithBuffer:
    def __init__(self, data: bytes) -> None:
        self.buffer = io.BytesIO(data)

    def read(self) -> str:  # pragma: no cover — must never be reached
        raise AssertionError("read_payload_text must prefer .buffer")


class TestReproductionIsLive(unittest.TestCase):
    """Vacuity guard: prove the forced codepage still corrupts the payload.

    Without this, a future Python that always decodes stdin as UTF-8
    would turn every test below green for a reason that has nothing to do
    with this plugin's code, and the class would go unwatched again.
    """

    def test_forced_codepage_mangles_utf8_on_text_stdin(self):
        code = (
            "import sys;"
            "sys.stdout.buffer.write(sys.stdin.read()"
            ".encode('utf-8', 'backslashreplace'))"
        )
        sent = "大白话 — x"
        proc = subprocess.run(
            [sys.executable, "-c", code],
            input=sent.encode("utf-8"),
            capture_output=True,
            env={**REPRO_BASE_ENV, **HOST_CODEPAGE_ENV},
        )
        got = proc.stdout.decode("utf-8", "replace")
        self.assertNotEqual(
            got, sent,
            "forced codepage no longer corrupts text-mode stdin — the "
            "reproduction is stale, not the defect fixed",
        )

    def test_forced_codepage_does_not_touch_binary_stdin(self):
        # The other half of the contract: the fix reads `.buffer`, which
        # PYTHONIOENCODING has no say over. If this ever failed, the fix
        # itself would be unsound.
        code = "import sys; sys.stdout.buffer.write(sys.stdin.buffer.read())"
        sent = "大白话 — x".encode("utf-8")
        proc = subprocess.run(
            [sys.executable, "-c", code],
            input=sent,
            capture_output=True,
            env={**REPRO_BASE_ENV, **HOST_CODEPAGE_ENV},
        )
        self.assertEqual(proc.stdout, sent)


class TestReadPayloadText(unittest.TestCase):
    """The module in isolation."""

    def setUp(self) -> None:
        self.hookio = _load_hookio()

    def test_binary_stream_is_decoded_as_utf8(self):
        text = "em-dash — and 中文标记 大白话"
        stream = _WithBuffer(text.encode("utf-8"))
        self.assertEqual(self.hookio.read_payload_text(stream), text)

    def test_cjk_survives_byte_for_byte(self):
        # The markers stop_guard actually looks for. Each is asserted by
        # identity, not by "no exception was raised" — mojibake also
        # raises nothing, which is the entire problem.
        for marker in ("大白话", "同步核对", "我觉得", "根因", "一句话总结"):
            stream = _WithBuffer(json.dumps(
                {"assistant_message": marker}, ensure_ascii=False,
            ).encode("utf-8"))
            got = json.loads(self.hookio.read_payload_text(stream))
            self.assertEqual(got["assistant_message"], marker, marker)

    def test_bufferless_stream_falls_back_to_read(self):
        self.assertEqual(
            self.hookio.read_payload_text(_Bufferless("already text")),
            "already text",
        )

    def test_non_utf8_bytes_raise_rather_than_being_rewritten(self):
        # The refusal twin of the two cases above. Failing loudly is the
        # point: the caller's fail-open handler logs a traceback, whereas
        # the old path produced a plausible string and scanned it.
        stream = _WithBuffer(b'{"a": "\xff\xfe not utf-8"}')
        with self.assertRaises(UnicodeDecodeError):
            self.hookio.read_payload_text(stream)

    def test_ascii_is_unchanged(self):
        stream = _WithBuffer(b'{"hook_event_name": "Stop"}')
        self.assertEqual(
            json.loads(self.hookio.read_payload_text(stream)),
            {"hook_event_name": "Stop"},
        )


class TestHarnessWireFormat(unittest.TestCase):
    """Pin the fixture property that made the defect unreachable.

    Without this, someone drops `ensure_ascii=False` from `_helpers`
    during a tidy-up, every test in this file keeps passing (their
    payloads become ASCII on the wire, which any codepage decodes), and
    the class is invisible again.
    """

    def test_run_hook_puts_raw_utf8_on_the_wire(self):
        source = (REPO_ROOT / "tests" / "_helpers.py").read_text(
            encoding="utf-8",
        )
        self.assertIn("ensure_ascii=False", source)

    def test_a_cjk_payload_reaches_the_subprocess_unescaped(self):
        # Behavioural, not textual: run a subprocess that echoes back the
        # raw bytes it received and assert the CJK is there as UTF-8, not
        # as a backslash escape.
        code = "import sys; sys.stdout.buffer.write(sys.stdin.buffer.read())"
        payload = {"assistant_message": "大白话"}
        proc = subprocess.run(
            [sys.executable, "-c", code],
            input=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            capture_output=True,
        )
        self.assertIn("大白话".encode("utf-8"), proc.stdout)
        self.assertNotIn(b"\\u", proc.stdout)


class TestStopGuardSeesCJK(unittest.TestCase):
    """The layer with the most to lose: every CJK marker it looks for.

    Pre-fix these all took the wrong branch — the markers arrived as
    mojibake, so hedges went undetected AND compliant replies were judged
    non-compliant.
    """

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.env = _env(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)

    def _stop(self, message: str, sid: str):
        return run_hook(
            [STOP_GUARD],
            {
                "session_id": sid,
                "hook_event_name": "Stop",
                "assistant_message": message,
            },
            self.env,
        )

    def test_chinese_hedge_near_a_done_claim_blocks(self):
        # Layer (b). `我觉得` is in _HEDGE_INNER; pre-fix it decoded to
        # mojibake and layer (b) never saw a hedge.
        _, out, _ = self._stop(
            "修好了。$ python -m unittest → Ran 5 tests, OK。我觉得没问题了。\n\n"
            "tldr: 改完了",
            "enc-hedge",
        )
        self.assertIsNotNone(out, "expected a BLOCK, got a silent allow")
        self.assertEqual(out.get("decision"), "block")
        self.assertIn("(b)", out.get("reason", ""))

    def test_ascii_hedge_still_blocks(self):
        # The control: the ASCII half was never broken, and must not
        # regress while the CJK half is being fixed.
        _, out, _ = self._stop(
            "Fixed. $ python -m unittest → Ran 5 tests, OK. I think it works.\n\n"
            "tldr: done",
            "enc-hedge-ascii",
        )
        self.assertIsNotNone(out)
        self.assertEqual(out.get("decision"), "block")
        self.assertIn("(b)", out.get("reason", ""))

    def test_chinese_done_claim_without_evidence_blocks(self):
        # Layer (a), and the headline of this whole release: pre-fix a
        # Chinese reply cleared the Stop gate ENTIRELY. Not one layer
        # fired, because the done-claim detector is itself CJK — with the
        # claim invisible, every layer downstream of it was vacuous. Only
        # replies written in English were ever policed.
        _, out, _ = self._stop(
            "都修好了，全部完成。\n\ntldr: 改完了", "enc-doneclaim",
        )
        self.assertIsNotNone(out, "expected a BLOCK, got a silent allow")
        self.assertEqual(out.get("decision"), "block")
        self.assertIn("(a)", out.get("reason", ""))

    def test_chinese_tldr_satisfies_layer_h(self):
        # CONTROL. `大白话` is a documented way to satisfy layer (h), and
        # it must keep working. It does not discriminate: pre-fix this
        # also passed — but only because the mangled done-claim meant
        # layer (h) was never reached at all (see the layer-(a) case).
        _, out, _ = self._stop(
            "修好了。$ python -m unittest → Ran 691 tests, OK。\n"
            "收敛验证：重跑原命令、边界用例、既有测试全过。\n"
            "自答：真解决了；更好方案无；未验部分已列；验证合理。\n"
            "忠实核对：请求逐项完成，标准未降级，无范围溢出。\n\n"
            "大白话: 编码修好了，测试全过",
            "enc-tldr",
        )
        if out is not None:
            self.assertNotIn(
                "(h)", out.get("reason", ""),
                "大白话 must count as a tldr marker",
            )

    def test_overlong_chinese_tldr_is_measured_in_display_columns(self):
        # Layer (h)'s length cap. 110 汉字 = 220 display columns, over the
        # 160 cap. Pre-fix the mojibake changed both the marker AND the
        # character count, so this assertion could not be made at all.
        _, out, _ = self._stop(
            "修好了。$ python -m unittest → Ran 5 tests, OK。\n\n"
            "tldr: " + "编码问题已经彻底修复完毕" * 10,
            "enc-tldr-long",
        )
        self.assertIsNotNone(out, "expected a BLOCK for an overlong tldr")
        self.assertEqual(out.get("decision"), "block")
        self.assertIn("(h)", out.get("reason", ""))


class TestReadGuardSeesNonAscii(unittest.TestCase):
    """The defect as originally reported, pinned as a regression.

    A `# noqa` whose inline note is too short to be a rationale must be
    denied. Pre-fix, the em-dash decoded into TWO characters, which
    pushed the note over `_MIN_INLINE_REASON_CHARS` and turned the DENY
    into an ALLOW — the guard was defeated by punctuation.
    """

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.env = _env(self.tmp.name)
        self.work = Path(self.tmp.name) / "w"
        self.work.mkdir()
        self.addCleanup(self.tmp.cleanup)

    def _write(self, body: str, name: str, sid: str):
        # Assembled at runtime: this repo scans its own test files, and a
        # literal suppression marker would make the module unwritable.
        marker = "#" + " noqa: BLE001"
        target = self.work / name
        return run_hook(
            [READ_GUARD],
            {
                "session_id": sid,
                "hook_event_name": "PreToolUse",
                "tool_name": "Write",
                "cwd": str(self.work),
                "tool_input": {
                    "file_path": str(target),
                    "content": body.format(marker=marker),
                },
            },
            self.env,
        )

    def test_em_dash_note_too_short_is_still_denied(self):
        _, out, _ = self._write(
            "def f(x):\n    return x  {marker} — the demo's\n",
            "a.py", "enc-noqa-emdash",
        )
        self.assertIsNotNone(out, "expected a DENY, got a silent allow")
        self.assertEqual(
            out["hookSpecificOutput"]["permissionDecision"], "deny",
        )
        self.assertIn("rule 09", out["hookSpecificOutput"][
            "permissionDecisionReason"])

    def test_the_ascii_spelling_of_the_same_note_is_denied(self):
        # Control: identical note with `--` instead of `—`. Same verdict,
        # which is the point — punctuation must not decide enforcement.
        _, out, _ = self._write(
            "def f(x):\n    return x  {marker} -- the demo's\n",
            "b.py", "enc-noqa-ascii",
        )
        self.assertIsNotNone(out)
        self.assertEqual(
            out["hookSpecificOutput"]["permissionDecision"], "deny",
        )

    def test_a_real_chinese_rationale_is_still_allowed(self):
        # CONTROL — passes on both trees, and the reason it passed before
        # is the interesting part: the mangled rationale happened to be
        # long enough to read as substantive, so the write was allowed
        # without `因为` ever being seen. Right answer, wrong mechanism.
        # Kept because the hatch itself must keep working post-fix.
        _, out, _ = self._write(
            "def f(x):\n    return x  {marker} 因为上游库的类型标注有误，"
            "等其修复后移除\n",
            "c.py", "enc-noqa-zh",
        )
        self.assertIsNone(
            out, "a stated Chinese rationale must allow the marker",
        )


class TestBashGuardSeesNonAscii(unittest.TestCase):
    """A bypass must be caught whatever else the command carries."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.env = _env(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)

    def _bash(self, command: str, sid: str):
        return run_hook(
            [BASH_GUARD],
            {
                "session_id": sid,
                "hook_event_name": "PreToolUse",
                "tool_name": "Bash",
                "tool_input": {"command": command},
            },
            self.env,
        )

    def test_no_verify_with_a_cjk_commit_message_is_denied(self):
        _, out, _ = self._bash(
            'git commit -m "修复编码问题——守卫读取 stdin" --no-verify',
            "enc-bash-cjk",
        )
        self.assertIsNotNone(out, "expected a DENY, got a silent allow")
        self.assertEqual(
            out["hookSpecificOutput"]["permissionDecision"], "deny",
        )

    def test_the_same_command_in_ascii_is_denied(self):
        _, out, _ = self._bash(
            'git commit -m "fix encoding" --no-verify', "enc-bash-ascii",
        )
        self.assertIsNotNone(out)
        self.assertEqual(
            out["hookSpecificOutput"]["permissionDecision"], "deny",
        )

    def test_a_clean_cjk_command_is_allowed(self):
        _, out, _ = self._bash(
            'git commit -m "修复编码问题——守卫读取 stdin"', "enc-bash-clean",
        )
        self.assertIsNone(out)


class TestInjectContextSeesNonAscii(unittest.TestCase):
    """The injection must land with a payload whose fields are CJK.

    `surrogateescape` can pull the byte after a multi-byte sequence into
    the preceding character, so a CJK value next to `session_id` can take
    the key's opening quote with it. Whether that lands depends on byte
    alignment — this asserts the outcome the caller depends on either
    way, and is honest that it is a consistency check rather than a
    reproduction of a symptom seen in the wild.
    """

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.env = _env(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)

    def test_injection_still_lands_with_a_cjk_payload(self):
        rc, out, _ = run_hook(
            [INJECT, "--event", "SessionStart"],
            {
                "session_id": "enc-inject-1",
                "hook_event_name": "SessionStart",
                "cwd": "D:/项目/中文目录",
                "prompt": "把编码问题查清楚——然后全量更新文档",
            },
            self.env,
        )
        self.assertEqual(rc, 0)
        self.assertIsNotNone(out)
        ctx = out["hookSpecificOutput"]["additionalContext"]
        self.assertIn("cc-enforcer", ctx)
        self.assertTrue(ctx.strip())


if __name__ == "__main__":
    unittest.main()
