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
# Block reason templates.
#
# Three distinct templates so the agent sees exactly which discipline
# layer failed:
#   NO_EVIDENCE:    rule 06 base layer (v0.6.0).
#   HEDGED_DONE:    rule 01 cross-enforcement at Stop (v0.7.0).
#   MISSING_QUIZ:   rule 06 deep layer — 4-question self-quiz (v0.7.0).
# --------------------------------------------------------------------------- #
NO_EVIDENCE_REASON = """cc-enslaver · rule 06 enforcement (Stop hook)

You appear to be claiming completion ({matched_phrase!r}) but your
message contains no convergence evidence — no shell command output,
no test results, no "重触发原症状" demonstration, no quantitative
comparison.

Per rule 06 (rules/06-verify-convergence.md), before declaring done
you must:

  1. 重触发原症状 — Re-run the exact failing input and show output.
  2. 边界 + 反向用例 — Cover at least 1 edge + 1 negative case.
  3. 连带不破坏 — Run the relevant test/lint/typecheck pass.
  4. 自答 4 题 — Is it really solved? Is there a better solution?
                 Which changes are unverified? Is the verification
                 actually meaningful?
  5. 量化优于定性 — For perf/race/compat: numbers, repeat counts,
                    matrix outputs.

Continue your response with the actual verification evidence. If you
have already done the verification mentally but did not include it in
the message, repeat with the concrete commands and outputs.

(One-shot guard: this is the only time you'll be blocked for this
sequence. The next Stop will be allowed even if evidence is still
weak. Use the next turn well.)
"""

HEDGED_DONE_REASON = """cc-enslaver · rule 01 + 06 enforcement (Stop hook)

Your message contains a completion claim ({done_phrase!r}) in
proximity to a hedge ({hedge_phrase!r}). Per rule 01
(rules/01-verify-dont-guess.md), confident verification cannot
coexist with hedged language — pick one:

  - If you have actual evidence: drop the hedge and state the result
    directly with command output.
  - If you are uncertain: drop the completion claim and say
    explicitly "尚未确认 / not yet verified" so the user can decide
    whether to ship as-is.

"我觉得修好了 / I think it's fixed / probably done / 应该是修好了"
are not acceptable forms — either you verified it or you didn't.

(One-shot guard: this is the only time you'll be blocked for this
sequence. The next Stop will be allowed even if hedging persists.)
"""

MISSING_QUIZ_REASON = """cc-enslaver · rule 06 deep enforcement (Stop hook v0.7)

Your message claims completion ({matched_phrase!r}) and shows some
evidence, but it does not surface either:

  (a) an explicit rule-06 marker (`rule 06`, `自答`, `收敛`,
      `重触发`, `边界用例`, `反向用例`, `convergence`, `self-quiz`), or
  (b) at least 2 of the 4 self-quiz questions:
        1. **真解决?** Is it really solved? (specific evidence,
           ruling out coincidence/cache/environment).
        2. **更好方案?** Is there a better approach? (compared on
           simplicity / performance / maintainability / fit).
        3. **哪些没验?** Which changes are unverified? Why don't
           they need to be?
        4. **验证合理?** Does the verification actually exercise
           the failure mechanism / cover the root-cause causal chain?

Tests passing alone is not convergence — the test inputs may not match
the user's input, and coverage gaps are common. Surface the self-quiz
explicitly. If you genuinely went through it but did not write it down,
write it down now.

(One-shot guard: this is the only time you'll be blocked for this
sequence. The next Stop will allow even with weak quiz coverage. Use
this turn well.)
"""

MISSING_RULE08_REASON = """cc-enslaver · rule 08 enforcement (Stop hook v0.11)

You modified a file this turn (Edit / Write was actually executed) and
are now claiming completion ({matched_phrase!r}). But your message did
not surface the rule-08 "read-before-edit / think-before-write"
closing markers.

Rule 08 collapses rule 04 (read fully) and rule 02 (seven questions)
into one pre-action hard discipline. The closing check is light: it
expects you to record, in chain-of-thought or final reply, **either**

  (a) an explicit rule-08 marker (`rule 08`, `改前必读`, `写前必想`,
      `read-before-edit`, `think-before-write`, `系统式自答`), or

  (b) at least 3 of the six rule-02 systematic-thinking keywords:
        架构 / architecture
        职责 / responsibility
        根源 / root cause
        方案 / solution
        连带 / impact / downstream
        风险 / invariant / risk

If you actually did the rule-08 work but did not write it down,
write it down now. If you skipped rule-08 (jumped to Edit without
Reading the call sites, or wrote new code without considering root
cause / impact / risk), surface what you skipped and either run the
missing pre-action step or alert the user.

(One-shot guard: this is the only time you'll be blocked for this
sequence. The next Stop will be allowed even if the rule-08 marker
is still missing. Use this turn well.)
"""

MISSING_RULE09_REASON = """cc-enslaver · rule 09 enforcement (Stop hook v0.11)

You modified a file this turn and are now claiming completion
({matched_phrase!r}). But your message did not surface the rule-09
"systematic modification, no patch-style" triplet markers.

Rule 09 demands that the modification be **systematic, not a local
patch**. The closing check is light: it expects, in chain-of-thought
or final reply, **either**

  (a) an explicit rule-09 marker (`rule 09`, `系统式修改`, `打补丁`,
      `systematic modification`, `patch-style`, `非补丁`, `反补丁`,
      `root cause`), or

  (b) **all three** of the triplet keywords:
        根源 / 根因 / root cause
        连带 / 影响范围 / impact / blast radius / downstream
        方案 / solution / approach / alternative

If you did the rule-09 work (rooted the cause, mapped impact,
compared at least 2 fix strategies), write the triplet down now.
If you didn't, your edit is likely patch-style; surface what is
incomplete and either redo the modification systematically or flag
the half-finish to the user.

(One-shot guard: this is the only time you'll be blocked for this
sequence. The next Stop will be allowed even if the rule-09 triplet
is still missing.)
"""

