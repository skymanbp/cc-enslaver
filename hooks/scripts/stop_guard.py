#!/usr/bin/env python3
"""cc-enslaver — Stop hook enforcing rules 06 + 07 + 08 + 09 + TL;DR.

At every Stop event, this hook inspects the agent's last assistant
message and refuses to let the agent finish the turn when any of nine
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

  (g) [v0.16.0] File-claim verification (rule 01 + 06): parses
      "I edited X" / "我修改了 Y" claims and blocks when the on-disk
      mtime contradicts the claim. Edit-turn only.

  (h) [v0.20.0; length check v0.23.0] Plain-language TL;DR (大白话总结)
      closing requirement. Fires on EVERY done-claim turn (not just edit
      turns): the reply must surface a one-line takeaway via the
      canonical schema's `tldr:` field or a 大白话 / TL;DR marker.
      v0.23 adds a HARD LENGTH CAP: each tldr item (the marker line's
      value plus any continuation / list-item line) must stay within
      TLDR_MAX_ITEM_CHARS characters — one sentence covering cause,
      action, and outcome. Multiple items are fine (one per line, each
      within the cap); a paragraph-length "tldr" is not a TL;DR and
      blocks with a dedicated recovery. Enforced as a closing
      convention, deliberately not promoted to a numbered rule.

  (i) [v0.23.0 NEW] Rule 12 — repo-wide sync gate. Edit turns only, and
      only in projects that committed a co-update config at
      .claude/cc-enslaver/sync-gate.toml (per-project opt-in; see
      lib/sync_gate.py). For each configured group: if a file edited
      this session matches a `when` glob but no edited file matches any
      `require` glob, AND the reply carries no sync-acknowledgement
      marker (SYNC_MARKERS — e.g. `同步核对` / `sync-check` / `rule 12`),
      the Stop is blocked. The marker escape makes "checked the
      co-update set, nothing else needs changing" a legitimate,
      explicit outcome rather than a silent omission. Escaped groups
      are recorded per session (`sync_acked_groups`) so one explicit
      answer suffices — the cumulative edited-file set cannot re-block
      an already-acknowledged group on later unrelated edits.

When any of (a)-(i) hold, the hook returns
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

# Why layered checks instead of one

The bar tightens monotonically: each layer fires only if the preceding
one passed. (a) catches the laziest case (no work shown). (b) catches
sloppy completion (hedged language). (c) catches faked rule-06 evidence
(any `$ ls` output passes (a) but the agent must engage with the rule-06
self-quiz to pass (c)). (d) catches the different axis covered by rule 07
— even an agent who genuinely converged on the part it edited may have
silently dropped sub-tasks, downgraded "mandatory" to "soft", or buried
TODOs. Each gate has its own block template so the agent sees exactly
which discipline failed.

**Evaluation order is not display order.** The layers are *displayed*
alphabetically, (a)…(i), because that is how every doc and recovery
message names them. They are *evaluated* in `_EVAL_ORDER`, which puts (b)
first: a hedge invalidates a done-claim regardless of how much evidence
sits next to it, so there is no point grading the evidence first. The
status table renders Pass / pending from the EVALUATION position — an
earlier v0.12–v0.29 version used the display position and therefore
printed "(a) ✅ Pass" whenever (b) failed, asserting that evidence had
been found when `_has_evidence` had never been called.

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
import os
import re
import sys
import traceback
from pathlib import Path

# Make `lib/` importable when run as a script.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib import state as state_lib  # noqa: E402
# E402 is suppressed on every lib import below because they must follow
# the sys.path bootstrap above -- that is the stated reason, not laziness.
from lib import sync_gate as sync_gate_lib  # noqa: E402
# because the sys.path bootstrap above must run before this import
from lib import mdctx  # noqa: E402


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
    re.compile(r"已完成"),
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
    # v0.25.1 — wordings that were missing. This list is not cosmetic:
    # `_has_done_claim` gates EVERY one of the nine layers, so a
    # completion phrased outside it skipped the whole enforcement stack
    # and cleared the edit flag on the way out. `已完成。`,
    # `Implemented the fix`, `Finished the refactor` and `the migration
    # is complete` were all silently exempt.
    re.compile(r"\bimplemented\b", re.IGNORECASE),
    re.compile(r"\bfinished\b", re.IGNORECASE),
    # `is/are complete` rather than bare `complete`, which is far more
    # often an imperative ("complete the migration") than a claim.
    re.compile(r"\b(?:is|are|was|were)\s+complete\b", re.IGNORECASE),
    # v0.26.0 audit — the predicative form with the noun in front.
    # `Work complete. Ready to ship.` matched nothing, and a done-claim
    # that matches nothing skips ALL NINE layers and clears the edit flag.
    # Anchored to a small noun set so the imperative ("complete the
    # migration") still does not match.
    re.compile(
        r"\b(?:work|task|job|migration|refactor|refactoring|fix|fixes|"
        r"change|changes|update|updates|implementation|build|setup|"
        r"cleanup)\s+complete\b",
        re.IGNORECASE,
    ),
    re.compile(r"\bready\s+to\s+ship\b", re.IGNORECASE),
    # English — soft "should be done" phrasings (also red flags)
    # `\ball\s+set\b` — the old unbounded `all set` substring matched
    # inside "Not all settings are loaded".
    re.compile(r"\ball\s+set\b", re.IGNORECASE),
    re.compile(r"should\s+work\s+now", re.IGNORECASE),
    re.compile(r"that\s+should\s+do\s+it", re.IGNORECASE),
]

# Negators that invert a done-claim. `Not done; tests failed.` and
# `This is not fixed` are the OPPOSITE of a completion claim, but the
# bare keyword search treated them as one — so an honest report of
# failure could be blocked for lacking convergence evidence (v0.25.1).
#
# v0.26.0 — the v0.25.1 spelling required the negator to sit IMMEDIATELY
# before the claim (`[\s，,、]{0,4}$`), which three ordinary English
# negations do not:
#   * `not yet done`      — one intervening word
#   * `isn't done`        — `\bn't\b` can NEVER match: in "isn't" the
#                           character before `n` is `s`, so there is no
#                           word boundary. The alternative was dead code.
#   * `Nothing is done.`  — `nothing` was not a negator at all.
# The replacement models the actual question — "is this claim inside a
# negated clause?" — by cutting at the nearest clause boundary and
# allowing a few intervening words. The comma IS a clause boundary, which
# is what keeps `没有遗漏，已完成` ("no omissions, completed") a genuine
# claim rather than a negation.
# A dash introduces a new clause too — `no longer broken - fixed` negates
# "broken", not "fixed".
# v0.26.0 audit — Chinese CONNECTIVES are clause boundaries too. Chinese
# runs without spaces, so `_WORDISH` counts an entire unspaced clause as
# ONE word: `没有遗漏这部分工作所以这次已经完成了` ("nothing was omitted, so
# this time it IS done") put the negator within the gap budget and the
# genuine completion claim was suppressed. Splitting at 所以 / 但是 / …
# models the actual sentence structure instead of guessing at distance.
_CLAUSE_BOUNDARY = re.compile(
    r"[.!?;。！？；，,\n—–-]"
    r"|所以|因此|因而|于是|於是|但是|但|不过|不過|然而|可是"
)
_NEGATION_WORD = re.compile(
    r"\bnot\b|\bno\b|\bnone\b|\bnever\b|\bnothing\b|\bwithout\b|\bfail\w*\b"
    r"|\bcannot\b|\bunable\b"
    # Degree-negations that deny completion without a plain negator.
    # `I am far from done` read as a completion claim and was BLOCKED for
    # lacking evidence — the damaging direction this function exists to
    # avoid.
    r"|\bfar\s+from\b|\bhardly\b|\bbarely\b|\bnowhere\s+near\b|\bshort\s+of\b"
    r"|n['’]t\b|没有|没|尚未|未|不|无法|尚待|還沒|还没|并非|並非|绝非|絕非|非|未能",
    re.IGNORECASE,
)
_WORDISH = re.compile(r"[A-Za-z0-9一-鿿]+")
# How many words may sit between the negator and the claim it negates.
_MAX_NEGATION_GAP_WORDS = 3

# Double negatives are AFFIRMATIVE: `不得不承认已完成` ("cannot but admit it
# is done") is a completion claim, not a denial of one.
_DOUBLE_NEGATIVE = re.compile(r"不得不|不能不|无不|無不|莫不|不无|不會不|不会不")

# Constructions where the negator scopes something else entirely, so the
# claim after it is NOT negated: `not only fixed but tested`.
_NON_SCOPING_AFTER = re.compile(r"^\s*(?:only|just|merely|simply)\b",
                                re.IGNORECASE)


def _is_negated(text: str, claim_start: int) -> bool:
    """True when the done-claim at `claim_start` sits in a negated clause.

    Deliberately biased: a MISSED negation blocks an honest "it is not
    done" report, which is the damaging direction, so the negator list errs
    wide. A spurious negation merely lets a turn through unchecked.
    """
    preceding = text[max(0, claim_start - 80):claim_start]
    clause = _CLAUSE_BOUNDARY.split(preceding)[-1]
    # A double negative is affirmative only when it is the LAST negation
    # before the claim. `不得不说明任务还没完成了` ("I must explain the task
    # is still NOT done") contains 不得不, but 还没 sits closer to the claim
    # and is the one that scopes it. The old clause-wide `search` returned
    # affirmative immediately and blocked an honest not-done report.
    dn = None
    for m in _DOUBLE_NEGATIVE.finditer(clause):
        dn = m
    last = None
    for m in _NEGATION_WORD.finditer(clause):
        # 不得不 itself contains 不; those matches are the double negative,
        # not an independent negation.
        if dn is not None and m.start() < dn.end():
            continue
        last = m
    if last is None:
        return False
    tail = clause[last.end():]
    if _NON_SCOPING_AFTER.match(tail):
        return False
    gap = _WORDISH.findall(tail)
    return len(gap) <= _MAX_NEGATION_GAP_WORDS

EVIDENCE_PATTERNS = [
    # Shell prompts and command-output markers
    re.compile(r"^\s*\$\s+\S", re.MULTILINE),
    re.compile(r"^\s*>\s+\S", re.MULTILINE),
    # Windows shells (v0.25.1). This plugin's primary platform emits
    # `PS C:\repo>` / `C:\repo>` transcripts, none of which matched the
    # POSIX-only prompt patterns above — so a Windows user pasting a real
    # command transcript could still be blocked by layer (a) for having
    # "no evidence".
    re.compile(r"^\s*PS\s+[A-Za-z]:[^\n>]*>\s*\S", re.MULTILINE),
    re.compile(r"^\s*[A-Za-z]:\\[^\n>]*>\s*\S", re.MULTILINE),
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
    """Return the matched done-claim phrase, or None.

    v0.25.1 — a match immediately preceded by a negator is skipped and
    the scan continues, so `Not done; tests failed.` no longer reads as
    a completion claim while `Fixed, and the earlier attempt was not
    done properly.` still does (the later, unnegated match wins).
    """
    for p in DONE_PATTERNS:
        for m in p.finditer(text):
            if _is_negated(text, m.start()):
                continue
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
# v0.20.0 — Layer (h): plain-language TL;DR (大白话总结) closing requirement.
#
# Motivation: the conversation between the agent and the human reading over
# its shoulder was "not standardised enough" — the reply skeleton drifts in
# shape turn to turn. v0.20 introduces a canonical YAML reply schema whose
# field names ARE the existing detection markers (so layers a-g need zero
# regex changes), and adds this layer (h) to HARD-enforce the schema's final
# `tldr:` field — one plain-language sentence summarising what happened.
#
# Unlike (e)/(f)/(g), layer (h) fires on EVERY done-claim turn (not just edit
# turns): a status report or an answer that claims "done" benefits from a
# one-line takeaway just as much as a code edit does. It is the last gate in
# the sequence, so by the time we reach it the agent has already passed all
# discipline checks — (h) is purely about leaving the reader a readable
# summary.
#
# It is enforced as a closing *convention* (a Stop layer), deliberately NOT
# promoted to a tenth numbered rule, to avoid the rules/*.md + rules/zh/ +
# 00-index + docs fan-out that a real rule would require.
# --------------------------------------------------------------------------- #
TLDR_MARKERS = [
    re.compile(r"\btl;?dr\b", re.IGNORECASE),
    re.compile(r"大白话"),
    re.compile(r"一句话(?:总结|讲|说清|概括)"),
    re.compile(r"一句总结"),
    # The canonical YAML schema field key.
    re.compile(r"\btldr\s*[:：]"),
]


def _has_tldr(text: str) -> bool:
    """v0.20 — True if the reply surfaces a plain-language TL;DR.

    Satisfied by the canonical YAML `tldr:` field, or any of the natural
    markers (大白话 / 一句话总结 / TL;DR). Permissive on phrasing: the goal
    is a readable one-line takeaway, not a specific keyword.

    v0.25.1 — the marker must actually introduce CONTENT, and must be the
    agent's own. A bare `tldr:`, a `tldr: ""`, or a blockquoted
    `> tldr: …` (quoting someone else) used to satisfy layer (h) outright:
    the presence test looked for the keyword anywhere in the reply, while
    the LENGTH test then measured nothing, so the emptiest possible
    "summary" sailed through both halves of the gate.

    v0.26.0 — the presence half and the LENGTH half of layer (h) now read
    the same context model (`lib/mdctx`). They previously disagreed, which
    is what let the emptiest summaries through:

      * `_tldr_items` measured only the canonical ```yaml block, while
        this check accepted a `tldr:` marker inside ANY fence — so
        quoting the schema in a ```text example satisfied the gate and
        the length half then had nothing to measure.
      * A blockquote was recognised only as a leading `>`, so `- > tldr:`
        (a quote nested in a list item) read as the agent's own line.
      * `rest` merely had to be non-empty, so `tldr: !!!` passed.
    """
    ctx = mdctx.lines(text)
    for i, line in enumerate(ctx):
        # PRESENCE uses the generous verdict (v0.27.0). The measurement
        # half below still uses `countable`. A tldr written directly under
        # a blockquote is inside that quote per CommonMark — not safe to
        # MEASURE, but plainly the agent's own sentence, and blocking it
        # for a "missing" summary the author can see is the worse error.
        if not line.attributable:
            continue
        for p in TLDR_MARKERS:
            m = p.search(line.raw)
            if not m:
                continue
            rest = line.raw[m.end():].lstrip(" \t:：|>-").strip().strip("'\"")
            if mdctx.has_substance(rest):
                return True
            # Value-less marker: accept only when real content follows.
            for nxt in ctx[i + 1:]:
                if nxt.is_fence_delim:
                    break
                if not nxt.raw.strip():
                    continue
                if not nxt.attributable:
                    break
                cand = nxt.raw.strip().strip("-*• \t").strip().strip("'\"")
                if mdctx.has_substance(cand):
                    return True
                break
    return False


# --------------------------------------------------------------------------- #
# v0.23.0 — TL;DR length cap (layer (h) part 2).
#
# Field failure that motivated this: the schema's `tldr` field kept
# growing into a paragraph, defeating its purpose. The contract is now:
# each tldr ITEM is one sentence — cause, action, outcome — within
# TLDR_MAX_ITEM_CHARS characters. Reporting several things is fine:
# one item per line (YAML list items or continuation lines), each within
# the cap. The cap is generous on purpose (a full English sentence fits;
# a Chinese sentence is far shorter) so only genuine paragraphs trip it
# — the repo's "prefer false negatives" detector philosophy.
#
# Extraction is line-based and conservative: only lines attributable to
# a tldr marker are measured. Measurable forms (v0.23.1 hardened after
# adversarial review):
#   - `tldr: value` / `大白话: value` / `TL;DR: value`, with optional
#     list (`- `) or ATX-heading (`## `) prefix and optional emphasis
#     wrappers (`**tldr:**`, `**tldr**:`).
#   - Continuation / list items under a value-less `tldr:` line: lines
#     that are more-indented than the marker's prefix, or `- ` list
#     items at the same indent (the legal YAML block-sequence form).
#   - A colon-less heading (`## TL;DR`): the first following paragraph
#     is measured line-by-line.
# NOT measured (failing open, deliberately):
#   - Blockquoted lines (`> tldr: ...`) — usually quoting someone else.
#   - Content inside non-YAML code fences — usually a fixture/example.
#     The canonical reply schema lives in a ```yaml fence, so yaml/yml
#     fences REMAIN measurable.
#   - Continuations under a marker line that already carried a value
#     when they are sibling/nested list items (a nested markdown list
#     under a short 大白话 bullet is detail, not more tldr).
# A YAML block scalar (`tldr: |`) is measured per physical line, which
# matches the "one item per line" reporting convention.
# --------------------------------------------------------------------------- #
TLDR_MAX_ITEM_CHARS = 160

_TLDR_ITEM_LINE = re.compile(
    r"^(?P<prefix>[ \t]*(?:(?:[*+-]|#{1,6})[ \t]+)?)"
    r"[*_`]{0,3}(?:tldr|大白话|一句话总结|一句总结|TL;?DR)[*_`]{0,3}"
    r"[ \t]*[:：](?P<rest>.*)$",
    re.IGNORECASE,
)

# Colon-less heading form: `## TL;DR` alone on a line; the following
# paragraph is the tldr content.
_TLDR_HEADING_LINE = re.compile(
    r"^[ \t]*#{1,6}[ \t]+[*_`]{0,3}(?:tldr|大白话|一句话总结|一句总结|TL;?DR)"
    r"[*_`]{0,3}[ \t]*$",
    re.IGNORECASE,
)

_YAML_BLOCK_SCALAR_INDICATORS = {"|", "|-", "|+", ">", ">-", ">+"}

_LIST_PREFIXES = ("- ", "* ", "+ ")


def _strip_item_decorations(s: str) -> str:
    """Trim whitespace, list dashes, emphasis marks, and quotes."""
    s = s.strip()
    while s[:2] in _LIST_PREFIXES:
        s = s[2:].strip()
    s = s.strip("*_`").strip()
    if len(s) >= 2 and s[0] == s[-1] and s[0] in ("'", '"'):
        s = s[1:-1].strip()
    return s


def _is_fence(stripped_line: str) -> bool:
    """True when the line opens or closes a fenced code block.

    v0.30 — the fence-run helper this used to carry privately is gone;
    `mdctx.fence_marker` is the one definition, and this module already
    consumes `mdctx` for the rest of layer (h)'s context model. Three
    byte-identical copies existed (here, in `lib/mdctx`, and in
    `i18n_check`), each with its own comment explaining the same v0.25
    CommonMark fix — which is precisely the shape that drifts: whoever
    corrects one has no reason to suspect the other two.
    """
    return mdctx.fence_marker(stripped_line) is not None


def _tldr_items(text: str) -> list[str]:
    """Collect every measurable tldr item from `text` (see note above)."""
    items: list[str] = []
    lines = text.splitlines()
    # v0.26.0 — fence / blockquote state comes from the shared context
    # model, the same one `_has_tldr` consumes. The two halves of layer
    # (h) each used to carry their own partial copy of this judgement and
    # disagreed about which fences count and what a blockquote looks like.
    ctx = mdctx.lines(text)
    n = len(lines)
    idx = 0

    def _collect_paragraph(start: int) -> int:
        """Measure the first paragraph at/after `start`; return next idx."""
        j = start
        while j < n and not lines[j].strip():
            j += 1
        while j < n:
            s = lines[j].strip()
            if not s or _is_fence(s) or s.startswith("#"):
                break
            # Continuation lines are subject to the SAME attribution test
            # as the marker line. Checking it only on the marker was the
            # disagreement bug one level down: a blockquoted continuation
            # (`  > …`) was measured as the agent's own tldr and blocked
            # the reply for a length the agent did not write.
            if not ctx[j].countable:
                break
            items.append(_strip_item_decorations(s))
            j += 1
        return j

    while idx < n:
        line = lines[idx]
        # Fence delimiters, blockquoted lines and the bodies of
        # non-canonical fences are all "not the agent's own assertion" —
        # one predicate, evaluated once, in mdctx.
        if not ctx[idx].countable:
            idx += 1
            continue
        m = _TLDR_ITEM_LINE.match(line)
        heading = _TLDR_HEADING_LINE.match(line) if m is None else None
        if m is None and heading is None:
            idx += 1
            continue
        if m is not None:
            base = len(m.group("prefix"))
            rest = m.group("rest").strip()
            rest_empty = (
                not rest
                or rest in _YAML_BLOCK_SCALAR_INDICATORS
                or not rest.strip("*_`").strip()
            )
            if rest_empty and "#" in m.group("prefix"):
                # `## TL;DR:` — a value-less HEADING marker. The content
                # is the following paragraph, exactly like the colon-less
                # heading form (an indent-based continuation scan would
                # never collect it: body text sits at indent 0).
                idx = _collect_paragraph(idx + 1)
                continue
            if not rest_empty:
                items.append(_strip_item_decorations(rest))
            j = idx + 1
            while j < n:
                nxt = lines[j]
                s = nxt.strip()
                if not s or _is_fence(s):
                    break
                nxt_indent = len(nxt) - len(nxt.lstrip(" \t"))
                is_list = s[:2] in _LIST_PREFIXES
                # Deeper-indented lines continue the value; same-indent
                # list items only continue a VALUE-LESS marker (the YAML
                # block-sequence form). A nested list under a marker
                # line that already carried its sentence is detail, not
                # more tldr — `base` includes the marker line's list
                # prefix, so such nested items compare <= base and stop.
                if not ctx[j].countable:
                    # Same attribution test as the marker line — see the
                    # note in `_collect_paragraph`.
                    break
                if nxt_indent > base or (
                    is_list and nxt_indent >= base and rest_empty
                ):
                    items.append(_strip_item_decorations(s))
                    j += 1
                    continue
                break
            idx = j
            continue
        # Colon-less heading form: measure the first paragraph after it.
        idx = _collect_paragraph(idx + 1)
    return items


def _find_overlong_tldr(text: str) -> tuple[str, int] | None:
    """Return (snippet, length) for the first over-cap tldr item, else None."""
    for item in _tldr_items(text):
        if len(item) > TLDR_MAX_ITEM_CHARS:
            snippet = item if len(item) <= 120 else item[:117] + "..."
            return snippet, len(item)
    return None


# --------------------------------------------------------------------------- #
# v0.23.0 — Layer (i): rule 12 (repo-wide sync gate) marker escape.
#
# A single marker suffices to pass layer (i) even when a configured
# co-update group is unmet: the agent explicitly acknowledging the sync
# check ("checked the co-update set; the require side needs no change
# because ...") is a legitimate outcome — the gate forces the check to
# be SAID, not the files to be touched unconditionally.
# --------------------------------------------------------------------------- #
# NOTE: `sync-gate` is deliberately NOT a marker — it is the config
# file's NAME, so any reply merely mentioning `sync-gate.toml` would
# pass the gate without making any claim. Markers must be claim-shaped.
SYNC_MARKERS = [
    re.compile(r"\brule\s*12\b", re.IGNORECASE),
    re.compile(r"全库同步"),
    re.compile(r"同步核对"),
    re.compile(r"连带核对"),
    re.compile(r"repo[\s-]?wide\s+sync", re.IGNORECASE),
    re.compile(r"sync[\s-]?check", re.IGNORECASE),
]


# Values that occupy the slot without answering it. Kept to the shapes that
# are unambiguously non-answers — a bare negation or placeholder — because
# this list is the only place where a HUMAN-legible sweep report can be
# refused, and over-reaching here costs a turn on an honest reply.
#
# Deliberately NOT attempted: judging whether prose says anything real.
# `同步核对: 核对过了` ("checked it") is just as empty and still passes. This
# closes the bottom tier only, which is what it claims to close.
_SYNC_NON_ANSWERS = {
    "n/a", "na", "none", "nil", "no", "nope", "skip", "todo", "tbd", "-", "--",
    "无", "没有", "不用", "不需要", "略", "暂无",
}


def _sync_value_answers(value: str) -> bool:
    """True when `value` carries an actual answer rather than a placeholder."""
    cleaned = value.strip().strip("'\"`*_ \t").rstrip("。.！!；;，,")
    if cleaned.lower() in _SYNC_NON_ANSWERS:
        return False
    return mdctx.has_substance(cleaned)


def _has_sync_marker(text: str) -> bool:
    """True when the reply carries a sync acknowledgement that says something.

    v0.32 — presence alone no longer suffices. Until now this was
    `any(pattern.search(text))`, so `sync-check: n/a` settled a group as
    firmly as a real sweep report, and — because the marker was searched
    over the RAW text — so did quoting someone else's inside a fenced
    example.

    Two changes, both mirroring what layer (h) already does for `tldr`:

      * **Attribution.** Lines are read through `lib/mdctx`, the same model
        both halves of layer (h) consume, so a marker inside a non-canonical
        fence or a blockquote is illustrative text rather than the agent's
        own claim. One judgement, one implementation — the alternative is
        how layer (h)'s two halves came to disagree in the first place.
      * **Substance.** The marker must introduce content: on its own line,
        or on the next non-blank line when the value is empty. A bare
        placeholder (`n/a` / `无` / `-`) is treated as absent.

    This is a deliberate strictness increase, decided by the user on
    2026-08-17 after v0.31.1 recorded the gap rather than closing it. It is
    NOT a claim to detect vacuous prose — see `_SYNC_NON_ANSWERS`.
    """
    ctx = mdctx.lines(text)
    for i, line in enumerate(ctx):
        if not line.attributable:
            continue
        for pattern in SYNC_MARKERS:
            m = pattern.search(line.raw)
            if m is None:
                continue
            rest = line.raw[m.end():].lstrip(" \t:：|>-").strip()
            if _sync_value_answers(rest):
                return True
            if rest.strip(" \t:：'\"") and not _sync_value_answers(rest):
                # An explicit non-answer: do not fall through to the next
                # line, or `sync-check: n/a` followed by unrelated prose
                # would pass on that prose.
                continue
            for nxt in ctx[i + 1:]:
                if nxt.is_fence_delim:
                    break
                if not nxt.raw.strip():
                    continue
                if not nxt.attributable:
                    break
                if _sync_value_answers(nxt.raw.strip().strip("-*• \t")):
                    return True
                break
    return False


def _pending_sync_violations(
    session_id: str, cwd: str | None,
) -> list:
    """Sync-gate violations not yet acknowledged this session.

    Shared by layer (i) and the one-shot grace path (v0.24): both need
    "which violated groups has the agent NOT answered yet", filtered
    against the session's `sync_acked_groups`.
    """
    violations = sync_gate_lib.evaluate(
        state_lib.get_edited_files(session_id), cwd,
    )
    if not violations:
        return []
    acked = set(state_lib.get_sync_acked_groups(session_id))
    return [v for v in violations if v.group.name not in acked]


def _ack_pending_sync_groups(session_id: str, cwd: str | None) -> None:
    """Acknowledge the groups the prior layer-(i) block actually presented.

    Called when a recovery reply carries a sync marker. v0.24 fix: the
    one-shot grace path used to return BEFORE the message was even read,
    so a recovery reply that answered a layer-(i) block with a `同步核对:`
    marker never had its acknowledgement persisted — and the same group
    re-blocked the next post-grace edit turn, breaking the "one explicit
    answer per group per session" contract the ack exists to provide.

    v0.25.1 — scoped to the BLOCKED group set rather than "everything
    pending now". A recovery turn is still an editing turn: if it touched
    files that violate a DIFFERENT group, that group became pending after
    the block, was never shown to the agent, and was never answered — yet
    the old code acknowledged it anyway, silencing it for the rest of the
    session. Falls back to the pending set when no group list was
    recorded (a block from before this field existed).
    """
    pending = _pending_sync_violations(session_id, cwd)
    if not pending:
        return
    presented = set(state_lib.get_last_blocked_groups(session_id))
    names = [v.group.name for v in pending]
    if presented:
        names = [n for n in names if n in presented]
    if names:
        state_lib.ack_sync_groups(session_id, names)


# --------------------------------------------------------------------------- #
# v0.16.0 — Layer (g): file-claim verification (rule 01 + 06).
#
# Detects "I edited X" / "I created Y" / "我修改了 Z" claims in the
# agent's final message and verifies them against state.baseline_mtimes
# captured by read_guard. If the on-disk evidence definitively
# contradicts a claim (file exists in baseline AND current mtime ==
# baseline mtime AND claim says "edited"; OR file did NOT exist in
# baseline AND still does not exist AND claim says "created") → BLOCK.
#
# Conservative-by-design: false-negatives (missed lies) preferred over
# false-positives (blocking honest claims). Specifically:
#
#   - "no baseline for this file" → skip the claim, never block on it
#   - regex requires explicit verb + path-with-extension token
#   - skips negated forms ("did NOT edit X")
#   - mtime granularity may miss same-second no-op edits — that's the
#     "Edit produced no net change" case, which IS a false claim worth
#     blocking on (per the recovery message), so we accept this edge
#
# A user-controlled escape hatch is provided via the
# `CC_ENSLAVER_DISABLE_LAYER_G` env var (set to any non-empty value to
# skip the layer entirely) — for cases where the layer misfires on a
# real workflow we don't yet know how to handle.
# --------------------------------------------------------------------------- #

# Match a file-path token: optional Windows drive letter (C:) + at
# least one alnum char + extension. Allows /, \, ., -, _, ~ as path
# chars. Excludes whitespace, quotes, brackets, parens. The extension
# restriction is what keeps casual phrases ("I think it's done") from
# looking like file paths.
#
# v0.17: drive-letter prefix added so Windows absolute paths
# (C:\Users\...\x.py, D:/Projects/foo.md) match. Linux/macOS paths
# (/tmp/foo.py, ./bar.py) still match because the prefix is optional.
#
# v0.21.1: '~' added to the char class because the GitHub Windows runner's
# TEMP is a DOS 8.3 short path (C:\Users\RUNNER~1\AppData\Local\Temp\...).
# Without '~' the class stopped at the tilde, the whole token failed to
# match, and _extract_file_claims returned [] on every runner path — so
# layer (g) silently no-op'd there while passing on tilde-free dev machines
# (the pre-existing windows-latest CI red). The trailing extension anchor
# is unchanged, so '~' cannot make casual prose (e.g. "~5 seconds") match.
_PATH_TOKEN = r"(?:[A-Za-z]:)?[\w./\\~-]+\.[A-Za-z][A-Za-z0-9_]{0,15}"

# English claim verbs. Restricted to verbs that unambiguously assert
# the agent did the action: created / wrote / edited / modified. "updated"
# / "changed" are too loose ("updated the issue tracker" = social action).
_FILE_CLAIMS_EN = re.compile(
    # Optional "I", then a verb, then optional "the"/"a"/"to", then path.
    # Verb captured so the verifier can distinguish edit-vs-create logic.
    r"\bI\s+(edited|modified|wrote(?:\s+to)?|created|added\s+to)\s+"
    r"(?:the\s+|a\s+|new\s+)?(?:file\s+)?"
    # Path may be in backticks, square brackets, or bare.
    r"[`\[]?(" + _PATH_TOKEN + r")[`\]]?",
    re.IGNORECASE,
)

# Chinese claim verbs.
#
# v0.25 — a first-person subject is now REQUIRED, mirroring the English
# pattern's `\bI\s+`. Without it, any third-party attribution became a
# self-claim: "上一版修改了 lib/state.py，本次没动" was parsed as the agent
# claiming to have edited state.py, and since read_guard records a
# baseline mtime for every file merely READ this session, layer (g) could
# then "disprove" it and BLOCK — accusing the agent of lying about an
# edit in the very sentence where it correctly said it had NOT touched
# the file. English speakers never hit this; this repo's primary language
# is Chinese and version attributions ("v0.23 修改了 X") are pervasive in
# its own docs and replies.
#
# The subject is optional-but-anchored: the verb must either be preceded
# by 我/本次/这次/此次/已经/刚 (first-person or "in this turn"), or start
# the sentence / follow a clause boundary with no other subject. We take
# the conservative reading — only an explicit first-person marker counts
# — because layer (g) BLOCKS, and a false block costs a turn while a
# missed lie costs nothing but a missed catch (the layer is documented
# false-negative-preferring).
# v0.26.0 audit — the "12 characters between the anchor and the verb" gap
# is wide enough to admit a DIFFERENT grammatical subject:
# `我确认 v0.23 修改了 lib/state.py` ("I confirm that v0.23 modified …")
# parsed as the agent's own edit claim. That is the same false-block this
# pattern was created to stop, one layer in. The gap must therefore not
# contain a version / release / PR token, which is what such an
# intervening subject looks like in this repo's prose.
_FILE_CLAIMS_ZH = re.compile(
    r"(?:我|本次|这次|此次)(?![^。；;\n]{0,12}?"
    r"(?:v\d|V\d|#\d|上一版|上个版本|上個版本|旧版|舊版|前一版))"
    r"[^。；;\n]{0,12}?"
    r"(修改|更新|创建|新增|新建|编辑|写入|添加|生成)了\s*"
    r"[`「\[]?(" + _PATH_TOKEN + r")[`」\]]?"
)

# Negation guard: don't extract claims when negated.
#
# v0.25 — the `\s+` after the negator made every CJK negation invisible:
# Chinese does not put whitespace between 没有 and the verb, so
# "我没有修改了 lib/state.py" still yielded a positive claim. The CJK
# negators now allow zero intervening spaces; the ASCII branch keeps its
# mandatory whitespace so "cannot" / "note" cannot be read as "not".
_NEGATED_BEFORE = re.compile(
    r"(?:(?:not?|n't)\s+\S{0,12}|(?:没有|没|未|不|沒|无|無)\s*\S{0,12})\Z",
    re.IGNORECASE,
)

# v0.25 — a second negation site the look-behind structurally cannot see.
# Now that the Chinese pattern anchors on a first-person subject, the
# negator sits INSIDE the match ("我" + "没有" + "修改了 X"), i.e. after
# the match start rather than before it. `_extract_file_claims` therefore
# also scans the subject→verb gap with this pattern.
_NEGATION_INNER = re.compile(r"没有|没|尚未|未|不|沒|无|無")


def _extract_file_claims(message: str) -> list[tuple[str, str, str]]:
    """Return list of (verb, path, claim_type) from `message`.

    claim_type is "create" for verbs that assert creation (created /
    wrote / 创建 / 新增 / 新建 / 生成); "edit" for the rest.

    Negated forms ("I did not edit X", "没修改 X") are filtered out by
    checking the immediately preceding window for negation tokens.
    """
    if not message:
        return []
    out: list[tuple[str, str, str]] = []
    seen: set[tuple[str, str]] = set()

    create_verbs_en = {"wrote", "wrote to", "created"}
    create_verbs_zh = {"创建", "新增", "新建", "生成"}

    for pattern in (_FILE_CLAIMS_EN, _FILE_CLAIMS_ZH):
        for m in pattern.finditer(message):
            verb = m.group(1).lower()
            path = m.group(2)
            # Negation window: look at up to 30 chars before the match.
            preceding = message[max(0, m.start() - 30):m.start()]
            if _NEGATED_BEFORE.search(preceding):
                continue
            # …and at the subject→verb gap INSIDE the match, which the
            # look-behind cannot reach (v0.25 — see _NEGATION_INNER).
            # Empty for the English pattern, whose subject is `I` glued
            # to the verb by whitespace only.
            if _NEGATION_INNER.search(message[m.start():m.start(1)]):
                continue
            ctype = "create" if (
                verb in create_verbs_en or verb in create_verbs_zh
            ) else "edit"
            key = (path, ctype)
            if key in seen:
                continue
            seen.add(key)
            out.append((verb, path, ctype))
    return out


def _verify_claims(
    session_id: str,
    claims: list[tuple[str, str, str]],
    cwd: str | None,
) -> list[str]:
    """Return a list of human-readable contradictions, one per false claim.

    A claim is contradicted only when:
      - claim_type == "edit" AND baseline exists with mtime AND current
        file exists with mtime == baseline mtime (no change), OR
      - claim_type == "create" AND baseline exists with mtime == None
        (didn't exist before) AND file still doesn't exist now.

    Otherwise the claim is unverifiable (no baseline) or verified
    (changed since baseline) — we report nothing.
    """
    # v0.30 — the function-local `import os` that used to sit here shadowed
    # the module-level import with an identical binding. Harmless, but it
    # reads as "this needs a deferred import", which is a claim about the
    # module that was never true.
    contradictions: list[str] = []
    for verb, path, ctype in claims:
        # Resolve relative paths against cwd if provided.
        if cwd and not os.path.isabs(path):
            resolved = os.path.join(cwd, path)
        else:
            resolved = path
        have_baseline, baseline_mtime = state_lib.get_baseline(
            session_id, resolved,
        )
        if not have_baseline:
            continue  # never tracked, can't verify
        try:
            current_mtime = os.path.getmtime(resolved)
            current_exists = True
        except OSError:
            current_mtime = None
            current_exists = False
        if ctype == "edit":
            # Need: baseline existed (mtime != None), current exists,
            # and mtimes match → contradicted.
            if (
                baseline_mtime is not None
                and current_exists
                and current_mtime == baseline_mtime
            ):
                contradictions.append(
                    f"  • Claimed `{verb} {path}` but file is unchanged "
                    f"since first encounter (mtime stable)."
                )
        else:  # create
            # Need: baseline was None (file didn't exist), current still
            # doesn't exist → contradicted.
            if baseline_mtime is None and not current_exists:
                contradictions.append(
                    f"  • Claimed `{verb} {path}` but file still does "
                    f"not exist on disk."
                )
    return contradictions


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
    {
        "id": "(g)",
        "rule": "01+06",
        "label": "rule 01+06 — file-claim verification (v0.16)",
        "recovery_keyword": "rule 01 + 06 file-claim",
    },
    {
        "id": "(h)",
        # Not a numbered rule — a closing readability convention (v0.20).
        "rule": "—",
        "label": "TL;DR — 大白话总结 missing",
        "recovery_keyword": "TL;DR 大白话",
    },
    {
        "id": "(i)",
        "rule": "12",
        "label": "rule 12 — repo-wide sync gate (v0.23)",
        "recovery_keyword": "rule 12 sync-gate",
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
    "(g)": "file-edit claim contradicts disk state",
    "(h)": "tldr / 大白话 absent",
    "(i)": "sync-gate group unmet",
}

# v0.20 — per-layer one-line plain-language takeaway ("大白话"). Appended to
# every block reason so cc-enslaver's OWN output also ends with a readable
# summary, symmetric with the layer-(h) requirement it imposes on the agent.
_LAYER_TLDR = {
    "(a)": "你说做完了但没贴证据——补一段「命令 + 输出」就放行。",
    "(b)": "你一边说修好了一边又「应该 / 可能」——删掉含糊词，或明说还没验。",
    "(c)": "有证据但没答收敛 4 题——把「真解决 / 更好方案 / 哪些没验 / 验证合理」写出来。",
    "(d)": "没回看用户原始请求——逐项列「做了哪些 / 有没有降级或遗漏」。",
    "(e)": "改了文件但没写「改前必读 / 写前必想」——补「根因 / 架构 / 方案」≥ 3 项。",
    "(f)": "改了文件但缺「根因 + 影响 + 方案」三件套——补全再收尾。",
    "(g)": "你说改了某文件但磁盘没变——要么真去改，要么撤回这句声明。",
    "(h)": "结尾少了一句大白话——加一行 tldr: \"...\" 就放行。",
    "(i)": "改了 A 类文件但没动它的连带 B 类——要么一起改，要么写一行「同步核对: 为什么不用改」。",
}


# The order `main()` actually evaluates the layers in — NOT the display
# order. (b) runs first because a hedge invalidates a done-claim however
# much evidence accompanies it, so grading the evidence first would be
# wasted work. Everything after that follows the letters.
#
# This tuple exists so the status table can tell "passed" from "never
# reached". v0.12–v0.29 derived both from the DISPLAY index, so a layer-(b)
# block rendered "(a) ✅ Pass" — a positive assertion that convergence
# evidence had been found, printed on a turn where `_has_evidence` was
# never called. Being wrong in that direction is the failure this whole
# hook exists to catch, so it is fixed rather than documented.
_EVAL_ORDER: tuple[str, ...] = (
    "(b)", "(a)", "(c)", "(d)", "(e)", "(f)", "(g)", "(h)", "(i)",
)


def _render_status_table(
    fail_layer_id: str, edit_turn: bool, fail_note: str | None = None,
) -> str:
    """Render the per-layer status table as a markdown table string.

    fail_layer_id is one of "(a)" .. "(i)" — the layer that just failed.
    Rows are DISPLAYED in `LAYER_META` order (a)…(i), because that is how
    every doc, recovery blurb and test names them; each row's verdict is
    computed from its position in `_EVAL_ORDER`, which is the order
    `main()` really runs. A layer that sorts earlier alphabetically but
    later in evaluation shows "not evaluated", not "Pass".

    edit_turn is True iff the agent actually ran Edit/Write this turn:
        - False → layers (e)/(f)/(g)/(i) display "— n/a (non-edit turn)"
        - True  → layers not yet evaluated display "⏸  pending"
    fail_note optionally overrides the failing row's default note (used
    by the v0.23 tldr length check, which fails (h) for a different
    reason than a missing marker).
    """
    fail_rank = _EVAL_ORDER.index(fail_layer_id)
    rows = []
    for meta in LAYER_META:
        lid = meta["id"]
        rule = meta["rule"]
        rank = _EVAL_ORDER.index(lid)
        # e/f/g/i only apply on edit turns — show n/a on non-edit turns
        # regardless of position relative to the failing layer. (Needed
        # since v0.20: layer (h) fires after the edit-only block, so on a
        # non-edit (h) failure, e/f/g would otherwise be mislabelled "Pass"
        # despite never being evaluated.)
        if lid in ("(e)", "(f)", "(g)", "(i)") and not edit_turn:
            status = "—  n/a"
            note = "(non-edit turn)"
        elif rank < fail_rank:
            status = "✅ Pass"
            note = ""
        elif rank == fail_rank:
            status = "❌ **FAIL**"
            note = fail_note or _LAYER_FAIL_NOTE.get(lid, "")
        else:
            # Layer not evaluated (gated by the failure above).
            status = "⏸  pending"
            note = "(not evaluated)"
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
    fail_note: str | None = None,
) -> str:
    """Compose: headline + status table + recovery + one-shot footer.

    The headline always names the failed layer's rule via the keyword
    string `recovery_keyword` so downstream consumers (tests, agents
    skimming the block reason) can locate the failed discipline gate.
    `fail_note` overrides the failing row's table note (v0.23 — used by
    the tldr length check to distinguish "overlong" from "absent").
    """
    meta = next(m for m in LAYER_META if m["id"] == fail_layer_id)
    headline = (
        f"cc-enslaver · Stop check FAILED at Layer {fail_layer_id} "
        f"[{meta['label']}]"
    )
    table = _render_status_table(fail_layer_id, edit_turn, fail_note)
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
    # v0.20: one-line plain-language takeaway before the footer.
    tldr_line = _LAYER_TLDR.get(fail_layer_id)
    if tldr_line:
        parts.append(f"大白话: {tldr_line}")
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

_RECOVERY_G = """Your reply claims to have edited / created / modified one or
more files, but the on-disk state contradicts at least one of those
claims:

