#!/usr/bin/env python3
"""cc-enslaver — Stop hook enforcing rules 06 + 07 + 08 + 09.

At every Stop event, this hook inspects the agent's last assistant
message and refuses to let the agent finish the turn when any of six
laziness signals appear in proximity to a "done" claim:

  (a) [v0.6.0] No convergence evidence at all (no `$ ` shell prompt,
      no command output, no "重触发", no test counts, no fenced code
      block). Pure "已解决" / "fixed" walking away.

  (b) [v0.7.0] Hedged completion (rule 01 cross-enforcement):
      done-claim appears within ~50 chars of a first-person uncertainty
      marker ("我觉得", "我相信", "I think", "I believe", "probably",
      "maybe", "应该是", "大概"). Confident verification cannot coexist
      with hedged language; one of the two has to give.

  (c) [v0.7.0] Missing rule-06 self-quiz: the agent supplied
      evidence but did not surface either an explicit convergence
      marker (`rule 06`, `自答`, `收敛`, `重触发`, `边界用例`) OR at
      least 2 of the 4 self-questions (真解决? 更好方案? 哪些没验?
      验证合理?).

  (d) [v0.8.0] Missing rule-07 task-fidelity confirmation: even
      after passing rule-06 convergence, the agent must show it has
      reconciled what it shipped against the user's *original* request
      — coverage (no omission), standard (no degrade from "mandatory"
      to "soft suggestion"), and fidelity (no concept-swap, no scope
      creep, no buried TODOs). Pass condition is identical in shape to
      (c): any explicit fidelity marker (`rule 07`, `任务忠实`,
      `请求覆盖`, `原始请求`, `无降级`, `无遗漏`, `task fidelity`,
      `request coverage`, `no degrad`, `no omission`) OR at least 2 of
      3 self-questions (覆盖 / 标准 / 忠实) matched.

  (e) [v0.11.0 NEW] Rule 08 closing check — read-before-edit /
      think-before-write. Layer (e) fires **only when the agent
      actually edited a file this turn** (state.did_edit_this_turn is
      True). Pass condition: any rule-08 marker (`rule 08`, `改前必读`,
      `写前必想`, `read-before-edit`, `think-before-write`) OR at
      least 3 of the six rule-02 systematic-thinking keywords
      (架构 / 职责 / 根源 / 方案 / 连带 / 风险 / 全局, or English
      equivalents). Without an actual edit this turn, layer (e)
      silently allows — analysis-only / answer-only turns aren't
      required to surface think-before-write markers.

  (f) [v0.11.0 NEW] Rule 09 closing check — systematic modification,
      no patch-style. Layer (f) also fires **only on edit turns**.
      Pass condition: any rule-09 marker (`rule 09`, `系统式修改`,
      `根因`, `打补丁`, `systematic modification`, `root cause`,
      `patch-style`) OR all three of the "root cause + impact +
      solution" triplet keywords (root-cause + impact + solution /
      根因 + 影响 + 方案). Without an actual edit this turn, layer
      (f) silently allows.

When any of (a)-(f) hold, the hook returns
`{"decision": "block", "reason": <appropriate reminder>}`. The agent
gets one corrective turn.

# v0.12 block-reason format

Every block reason has the same four-part shape:

    cc-enslaver · Stop check FAILED at Layer (X) [rule NN — short label]

    | Layer | Rule | Status      | Note                              |
    |-------|------|-------------|-----------------------------------|
    | (a)   | 06   | ✅ Pass      |                                   |
    | (b)   | 01   | ✅ Pass      |                                   |
    | (c)   | 06   | ❌ FAIL     | self-quiz / marker absent         |
    | (d)   | 07   | ⏸  pending  | (gated by earlier fail)           |
    | (e)   | 08   | —  n/a      | (non-edit turn)                   |
    | (f)   | 09   | —  n/a      | (non-edit turn)                   |

    Done-claim matched: '...'

    [Recovery — rule 06 self-quiz]
    <short, actionable recovery instructions>

    (One-shot guard: ...)

The status table is built by `_render_status_table(fail_layer_id,
edit_turn)`; the body is composed by `_build_block_reason(...)`. This
replaces the v0.6-v0.11 monolithic 50-line REASON templates with a
uniform compact format.

# One-shot guard — why we never block twice in a row

A Stop hook that always blocks would loop forever: block → continue →
block → continue → … . We record `last_blocked_turn` in the
session state file. If the *current* `turn_count` is within 3 turns
of the last block, we skip the heuristic and allow the Stop. The
agent gets one (well, up to three) chances to recover before we
fire again.

# Why four layered checks instead of one

The bar tightens monotonically: (a) → (b) → (c) → (d) only fire if
the preceding gate passed. (a) catches the laziest case (no work
shown). (b) catches sloppy completion (hedged language). (c) catches
faked rule-06 evidence (any `$ ls` output passes (a) but the agent
must engage with the rule-06 self-quiz to pass (c)). (d) catches the
different axis covered by rule 07 — even an agent who genuinely
converged on the part it edited may have silently dropped sub-tasks,
downgraded "mandatory" to "soft", or buried TODOs. Each gate has its
own block template so the agent sees exactly which discipline failed.

Permissiveness within (c) and (d): we accept 2 of N self-questions
OR any single explicit marker, so an agent who truly performed the
check using their own phrasing isn't penalised. The one-shot guard
keeps false-positive cost at exactly 1 turn.

# Output contract (Stop event, verified against
# https://code.claude.com/docs/en/hooks.md):
#
#   Block:  {"decision": "block", "reason": "<text>"}   (top-level)
#   Allow:  exit 0 with no stdout
#
# Note this differs from PreToolUse, which uses
# `hookSpecificOutput.permissionDecision`.

# Failing-open contract: any exception → log to stderr + exit 0
# (allow). A bug in the guard cannot be permitted to brick the agent.
"""

