#!/usr/bin/env python3
"""cc-enforcer — read-before-edit guard + patch-style content guard.

A single PreToolUse handler covering Read / Write / Edit. Recording and
gating live in the same hook event so they share a scope:

  Read    → record file_path; allow
  Write   → if target exists and is unrecorded: DENY (file is unread)
            else: record file_path; record last_edit_turn; allow
  Edit    → if target exists and is unrecorded: DENY (file is unread)
            else if new_string contains unjustified patch markers: DENY
            else: record last_edit_turn; allow

Why everything in PreToolUse (and not split with PostToolUse):
  Empirically (Claude Code v2.1.x), `PostToolUse` does not fire for tool
  calls whose `tool_input.file_path` lies outside the current project's
  working directory, but `PreToolUse` *does* fire for such calls. If we
  recorded in Post and gated in Pre, an out-of-project Read would never
  be recorded, then the next out-of-project Edit on the same file would
  be denied even though the agent *just* read it. v0.3.1 shipped that
  bug; v0.3.2 fixes it by moving recording to Pre, which has a scope
  consistent with the gating side.

  The trade-off: in Pre we record speculatively (before the tool has
  actually succeeded). If a Read fails, we still recorded the path —
  but a later Edit against that same (non-existent) path is allowed
  anyway by the `os.path.exists` short-circuit, so the speculative
  record is harmless.

v0.11.0 — Two new responsibilities, both for rule 08 + rule 09:

  1. **Patch-style new_string interception** (rule 09). Before allowing
     an Edit / Write that passed the read-before-edit gate, scan the
     `new_string` for "patch markers" that bypass type/lint/test
     systems without justification. The spellings named below are
     intentional documentation, never live suppressions:
     `try: ... except: pass`, `# noqa` (intentional), `# type: ignore`,
     `// @ts-ignore` (intentional), `// eslint-disable`,
     `time.sleep(...) # race/wait/workaround` (intentional). Each
     marker must carry a "why" rationale in an immediately adjacent
     comment (containing "because" / "原因" / "why" / a substantive
     justification) to be allowed through. Bare markers = DENY.

  2. **Edit-turn recording** (rule 08 + 09 Stop-hook backstop). When
     an Edit or Write passes all checks, stamp `last_edit_turn =
     current turn_count` into session state. The Stop hook's layers
     (e) and (f) only fire on turns where an edit actually happened,
     so this stamp is what scopes them.

Failing-open contract: if anything in this script raises, we still
allow the tool call and only log to stderr. A bug in the guard cannot
be permitted to brick the agent.

Hook output spec (verified against
https://code.claude.com/docs/en/hooks.md as of 2026-04-27):

    {
      "hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "permissionDecision": "deny",
        "permissionDecisionReason": "<human-readable reason>"
      }
    }

`allow` is the default when no JSON is emitted, so we stay silent on
the non-blocking paths.
"""

from __future__ import annotations

import json
import os
import re
import sys
import traceback
from pathlib import Path

# Make `lib/` importable when run directly as a script.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib import state as state_lib  # noqa: E402
# E402 is suppressed on every lib import below because they must follow
# the sys.path bootstrap above -- that is the stated reason, not laziness.
from lib import edicts as edicts_lib  # noqa: E402
# because the sys.path bootstrap above must run before this import
from lib import srclex  # noqa: E402
# because the sys.path bootstrap above must run before this import
from lib import editscale  # noqa: E402
# because the sys.path bootstrap above must run before this import
from lib import hookio  # noqa: E402
# because the sys.path bootstrap above must run before this import
from lib import messages  # noqa: E402

# --------------------------------------------------------------------------- #
# Tools this guard handles (PreToolUse matcher must include all of them).
# --------------------------------------------------------------------------- #
HANDLED_TOOLS = {"Read", "Write", "Edit"}

# --------------------------------------------------------------------------- #
# Deny messages.
# --------------------------------------------------------------------------- #
UNREAD_DENY_TEMPLATE = messages.text("read.deny.unread")


# --------------------------------------------------------------------------- #
# Rolling-patch frequency layer (v0.13.0 — rule 09 hard layer).
#
# The SIZE/SHAPE judgement — what counts as a small edit, what counts as a
# systematic rewrite, and which changes are exempt outright — lives in
# lib/editscale.py, along with the v0.35.0 root-cause note on why the
# thresholds became relative to the target file. This module owns only the
# FREQUENCY policy: how many small edits to one file are tolerated before
# the next one is refused.
#
# DENY fires when the predicted next small-edit count would be ≥
# ROLLING_PATCH_THRESHOLD. The recorded count is *not* incremented on
# DENY (a denied edit never landed; counting it would double-count and
# silently disable the threshold). Recovery: do one systematic edit to
# reset the counter to 0.
# --------------------------------------------------------------------------- #
ROLLING_PATCH_THRESHOLD = 4


def _scale_note(scale: tuple[int, int] | None) -> str:
    """Render the file's own coverage bar for the DENY message, if known.

    Empty when the target could not be measured — saying nothing is right
    there, because in that case the classifier genuinely did not apply a
    coverage test and printing one would describe a check that never ran.
    """
    bar = editscale.coverage_bar(scale)
    if bar is None or scale is None:
        return ""
    chars_bar, lines_bar = bar
    file_chars, file_lines = scale
    return messages.text("read.scale_note").format(
        lines_bar=lines_bar, file_lines=file_lines,
        chars_bar=chars_bar, file_chars=file_chars,
    )


def _cover_hint(scale: tuple[int, int] | None) -> str:
    """Render the spanning route in recovery path (1), if it is known."""
    bar = editscale.coverage_bar(scale)
    if bar is None:
        return ""
    chars_bar, lines_bar = bar
    return messages.text("read.cover_hint").format(
        lines_bar=lines_bar, chars_bar=chars_bar,
    )


ROLLING_PATCH_DENY_TEMPLATE = messages.text("read.deny.rolling")


PATCH_DENY_TEMPLATE = messages.text("read.deny.patch")


HARDCODE_DENY_TEMPLATE = messages.text("read.deny.hardcode")


PATHDEP_DENY_TEMPLATE = messages.text("read.deny.pathdep")


def _emit_deny(template: str, **fields: object) -> None:
    """Write a structured deny response and exit 0.

    We use sys.stdout.buffer for UTF-8 correctness on Windows, where
    sys.stdout otherwise defaults to the system code page (e.g. cp936)
    and would mangle non-ASCII characters in the reason text.
    """
    reason = template.format(**fields)
    _emit_raw_deny(reason)