MISSING_FIDELITY_REASON = """cc-enslaver · rule 07 enforcement (Stop hook v0.8)

Your message claims completion ({matched_phrase!r}) and you have
already shown rule-06 convergence on the part you edited. But rule
07 covers a *different* axis — and your message did not surface it.

Rule 06 asks: "did the fix actually converge on what I edited?"
Rule 07 asks: "did I deliver everything the user asked for, at the
standard they requested, without scope creep or buried TODOs?"

A test suite cannot answer rule 07. Tests cover the code that exists;
they do not know about the sub-task you forgot to write, the
"mandatory" requirement you silently downgraded to a "soft suggestion"
in the docs, or the TODO you buried in line 200.

Surface either:

  (a) an explicit rule-07 marker (`rule 07`, `任务忠实`, `请求覆盖`,
      `原始请求`, `无降级`, `无遗漏`, `无超范围`, `task fidelity`,
      `request coverage`, `no degradation`, `no omission`,
      `no scope creep`, `covered all`, `all requested`), or

  (b) at least 2 of the 3 fidelity self-questions:

        1. **覆盖性 (coverage)** — Decompose the user's *original*
           message. How many sub-items? Which did you do? Which
           did you not do, and why?

        2. **标准性 (standard)** — Which modifier words did the user
           use ("强制 / 必须 / 完整 / 严格 / 所有 / 立即 / 全面",
           "mandatory / strict / comprehensive / all / every /
           immediate")? Did each one land as a verifiable hard action
           (hook / assertion / test) or did some end up as soft
           documentation only?

        3. **忠实性 (fidelity)** — Concept swap? (Did you ship a
           subset / approximation / something related to A but not
           A?) Scope creep? (Did you do refactors / abstractions
           the user did not ask for?) Buried TODOs / FIXMEs / "for
           now" / commented-out tests left while you said "done"?

Go back to the user's *original* message — not your in-flight
restatement of it — and reconcile what you shipped against what was
asked. If anything was omitted, downgraded, swapped, or buried,
surface it explicitly so the user can decide whether to ship.

(One-shot guard: this is the only time you'll be blocked for this
sequence. The next Stop will allow even with weak fidelity coverage.
Use this turn well.)
"""


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

        # v0.7.0 layered check (b): hedged completion (rule 01).
        # Even if evidence is present, hedging undermines the claim — block.
        hedge_pair = _has_hedge_near_done(message)
        if hedge_pair is not None:
            state_lib.record_stop_block(session_id, turn_count)
            _emit_block(HEDGED_DONE_REASON.format(
                done_phrase=matched,
                hedge_phrase=(
                    hedge_pair[0]
                    if hedge_pair[1] == matched or matched in hedge_pair[1]
                    else hedge_pair[1]
                ),
            ))
            return 0

        # v0.6.0 base layer (a): no evidence at all.
        if not _has_evidence(message):
            state_lib.record_stop_block(session_id, turn_count)
            _emit_block(NO_EVIDENCE_REASON.format(matched_phrase=matched))
            return 0

        # v0.7.0 deep layer (c): evidence present but rule-06 self-quiz
        # neither named nor answered (>=2 of 4 questions).
        if not _has_self_quiz_or_marker(message):
            state_lib.record_stop_block(session_id, turn_count)
            _emit_block(MISSING_QUIZ_REASON.format(matched_phrase=matched))
            return 0

        # v0.8.0 fidelity layer (d): rule-06 convergence shown, but the
        # message does not surface a rule-07 fidelity marker or quiz.
        # Different axis from (c): coverage / standard / no-degrade
        # versus root-cause / re-trigger / boundary.
        if not _has_fidelity_marker_or_quiz(message):
            state_lib.record_stop_block(session_id, turn_count)
            _emit_block(MISSING_FIDELITY_REASON.format(matched_phrase=matched))
            return 0

        # v0.11.0 layers (e) + (f): rule-08 / rule-09 closing checks
        # **only fire on turns that actually edited a file**. A pure
        # analysis / answer turn shouldn't be forced to surface
        # think-before-write or root-cause/impact/solution markers —
        # there was nothing modified for those to apply to.
        edited_this_turn = state_lib.did_edit_this_turn(
            session_id, turn_count,
        )
        if edited_this_turn:
            # Layer (e): rule 08 — read-before-edit / think-before-write
            # closing marker. Pass if either an explicit rule-08 marker
            # OR ≥ 3 of six rule-02 keywords are present.
            if not _has_rule08_marker_or_keywords(message):
                state_lib.record_stop_block(session_id, turn_count)
                _emit_block(MISSING_RULE08_REASON.format(matched_phrase=matched))
                return 0

            # Layer (f): rule 09 — systematic-modification triplet.
            # Pass if either an explicit rule-09 marker OR all three of
            # (root-cause + impact + solution) keywords are present.
            if not _has_rule09_marker_or_triplet(message):
                state_lib.record_stop_block(session_id, turn_count)
                _emit_block(MISSING_RULE09_REASON.format(matched_phrase=matched))
                return 0

        # All six gates passed — allow.
    except Exception:
        # Failing open: log to stderr but never block by accident.
        sys.stderr.write("[cc-enslaver] stop_guard exception:\n")
        sys.stderr.write(traceback.format_exc())
    return 0


if __name__ == "__main__":
    sys.exit(main())