from __future__ import annotations

import json
import re
import sys
import traceback
from pathlib import Path

# Make `lib/` importable when run as a script.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib import state as state_lib  # noqa: E402


# --------------------------------------------------------------------------- #
# Heuristic patterns.
#
# DONE_PATTERNS: phrasings that signal the agent claims completion.
# EVIDENCE_PATTERNS: phrasings that signal the agent supplied verification
#                    evidence per rule 06.
#
# Both pattern lists are intentionally loose. False positives (block when
# work was actually done) cost one extra turn each; false negatives (no
# block when work is sloppy) cost the discipline. The one-shot guard
# bounds the false-positive damage.
# --------------------------------------------------------------------------- #
DONE_PATTERNS = [
    # Chinese — explicit completion
    re.compile(r"已解决"),
    re.compile(r"已修复"),
    re.compile(r"完成了"),
    re.compile(r"完工"),
    re.compile(r"搞定"),
    # Chinese — natural "fixed it" phrasings (V + 好了 idiom).
    # Caught the test failure where "我把 bug 改好了" was overlooked
    # because we had only 修好了 but not 改好了 / 弄好了 / 搞好了 etc.
    re.compile(r"[修改弄搞]好了"),
    # English — explicit completion
    re.compile(r"\bfixed\b", re.IGNORECASE),
    re.compile(r"\bdone\b", re.IGNORECASE),
    re.compile(r"\bcompleted\b", re.IGNORECASE),
    re.compile(r"\bresolved\b", re.IGNORECASE),
    # English — soft "should be done" phrasings (also red flags)
    re.compile(r"all set", re.IGNORECASE),
    re.compile(r"should\s+work\s+now", re.IGNORECASE),
    re.compile(r"that\s+should\s+do\s+it", re.IGNORECASE),
]

EVIDENCE_PATTERNS = [
    # Shell prompts and command-output markers
    re.compile(r"^\s*\$\s+\S", re.MULTILINE),
    re.compile(r"^\s*>\s+\S", re.MULTILINE),
    # Test-runner output snippets
    re.compile(r"\b\d+\s+(passed|failed|errors?)\b", re.IGNORECASE),
    re.compile(r"Ran\s+\d+\s+tests?", re.IGNORECASE),
    re.compile(r"\bpytest\b", re.IGNORECASE),
    re.compile(r"\bunittest\b", re.IGNORECASE),
    # Convergence keywords from rule 06 itself
    re.compile(r"重触发"),
    re.compile(r"边界用例"),
    re.compile(r"反向用例"),
    re.compile(r"收敛"),
    # Generic verification language
    re.compile(r"\bverified\b", re.IGNORECASE),
    re.compile(r"\bre-?ran\b", re.IGNORECASE),
    re.compile(r"\bvalidated\b", re.IGNORECASE),
    # Evidence formatting cues — fenced code blocks of output
    re.compile(r"```\n[^`]{20,}", re.MULTILINE),
]


# --------------------------------------------------------------------------- #
# v0.7.0 — Hedge-near-done detection (rule 01 cross-enforcement at Stop).
#
# We deliberately scope hedge detection to *first-person uncertainty* in
# *immediate proximity* to the done-claim. Generic words like "通常" or
# "should" are NOT in this list — they appear in legitimate technical
# writing far from the completion claim. The proximity window (~50 chars)
# rules out cross-paragraph false positives where a hedge is descriptive
# rather than self-undermining.
# --------------------------------------------------------------------------- #
_HEDGE_INNER = (
    r"我[记觉]得|我相信|可能就|应该是|大概(?:是)?|"
    r"I\s+(?:think|believe|guess)|maybe|probably|kinda|sort\s+of"
)
_DONE_INNER = (
    r"已解决|已修复|[修改弄搞]好了|完成了|完工|搞定|"
    r"fixed|done|completed|resolved"
)
HEDGE_NEAR_DONE_PATTERNS = [
    # Hedge then done (within 50 chars)
    re.compile(rf"({_HEDGE_INNER}).{{0,50}}?({_DONE_INNER})", re.IGNORECASE),
    # Done then hedge (within 50 chars)
    re.compile(rf"({_DONE_INNER}).{{0,50}}?({_HEDGE_INNER})", re.IGNORECASE),
]