def _emit_raw_deny(reason: str) -> None:
    """Write a structured deny response (with a pre-built reason) and exit 0."""
    payload = {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }
    }
    encoded = (json.dumps(payload, ensure_ascii=False) + "\n").encode("utf-8")
    sys.stdout.buffer.write(encoded)
    sys.stdout.buffer.flush()
    sys.exit(0)


BARE_TRY_EXCEPT_PASS_LABEL = (
    "Python: bare try / except: pass (silent exception swallow)"
)


def _strip_py_comment(source_line_body: str) -> str:
    """Return the executable code on a Python line (`;` trimmed).

    Comments are already gone by the time this runs — `srclex.logical_lines`
    strips them *after* masking string literals, so a `#` inside a literal
    can no longer decapitate the line.
    """
    return source_line_body.rstrip().rstrip(";").rstrip()


# A handler clause continues the `try` statement rather than ending it.
# `\b` matters: the old `code.startswith("finally")` test also fired on an
# ordinary identifier such as `finally_hook = 1`.
_HANDLER_HEADER = re.compile(r"^(?:except|finally|else)\b")
_EXCEPT_HEADER = re.compile(r"^except\b")
# `except <anything>: <statement>` written on a single line. `[^:]*` is
# safe here because an except clause never contains a colon before its
# own terminator (no annotations, no slices, no dict literals).
_EXCEPT_ONELINER = re.compile(r"^except\b[^:]*:\s*(\S.*)$")
_TRY_HEADER = re.compile(r"^try\s*:$")


def _scan_bare_try_except_pass(text: str) -> list[tuple[int, int]]:
    """Linear, regex-light scan for the bare ``try/except/pass`` antipattern.

    Returns a list of ``(char_start, char_end)`` spans, one per offending
    swallow, each matching the span contract that ``_line_window``
    expects. Empty list on clean.

    Shapes detected::

        <indent>try:                    <indent>try:
        ... body ...                    ... body ...
        <same indent>except[ ...]:      <same indent>except Exception: pass
        <deeper indent>pass

    Why a scanner and not a regex (root cause — fixed in v0.18.1): the
    earlier multi-line regex ``try:\\n(?:[ \\t]+[^\\n]*\\n)+?except...pass``
    combined a non-greedy line repeater with a later anchor and caused
    **catastrophic backtracking** on any healthy Python containing a
    ``try:`` without the bare-pass closure — i.e. essentially all real
    code (N=20 body lines took > 60 s). A single-pass line scanner is
    O(N) lines with no backtracking.

    v0.25.1 — three coverage holes closed, all of the same shape ("the
    detector recognised one exact layout"):

      * **Comment lines between ``except:`` and ``pass`` masked the hit.**
        Because the scanner looked only at the next *non-blank* line, an
        intervening comment made it miss — which meant rule 09's
        documented escape hatch was STILL vacuous for its most natural
        spelling: a rationale written on its own line above ``pass``
        silenced the detector by moving the ``pass``, so
        ``_has_rationale`` was never consulted. (v0.25 fixed the
        same-line spelling of this bug and left the own-line spelling in
        place — including in the regression test it added, which passed
        for the wrong reason.) Comment lines are now skipped, so the
        marker fires and the ±1-line window genuinely decides. (The
        checker itself is now ``_has_rationale_at``; the v0.25.1-era
        ``_has_rationale`` was retired in v0.30.)
      * **``except Exception: pass`` one-liners were invisible** — the
        most compact spelling of the antipattern.
      * **Only the first hit was returned**, so a justified swallow
        earlier in the edit hid an unjustified one after it, and nested
        ``try`` blocks were never watched at all (a single pending
        indent cannot represent nesting; it is now a stack).
    """
    if "try" not in text:
        # Fast path: no possible ``try`` header. Cheap pre-filter that
        # makes the scanner free on the overwhelming majority of edits.
        return []

    lines = text.split("\n")
    # Cumulative line-start offsets so returned spans line up with the
    # original string indices that ``_line_window`` slices into.
    starts = [0]
    for ln in lines[:-1]:
        starts.append(starts[-1] + len(ln) + 1)

    # Block shape is read from LOGICAL lines with string bodies masked
    # (v0.26.0). Two whole classes of miss disappear at the source rather
    # than being special-cased: the text inside a multi-line string can no
    # longer re-anchor indentation, and a bracketed ``except (\n …\n):``
    # header arrives as the single clause it actually is.
    logical = srclex.logical_lines(text, "py")

    hits: list[tuple[int, int]] = []
    stack: list[int] = []
    n = len(logical)
    k = 0
    while k < n:
        phys_idx, code = logical[k]
        body = _strip_py_comment(code.strip())
        if not body:
            k += 1
            continue
        indent = len(code) - len(code.lstrip(" \t"))
        is_handler = bool(_HANDLER_HEADER.match(body))

        # Close every try-watch whose block has ended. A handler clause at
        # the try's own column continues that statement, so it pops only
        # the levels strictly BELOW it. v0.25.1 suppressed *every* pop for
        # a handler, which left the inner try's indent stranded on top of
        # the stack and made the outer ``except`` unreachable — a nested
        # try/except that v0.25.0 denied regressed to "allow".
        while stack and (stack[-1] > indent
                         or (stack[-1] == indent and not is_handler)):
            stack.pop()

        if stack and stack[-1] == indent and _EXCEPT_HEADER.match(body):
            one_liner = _EXCEPT_ONELINER.match(body)
            if one_liner is not None:
                if _strip_py_comment(one_liner.group(1)) == "pass":
                    hits.append((starts[phys_idx],
                                 starts[phys_idx] + len(lines[phys_idx])))
            elif body.endswith(":"):
                j = k + 1
                while j < n and not _strip_py_comment(logical[j][1].strip()):
                    j += 1
                if j < n:
                    nxt_idx, nxt_code = logical[j]
                    nxt_indent = len(nxt_code) - len(nxt_code.lstrip(" \t"))
                    if (_strip_py_comment(nxt_code.strip()) == "pass"
                            and nxt_indent > indent):
                        hits.append((starts[nxt_idx],
                                     starts[nxt_idx] + len(lines[nxt_idx])))
            k += 1
            continue

        if _TRY_HEADER.match(body):
            stack.append(indent)
        k += 1

    return hits


