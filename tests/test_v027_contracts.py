"""v0.27.0 — the three deferred items, closed as deliberate contract changes.

Each of these was recorded in v0.26.0 as "known, not fixed". They are
closed here, and each carries the evidence that decided the direction —
not a preference, a measurement or a spelled-out trade-off.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

# The sys.path bootstrap must precede these imports; E402 is silenced
# because the bootstrap is a precondition of the import, not dead code.
_SCRIPTS = Path(__file__).resolve().parents[1] / "hooks" / "scripts"
sys.path.insert(0, str(_SCRIPTS))
import bash_guard  # noqa: E402 -- because the path bootstrap must run first
import stop_guard  # noqa: E402 -- because of the path bootstrap above
# because of the sys.path bootstrap above, this import cannot sit at top
from lib import mdctx, shellcmd  # noqa: E402

BS = chr(92)


class TestShellGrammarNotHostOS(unittest.TestCase):
    """Tokenisation follows the SHELL, not `os.name`.

    Decided by measurement, not preference. On Windows, Claude Code's
    Bash tool runs Git Bash / MSYS (`bash 5.2.37(1)-release`,
    `OSTYPE=msys`). That shell was observed to eat the separators of an
    unquoted drive-letter path, and to reassemble a backslash-split flag
    into `--force` before git ever sees it. (The transcript is in the
    v0.27.0 CHANGELOG entry.)

    So the pre-v0.27 `escape=""` branch disagreed with the real shell in
    both directions: it never rescued the path case, and it hid a live
    force-push evasion.
    """

    FORCE_EVASION = "git push --for" + BS + "ce origin main"

    def test_backslash_split_force_flag_is_detected(self) -> None:
        toks = shellcmd.tokenize(self.FORCE_EVASION)
        self.assertIn("--force", toks,
                      "the shell reassembles this into --force")
        self.assertIsNotNone(
            bash_guard._detect_force_push(self.FORCE_EVASION),
            "a force push the shell will really perform must be denied",
        )

    def test_legacy_windows_branch_is_why_it_was_abandoned(self) -> None:
        """Pinned so the old behaviour cannot quietly return."""
        toks = shellcmd.tokenize(self.FORCE_EVASION, windows=True)
        self.assertNotIn(
            "--force", toks,
            "the legacy branch saw a token it did not recognise — which "
            "is exactly how the evasion worked",
        )

    def test_quoted_drive_path_still_survives(self) -> None:
        toks = shellcmd.tokenize(
            'python r.py --file "C:' + BS + 'a' + BS + 'b.py"')
        self.assertIn("C:" + BS + "a" + BS + "b.py", toks,
                      "quoting is what preserves a drive path, in this "
                      "tokeniser and in the shell alike")

    def test_unquoted_drive_path_matches_the_shell(self) -> None:
        toks = shellcmd.tokenize(
            "python r.py --file C:" + BS + "a" + BS + "b.py")
        self.assertIn("C:ab.py", toks,
                      "the real shell eats these separators too; agreeing "
                      "with it is the point of dropping the host branch")

    def test_ordinary_force_push_and_lease_are_unchanged(self) -> None:
        self.assertIsNotNone(
            bash_guard._detect_force_push("git push --force origin main"))
        self.assertIsNone(
            bash_guard._detect_force_push(
                "git push --force-with-lease origin main"))


class TestLayerHPresenceVsMeasurement(unittest.TestCase):
    """Presence is generous; measurement is conservative.

    v0.26 skipped CommonMark lazy continuation because a single
    `countable` verdict forced a bad trade: implementing it made a
    visible `tldr:` under a blockquote uncountable, so the presence half
    then blocked the reply for a MISSING summary the author could see.
    Splitting the verdict removes the trade entirely.
    """

    LONG = "A" * 200

    def test_lazily_continued_tldr_is_not_measured(self) -> None:
        text = "> quoted paragraph\ntldr: " + self.LONG
        self.assertIsNone(
            stop_guard._find_overlong_tldr(text),
            "per CommonMark that line is inside the blockquote, so its "
            "length is not the agent's to answer for",
        )

    def test_lazily_continued_tldr_still_counts_as_present(self) -> None:
        text = "> quoted paragraph\ntldr: did the thing"
        self.assertTrue(
            stop_guard._has_tldr(text),
            "blocking for a 'missing' tldr that is plainly on screen is "
            "the worse error, and undiagnosable from the block reason",
        )

    def test_explicitly_quoted_tldr_is_not_the_agents_own(self) -> None:
        self.assertFalse(
            stop_guard._has_tldr("> tldr: someone else wrote this"))

    def test_blank_line_ends_the_lazy_continuation(self) -> None:
        text = "> quoted\n\ntldr: " + self.LONG
        self.assertIsNotNone(
            stop_guard._find_overlong_tldr(text),
            "a blank line closes the quote, so this tldr is the agent's",
        )

    def test_ordinary_overlong_tldr_still_blocks(self) -> None:
        self.assertIsNotNone(
            stop_guard._find_overlong_tldr("tldr: " + self.LONG))

    def test_context_exposes_both_verdicts(self) -> None:
        ctx = mdctx.lines("> quoted paragraph\ntldr: mine")
        self.assertFalse(ctx[1].countable, "lazy continuation: not measured")
        self.assertTrue(ctx[1].attributable, "lazy continuation: still theirs")


class TestSyncAckIsScopedToShownGroups(unittest.TestCase):
    """A marker settles only groups the agent has actually been shown.

    Both layer-(i) paths now use the same rule. Before v0.27 the primary
    path acked everything pending while the grace path acked only the
    presented set — and that inconsistency WAS the bypass: outlasting the
    grace window reached the looser path.
    """

    def test_primary_ack_path_filters_by_the_presented_set(self) -> None:
        import inspect
        src = inspect.getsource(stop_guard)
        self.assertIn("_ack_pending_sync_groups", src,
                      "the grace path's scoping helper must still exist")
        parts = src.split("if _has_sync_marker(message):")
        self.assertGreater(len(parts), 1, "primary marker branch not found")
        self.assertIn(
            "get_last_blocked_groups", parts[-1][:1400],
            "the primary ack path must filter by the presented set; "
            "acking every pending group is the pre-v0.27 behaviour this "
            "release deliberately replaced",
        )


if __name__ == "__main__":
    unittest.main()
