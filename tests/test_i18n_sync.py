"""Tests for hooks/scripts/i18n_check.py — language version control.

English is the skeleton (source of truth). ``check_sync()`` must:
  1. Report ``[]`` when the real repo's translations track the skeleton
     (the CI green condition).
  2. Actually DETECT drift — missing file, orphan file, header-structure
     mismatch — otherwise the CI gate would pass vacuously (a checker
     that always returns ``[]`` would satisfy assertion 1 too).
  3. Skip ``#`` comments inside fenced code blocks (not count them as
     headers).
  4. Discover any language subdir automatically (not just ``zh``).

These import ``check_sync`` directly (it is a pure library function, not
a hook subprocess) and drive it against synthetic temp trees so drift
can be injected deterministically.
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

# The sys.path.insert must run before importing i18n_check, so the import
# cannot sit at module top — E402 (import-not-at-top) is silenced because
# the path bootstrap is a precondition of the import, not dead code.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "hooks" / "scripts"))
from i18n_check import check_sync  # noqa: E402 -- see path-bootstrap note above


class TestRepoInSync(unittest.TestCase):
    def test_real_repo_translations_in_sync(self) -> None:
        # The shipped repo must be green: every rules/<lang> and
        # prompts/<lang> tracks the English skeleton section-for-section.
        drifts = check_sync()
        self.assertEqual(
            drifts, [],
            msg="i18n drift in repo:\n" + "\n".join(str(d) for d in drifts),
        )


class TestDriftDetection(unittest.TestCase):
    """Prove the checker is not vacuously passing — it must catch drift."""

    def _skeleton(self, base: Path) -> None:
        """Write a minimal 2-root skeleton with one in-sync zh translation."""
        (base / "rules" / "zh").mkdir(parents=True)
        (base / "prompts" / "zh").mkdir(parents=True)
        # Skeleton file with a [1, 2, 2] header structure.
        skel = "# Title\n\n## One\n\ntext\n\n## Two\n\ntext\n"
        (base / "rules" / "a.md").write_text(skel, encoding="utf-8")
        # Matching translation: headers translated, structure identical.
        trans = "# 标题\n\n## 一\n\n文字\n\n## 二\n\n文字\n"
        (base / "rules" / "zh" / "a.md").write_text(trans, encoding="utf-8")

    def test_in_sync_temp_repo_reports_nothing(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            self._skeleton(base)
            self.assertEqual(check_sync(base), [])

    def test_detects_missing_file(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            self._skeleton(base)
            # Skeleton gains a file with no zh translation.
            (base / "rules" / "b.md").write_text("# B\n", encoding="utf-8")
            drifts = check_sync(base)
            self.assertTrue(
                any(d.kind == "missing_file" and d.file == "b.md" for d in drifts),
                msg=f"missing_file not reported: {[str(d) for d in drifts]}",
            )

    def test_detects_orphan_file(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            self._skeleton(base)
            # zh gains a file the skeleton doesn't have.
            (base / "rules" / "zh" / "extra.md").write_text("# X\n", encoding="utf-8")
            drifts = check_sync(base)
            self.assertTrue(
                any(d.kind == "orphan_file" and d.file == "extra.md" for d in drifts),
                msg=f"orphan_file not reported: {[str(d) for d in drifts]}",
            )

    def test_detects_header_structure_drift(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            self._skeleton(base)
            # zh drops a section → [1, 2] vs skeleton [1, 2, 2].
            (base / "rules" / "zh" / "a.md").write_text(
                "# 标题\n\n## 一\n\n文字\n", encoding="utf-8",
            )
            drifts = check_sync(base)
            self.assertTrue(
                any(d.kind == "header_structure" and d.file == "a.md" for d in drifts),
                msg=f"header_structure not reported: {[str(d) for d in drifts]}",
            )

    def test_ignores_headers_inside_code_fences(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            self._skeleton(base)
            # Same real headers, but a fenced code block adds '#'-prefixed
            # lines. These must NOT count as headers → no drift.
            trans = (
                "# 标题\n\n## 一\n\n"
                "```bash\n# this is a shell comment, not a header\n"
                "## nor is this\n```\n\n"
                "## 二\n\n文字\n"
            )
            (base / "rules" / "zh" / "a.md").write_text(trans, encoding="utf-8")
            drifts = check_sync(base)
            self.assertEqual(
                drifts, [],
                msg="code-fence '#' lines wrongly counted as headers:\n"
                    + "\n".join(str(d) for d in drifts),
            )

    def test_detects_enforcement_token_drift(self) -> None:
        """v0.26.0: a translation may not silently shrink the deny set.

        This is the check that would have caught the real defect —
        prompts/zh/ listed four of the seven Bash patterns bash_guard
        denies, so a zh session was told a smaller deny set than an en
        session, every turn. File-set and header-structure parity are
        both perfectly green in that situation.
        """
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            self._skeleton(base)
            skel = (
                "# Title\n\n## One\n\n"
                "| Bash containing `--no-verify` / `git rebase --skip` "
                "| DENY |\n\n"
                "## Two\n\ntext\n"
            )
            (base / "rules" / "a.md").write_text(skel, encoding="utf-8")
            # Same structure, same header levels — but one token dropped.
            (base / "rules" / "zh" / "a.md").write_text(
                "# 标题\n\n## 一\n\n"
                "| Bash 含 `--no-verify` | DENY |\n\n"
                "## 二\n\n文字\n",
                encoding="utf-8",
            )
            drifts = check_sync(base)
            self.assertTrue(
                any(d.kind == "enforcement_tokens" and "git rebase --skip" in d.detail
                    for d in drifts),
                msg=f"enforcement drift not reported: {[str(d) for d in drifts]}",
            )

    def test_enforcement_parity_ignores_non_deny_lines(self) -> None:
        """Twin of the above: prose code spans are translated freely.

        Without this bound the check would flag every ordinary wording
        difference, which is why it is scoped to DENY lines — measured at
        24 false positives across rules/ when applied to all code spans.
        """
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            self._skeleton(base)
            (base / "rules" / "a.md").write_text(
                "# Title\n\n## One\n\nUse `Path.home()` here.\n\n"
                "## Two\n\ntext\n",
                encoding="utf-8",
            )
            (base / "rules" / "zh" / "a.md").write_text(
                "# 标题\n\n## 一\n\n这里用运行时派生。\n\n## 二\n\n文字\n",
                encoding="utf-8",
            )
            self.assertEqual(
                check_sync(base), [],
                msg="a non-DENY code span must not count as enforcement drift",
            )

    def test_discovers_any_language_subdir(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            self._skeleton(base)
            # A brand-new 'ja' translation dir with a structural drift must
            # be discovered with no allow-list edit (any-language support).
            (base / "rules" / "ja").mkdir()
            (base / "rules" / "ja" / "a.md").write_text(
                "# タイトル\n", encoding="utf-8",  # [1] vs skeleton [1, 2, 2]
            )
            drifts = check_sync(base)
            self.assertTrue(
                any(d.lang == "ja" and d.kind == "header_structure" for d in drifts),
                msg=f"ja drift not discovered: {[str(d) for d in drifts]}",
            )


if __name__ == "__main__":
    unittest.main()