# --------------------------------------------------------------------------- #
# Patch-style markers (rule 09, v0.11.0; v0.18.1 dropped the multi-line
# try/except/pass regex in favour of the linear scanner above — see
# ``_scan_bare_try_except_pass`` for the ReDoS root cause).
#
# Each entry is (label, regex). All remaining entries are **single-line,
# anchored** patterns that are O(N) safe (no nested quantifiers, no
# multi-line backtracking). They match the *bare* marker form; the caller
# looks at a small surrounding window (±1 line) for a "why" comment and
# allows the marker through when a rationale is present.
#
# Design notes:
#   - Detection is intentionally conservative: only the well-known
#     suppression idioms. False negatives (a clever workaround we don't
#     match) cost a soft-layer reminder; false positives (denying a
#     legitimate use) cost the agent a turn. Conservative regex set keeps
#     false-positive rate low.
#   - The ``try/except: pass`` detector lives outside this list because
#     it is intrinsically multi-line and must remain backtrack-free.
# --------------------------------------------------------------------------- #
# v0.25.1 — the trailing `(?:\n|$)` anchors are GONE from the five
# single-line markers, and that removal is the fix. Requiring the marker
# to sit at end-of-line meant ANY trailing text made the pattern miss
# entirely, so `// @ts-ignore: TODO` was ALLOWED while the bare form was
# denied — the rationale check was never reached, it was simply skipped.
# The same hole made the deny message's own "acceptable form" examples
# (`# noqa: E501  -- URL string exceeds 100 chars`) pass for the wrong
# reason, and made `test_ts_ignore_with_rationale_is_allowed` a vacuous
# test. Dropping the anchors also fixes CRLF: `[ \t]*\n` could never
# match `\r\n`, so on this plugin's primary platform every one of these
# five detectors was silently off for CRLF files.
#
# Trailing text is now handed to `_inline_reason_is_substantive`, so an
# inline explanation still justifies the marker while a bare
# `TODO` / `FIXME` does not. Prose targets keep the old bare-only
# behaviour — see `_find_unjustified_patch_marker`.
PATCH_MARKERS: list[tuple[str, re.Pattern[str]]] = [
    # v0.26.0 — every marker now ends at a TOKEN boundary. Dropping the
    # `(?:\n|$)` anchors in v0.25.1 left the markers as bare substrings,
    # so `# noquality`, `@ts-ignore-generated` and `eslint-disablement`
    # were each read as the suppression they merely start with and were
    # DENIED. `\b` is not enough for the `-` spellings (a hyphen is a
    # non-word char, so `\b` matches happily before it); those need an
    # explicit `(?![\w-])`.
    (
        "Python: # noqa without rationale",
        re.compile(
            r"#[ \t]*noqa\b(?::[ \t]*[A-Za-z]+\d*(?:[ \t]*,[ \t]*[A-Za-z]+\d*)*)?"
        ),
    ),
    (
        "Python: # type: ignore without rationale",
        re.compile(r"#[ \t]*type:[ \t]*ignore\b(?:\[[^\]\n]*\])?"),
    ),
    (
        "TypeScript: // @ts-ignore without rationale",
        re.compile(r"//[ \t]*@ts-ignore(?![\w-])"),
    ),
    (
        "TypeScript: // @ts-expect-error without rationale",
        re.compile(r"//[ \t]*@ts-expect-error(?![\w-])"),
    ),
    (
        "JavaScript/TypeScript: // eslint-disable[-next-line] without rationale",
        re.compile(
            r"//[ \t]*eslint-disable(?:-next-line|-line)?(?![\w-])"
            r"(?:[ \t]+[a-zA-Z0-9/_-]+(?:[ \t]*,[ \t]*[a-zA-Z0-9/_-]+)*)?"
        ),
    ),
    (
        "Python: time.sleep used to mask a race/wait/workaround",
        # `[^\n]{0,200}?` (lazy, bounded) instead of `[^)]*` so a nested
        # call survives: `time.sleep(max(0, delay))  # workaround` used to
        # miss, because `[^)]*` stopped at the INNER `)`. Bounded and
        # backtrack-safe — the required `#` anchor caps the search.
        re.compile(
            r"\btime\.sleep\([^\n]{0,200}?\)[ \t]*#[ \t]*"
            r"(?:wait|race|workaround|hack|fix(?:me)?)\b",
            re.IGNORECASE,
        ),
    ),
]

# Rationale keywords. The line containing a patch marker, or its immediate
# neighbours (±1 line), must contain at least one of these tokens (case-
# insensitive) for the marker to be considered justified.
RATIONALE_TOKENS = (
    "because", "原因", "why", "正当", "rationale", "reason",
    # v0.26.0 — Chinese "because"/"deliberately" forms. Only the NOUN
    # `原因` was listed, so `# noqa 因为上游库类型有误` was DENIED while the
    # English `because …` was allowed. This repo's primary language is
    # Chinese and its own docs use these forms throughout; the hatch was
    # English-first by accident, not by design.
    "因为", "之所以", "理由", "故意", "刻意", "有意", "特意",
    # Common justification leads
    "see issue", "see pr", "see comment", "see ticket", "tracking",
    "intentional", "intentionally", "deliberate", "deliberately",
    # Third-party-lib excuse (acceptable as a stated reason)
    "third-party", "third party", "vendor",
    # Spec / standard reference
    "per spec", "per rfc", "per standard",
)


def _window_bounds(text: str, span_start: int, span_end: int) -> tuple[int, int]:
    """Char bounds of the line containing the span, plus ±1 line.

    Split out from `_line_window` (v0.26.0) so the rationale check can be
    evaluated against the WHOLE text's lexical state over this range,
    rather than re-lexing the three-line slice in isolation. A window
    inside a docstring contains no `\"\"\"` of its own, so judged alone it
    looks like bare code and a perfectly good why-note went unseen.
    """
    # CR counts as a line break, not just LF. Reading only "\n" made the
    # whole of a lone-CR file a single "line", so the +/-1 window covered
    # everything and any `because` anywhere in the file satisfied the
    # hatch for every marker in it. (srclex ends comment spans at CR for
    # the same reason; both had to change or the pair still disagreed.)
    def _rfind_break(upto: int) -> int:
        return max(text.rfind("\n", 0, upto), text.rfind("\r", 0, upto))

    def _find_break(frm: int) -> int:
        lf = text.find("\n", frm)
        cr = text.find("\r", frm)
        cand = [x for x in (lf, cr) if x != -1]
        return min(cand) if cand else len(text)

    if span_end > span_start and text[span_end - 1] in "\n\r":
        span_end -= 1
    line_start = _rfind_break(span_start)
    line_start = 0 if line_start == -1 else line_start + 1
    line_end = _find_break(span_end)
    prev_start = _rfind_break(max(0, line_start - 1))
    prev_start = 0 if prev_start == -1 else prev_start + 1
    next_end = _find_break(min(len(text), line_end + 1))
    return prev_start, next_end


