"""The before/after demo must keep showing what the READMEs say it shows.

Two obligations, and the second is the one that matters:

1. **The committed images are current.** `demo/out/*.svg` are embedded in
   both READMEs. Re-running the demo must reproduce them byte for byte, so
   a change in any hook's wording fails here instead of leaving a stale
   picture on the front page — the v0.35.1 class (a sample that no longer
   matched the code) applied to an image.

2. **The images still show three real refusals.** Obligation 1 alone is
   satisfied by a demo that stopped denying anything, as long as somebody
   re-rendered afterwards. So each verdict is asserted by content, and the
   "without" half is asserted to end in the silent failure that gives the
   comparison its point. An equality check against a regenerated artefact
   cannot tell a working gate from a deleted one.
"""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DEMO = REPO_ROOT / "demo"
OUT = DEMO / "out"

# demo/ is a standalone example project, not a package: it is meant to be
# runnable as `python demo/run_demo.py` from a clone, so it has no __init__
# and its modules import each other by bare name. Adding it to sys.path here
# is what lets this gate drive the same code path a user would.
sys.path.insert(0, str(DEMO))

import render_svg  # noqa: E402  -- because the sys.path line above is a
import run_demo    # noqa: E402  -- prerequisite for these two imports


class TestDemoImagesAreCurrent(unittest.TestCase):
    """demo/out/*.svg must equal a fresh render of a fresh run."""

    def _fresh(self, lines: list[str], title: str) -> str:
        with tempfile.TemporaryDirectory() as tmp:
            path = render_svg.render(lines, Path(tmp) / "x.svg", title)
            return path.read_text(encoding="utf-8")

    def test_without_image_matches_a_fresh_run(self) -> None:
        committed = (OUT / "without-cc-enforcer.svg").read_text(encoding="utf-8")
        self.assertEqual(
            self._fresh(run_demo.run_without(), "WITHOUT cc-enforcer"),
            committed,
            "demo/out/without-cc-enforcer.svg is stale. Re-render with "
            "`python demo/run_demo.py --svg` and commit the result — both "
            "READMEs embed this image.",
        )

    def test_with_image_matches_a_fresh_run(self) -> None:
        committed = (OUT / "with-cc-enforcer.svg").read_text(encoding="utf-8")
        self.assertEqual(
            self._fresh(run_demo.run_with(), "WITH cc-enforcer"),
            committed,
            "demo/out/with-cc-enforcer.svg is stale. A hook's wording "
            "changed and the picture on the front page did not. Re-render "
            "with `python demo/run_demo.py --svg`.",
        )


class TestDemoStillDemonstratesRefusals(unittest.TestCase):
    """The twin: equality alone cannot tell a live gate from a dead one."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.without = "\n".join(run_demo.run_without())
        cls.with_ = "\n".join(run_demo.run_with())

    def test_the_swallow_is_refused(self) -> None:
        self.assertIn("bare try / except: pass", self.with_,
                      "the demo no longer shows rule 09's patch-marker deny")

    def test_the_fourth_small_edit_is_refused(self) -> None:
        self.assertIn("rolling-patch interception", self.with_,
                      "the demo no longer shows the rolling-patch deny")

    def test_the_evidence_free_sign_off_is_refused(self) -> None:
        self.assertIn("FAILED at Layer (a)", self.with_,
                      "the demo no longer shows the Stop gate blocking a "
                      "completion claim that carries no evidence")

    def test_all_three_verdicts_are_verbatim_hook_output(self) -> None:
        """Each refusal carries the hook's own banner, not a paraphrase."""
        self.assertEqual(
            self.with_.count("cc-enforcer · "), 3,
            "expected exactly three verbatim cc-enforcer verdicts in the "
            "'with' transcript; a different count means the demo drifted "
            "from the sequence the READMEs describe.",
        )

    def test_without_half_ends_in_a_silent_failure(self) -> None:
        """The contrast is the product. Without it the image says nothing."""
        self.assertIn("SILENT:", self.without,
                      "the unguarded run no longer ends in a silent failure, "
                      "so the comparison has lost its point")
        self.assertIn("FAILED", self.without,
                      "the unguarded run's suite is no longer red, so the "
                      "sign-off claiming it is green is no longer a false claim")
        self.assertNotIn("cc-enforcer · ", self.without,
                         "the unguarded run must contain no verdicts at all")

    def test_transcripts_carry_no_host_specific_paths(self) -> None:
        """The images are pinned byte for byte, so they must be portable.

        v0.36.0 shipped images rendered on Windows: the deny banner's target
        read `paygate\\charge.py`, which Linux reproduces as `paygate/…`, and
        CI went red minutes after the release. Asserted here rather than left
        to CI, so the failure names the cause instead of showing a diff of
        two 8 KB SVGs.
        """
        for name, text in (("without", self.without), ("with", self.with_)):
            with self.subTest(run=name):
                self.assertNotIn(
                    "paygate" + chr(92), text,
                    "the transcript renders the demo path with a Windows "
                    "separator; _frame must normalise it to '/'",
                )
                self.assertNotIn(
                    "cce-demo-", text,
                    "the throwaway workspace path leaked into the transcript",
                )

    def test_the_two_runs_perform_the_same_edits(self) -> None:
        """Same task, same sequence — the hooks are the only variable."""
        for n, (label, _, _) in enumerate(run_demo.STEPS, 1):
            with self.subTest(step=n):
                self.assertIn(label, self.without)
                self.assertIn(label, self.with_)


if __name__ == "__main__":
    unittest.main()