# --------------------------------------------------------------------------- #
# v0.7.0 — rule-06 self-quiz / convergence-marker detection.
#
# Two ways to satisfy this gate:
#   (1) Any single CONVERGENCE_MARKER appears (the agent explicitly named
#       the framework or one of its checks), OR
#   (2) At least 2 of the 4 SELF_QUIZ_PATTERNS match (the agent answered
#       at least half of the quiz, in their own phrasing).
# --------------------------------------------------------------------------- #
CONVERGENCE_MARKERS = [
    re.compile(r"\brule\s*0?6\b", re.IGNORECASE),
    re.compile(r"自答"),
    re.compile(r"收敛"),
    re.compile(r"\bconvergen", re.IGNORECASE),
    re.compile(r"\bself[\s-]?quiz", re.IGNORECASE),
    # Specific check names from rule 06 — invoking the check by name
    # demonstrates rule-06 awareness.
    re.compile(r"重触发"),
    re.compile(r"边界用例"),
    re.compile(r"反向用例"),
]

SELF_QUIZ_PATTERNS = [
    # Q1 — really solved?
    re.compile(r"真.{0,4}?解决|really.{0,4}?(?:solv|fix)", re.IGNORECASE),
    # Q2 — better solution?
    re.compile(
        r"更好.{0,4}?(?:方案|方法|做法)|better.{0,4}?(?:solut|approach|way)",
        re.IGNORECASE,
    ),
    # Q3 — unverified parts?
    re.compile(
        r"(?:哪些|哪里).{0,6}?(?:没验|未验)|unverif",
        re.IGNORECASE,
    ),
    # Q4 — meaningful verification?
    re.compile(
        r"验证.{0,6}?(?:合理|是否充分)|verification.{0,6}?(?:meaning|reasonab)",
        re.IGNORECASE,
    ),
]


# --------------------------------------------------------------------------- #
# v0.8.0 — rule-07 fidelity-marker / fidelity self-quiz detection.
#
# Rule 07 covers a different axis from rule 06. Rule 06 asks "did the
# part you edited converge?". Rule 07 asks "did you do everything the
# user asked for, at the standard they asked for, without scope creep
# or buried TODOs?". Two ways to satisfy this gate:
#   (1) Any single FIDELITY_MARKER appears (the agent named the
#       framework or one of its three checks), OR
#   (2) At least 2 of the 3 FIDELITY_QUIZ_PATTERNS match (the agent
#       answered at least 2/3 of: coverage, standard, fidelity).
# --------------------------------------------------------------------------- #
FIDELITY_MARKERS = [
    re.compile(r"\brule\s*0?7\b", re.IGNORECASE),
    re.compile(r"任务忠实"),
    re.compile(r"请求覆盖"),
    re.compile(r"原始请求"),
    re.compile(r"无遗漏"),
    re.compile(r"无降级"),
    re.compile(r"未降级"),
    re.compile(r"未遗漏"),
    re.compile(r"无超范围"),
    re.compile(r"未超范围"),
    re.compile(r"\btask\s+fidelity\b", re.IGNORECASE),
    re.compile(r"\brequest\s+coverage\b", re.IGNORECASE),
    re.compile(r"\brequest\s+fidelity\b", re.IGNORECASE),
    re.compile(r"no\s+degrad", re.IGNORECASE),
    re.compile(r"no\s+omission", re.IGNORECASE),
    re.compile(r"no\s+scope\s+creep", re.IGNORECASE),
    re.compile(r"covered\s+all", re.IGNORECASE),
    re.compile(r"all\s+requested", re.IGNORECASE),
    # Per-item enumeration cue — the user-original-request decomposition
    # form usually surfaces as ✅/⚠️/❌ checklists, which strongly imply
    # the agent went through the rule-07 wrap-up.
    re.compile(r"[✅⚠️❌].{0,40}?(?:完成|done|完工)", re.IGNORECASE),
]