def _has_rationale_at(
    text: str,
    span_start: int,
    span_end: int,
    tokens: tuple[str, ...] = RATIONALE_TOKENS,
    lang: str = "auto",
) -> bool:
    """True when a why-token appears in documentation near the span."""
    lo, hi = _window_bounds(text, span_start, span_end)
    docs = srclex.comment_text_in_range(text, lo, hi, lang).lower()
    return any(tok in docs for tok in tokens)


def _line_window(text: str, span_start: int, span_end: int) -> str:
    """Return the line containing [span_start, span_end] plus ±1 line.

    Used for the SNIPPET shown in the deny message. The rationale decision
    itself goes through `_has_rationale_at`, which needs whole-text
    context.
    """
    # Clamp a span that consumed its own terminating newline: m.end()
    # would land at the START of the next line, find("\n", span_end)
    # would then locate the NEXT line's terminator, and the documented
    # "±1 line" window would silently become "+2 lines below" — an
    # unrelated rationale two lines away suppressing the DENY. That was
    # live through v0.25.0, when five PATCH_MARKERS regexes still ended
    # in `(?:\n|$)`; v0.25.1 dropped those anchors (see the note above
    # PATCH_MARKERS), so no current marker span reaches here with a
    # trailing newline and the clamp is defensive, kept for whatever
    # pattern is added next. `_window_bounds` carries the same clamp,
    # widened to CR.
    if span_end > span_start and text[span_end - 1] == "\n":
        span_end -= 1
    line_start = text.rfind("\n", 0, span_start)
    line_start = 0 if line_start == -1 else line_start + 1
    line_end = text.find("\n", span_end)
    line_end = len(text) if line_end == -1 else line_end
    # Extend one line up
    prev_start = text.rfind("\n", 0, max(0, line_start - 1))
    prev_start = 0 if prev_start == -1 else prev_start + 1
    # Extend one line down
    next_end = text.find("\n", line_end + 1)
    next_end = len(text) if next_end == -1 else next_end
    return text[prev_start:next_end]


# v0.30 — `_comment_text`, `_cjk_count` and `_has_rationale` used to live
# here and are gone; nothing called any of them.
#
# `_has_rationale` was the ±1-line rationale search that v0.26 replaced
# with `_has_rationale_at`, which evaluates the window against the WHOLE
# text's lexical state (a three-line window inside a docstring carries no
# delimiter of its own, so judged alone it reads as bare code). Every call
# site moved; the function did not. `_comment_text` was its one-line
# delegation to `srclex.comment_text`, and `_cjk_count` duplicated a
# counting loop that `_inline_reason_is_substantive` performs inline.
#
# Leaving a superseded rationale checker beside the live one is not
# harmless housekeeping: the two answer the same question differently, and
# the next reader has no way to tell which one the guard actually consults.

# CJK ranges: Han, Han extension A, kana, hangul. Used to size a rationale
# written in a language that does not delimit words with spaces.
_CJK_RANGES = (
    (0x3040, 0x30FF), (0x3400, 0x4DBF), (0x4E00, 0x9FFF), (0xAC00, 0xD7AF),
)
_MIN_INLINE_REASON_CJK_CHARS = 6
_MIN_DISTINCT_CJK_CHARS = 5


# Words that look like a reason but assert nothing. Leading one of these
# is what distinguishes `// @ts-ignore: TODO` (a deferral) from
# `// @ts-ignore: upstream types are wrong for Node 20` (a reason).
_NON_REASON_LEADS = {
    "todo", "fixme", "hack", "xxx", "wip", "tbd", "later", "temp",
    "temporary", "wontfix", "n/a", "na", "?", "??",
}
_MIN_INLINE_REASON_CHARS = 12


def _inline_reason_is_substantive(trailing: str) -> bool:
    """True when text following a marker reads as an actual explanation.

    Deliberately permissive in the "allow" direction (this repo prefers
    false negatives to false positives): several words of prose count.
    Deliberately strict about the ONE shape that is a deferral rather
    than a reason — a leading TODO / FIXME / HACK / … keyword.

    v0.26.0 — "several words" was implemented as "contains an ASCII
    space", which no Chinese sentence does. A CJK rationale of any length
    therefore scored as non-substantive, so the identical justification
    passed in English and was DENIED in Chinese — in a repo whose primary
    language is Chinese. Length in CJK characters is the equivalent
    measure.
    """
    text = trailing.strip().lstrip(":-—–,;").strip()
    # Padding does not add meaning. Without this, `改了改了改了!!!!!!` and
    # `变量名字变量名字____` reached the length bar on punctuation alone.
    text = text.strip("!?！？。,，、;；_*~`\"'()（） \t")
    if len(text) < _MIN_INLINE_REASON_CHARS:
        return False
    if " " not in text:
        cjk = [ch for ch in text
               if any(lo <= ord(ch) <= hi for lo, hi in _CJK_RANGES)]
        # Repetition is not an explanation: `改了` six times clears a raw
        # character count but says one thing. Distinct characters is the
        # cheap proxy for "actually says something".
        if (len(cjk) < _MIN_INLINE_REASON_CJK_CHARS
                or len(set(cjk)) < _MIN_DISTINCT_CJK_CHARS):
            return False
    first = re.split(r"[^\w?/]+", text.lower(), maxsplit=1)[0]
    return first not in _NON_REASON_LEADS