{contradictions}

Per rule 01 (verify don't guess) + rule 06 (verify convergence), a
claim about your own actions must be true. If you said "I edited
X.py" but X.py's content/mtime matches what it was when you first
encountered it this session, you either:

  (1) did not actually run the Edit (it was DENIED by another hook;
      check earlier in the transcript), or
  (2) ran Edit on a different file than the one you claimed, or
  (3) the Edit produced no net change (old_string == new_string).

In any of these cases the claim is false and the user is being
misled. Fix the reply:

  • If (1): retry the Edit, or surface the deny to the user.
  • If (2): correct the path in your reply.
  • If (3): retract the claim — describe what you actually did.

This layer is **only** triggered when the on-disk evidence
**contradicts** a claim. If we don't have a baseline for the claimed
file (you never Read it) we can't verify it — those claims pass
through silently. If the file actually changed but you forgot to
mention it, that's also fine — we only catch claimed-but-didn't.

If this fires falsely (you DID edit the file via another tool /
external editor / etc.), surface the discrepancy and let the user
decide whether to override."""

_RECOVERY_H = """Your reply claims completion but does not end with a
plain-language TL;DR (大白话总结).

Per the v0.20 canonical reply schema, every done-claim reply must close
with a one-sentence takeaway the user can read at a glance. Add either:

  • The schema's final field:  tldr: "<一句大白话>"
  • A line starting with `大白话:` / `一句话总结:` / `TL;DR:`

The sentence should say, in plain words: what you actually did, what the
result was, and whether the user needs to do anything next. Not a restate
of the rule checks — a human takeaway.

Example:
  tldr: "改完了 Stop hook 加了 tldr 强制层，203 个测试全绿，可以直接 ship。"
"""

_RECOVERY_H_LONG = """Your reply has a TL;DR, but at least one of its items is
too long to be a TL;DR:

  item ({length} chars > {cap} cap): {snippet!r}

Per the v0.23 length contract, each tldr item is ONE sentence — cause,
action, outcome — within {cap} characters:

  tldr: "<前因 + 做了什么 + 结果如何，一句话>"

If you have several things to report, report them one per line, each a
single short sentence within the cap:

  tldr:
    - "修了 X：根因是 A，现在测试全绿。"
    - "顺带把 B 的引用同步了，无行为变化。"

Do not compress by dropping the outcome — drop the process detail
instead; the body of the reply already carries the detail."""

_RECOVERY_I = """One or more of this project's co-update groups
(.claude/cc-enslaver/sync-gate.toml) are unmet for this session's edits:

{violations}

Per rule 12 (rules/12-repo-wide-sync.md), editing a file that has
registered downstream/reference siblings requires either:

  (1) editing at least one file matching the group's `require` globs in
      the same session (co-update the references, docs, tests,
      translations that depend on what you changed), or
  (2) explicitly acknowledging the check in your reply with a sync
      marker — e.g. a line like:
        同步核对: <require 侧为什么无需变更>
        sync-check: <why the require side needs no change>

Silently editing only the `when` side is exactly the stale-reference
laziness rule 12 exists to stop. Check each listed group now: update
the co-files, or say out loud why they are already correct."""


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
        if turn_count is None:
            # v0.23 E2E finding: production hook payloads carry NO
            # turn_count (verified live — a session with 27 recorded
            # edits had no last_edit_turn key, i.e. every stamp had
            # no-op'd and the edit-gated layers + the one-shot grace
            # window were both vacuous in production). Synthesize a
            # monotonic turn number from the per-session Stop counter:
            # Stop fires once per turn, so the counter IS a turn number
            # and the grace arithmetic below works unchanged. The
            # edit-turn signal itself comes from the
            # `edited_since_last_stop` flag (see lib/state.py).
            turn_count = state_lib.next_stop_turn(session_id)

        # Get the message text, preferring the direct payload field.
        # Extracted BEFORE the one-shot guard (v0.24): the grace path
        # must also see the reply — a recovery answer to a layer-(i)
        # block carries its sync marker here, and returning early used
        # to drop that acknowledgement on the floor (the group then
        # re-blocked after the grace window despite having been
        # explicitly answered).
        message = payload.get("assistant_message") or ""
        if not message and payload.get("transcript_path"):
            message = _last_assistant_message_from_transcript(
                payload["transcript_path"]
            )

        # One-shot guard: if we just blocked, allow this Stop
        # unconditionally — but first honor an explicit sync
        # acknowledgement in the recovery reply (see above). The ack is
        # scoped to recoveries from a layer-(i) block specifically
        # (last_blocked_layer): a reply that merely QUOTES "sync-check"
        # while recovering from an unrelated layer must not silently
        # ack every pending group — only a reply answering the sync
        # gate itself is an answer. Every ALLOWED Stop is a turn
        # boundary → clear the edit flag so the next turn starts clean;
        # blocked Stops keep it (the recovery reply is the same logical
        # turn).
        forgiven: set[str] = set()
        if state_lib.was_just_blocked(session_id, turn_count):
            if (
                message
                and _has_sync_marker(message)
                and state_lib.get_last_blocked_layer(session_id) == "(i)"
            ):
                _ack_pending_sync_groups(session_id, payload.get("cwd"))
            # v0.29 — grace is per LAYER, not per sequence. This used to
            # `return 0` here, which forgave the entire check: a recovery
            # reply that fixed the layer it was told about while still
            # violating another was never evaluated against the others.
            # Observed live: layer (a) blocked for missing evidence, the
            # recovery reply supplied the evidence but carried no `tldr`,
            # and layer (h) was skipped — so the reply-schema layer was
            # unenforceable in precisely the case it exists for.
            #
            # Now the layers already spent in this sequence are forgiven
            # (no layer can block twice for one recovery — the original
            # anti-deadlock property) and the rest are still live. Bounded
            # by the layer count and reset on the first allowed Stop.
            forgiven = state_lib.get_forgiven_layers(session_id)

        if not message:
            state_lib.clear_edit_flag(session_id)
            state_lib.clear_blocked_layers(session_id)
            return 0  # nothing to inspect

        matched = _has_done_claim(message)
        if matched is None:
            state_lib.clear_edit_flag(session_id)
            state_lib.clear_blocked_layers(session_id)
            return 0  # no done-claim → don't block

        def _live(layer_id: str) -> bool:
            """True when `layer_id` may still block in this sequence.

            One predicate consulted by every layer below, rather than a
            per-layer condition: the forgiveness policy is a property of
            the check as a whole, and duplicating it nine times is how it
            would drift.
            """
            return layer_id not in forgiven

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
        if hedge_pair is not None and _live("(b)"):
            state_lib.record_stop_block(session_id, turn_count, "(b)")
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
        if not _has_evidence(message) and _live("(a)"):
            state_lib.record_stop_block(session_id, turn_count, "(a)")
            _emit_block(_build_block_reason(
                "(a)", edited_this_turn,
                _RECOVERY_A,
                matched_phrase=matched,
            ))
            return 0

        # v0.7.0 deep layer (c): evidence present but rule-06 self-quiz
        # neither named nor answered (>=2 of 4 questions).
        if not _has_self_quiz_or_marker(message) and _live("(c)"):
            state_lib.record_stop_block(session_id, turn_count, "(c)")
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
        if not _has_fidelity_marker_or_quiz(message) and _live("(d)"):
            state_lib.record_stop_block(session_id, turn_count, "(d)")
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
            if not _has_rule08_marker_or_keywords(message) and _live("(e)"):
                state_lib.record_stop_block(session_id, turn_count, "(e)")
                _emit_block(_build_block_reason(
                    "(e)", edited_this_turn,
                    _RECOVERY_E,
                    matched_phrase=matched,
                ))
                return 0

            # Layer (f): rule 09 — systematic-modification triplet.
            # Pass if either an explicit rule-09 marker OR all three of
            # (root-cause + impact + solution) keywords are present.
            if not _has_rule09_marker_or_triplet(message) and _live("(f)"):
                state_lib.record_stop_block(session_id, turn_count, "(f)")
                _emit_block(_build_block_reason(
                    "(f)", edited_this_turn,
                    _RECOVERY_F,
                    matched_phrase=matched,
                ))
                return 0

            # v0.16 Layer (g): file-claim verification (rule 01 + 06).
            # Parse "I edited X" / "我修改了 X" claims and verify them
            # against baselines captured by read_guard. Only block when
            # the on-disk evidence definitively contradicts a claim.
            # Honors CC_ENSLAVER_DISABLE_LAYER_G escape hatch.
            if (
                not os.environ.get("CC_ENSLAVER_DISABLE_LAYER_G")
                and _live("(g)")
            ):
                claims = _extract_file_claims(message)
                if claims:
                    contradictions = _verify_claims(
                        session_id, claims, payload.get("cwd"),
                    )
                    if contradictions:
                        state_lib.record_stop_block(session_id, turn_count, "(g)")
                        _emit_block(_build_block_reason(
                            "(g)", edited_this_turn,
                            _RECOVERY_G.format(
                                contradictions="\n".join(contradictions),
                            ),
                            matched_phrase=matched,
                        ))
                        return 0

        # v0.20 Layer (h): plain-language TL;DR (大白话总结) closing
        # requirement. Fires on EVERY done-claim turn (edit or not) — the
        # reader deserves a one-line takeaway regardless.
        if not _has_tldr(message) and _live("(h)"):
            state_lib.record_stop_block(session_id, turn_count, "(h)")
            _emit_block(_build_block_reason(
                "(h)", edited_this_turn,
                _RECOVERY_H,
                matched_phrase=matched,
            ))
            return 0

        # v0.23 Layer (h) part 2: the tldr must actually BE a TL;DR —
        # each item within TLDR_MAX_ITEM_CHARS. A paragraph-length
        # "summary" defeats the field's purpose.
        overlong = _find_overlong_tldr(message) if _live("(h)") else None
        if overlong is not None:
            state_lib.record_stop_block(session_id, turn_count, "(h)")
            snippet, length = overlong
            _emit_block(_build_block_reason(
                "(h)", edited_this_turn,
                _RECOVERY_H_LONG.format(
                    snippet=snippet, length=length, cap=TLDR_MAX_ITEM_CHARS,
                ),
                matched_phrase=matched,
                fail_note=f"tldr item overlong ({length} > {TLDR_MAX_ITEM_CHARS})",
            ))
            return 0

        # v0.23 Layer (i): rule 12 — repo-wide sync gate. Edit turns
        # only, and only when the project committed a sync-gate.toml
        # (per-project opt-in; no config → sync_gate.evaluate returns []
        # and this layer never fires). A sync-acknowledgement marker in
        # the reply passes the gate even when a group is unmet — the
        # check must be said, the files need not be touched blindly.
        #
        # Session-level acknowledgement: `edited_files` is cumulative,
        # so an unmet group would otherwise re-block every post-grace
        # edit turn for the rest of the session even after the agent
        # explicitly answered it. When a marker escape covers a pending
        # group, the group is recorded as acknowledged (sync_acked_groups)
        # and never blocks again this session — one explicit answer per
        # group is the contract.
        if edited_this_turn:
            pending = _pending_sync_violations(
                session_id, payload.get("cwd"),
            )
            if pending:
                if _has_sync_marker(message):
                    # v0.27.0 — a marker acknowledges only groups the agent
                    # has actually been SHOWN. Until now the primary path
                    # acked everything pending while the grace path (fixed
                    # in v0.25.1) acked only the presented set, and that
                    # inconsistency was itself the bypass: outlast the
                    # grace window and the looser path silenced groups the
                    # agent had never seen named.
                    #
                    # Cost is bounded and intentional: a group blocks once,
                    # the block names it, and the next reply's marker
                    # settles it for the session. One informed answer per
                    # group is the contract rule 12 actually asks for —
                    # one blanket sentence covering groups you never
                    # considered is the laziness it exists to stop.
                    presented = set(
                        state_lib.get_last_blocked_groups(session_id))
                    covered = [v.group.name for v in pending
                               if v.group.name in presented]
                    if covered:
                        state_lib.ack_sync_groups(session_id, covered)
                    pending = [v for v in pending
                               if v.group.name not in presented]
                if pending and _live("(i)"):
                    state_lib.record_stop_block(
                        session_id, turn_count, "(i)",
                        blocked_groups=[v.group.name for v in pending],
                    )
                    detail_lines = []
                    for v in pending:
                        hits = ", ".join(v.when_hits[:5])
                        if len(v.when_hits) > 5:
                            hits += f", … (+{len(v.when_hits) - 5} more)"
                        line = (
                            f"  • group '{v.group.name}': edited [{hits}] "
                            f"(matched when={list(v.group.when)}) but "
                            f"require={list(v.group.require)} is not "
                            f"satisfied (mode={v.group.mode})."
                        )
                        if v.group.note:
                            line += f"\n    Note: {v.group.note}"
                        detail_lines.append(line)
                    _emit_block(_build_block_reason(
                        "(i)", edited_this_turn,
                        _RECOVERY_I.format(violations="\n".join(detail_lines)),
                        matched_phrase=matched,
                    ))
                    return 0

        # All nine gates passed — allow. Turn boundary → clear the flag,
        # and end the recovery sequence: the next block starts from a
        # clean slate where every layer is live again (v0.29).
        state_lib.clear_edit_flag(session_id)
        state_lib.clear_blocked_layers(session_id)
    except Exception:
        # Failing open: log to stderr but never block by accident.
        sys.stderr.write("[cc-enslaver] stop_guard exception:\n")
        sys.stderr.write(traceback.format_exc())
    return 0


if __name__ == "__main__":
    sys.exit(main())