FIDELITY_QUIZ_PATTERNS = [
    # Q1 — coverage: did I do every sub-item the user asked for?
    re.compile(
        r"(?:用户|原始).{0,8}?(?:请求|要求).{0,16}?(?:拆|列|包含|分成|项|子项)"
        r"|decompos[a-z]{0,4}.{0,12}?request"
        r"|sub-?item"
        r"|coverage.{0,8}?(?:check|complete)",
        re.IGNORECASE,
    ),
    # Q2 — standard: did each modifier word land as a hard action?
    re.compile(
        r"(?:强制|必须|完整|严格|全面|所有).{0,30}?(?:落实|硬动作|硬证据|拦截|断言|实现|生效)"
        r"|(?:mandator|strict|comprehensive|all|every|hard).{0,30}?"
        r"(?:enforced|verifi|hook|assert|land)",
        re.IGNORECASE,
    ),
    # Q3 — fidelity: any concept-swap, scope creep, or buried TODO?
    re.compile(
        r"偷换|降级|超范围|额外的?(?:改|修)|遗漏|裁剪"
        r"|concept.?swap|degrad|scope.?creep|omission|trim|drive-?by",
        re.IGNORECASE,
    ),
]


def _has_done_claim(text: str) -> str | None:
    """Return the matched done-claim phrase, or None."""
    for p in DONE_PATTERNS:
        m = p.search(text)
        if m:
            return m.group(0)
    return None


def _has_evidence(text: str) -> bool:
    return any(p.search(text) for p in EVIDENCE_PATTERNS)


def _has_hedge_near_done(text: str) -> tuple[str, str] | None:
    """If a hedge phrase appears within ~50 chars of a done-claim, return
    (hedge, done) snippets. Otherwise None.

    Used to enforce rule 01 (no confident-sounding completion that's
    actually hedged) at the Stop boundary.
    """
    for p in HEDGE_NEAR_DONE_PATTERNS:
        m = p.search(text)
        if m:
            # Group 1 is hedge in pattern[0], done in pattern[1]; the
            # caller doesn't actually need them ordered, so we return
            # them as ("hedge_or_done_a", "done_or_hedge_b").
            return m.group(1), m.group(2)
    return None


def _has_self_quiz_or_marker(text: str) -> bool:
    """v0.7.0 — True if the agent demonstrated rule-06 awareness via:
        (1) any explicit convergence marker, or
        (2) at least 2 of the 4 self-questions.

    Permissive on phrasing variety (>=2 of 4) so a careful agent who
    used different wording isn't penalised.
    """
    if any(p.search(text) for p in CONVERGENCE_MARKERS):
        return True
    matched = sum(1 for p in SELF_QUIZ_PATTERNS if p.search(text))
    return matched >= 2


def _has_fidelity_marker_or_quiz(text: str) -> bool:
    """v0.8.0 — True if the agent demonstrated rule-07 awareness via:
        (1) any explicit fidelity marker, or
        (2) at least 2 of the 3 fidelity self-questions.

    Same shape as `_has_self_quiz_or_marker` but on a different axis:
    rule 06 is "did the fix converge?", rule 07 is "did you deliver
    everything the user asked for at the standard requested?".
    """
    if any(p.search(text) for p in FIDELITY_MARKERS):
        return True
    matched = sum(1 for p in FIDELITY_QUIZ_PATTERNS if p.search(text))
    return matched >= 2


# --------------------------------------------------------------------------- #
# v0.11.0 — rule 08 (read-before-edit / think-before-write) closing check.
#
# Pass condition (either):
#   (1) an explicit rule-08 marker appears, or
#   (2) at least 3 of the six rule-02 seven-questions keywords surface
#       (架构 / 职责 / 根源 / 方案 / 连带 / 风险, or English equivalents).
#
# Layer (e) only fires when the agent actually edited a file this turn;
# analysis-only / answer-only turns are never blocked by (e).
# --------------------------------------------------------------------------- #
RULE_08_MARKERS = [
    re.compile(r"\brule\s*0?8\b", re.IGNORECASE),
    re.compile(r"改前必读"),
    re.compile(r"写前必想"),
    re.compile(r"read[\s-]before[\s-]edit", re.IGNORECASE),
    re.compile(r"think[\s-]before[\s-]write", re.IGNORECASE),
    re.compile(r"系统式自答"),
]

# Six rule-02 systematic-thinking keywords. We accept ≥ 3 of these as a
# stand-in for "the agent demonstrated rule-08 think-before-write
# discipline in their own phrasing". Each keyword has Chinese + English
# variants joined into one regex to keep the count honest (matching the
# same idea twice in two languages still counts as one).
RULE_02_KEYWORDS = [
    # Q1 / Q2 — architecture + responsibility
    re.compile(r"架构|architecture|architectural", re.IGNORECASE),
    re.compile(r"职责|responsibilit", re.IGNORECASE),
    # Q3 — root cause
    re.compile(r"根源|根因|root[\s-]?cause", re.IGNORECASE),
    # Q4 — solution / bottom-out
    re.compile(r"方案|solution|approach", re.IGNORECASE),
    # Q5 — connected impact
    re.compile(r"连带|下游|影响范围|downstream|impact|connected", re.IGNORECASE),
    # Q6 — risk / invariants
    re.compile(r"风险|不变量|invariant|risk", re.IGNORECASE),
]