def _find_unjustified_patch_marker(
    new_string: str, scannable: bool = True, lang: str = "auto"
) -> tuple[str, str] | None:
    """Scan `new_string` for the first unjustified patch marker.

    Returns (label, surrounding_snippet) on hit, or None on clean.

    Order of checks:
      1. Linear (regex-free) scan for bare ``try/except: pass``. Run
         first because it is the only intrinsically multi-line pattern
         and replaced a catastrophic-backtracking regex in v0.18.1. Every
         hit is inspected (v0.25.1) — a justified swallow no longer hides
         an unjustified one later in the same edit.
      2. Single-line regexes in ``PATCH_MARKERS``. All O(N) safe by
         construction.

    Both stages reuse the same ``_has_rationale_at`` allowance check (the
    window is located by ``_window_bounds`` but judged against the whole
    text's lexical state), so adjacent ``because`` / ``原因`` / etc.
    comments suppress the DENY. ``_line_window`` only builds the snippet
    the deny message displays.

    `scannable` is False for prose docs (.md / .rst / …), where the
    markers are discussed rather than executed. Those targets keep the
    pre-v0.25.1 behaviour of matching only the BARE marker form: this
    repo's own docs mention `noqa` / `@ts-ignore` 54 times, and the
    permissive form below would flag every one of them. Enforcement on
    code is unchanged-or-stricter; only the doc false-positive surface
    moves.
    """
    if not new_string:
        return None

    # Stage 1: bare try/except/pass via linear scan (no ReDoS).
    for start, end in _scan_bare_try_except_pass(new_string):
        # The rationale decision uses whole-text lexical context
        # (`_has_rationale_at`); `_line_window` only builds the snippet the
        # deny message shows.
        if not _has_rationale_at(new_string, start, end, lang=lang):
            window = _line_window(new_string, start, end)
            short = window if len(window) <= 240 else window[:237] + "..."
            return BARE_TRY_EXCEPT_PASS_LABEL, short

    # Stage 2: single-line patch markers.
    for label, pat in PATCH_MARKERS:
        for m in pat.finditer(new_string):
            line_end = new_string.find("\n", m.end())
            line_end = len(new_string) if line_end == -1 else line_end
            trailing = new_string[m.end():line_end].rstrip("\r")
            if not scannable and trailing.strip():
                continue
            if _inline_reason_is_substantive(trailing):
                continue
            if not _has_rationale_at(new_string, m.start(), m.end(),
                                     lang=lang):
                # Trim snippet to a reasonable size for the deny message.
                window = _line_window(new_string, m.start(), m.end())
                short = window if len(window) <= 240 else window[:237] + "..."
                return label, short
    return None


# --------------------------------------------------------------------------- #
# Rule 10 (no non-essential hardcoding) + rule 11 (no non-essential path
# dependency) — write-time content detectors, v0.22.0.
#
# Same mechanism as the rule-09 patch-marker detector above: scan the
# incoming new_string / content, and DENY on a high-confidence match
# unless an adjacent why-comment (or, for secrets, an obvious placeholder
# value) marks it as essential / example. That escape hatch is how the
# user's "*非必须*" (non-essential) scoping is operationalized: a flagged
# literal WITH a stated justification is allowed; a bare one is not.
#
# Design (mirrors the conservative-detector note at PATCH_MARKERS above):
# prefer false negatives to false positives. Only the unambiguous
# should-be-config classes are hard-matched; magic numbers and bare
# network endpoints are left to the soft rule text (rules/10, rules/11),
# not enforced here.
#
# Self-scan safety: this module is itself a .py file, so a future Edit to
# it re-runs these very detectors on the new source. Every pattern below
# is written so its own *definition* text does not match it (the home-var
# literals are split across string concatenation for exactly this
# reason), and the DENY templates use env-read / placeholder examples
# that the value filter skips. Test fixtures build offending strings at
# runtime for the same reason.
# --------------------------------------------------------------------------- #

# Extra rationale tokens that mark a flagged literal / path as essential
# or as a deliberate example / fixture. Union with rule-09
# RATIONALE_TOKENS so `because` / `原因` / etc. also work; rule-09's own
# tuple is left untouched (byte-identical rule-09 behavior).
HARDCODE_RATIONALE_TOKENS = RATIONALE_TOKENS + (
    "essential", "必须", "必需", "example", "fixture",
    "placeholder", "占位", "sample", "test data", "test-data",
)

# A secret-named identifier assigned a quoted literal of >= 8 chars. The
# value is captured (group `val`) so obvious placeholders can be filtered
# out below. Bounded, backtrack-free (the value class excludes both
# quotes, so the closing quote terminates the run in one pass).
# v0.25 — the optional quote before the separator makes the QUOTED-KEY
# spelling matchable. `"api_key": "…"` is the single most common way a
# credential gets committed (JSON config, quoted-key YAML/TOML), and
# `.json` is fully scannable — but the old pattern required the `:` to
# follow the keyword with only spaces between, so the closing quote of
# the key blocked every match. The rarer bare-key form was caught while
# the common one was waved through.
# v0.25.1 — the separator is captured (`sep`) so the type-annotation
# relief below can be scoped to the `:` form it was written for. Applying
# it to `=` too meant a plain-alphabetic credential assigned with `=`
# (example: a CamelCase-looking password literal) was silently allowed.
_SECRET_ASSIGN = re.compile(
    r"\b(?:password|passwd|pwd|secret|api[_-]?key|access[_-]?key"
    r"|secret[_-]?key|auth[_-]?token|client[_-]?secret|private[_-]?key"
    r"|bearer)\b['\"]?[ \t]*(?P<sep>[:=])[ \t]*"
    r"(?P<q>['\"])(?P<val>[^'\"\n]{8,})(?P=q)",
    re.IGNORECASE,
)

# If the captured value contains any of these, it is a placeholder /
# env-read / template reference, not a real embedded secret -> skip it.
_SECRET_PLACEHOLDERS = (
    "example", "changeme", "change-me", "change_me", "your-", "your_",
    "yourkey", "redacted", "dummy", "placeholder", "sample", "fake",
    "todo", "xxxx", "****", "....", "<", ">", "${", "os.environ",
    "getenv", "process.env", "config.", "settings.",
)

# v0.24 — pure-alpha CamelCase value shape. A `password: "SecretStr"`
# match is a Python forward-reference type annotation (the `:` form is
# indistinguishable from YAML assignment at the regex level), not an
# embedded credential: real secrets carry digits / symbols. Skipping
# this shape trades a far-fetched false negative (an all-alpha,
# capitalised, 8+ char real password) for a realistic false-positive
# class, per the repo's "prefer false negatives" philosophy.
_TYPE_NAME_VALUE = re.compile(r"^[A-Z][A-Za-z]*$")

# Standalone secret literals that need no keyword on the left.
#
# v0.25.1 adds provider-issued token shapes. These are preferred over
# widening the keyword list with a bare `token`: the value shape is
# self-identifying, so precision stays high, whereas `token = "…"` would
# fire on ordinary parser/lexer code (`token = "NUMBER_LITERAL"`) — a
# false positive this repo's "prefer false negatives" philosophy rejects.
_SECRET_LITERAL_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    (
        "Hardcoded credential: private-key PEM header",
        re.compile(r"-----BEGIN (?:[A-Z][A-Z ]*)?PRIVATE KEY-----"),
    ),
    (
        "Hardcoded credential: AWS access-key literal",
        re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    ),
    (
        "Hardcoded credential: provider-issued token literal",
        re.compile(
            r"\bgh[pousr]_[A-Za-z0-9]{16,}"
            r"|\bxox[baprs]-[A-Za-z0-9-]{10,}"
            r"|\bAIza[0-9A-Za-z_-]{20,}"
        ),
    ),
    (
        "Hardcoded credential: username:password in a connection URL",
        re.compile(r"://[^/\s:@'\"]+:[^/\s:@'\"]+@"),
    ),
]

