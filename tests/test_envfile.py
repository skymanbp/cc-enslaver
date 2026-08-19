"""Tests for hooks/scripts/lib/envfile.py (v0.34 env-file hygiene).

Two halves, matching the module's own split:
  - ``TestDedupeText`` — the pure line model: last-occurrence wins,
    order survives, and every shape the model does not represent
    refuses the whole pass (the failing-open twins).
  - ``TestSessionStartHygiene`` — black-box through the real
    inject_context subprocess: a duplicated CLAUDE_ENV_FILE shrinks on
    SessionStart, a refused file is byte-identical afterwards, and an
    unset variable touches nothing.

The field failure this guards (2026-08-17, CodeEraser session): a
plugin re-appended three exports per compact until ~8 KB of duplicate
environment killed every Bash call silently.
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

# The sys.path.insert must precede importing _helpers, so the import
# cannot sit at module top — E402 is silenced because the path bootstrap
# is a precondition of the import, not misplaced code.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _helpers import SCRIPTS_DIR, run_hook  # noqa: E402 -- see path-bootstrap note

sys.path.insert(0, str(SCRIPTS_DIR))
from lib import envfile  # noqa: E402 -- see path-bootstrap note

INJECT = str(SCRIPTS_DIR / "inject_context.py")


class TestDedupeText(unittest.TestCase):
    """The pure model: what collapses, what refuses."""

    def test_last_occurrence_wins_and_order_survives(self) -> None:
        text = (
            "export A='one'\n"
            "export B='two'\n"
            "export A='three'\n"
        )
        new, dropped = envfile.dedupe_text(text)
        self.assertEqual(dropped, 1)
        self.assertEqual(new, "export B='two'\nexport A='three'\n")

    def test_repeated_generations_collapse_to_one(self) -> None:
        # The field shape: three exports re-appended once per compact.
        generation = (
            "export SID='abc'\n"
            "export TRANSCRIPT='C:/t/x.jsonl'\n"
            "export DATA='C:/d'\n"
        )
        new, dropped = envfile.dedupe_text(generation * 40)
        self.assertEqual(dropped, 39 * 3)
        self.assertEqual(new, generation)

    def test_clean_file_returns_unchanged_with_zero(self) -> None:
        text = "export A='one'\nexport B='two'\n"
        new, dropped = envfile.dedupe_text(text)
        self.assertEqual((new, dropped), (text, 0))

    def test_blank_and_comment_lines_are_tolerated(self) -> None:
        text = "# header\n\nexport A='x'\nexport A='y'\n"
        new, dropped = envfile.dedupe_text(text)
        self.assertEqual(dropped, 1)
        self.assertEqual(new, "# header\n\nexport A='y'\n")

    def test_embedded_escaped_quote_still_dedupes(self) -> None:
        # The appender idiom for a single quote inside a value closes
        # every quote on the same line — eligible, not a refusal.
        text = (
            "export P='it'\\''s'\n"
            "export P='it'\\''s again'\n"
        )
        new, dropped = envfile.dedupe_text(text)
        self.assertEqual(dropped, 1)
        self.assertEqual(new, "export P='it'\\''s again'\n")

    def test_unknown_line_refuses_the_whole_pass(self) -> None:
        # Refusal twin: same duplicates as the collapsing case, plus one
        # line the model cannot classify — nothing may move.
        text = "export A='x'\nsource other.sh\nexport A='y'\n"
        self.assertEqual(envfile.dedupe_text(text), (text, 0))

    def test_open_quote_refuses_the_whole_pass(self) -> None:
        # A value spanning lines: dropping its opening line would
        # corrupt the file, so the pass refuses even with duplicates.
        text = "export A='x'\nexport A='multi\nline'\n"
        self.assertEqual(envfile.dedupe_text(text), (text, 0))


class TestSessionStartHygiene(unittest.TestCase):
    """Black-box: the real hook subprocess against a real file."""

    def _run_session_start(self, env_file: str | None) -> None:
        overrides = {"CLAUDE_ENV_FILE": env_file} if env_file else {}
        rc, out, _ = run_hook(
            [INJECT, "--event", "SessionStart"],
            stdin_payload={"session_id": "t", "hook_event_name": "SessionStart"},
            env_overrides=overrides,
        )
        self.assertEqual(rc, 0)
        self.assertIn("hookSpecificOutput", out)

    def test_duplicated_env_file_shrinks_on_session_start(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "env.sh"
            path.write_text(
                "export SID='a'\nexport SID='b'\nexport SID='c'\n",
                encoding="utf-8",
            )
            self._run_session_start(str(path))
            self.assertEqual(
                path.read_text(encoding="utf-8"), "export SID='c'\n"
            )

    def test_refused_file_is_byte_identical(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "env.sh"
            original = "export A='x'\nnot an export line\nexport A='y'\n"
            path.write_text(original, encoding="utf-8")
            self._run_session_start(str(path))
            self.assertEqual(path.read_text(encoding="utf-8"), original)

    def test_missing_file_is_a_quiet_noop(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            ghost = Path(td) / "never-written.sh"
            self._run_session_start(str(ghost))
            self.assertFalse(ghost.exists())

    def test_unset_variable_touches_nothing(self) -> None:
        # No CLAUDE_ENV_FILE override at all — the injection must still
        # land (rc 0 asserted inside) with the hygiene pass inert.
        self._run_session_start(None)


if __name__ == "__main__":
    unittest.main()