def _has_rule08_marker_or_keywords(text: str) -> bool:
    """v0.11 — True if the agent demonstrated rule-08 awareness via:
        (1) any explicit rule-08 marker, or
        (2) at least 3 of the six rule-02 systematic-thinking keywords.
    """
    if any(p.search(text) for p in RULE_08_MARKERS):
        return True
    matched = sum(1 for p in RULE_02_KEYWORDS if p.search(text))
    return matched >= 3


# --------------------------------------------------------------------------- #
# v0.11.0 — rule 09 (systematic modification, no patch-style) closing
# check. Pass condition (either):
#   (1) an explicit rule-09 marker, or
#   (2) all three of the "root-cause + impact + solution" triplet
#       keywords (which is also the rule-09 systematic-modification
#       requirement).
#
# Layer (f) only fires when the agent actually edited a file this turn.
# --------------------------------------------------------------------------- #
RULE_09_MARKERS = [
    re.compile(r"\brule\s*0?9\b", re.IGNORECASE),
    re.compile(r"系统式修改"),
    re.compile(r"打补丁"),
    re.compile(r"patch[\s-]?style", re.IGNORECASE),
    re.compile(r"systematic[\s-]?modification", re.IGNORECASE),
    re.compile(r"non[\s-]?patch", re.IGNORECASE),
    re.compile(r"反补丁"),
]

# The three rule-09 "triplet" keywords. All three must be present for
# the keyword fallback to count as satisfying the gate.
RULE_09_TRIPLET = (
    # Root cause
    re.compile(r"根源|根因|root[\s-]?cause", re.IGNORECASE),
    # Impact / blast radius
    re.compile(r"连带|影响范围|impact|blast[\s-]?radius|downstream", re.IGNORECASE),
    # Solution / alternatives considered
    re.compile(r"方案|solution|approach|alternative", re.IGNORECASE),
)


def _has_rule09_marker_or_triplet(text: str) -> bool:
    if any(p.search(text) for p in RULE_09_MARKERS):
        return True
    return all(p.search(text) for p in RULE_09_TRIPLET)


# --------------------------------------------------------------------------- #
# Layer metadata & status-table rendering (v0.12).
#
# The block reason text used to be six ~50-line monolithic templates. v0.12
# regularises the output so every block reason has the same shape:
#
#   1. A single-line headline naming the failed layer and the rule it
#      enforces. Tests assert on the keywords here (`rule 06`, `rule 01`,
#      `self-quiz`, `hedge`, `rule 07`, `rule 08`, `rule 09`).
#   2. A status table listing all six layers (a)-(f) with a Pass / FAIL /
#      pending / n/a marker. The agent (and the human reading over its
#      shoulder) can see at a glance what passed and what didn't.
#   3. A short recovery block specific to the failing layer.
#   4. A common one-shot-guard footer.
#
# The six layers are ordered (a) → (f). When layer N fails, layers < N are
# Pass (we got past them), layer N is FAIL, layers > N are "pending" (never
# evaluated). When the failure occurs on a non-edit turn, layers (e)+(f)
# show "n/a (non-edit turn)" instead of pending — they would not have
# fired anyway. On an edit turn they show "pending".
# --------------------------------------------------------------------------- #
LAYER_META: list[dict[str, str]] = [
    {
        "id": "(a)",
        "rule": "06",
        "label": "rule 06 — no evidence",
        "recovery_keyword": "rule 06",
    },
    {
        "id": "(b)",
        "rule": "01",
        "label": "rule 01 — hedge near done-claim",
        "recovery_keyword": "rule 01 + hedge",
    },
    {
        "id": "(c)",
        "rule": "06",
        "label": "rule 06 — self-quiz missing",
        "recovery_keyword": "rule 06 self-quiz",
    },
    {
        "id": "(d)",
        "rule": "07",
        "label": "rule 07 — task fidelity missing",
        "recovery_keyword": "rule 07 fidelity",
    },
    {
        "id": "(e)",
        "rule": "08",
        "label": "rule 08 — read-before-edit / think-before-write",
        "recovery_keyword": "rule 08",
    },
    {
        "id": "(f)",
        "rule": "09",
        "label": "rule 09 — systematic-modification triplet",
        "recovery_keyword": "rule 09",
    },
]

# Per-layer short "note" rendered in the status table when that layer is
# the FAIL row. Keep these to a single short line each.
_LAYER_FAIL_NOTE = {
    "(a)": "no convergence evidence",
    "(b)": "hedge near done-claim",
    "(c)": "self-quiz / marker absent",
    "(d)": "fidelity marker / quiz absent",
    "(e)": "rule-08 marker / 3+ keywords absent",
    "(f)": "rule-09 marker / triplet incomplete",
}