# Machine-specific absolute filesystem paths (user-home rooted). Kept
# deliberately narrow to *user-specific* roots to hold the false-positive
# rate down -- not every C:\ or /etc/ path, only ones tied to a person's
# home directory or profile.
_PATH_DEP_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    (
        "Path dependency: Windows user-home absolute path",
        # v0.25.1 — `(?:\\{1,2}|/)` instead of `[\\/]`. The single-slash
        # class only matched a RAW spelling; in real Python / JSON / JS
        # source the separator is DOUBLED, which is how a user-home path
        # actually appears in committed code (example only, this module
        # depends on no such path). The detector caught the rare spelling
        # and waved through the normal one — on the primary platform.
        re.compile(
            r"[A-Za-z]:(?:\\{1,2}|/)(?:Users|home)(?:\\{1,2}|/)[^\\/\s'\"<>|]+",
            re.IGNORECASE,
        ),
    ),
    (
        "Path dependency: POSIX user-home absolute path",
        # v0.24 — the lookbehind rejects a match glued to a hostname /
        # URL path segment (https://host.test/home/alice/… is a route,
        # not a filesystem path). A quoted or slash-anchored real path
        # still matches: file:///home/x has `/` before /home, which is
        # not in the excluded class.
        re.compile(r"(?<![\w.-])/(?:home|Users)/[^/\s'\"<>|]+/"),
    ),
    (
        "Path dependency: shell home variable in a literal",
        # Split across concatenation so this definition does not match
        # itself when the guard later scans its own source (rule 11
        # self-scan safety; see the module note above).
        re.compile(r"\$" r"HOME\b|%USER" r"PROFILE%"),
    ),
    (
        "Path dependency: user-home tilde path in a string literal",
        re.compile(r"['\"]~/[^'\"\n]*['\"]"),
    ),
]

# Targets exempt from the rule 10 + 11 content detectors: prose docs and
# lockfiles legitimately carry illustrative example paths / placeholder
# values, and lockfiles are machine-generated. The rule-09 patch-marker
# detector keeps its all-files behavior; only these two new detectors
# honor the exemption. Mirrors the user's "写完*代码*后" framing.
# v0.24: `.asciidoc` added (same format as the already-exempt `.adoc`).
_PROSE_DOC_EXTS = {".md", ".markdown", ".rst", ".txt", ".adoc", ".asciidoc"}
_LOCKFILE_NAMES = {
    "package-lock.json", "yarn.lock", "pnpm-lock.yaml", "poetry.lock",
    "cargo.lock", "gemfile.lock", "composer.lock",
}

# v0.24 — exception inside the .txt exemption: requirements*.txt /
# constraints*.txt are dependency manifests, not prose. An index URL
# with embedded credentials in requirements.txt is a real leak vector
# the blanket .txt exemption used to wave through.
_DEP_MANIFEST_TXT_PREFIXES = ("requirements", "constraints")


def _is_scannable_target(file_path: str) -> bool:
    """Return False for prose-doc / lockfile targets (rule 10 + 11 exempt).

    Dependency manifests that merely *look* like prose by extension
    (requirements*.txt / constraints*.txt) stay scannable — see
    _DEP_MANIFEST_TXT_PREFIXES.
    """
    name = os.path.basename(file_path).lower()
    if name in _LOCKFILE_NAMES or name.endswith(".lock"):
        return False
    stem, ext = os.path.splitext(name)
    if ext not in _PROSE_DOC_EXTS:
        return True
    return ext == ".txt" and stem.startswith(_DEP_MANIFEST_TXT_PREFIXES)


def _find_hardcoded_secret(
    text: str, lang: str = "auto"
) -> tuple[str, str] | None:
    """Scan `text` for the first unjustified hardcoded secret (rule 10).

    Returns (label, surrounding_snippet) on hit, or None on clean. A
    match is suppressed when the value is an obvious placeholder / env-
    read or when an adjacent line carries an essential / example
    rationale (HARDCODE_RATIONALE_TOKENS).

    `lang` reaches `_has_rationale_at` so the rationale search is confined
    to real comments. This detector was the worst casualty of the old
    "find the first `#` or `//`" approximation: `example` is a rationale
    token and `example.com` is the IANA reserved example domain, so a
    single neighbouring line such as `API = "https://api.example.com"`
    turned the entire secret detector off — precisely the neighbourhood a
    committed credential lives in.
    """
    if not text:
        return None
    for m in _SECRET_ASSIGN.finditer(text):
        val_lc = m.group("val").lower()
        if any(ph in val_lc for ph in _SECRET_PLACEHOLDERS):
            continue
        if m.group("sep") == ":" and _TYPE_NAME_VALUE.match(m.group("val")):
            # Forward-reference type annotation, not a credential
            # (v0.24 — see _TYPE_NAME_VALUE). v0.25.1 scopes the relief to
            # the `:` spelling it was written for; under `=` the same
            # shape is an ordinary assignment of a real secret.
            continue
        if _has_rationale_at(text, m.start(), m.end(),
                             HARDCODE_RATIONALE_TOKENS, lang=lang):
            continue
        window = _line_window(text, m.start(), m.end())
        short = window if len(window) <= 240 else window[:237] + "..."
        return (
            "Hardcoded credential: secret-named variable assigned a literal",
            short,
        )
    for label, pat in _SECRET_LITERAL_PATTERNS:
        for m in pat.finditer(text):
            # v0.25.1 — placeholder filtering applies to standalone
            # literals too. It used to gate only the keyword-assignment
            # branch, so an obviously-fake connection string such as
            # `postgres://user:redacted@host/db` was denied while the
            # identical value behind `password = …` was allowed.
            if any(ph in m.group(0).lower() for ph in _SECRET_PLACEHOLDERS):
                continue
            if _has_rationale_at(text, m.start(), m.end(),
                                 HARDCODE_RATIONALE_TOKENS, lang=lang):
                continue
            window = _line_window(text, m.start(), m.end())
            short = window if len(window) <= 240 else window[:237] + "..."
            return label, short
    return None


