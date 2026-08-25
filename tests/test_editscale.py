"""Unit tests for hooks/scripts/lib/editscale.py (rule 09, v0.35).

Like tests/test_sync_gate.py these import the library directly rather
than driving it through a hook payload. That is deliberate and is the
lesson of the defect this module exists to fix: the rolling-patch
classification had only ever been exercised end-to-end, through a
fixture file that happened to be one line long, so the "a small file can
never reset its counter" lock-in was invisible for twenty-two releases.
A classifier that takes (old, new, scale) can be asked about every
region of that space directly, and is.

The end-to-end wiring — that read_guard really reads the target's scale,
really passes it, and really honours the exemptions — is covered by
tests/test_read_guard.py::TestRelativeScaleAndExemptions.

Convention followed throughout (repo-wide since v0.24): every case that
demonstrates an ALLOWANCE ships with its refusal twin. A file of
"this passes now" assertions stays green when the detector is deleted.
"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

# The sys.path.insert must run before importing editscale, so the import
# cannot sit at module top — E402 is silenced because the path bootstrap
# is a precondition of the import.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "hooks" / "scripts"))
from lib import editscale  # noqa: E402 -- see path-bootstrap note above


def _text(lines: int, width: int = 40) -> str:
    """A synthetic file body of `lines` lines, each `width` chars wide."""
    body = "x" * (width - 1)
    return "".join(f"{body}\n" for _ in range(lines))


class TestAbsoluteClassificationUnchanged(unittest.TestCase):
    """v0.35 must be monotone-loosening: passing scale=None reproduces
    the v0.13-v0.34 classifier exactly. These pin that contract, because
    it is what makes the unmeasurable-file fallback safe rather than
    merely quiet."""

    def test_small_stays_small_without_scale(self) -> None:
        self.assertEqual(
            editscale.classify_change("old line\n", "new line\n"), "small")

    def test_systematic_by_line_floor_without_scale(self) -> None:
        big = "\n".join(f"line {i}" for i in range(60))
        self.assertEqual(editscale.classify_change("x\n", big), "systematic")

    def test_systematic_by_char_floor_without_scale(self) -> None:
        self.assertEqual(
            editscale.classify_change("x", "y" * 1500), "systematic")

    def test_medium_stays_medium_without_scale(self) -> None:
        mid = "\n".join(f"l{i}" for i in range(15))
        self.assertEqual(editscale.classify_change("a\n", mid), "medium")

    def test_char_floor_boundary_is_inclusive(self) -> None:
        self.assertEqual(
            editscale.classify_change("x", "y" * 1499), "medium")
        self.assertEqual(
            editscale.classify_change("x", "y" * 1500), "systematic")


class TestRelativeCoverageRoute(unittest.TestCase):
    """The v0.35 addition: a change may reach 'systematic' by SPANNING
    the target rather than by absolute size."""

    def test_full_rewrite_of_a_small_file_is_systematic(self) -> None:
        # THE defect. A 30-line, ~900-char module: rewriting all of it is
        # under both absolute floors, so before v0.35 this was "medium" —
        # neither counting nor resetting — and the file's counter could
        # never be cleared once three small edits had landed.
        src = _text(30, 30)
        self.assertLess(len(src), editscale.SYSTEMATIC_MIN_CHARS)
        self.assertLess(editscale.line_count(src), editscale.SYSTEMATIC_MIN_LINES)
        self.assertEqual(
            editscale.classify_change("", src, editscale.file_scale(src)),
            "systematic",
        )

    def test_twin_same_change_without_scale_is_only_medium(self) -> None:
        # The refusal twin: delete the scale argument and the old verdict
        # comes straight back, proving the coverage route is what moved
        # it and not some incidental threshold drift.
        src = _text(30, 30)
        self.assertEqual(editscale.classify_change("", src), "medium")

    def test_small_edit_to_a_large_file_is_still_small(self) -> None:
        # The other end: the coverage route must not turn ordinary small
        # edits to real files into free counter resets.
        big = _text(1200, 60)
        self.assertEqual(
            editscale.classify_change(
                "old line\n", "new line\n", editscale.file_scale(big)),
            "small",
        )

    def test_ratio_boundary_is_inclusive_on_chars(self) -> None:
        # The line axis is deliberately parked out of reach (a 10k-line
        # file needs a 3000-line change to span it) so this test isolates
        # the CHARACTER route. An earlier draft used scale=(1000, 1),
        # where the line bar is ceil(0.3*1) = 1 and every single-line
        # change qualified — the axis under test was never the deciding
        # one.
        scale = (1000, 10_000)
        bar = editscale.coverage_bar(scale)[0]
        self.assertEqual(bar, 300)
        self.assertEqual(
            editscale.classify_change("", "y" * bar, scale), "systematic")
        # One char short — no longer systematic. It is "medium" rather
        # than "small" because 299 chars is over the 200-char small bound.
        self.assertEqual(
            editscale.classify_change("", "y" * (bar - 1), scale), "medium")

    def test_ratio_boundary_is_inclusive_on_lines(self) -> None:
        scale = (10_000, 100)
        bar = editscale.coverage_bar(scale)[1]
        self.assertEqual(bar, 30)
        # Built to an EXACT line_count under the module's own convention
        # (trailing newline opens a final empty line), asserted rather
        # than assumed — the _text helper yields n+1 by that counting and
        # an off-by-one here would silently test the wrong side of the bar.
        at_bar = "x\n" * (bar - 1) + "x"
        under = "x\n" * (bar - 2) + "x"
        self.assertEqual(editscale.line_count(at_bar), bar)
        self.assertEqual(editscale.line_count(under), bar - 1)
        self.assertEqual(
            editscale.classify_change("", at_bar, scale), "systematic")
        # One line short: 29 lines is over the 10-line small bound, so it
        # lands in medium — still NOT systematic, which is the assertion.
        self.assertNotEqual(
            editscale.classify_change("", under, scale), "systematic")

    def test_inertness_boundary_is_five_lines_not_twenty(self) -> None:
        """Pin the documented inert-range figure to the real one.

        `rules/09`, both READMEs, the CHANGELOG and editscale's own docstring
        all state where this layer stops biting. The first draft of that
        sentence said "a twenty-line file", written from intuition — and a
        live probe then denied a fourth small edit on a THIRTY-line file,
        which is the claim's own counterexample. Documented numbers in this
        repo are derived, so this is the derivation.
        """
        two_line_edit = ("a\n", "b\n")
        inert = [
            n for n in range(2, 31)
            if editscale.classify_change(
                *two_line_edit, editscale.file_scale("x\n" * n)) == "systematic"
        ]
        self.assertEqual(
            inert, [2, 3, 4, 5],
            "the documented inert range (~5 lines and under) no longer "
            "matches the classifier; update rules/09, both READMEs, the "
            "CHANGELOG and editscale's docstring together",
        )

    def test_coverage_bar_rounds_up_not_down(self) -> None:
        # ceil, because the comparison is `>=` on integers: truncating
        # would advertise a bar one unit below the one enforced.
        self.assertEqual(editscale.coverage_bar((11, 11)), (4, 4))

    def test_coverage_bar_is_none_without_scale(self) -> None:
        self.assertIsNone(editscale.coverage_bar(None))

    def test_empty_file_scale_does_not_divide_by_zero(self) -> None:
        self.assertEqual(
            editscale.classify_change("a", "b", (0, 0)), "small")


class TestNetReduction(unittest.TestCase):
    def test_shorter_new_string_is_a_net_reduction(self) -> None:
        self.assertTrue(editscale.is_net_reduction("aaaa", "aa"))

    def test_twin_longer_new_string_is_not(self) -> None:
        self.assertFalse(editscale.is_net_reduction("aa", "aaaa"))

    def test_equal_length_is_not_a_reduction(self) -> None:
        # Equal is not "net reducing" — a same-size rewrite is exactly the
        # swap-one-symptom-for-another shape rule 09 is about.
        self.assertFalse(editscale.is_net_reduction("abcd", "wxyz"))

    def test_deleting_everything_is_a_reduction(self) -> None:
        self.assertTrue(editscale.is_net_reduction("something", ""))

    def test_none_sides_are_tolerated(self) -> None:
        self.assertFalse(editscale.is_net_reduction(None, None))
        self.assertTrue(editscale.is_net_reduction("abc", None))


class TestBookkeepingInCode(unittest.TestCase):
    """allow_bare_numbers=False — the code case. Only version-shaped and
    ISO-date-shaped literals may move."""

    def _bk(self, old: str, new: str) -> bool:
        return editscale.is_bookkeeping_edit(old, new, allow_bare_numbers=False)

    def test_semver_bump_is_bookkeeping(self) -> None:
        self.assertTrue(self._bk('"version": "0.34.1"', '"version": "0.35.0"'))

    def test_v_prefixed_version_bump_is_bookkeeping(self) -> None:
        self.assertTrue(self._bk("tag = v0.34.1", "tag = v0.35.0"))

    def test_iso_date_bump_is_bookkeeping(self) -> None:
        self.assertTrue(self._bk("# 2026-08-19", "# 2026-08-25"))

    def test_twin_timeout_lengthening_is_not_bookkeeping(self) -> None:
        # rule 09 names this explicitly as forbidden. It is the reason the
        # allowlist is shaped rather than "any digit changed".
        self.assertFalse(self._bk("timeout = 30", "timeout = 300"))

    def test_twin_loosened_assertion_is_not_bookkeeping(self) -> None:
        self.assertFalse(self._bk("if n > 3:", "if n > 4:"))

    def test_twin_bare_count_in_code_is_not_bookkeeping(self) -> None:
        self.assertFalse(self._bk("assertEqual(x, 617)", "assertEqual(x, 619)"))

    def test_twin_changed_text_around_a_version_is_not_bookkeeping(self) -> None:
        # The skeleton must be byte-identical; smuggling a code change in
        # alongside a legitimate version bump must not be exempt.
        self.assertFalse(
            self._bk('v = "0.34.1"; safe = True', 'v = "0.35.0"; safe = False'))

    def test_twin_reshaping_a_number_into_a_version_is_not_bookkeeping(self) -> None:
        self.assertFalse(self._bk("x = 1", "x = 1.2.3"))

    def test_twin_added_numeric_token_is_not_bookkeeping(self) -> None:
        self.assertFalse(self._bk("v = 1.0.0", "v = 1.0.0 + 2.0.0"))

    def test_punctuation_change_beside_a_number_is_caught(self) -> None:
        # `617.` yields the token `617` with the full stop left in the
        # skeleton, so a change to the punctuation is still visible.
        self.assertFalse(self._bk("Ran 617.", "Ran 619!"))

    def test_identical_sides_are_trivially_bookkeeping(self) -> None:
        self.assertTrue(self._bk("unchanged", "unchanged"))


class TestBookkeepingInProse(unittest.TestCase):
    """allow_bare_numbers=True — the prose-doc case, where there is no
    timeout to lengthen and no assertion to loosen."""

    def _bk(self, old: str, new: str) -> bool:
        return editscale.is_bookkeeping_edit(old, new, allow_bare_numbers=True)

    def test_test_count_update_is_bookkeeping(self) -> None:
        self.assertTrue(self._bk("**617 tests**", "**619 tests**"))

    def test_version_and_date_still_work(self) -> None:
        self.assertTrue(self._bk("## [0.34.1] — 2026-08-19",
                                 "## [0.35.0] — 2026-08-25"))

    def test_twin_changed_prose_is_not_bookkeeping(self) -> None:
        self.assertFalse(self._bk("**617 tests** pass", "**619 tests** fail"))

    def test_twin_same_edit_in_code_mode_is_refused(self) -> None:
        # The whole point of the flag: identical text, different verdict,
        # decided by what kind of file it is going into.
        self.assertTrue(self._bk("**617 tests**", "**619 tests**"))
        self.assertFalse(
            editscale.is_bookkeeping_edit(
                "**617 tests**", "**619 tests**", allow_bare_numbers=False))


class TestFileMeasurement(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="ccens-es-")
        self.root = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_reads_a_normal_file(self) -> None:
        p = self.root / "a.py"
        p.write_text("one\ntwo\n", encoding="utf-8")
        # 8 chars; 3 "lines" because the trailing newline opens an empty
        # final one — line_count's documented convention, asserted here at
        # the file boundary so a change to it cannot pass unnoticed.
        self.assertEqual(editscale.file_scale(editscale.file_text(str(p))), (8, 3))

    def test_missing_file_measures_as_none(self) -> None:
        self.assertIsNone(editscale.file_text(str(self.root / "nope.py")))

    def test_non_utf8_file_measures_as_none(self) -> None:
        p = self.root / "b.bin"
        p.write_bytes(b"\xff\xfe\x00binary")
        self.assertIsNone(editscale.file_text(str(p)))

    def test_oversized_file_measures_as_none(self) -> None:
        p = self.root / "big.py"
        p.write_text("x" * (editscale.SCALE_READ_MAX_BYTES + 10), encoding="utf-8")
        self.assertIsNone(editscale.file_text(str(p)))

    def test_unmeasurable_falls_back_to_stricter_not_looser(self) -> None:
        # The direction claim in file_text's docstring, pinned. With no
        # scale a 30-line file's full rewrite is "medium" (no reset);
        # with a scale it is "systematic" (reset). Losing the measurement
        # can therefore only withhold a reset, never grant one.
        src = _text(30, 30)
        self.assertEqual(editscale.classify_change("", src, None), "medium")
        self.assertEqual(
            editscale.classify_change("", src, editscale.file_scale(src)),
            "systematic",
        )

    def test_line_count_treats_empty_as_zero(self) -> None:
        self.assertEqual(editscale.line_count(""), 0)
        self.assertEqual(editscale.line_count("a"), 1)
        self.assertEqual(editscale.line_count("a\n"), 2)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