def _render_status_table(fail_layer_id: str, edit_turn: bool) -> str:
    """Render the 6-row status table as a markdown table string.

    fail_layer_id is one of "(a)" .. "(f)" — the layer that just failed.
    edit_turn is True iff the agent actually ran Edit/Write this turn:
        - False → layers (e) and (f) display "— n/a (non-edit turn)"
        - True  → layers > fail_layer_id display "⏸  pending"
    """
    # Build rows. Layer order is fixed (a)-(f).
    fail_idx = next(
        i for i, meta in enumerate(LAYER_META) if meta["id"] == fail_layer_id
    )
    rows = []
    for i, meta in enumerate(LAYER_META):
        lid = meta["id"]
        rule = meta["rule"]
        if i < fail_idx:
            status = "✅ Pass"
            note = ""
        elif i == fail_idx:
            status = "❌ **FAIL**"
            note = _LAYER_FAIL_NOTE.get(lid, "")
        else:
            # Layer not evaluated yet (gated by earlier fail) OR not
            # applicable (e/f on non-edit turn).
            if lid in ("(e)", "(f)") and not edit_turn:
                status = "—  n/a"
                note = "(non-edit turn)"
            else:
                status = "⏸  pending"
                note = "(gated by earlier fail)"
        rows.append(
            f"| {lid:5s} | {rule:4s} | {status:<11s} | {note:<33s} |"
        )
    header = (
        "| Layer | Rule | Status      | Note                              |\n"
        "|-------|------|-------------|-----------------------------------|"
    )
    return header + "\n" + "\n".join(rows)


_ONE_SHOT_FOOTER = (
    "(One-shot guard: this is the only block in the current sequence — "
    "the next Stop is allowed even if this layer still fails. Use the "
    "next turn well.)"
)


def _build_block_reason(
    fail_layer_id: str,
    edit_turn: bool,
    recovery: str,
    *,
    matched_phrase: str | None = None,
    extra_kv: dict[str, str] | None = None,
) -> str:
    """Compose: headline + status table + recovery + one-shot footer.

    The headline always names the failed layer's rule via the keyword
    string `recovery_keyword` so downstream consumers (tests, agents
    skimming the block reason) can locate the failed discipline gate.
    """
    meta = next(m for m in LAYER_META if m["id"] == fail_layer_id)
    headline = (
        f"cc-enslaver · Stop check FAILED at Layer {fail_layer_id} "
        f"[{meta['label']}]"
    )
    table = _render_status_table(fail_layer_id, edit_turn)
    parts: list[str] = [headline, "", table, ""]
    if matched_phrase is not None:
        parts.append(f"Done-claim matched: {matched_phrase!r}")
    if extra_kv:
        for k, v in extra_kv.items():
            parts.append(f"{k}: {v}")
    if matched_phrase is not None or extra_kv:
        parts.append("")
    parts.append(f"[Recovery — {meta['recovery_keyword']}]")
    parts.append(recovery.rstrip())
    parts.append("")
    parts.append(_ONE_SHOT_FOOTER)
    return "\n".join(parts) + "\n"


# --------------------------------------------------------------------------- #
# Per-layer recovery blurbs. Short, actionable; the long-form rule docs
# live in rules/*.md (and the headline + status table link the agent there
# implicitly via the rule number).
# --------------------------------------------------------------------------- #
_RECOVERY_A = """Your reply claims completion but the message contains no
convergence evidence — no `$ ` shell prompt, no test counts, no
"重触发原症状" demonstration, no fenced output block.

Per rule 06 (rules/06-verify-convergence.md), surface either:
  • The original failing command + its now-passing output, or
  • A `pytest` / `unittest` / `npm test` run with counts, or
  • An explicit 重触发 / boundary / negative-case write-up.

If you actually verified mentally but skipped writing it down, write
it down now with the concrete commands + outputs."""

_RECOVERY_B = """Your reply pairs a completion claim with hedged language
within ~50 characters. Per rule 01 (rules/01-verify-dont-guess.md),
confident verification cannot coexist with "我觉得 / I think /
probably / maybe / 应该是" near the done-claim.

Pick one:
  • Drop the hedge and state the result with concrete output, or
  • Drop the done-claim and say explicitly "尚未确认 / not yet
    verified" so the user decides whether to ship.

A hedge marker is not a rhetorical flourish — it signals you are not
sure. If you are sure, write so; if you are not, say so."""

_RECOVERY_C = """Your reply has evidence but does not surface the rule-06
self-quiz. Pass condition is either:

  (a) an explicit marker — `rule 06`, `自答`, `收敛`, `重触发`,
      `边界用例`, `反向用例`, `convergence`, `self-quiz`; OR
  (b) ≥ 2 of the 4 self-quiz questions:
        1. 真解决?  Specific evidence, not just "no error"
        2. 更好方案?  Compared with alternatives
        3. 哪些没验?  Explicitly enumerate what wasn't tested
        4. 验证合理?  Verification exercises the root-cause chain

Tests passing alone is not convergence. Surface the self-quiz now."""