def _find_path_dependency(
    text: str, lang: str = "auto"
) -> tuple[str, str] | None:
    """Scan `text` for the first unjustified machine-specific path (rule 11).

    Returns (label, surrounding_snippet) on hit, or None on clean. A
    match is suppressed when an adjacent line carries an essential
    rationale (HARDCODE_RATIONALE_TOKENS).

    Same `lang` plumbing, same reason, as `_find_hardcoded_secret` above.
    """
    if not text:
        return None
    for label, pat in _PATH_DEP_PATTERNS:
        for m in pat.finditer(text):
            if _has_rationale_at(text, m.start(), m.end(),
                                 HARDCODE_RATIONALE_TOKENS, lang=lang):
                continue
            window = _line_window(text, m.start(), m.end())
            short = window if len(window) <= 240 else window[:237] + "..."
            return label, short
    return None


# --------------------------------------------------------------------------- #
# Single PreToolUse handler.
# --------------------------------------------------------------------------- #
def _handle_pre_tool_use(payload: dict) -> None:
    tool = payload.get("tool_name", "")
    if tool not in HANDLED_TOOLS:
        return
    tool_input = payload.get("tool_input") or {}
    file_path = tool_input.get("file_path")
    if not file_path:
        return
    session_id = payload.get("session_id") or "default"
    turn_count = payload.get("turn_count")

    if tool == "Read":
        # Record the read so subsequent Edit/Write on this file is allowed.
        # Always ALLOW the Read itself — it will fail naturally if the file
        # does not exist.
        #
        # v0.25 — but only RECORD an existing target. The previous code
        # recorded unconditionally, justified by "a phantom record of a
        # non-existent path is harmless (Edit's os.path.exists
        # short-circuit covers it)". That reasoning is wrong: the
        # short-circuit only fires while the file is STILL absent. Read a
        # path before it exists (reading a generated artifact before
        # generating it is an everyday flow), let a build step / git
        # checkout / another process create it, and the stale entry now
        # satisfies has_read — so an Edit or a whole-file Write lands on
        # content the session never saw, with rule 04 silently disabled
        # for that path for the rest of the session. Same defect class as
        # the v0.24 fix below, where a DENIED Write must not grant
        # read-before-edit authorization.
        if os.path.exists(file_path):
            state_lib.add_read(session_id, file_path)
        # v0.16: also capture file-state baseline for Stop layer (g)
        # (file-claim verification). Lazy, idempotent. Recorded even for a
        # missing target — "did not exist at baseline" is exactly what
        # layer (g) needs to adjudicate a later "I created X" claim.
        state_lib.record_baseline(session_id, file_path)
        return

    # Load edicts once per invocation (v0.12). Cheap (one disk read of a
    # small TOML file) and avoids stale state between Edits in the same
    # session if the user is iterating on edicts.toml.
    loaded_edicts = edicts_lib.load()

    def _check_edicts(content: str) -> None:
        """Scan content against all must edicts; DENY on first hit."""
        if not loaded_edicts:
            return
        hit = edicts_lib.find_edit_violation(loaded_edicts, content)
        if hit is not None:
            _emit_raw_deny(edicts_lib.deny_reason(
                hit, kind=tool, tool_or_cmd=file_path,
            ))
            return  # unreachable; _emit_raw_deny exits

    def _check_hardcode_and_path(content: str) -> None:
        """Rule 10 + 11 content detectors (v0.22.0). DENY on first hit.

        Skips prose-doc / lockfile targets (they legitimately carry
        example paths and placeholder values). Ordered secret-first,
        path-second, matching the rules' numeric order.
        """
        if not _is_scannable_target(file_path):
            return
        hit = _find_hardcoded_secret(content, lang=srclex.lang_for_path(file_path))
        if hit is not None:
            _emit_deny(
                HARDCODE_DENY_TEMPLATE,
                tool_name=tool,
                file_path=file_path,
                pattern_label=hit[0],
                snippet=hit[1],
            )
            return  # unreachable; _emit_deny exits
        hit = _find_path_dependency(content, lang=srclex.lang_for_path(file_path))
        if hit is not None:
            _emit_deny(
                PATHDEP_DENY_TEMPLATE,
                tool_name=tool,
                file_path=file_path,
                pattern_label=hit[0],
                snippet=hit[1],
            )
            return  # unreachable; _emit_deny exits

    def _run_content_checks(content: str) -> None:
        """Shared write-content gate: patch markers (rule 09) →
        hardcode / path (rule 10 + 11) → edicts (圣旨, v0.12).

        Every write branch runs the SAME sequence through this one
        helper. v0.11-v0.23 hand-copied the sequence into each branch,
        which is exactly how the branches drifted: the Write-new branch
        registered its target as read BEFORE the checks had passed (so a
        DENIED Write still granted read-before-edit authorization), and
        each new detector had to be spliced into three places.
        """
        hit = _find_unjustified_patch_marker(
            content, scannable=_is_scannable_target(file_path),
            lang=srclex.lang_for_path(file_path),
        )
        if hit is not None:
            _emit_deny(
                PATCH_DENY_TEMPLATE,
                tool_name=tool,
                file_path=file_path,
                pattern_label=hit[0],
                snippet=hit[1],
            )
            return  # unreachable; _emit_deny exits
        _check_hardcode_and_path(content)
        _check_edicts(content)

    def _check_rolling_patch(
        old_string: str,
        new_string: str,
        scale: tuple[int, int] | None = None,
    ) -> None:
        """Rule-09 rolling-patch counter (v0.13; atomic since v0.24).

        Classify the change and either DENY (small-edit threshold met),
        reset the counter (systematic rewrite), or record-and-allow
        (small edit under threshold). Medium-sized changes are a no-op:
        too big to count as "rolling" but too small to count as a
        re-engagement reset. The decide-and-record step is a single
        locked state operation (try_record_small_edit) — the previous
        read-count-then-increment pair let two parallel hooks both see
        count=2 and both allow, landing the forbidden 4th small edit.

        v0.35 — `scale` carries the target file's (chars, lines) so a
        change can qualify as systematic by SPANNING the file rather than
        only by absolute size, and two shapes short-circuit before the
        counter is ever consulted. Order matters: systematic is tested
        first so a large deletion RESETS rather than merely being
        skipped, which is the more useful outcome of the two.
        """
        kind = editscale.classify_change(old_string, new_string, scale)
        if kind == "systematic":
            state_lib.reset_edit_count(session_id, file_path)
            return
        if kind != "small":
            return  # "medium" — leave counter untouched
        # v0.35 exemptions. Neither resets the counter: they are not
        # re-engagement with the file, they are simply not the behaviour
        # this layer polices, so they pass through leaving it as it was.
        if editscale.is_net_reduction(old_string, new_string):
            return
        if editscale.is_bookkeeping_edit(
            old_string, new_string,
            allow_bare_numbers=not _is_scannable_target(file_path),
        ):
            return
        allowed, current = state_lib.try_record_small_edit(
            session_id, file_path, ROLLING_PATCH_THRESHOLD,
        )
        if not allowed:
            _emit_deny(
                ROLLING_PATCH_DENY_TEMPLATE,
                tool_name=tool,
                file_path=file_path,
                current_count=current,
                attempt_count=current + 1,
                threshold=ROLLING_PATCH_THRESHOLD,
                small_chars=editscale.SMALL_EDIT_MAX_CHARS,
                small_lines=editscale.SMALL_EDIT_MAX_LINES,
                sys_chars=editscale.SYSTEMATIC_MIN_CHARS,
                sys_lines=editscale.SYSTEMATIC_MIN_LINES,
                ratio_pct=int(editscale.SYSTEMATIC_COVERAGE_RATIO * 100),
                scale_note=_scale_note(scale),
                cover_hint=_cover_hint(scale),
            )
            return  # unreachable; _emit_deny exits

    if tool == "Write":
        # v0.16: capture baseline BEFORE the Write lands. For a brand-new
        # file this captures None (file did not exist at baseline); for
        # an existing file it captures the pre-Write mtime. Either way
        # Stop layer (g) can later verify "created X" / "modified X"
        # claims against this snapshot. (Baseline capture is
        # observational — safe before the checks, unlike add_read.)
        state_lib.record_baseline(session_id, file_path)
        target_exists = os.path.exists(file_path)
        content = tool_input.get("content") or ""
        if not target_exists:
            # New file creation: nothing to gate on read-before-edit,
            # but ALL content checks still apply — writing a brand-new
            # file full of `# noqa` / secrets is still laziness.
            _run_content_checks(content)
            # v0.24: a fresh file has no rolling history — clear any
            # stale counter left by a same-named file that was deleted
            # and is being recreated (its first small edit used to be
            # denied as attempt #4).
            state_lib.reset_edit_count(session_id, file_path)
            # Register as read ONLY after every check passed (v0.24 —
            # a DENIED Write must not grant read-before-edit
            # authorization for content the agent never saw).
            state_lib.add_read(session_id, file_path)
            state_lib.record_edit_turn(session_id, turn_count)
            # v0.23: rule-12 edited-file set (Stop layer (i) sync gate).
            state_lib.record_edited_file(session_id, file_path)
            return
        # Existing file: agent must have seen it before (Read or Write).
        if not state_lib.has_read(session_id, file_path):
            _emit_deny(
                UNREAD_DENY_TEMPLATE,
                tool_name=tool,
                file_path=file_path,
            )
            return  # not reached; _emit_deny exits
        _run_content_checks(content)
        # Rolling-patch check (v0.13). A Write to an existing file is a
        # full-file replacement, so the side being replaced is the file's
        # CURRENT text (v0.35) — passing it makes the coverage, net-reduction
        # and bookkeeping tests see the change that is actually happening.
        # Before v0.35 this passed old_string="", which measured only the
        # incoming content: replacing a 3000-char file with 50 chars read as
        # a "small edit" and counted toward the rolling-patch threshold,
        # when it is the most complete re-engagement a Write can be.
        # Unreadable target → None → "" → the pre-v0.35 behaviour exactly.
        disk_text = editscale.file_text(file_path)
        _check_rolling_patch(
            disk_text or "", content, editscale.file_scale(disk_text),
        )
        state_lib.add_read(session_id, file_path)
        state_lib.record_edit_turn(session_id, turn_count)
        # v0.23: rule-12 edited-file set (Stop layer (i) sync gate).
        state_lib.record_edited_file(session_id, file_path)
        return

    if tool == "Edit":
        # Editing a non-existent file is invalid input that Claude Code
        # itself will reject; we don't second-guess.
        if not os.path.exists(file_path):
            return
        # v0.16: capture baseline BEFORE Edit lands (idempotent — most of
        # the time the Read recording already captured it on first
        # access, but Edit-only flows that bypassed Read via the
        # register_read escape hatch still need baseline capture).
        state_lib.record_baseline(session_id, file_path)
        if not state_lib.has_read(session_id, file_path):
            _emit_deny(
                UNREAD_DENY_TEMPLATE,
                tool_name=tool,
                file_path=file_path,
            )
            return  # unreachable; _emit_deny exits
        # The new_string is what actually lands in the file (Edit may
        # carry replace_all; the scanned content is the same), so that
        # is what the shared content gate scans.
        new_string = tool_input.get("new_string") or ""
        old_string = tool_input.get("old_string") or ""
        _run_content_checks(new_string)
        # Rolling-patch check (v0.13; file-relative since v0.35). The scale
        # is read from disk so "small" can be judged against what the file
        # actually is, not against a constant chosen for some other file.
        _check_rolling_patch(
            old_string, new_string,
            editscale.file_scale(editscale.file_text(file_path)),
        )
        # Edit allowed — stamp the edit-turn for Stop layers (e)+(f).
        # We do NOT add_read here because Edit is downstream of a prior
        # Read/Write that already recorded.
        state_lib.record_edit_turn(session_id, turn_count)
        # v0.23: rule-12 edited-file set (Stop layer (i) sync gate).
        state_lib.record_edited_file(session_id, file_path)


# --------------------------------------------------------------------------- #
# Entry point.
# --------------------------------------------------------------------------- #
def main() -> int:
    try:
        # v0.37 — bytes + explicit UTF-8, never the locale codepage. See
        # lib/hookio: text-mode stdin decodes with `surrogateescape`, so a
        # UTF-8 payload was silently rewritten rather than rejected, and
        # this guard scanned a string the agent never wrote.
        raw = hookio.read_payload_text()
        if not raw.strip():
            return 0  # nothing to inspect, fail open
        payload = json.loads(raw)
        if payload.get("hook_event_name") == "PreToolUse":
            _handle_pre_tool_use(payload)
        # Any other event (including the legacy PostToolUse if it ever
        # arrives): no-op, exit 0. Recording is fully owned by Pre now.
    except Exception:
        # Failing open: log and exit 0 so the agent is never blocked
        # by a bug in our own guard.
        sys.stderr.write("[cc-enforcer] read_guard exception:\n")
        sys.stderr.write(traceback.format_exc())
    return 0


if __name__ == "__main__":
    sys.exit(main())