_RECOVERY_D = """You passed rule-06 convergence on the part you edited, but
your reply does not surface rule-07 task fidelity (a different axis:
"did I deliver everything the user asked for, at the standard
requested?").

Pass condition is either:
  (a) an explicit marker — `rule 07`, `任务忠实`, `请求覆盖`,
      `原始请求`, `无降级`, `无遗漏`, `task fidelity`,
      `request coverage`, `no degradation`, `no omission`,
      `no scope creep`, `covered all`, `all requested`; OR
  (b) ≥ 2 of 3 fidelity questions:
        1. 覆盖性 — decompose original request, list which sub-items
           you did vs. didn't and why
        2. 标准性 — for each modifier word (强制 / 必须 / 完整 /
           严格 / 所有 / mandatory / strict / all): did it land
           as a hard action or stay soft doc?
        3. 忠实性 — any concept swap / scope creep / buried TODO?

Re-read the user's *original* message, not your in-flight restatement."""

_RECOVERY_E = """You modified a file this turn but did not surface the
rule-08 (read-before-edit / think-before-write) closing markers.

Pass condition is either:
  (a) an explicit marker — `rule 08`, `改前必读`, `写前必想`,
      `read-before-edit`, `think-before-write`, `系统式自答`; OR
  (b) ≥ 3 of 6 rule-02 keywords:
        架构 / architecture
        职责 / responsibility
        根源 / 根因 / root cause
        方案 / solution
        连带 / 影响 / downstream / impact
        风险 / 不变量 / invariant / risk

If you did the rule-08 work in chain-of-thought but didn't surface it
in the final reply, surface it now."""

_RECOVERY_F = """You modified a file this turn but did not surface the
rule-09 systematic-modification triplet (root cause + impact + solution).

Pass condition is either:
  (a) an explicit marker — `rule 09`, `系统式修改`, `打补丁`,
      `systematic modification`, `patch-style`, `反补丁`,
      `non-patch`, `root cause`; OR
  (b) **all three** of the triplet keywords in the same reply:
        • 根源 / 根因 / root cause
        • 连带 / 影响范围 / impact / blast radius / downstream
        • 方案 / solution / approach / alternative

If the edit was actually patch-style (one local suppression, no impact
analysis, no alternative considered), redo it systematically or flag
the half-finish to the user."""


def _emit_block(reason_text: str) -> None:
    """Write a `decision: block` response and exit 0.

    Stop hook output uses top-level `decision`/`reason`, NOT the
    `hookSpecificOutput` envelope used by PreToolUse.
    """
    payload = {"decision": "block", "reason": reason_text}
    encoded = (json.dumps(payload, ensure_ascii=False) + "\n").encode("utf-8")
    sys.stdout.buffer.write(encoded)
    sys.stdout.buffer.flush()


# --------------------------------------------------------------------------- #
# Transcript fallback.
#
# The Stop payload normally includes `assistant_message`. If a future
# version of Claude Code drops that field (or if our payload-shape
# assumption is wrong), we fall back to reading the last assistant
# entry from `transcript_path` (a JSONL file).
# --------------------------------------------------------------------------- #
def _last_assistant_message_from_transcript(transcript_path: str) -> str:
    p = Path(transcript_path)
    if not p.is_file():
        return ""
    try:
        # Read the last few lines; the last assistant message will be
        # near the end. We read the whole file because JSONL lines can
        # be long and a tail-based approach is fiddlier.
        text = p.read_text(encoding="utf-8")
    except OSError:
        return ""
    last_assistant = ""
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        # Common transcript schemas use 'role' or 'type'; tolerate either.
        role = entry.get("role") or entry.get("type") or ""
        if role != "assistant":
            continue
        # Claude Code 2.x JSONL schema nests content under
        # entry["message"]["content"]; older / generic schemas place
        # it at the top level entry["content"]. Read the nested one
        # first, fall back to top level. v0.9.1 fixed two related
        # silent-failure bugs:
        #   (1) Reading only top-level entry["content"] missed every
        #       Claude Code 2.x transcript (nested schema), making the
        #       whole Stop hook a no-op for releases v0.6.0..v0.9.0.
        #   (2) Overwriting last_assistant on EVERY assistant entry
        #       (including pure tool_use entries with no text blocks)
        #       wiped out the actual text reply when the final
        #       assistant entry of the turn was a tool call. We now
        #       only update when the entry yields non-empty text, so
        #       the most recent text-bearing reply wins.
        content = entry.get("message", {}).get("content")
        if content is None:
            content = entry.get("content")
        extracted = ""
        if isinstance(content, list):
            # content array of mixed {type, text} / {type, tool_use} / etc.
            parts = []
            for block in content:
                if isinstance(block, dict) and block.get("type") == "text":
                    t = block.get("text", "")
                    if t:
                        parts.append(t)
            extracted = "\n".join(parts)
        elif isinstance(content, str):
            extracted = content
        if extracted:
            last_assistant = extracted
    return last_assistant


# --------------------------------------------------------------------------- #
# Entry point.
# --------------------------------------------------------------------------- #
def main() -> int:
    try:
        raw = sys.stdin.read()
        if not raw.strip():
            return 0  # nothing to inspect, fail open
        payload = json.loads(raw)
        if payload.get("hook_event_name") != "Stop":
            return 0  # SubagentStop and others: no-op

        session_id = payload.get("session_id") or "default"
        turn_count = payload.get("turn_count")

        # One-shot guard: if we just blocked, allow this Stop unconditionally.
        if state_lib.was_just_blocked(session_id, turn_count):
            return 0

        # Get the message text, preferring the direct payload field.
        message = payload.get("assistant_message") or ""
        if not message and payload.get("transcript_path"):
            message = _last_assistant_message_from_transcript(
                payload["transcript_path"]
            )
        if not message:
            return 0  # nothing to inspect

        matched = _has_done_claim(message)
        if matched is None:
            return 0  # no done-claim → don't block

        # Compute edit-turn status up front: layer (e)/(f) applicability
        # AND the status-table rendering both need it. Cheap (one disk
        # read) and avoids drift between "did this layer fire?" and "did
        # the table render it as n/a?".
        edited_this_turn = state_lib.did_edit_this_turn(
            session_id, turn_count,
        )

        # v0.7.0 layered check (b): hedged completion (rule 01).
        # Even if evidence is present, hedging undermines the claim — block.
        hedge_pair = _has_hedge_near_done(message)
        if hedge_pair is not None:
            state_lib.record_stop_block(session_id, turn_count)
            hedge_phrase = (
                hedge_pair[0]
                if hedge_pair[1] == matched or matched in hedge_pair[1]
                else hedge_pair[1]
            )
            _emit_block(_build_block_reason(
                "(b)", edited_this_turn,
                _RECOVERY_B,
                matched_phrase=matched,
                extra_kv={"Hedge matched": repr(hedge_phrase)},
            ))
            return 0

        # v0.6.0 base layer (a): no evidence at all.
        if not _has_evidence(message):
            state_lib.record_stop_block(session_id, turn_count)
            _emit_block(_build_block_reason(
                "(a)", edited_this_turn,
                _RECOVERY_A,
                matched_phrase=matched,
            ))
            return 0

        # v0.7.0 deep layer (c): evidence present but rule-06 self-quiz
        # neither named nor answered (>=2 of 4 questions).
        if not _has_self_quiz_or_marker(message):
            state_lib.record_stop_block(session_id, turn_count)
            _emit_block(_build_block_reason(
                "(c)", edited_this_turn,
                _RECOVERY_C,
                matched_phrase=matched,
            ))
            return 0

        # v0.8.0 fidelity layer (d): rule-06 convergence shown, but the
        # message does not surface a rule-07 fidelity marker or quiz.
        # Different axis from (c): coverage / standard / no-degrade
        # versus root-cause / re-trigger / boundary.
        if not _has_fidelity_marker_or_quiz(message):
            state_lib.record_stop_block(session_id, turn_count)
            _emit_block(_build_block_reason(
                "(d)", edited_this_turn,
                _RECOVERY_D,
                matched_phrase=matched,
            ))
            return 0

        # v0.11.0 layers (e) + (f): rule-08 / rule-09 closing checks
        # **only fire on turns that actually edited a file**. A pure
        # analysis / answer turn shouldn't be forced to surface
        # think-before-write or root-cause/impact/solution markers —
        # there was nothing modified for those to apply to.
        if edited_this_turn:
            # Layer (e): rule 08 — read-before-edit / think-before-write
            # closing marker. Pass if either an explicit rule-08 marker
            # OR ≥ 3 of six rule-02 keywords are present.
            if not _has_rule08_marker_or_keywords(message):
                state_lib.record_stop_block(session_id, turn_count)
                _emit_block(_build_block_reason(
                    "(e)", edited_this_turn,
                    _RECOVERY_E,
                    matched_phrase=matched,
                ))
                return 0

            # Layer (f): rule 09 — systematic-modification triplet.
            # Pass if either an explicit rule-09 marker OR all three of
            # (root-cause + impact + solution) keywords are present.
            if not _has_rule09_marker_or_triplet(message):
                state_lib.record_stop_block(session_id, turn_count)
                _emit_block(_build_block_reason(
                    "(f)", edited_this_turn,
                    _RECOVERY_F,
                    matched_phrase=matched,
                ))
                return 0

        # All six gates passed — allow.
    except Exception:
        # Failing open: log to stderr but never block by accident.
        sys.stderr.write("[cc-enslaver] stop_guard exception:\n")
        sys.stderr.write(traceback.format_exc())
    return 0


if __name__ == "__main__":
    sys.exit(main())
