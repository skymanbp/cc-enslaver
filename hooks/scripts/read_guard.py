#!/usr/bin/env python3
"""cc-enslaver — read-before-edit guard + patch-style content guard.

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
     systems without justification: `try: ... except: pass`, `# noqa`,
     `# type: ignore`, `// @ts-ignore`, `// eslint-disable`,
     `time.sleep(...) # race/wait/workaround`. Each marker must carry
     a "why" rationale in an immediately adjacent comment (containing
     "because" / "原因" / "why" / a substantive justification) to be
     allowed through. Bare markers = laziness = DENY.

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
# noqa: E402 on both lib imports because they must follow the sys.path bootstrap
from lib import edicts as edicts_lib  # noqa: E402

# --------------------------------------------------------------------------- #
# Tools this guard handles (PreToolUse matcher must include all of them).
# --------------------------------------------------------------------------- #
HANDLED_TOOLS = {"Read", "Write", "Edit"}

# --------------------------------------------------------------------------- #
# Deny messages.
# --------------------------------------------------------------------------- #
UNREAD_DENY_TEMPLATE = """cc-enslaver · rule 04 + 08 violation (read-before-edit)

Tool: {tool_name}
Target: {file_path}

This file already exists on disk but has not been Read (or Written) in
this session. Per rule 04 (rules/04-full-context.md) + rule 08
(rules/08-read-before-edit-think-before-write.md), edits must be
preceded by a complete reading of the target file so you understand
the surrounding architecture and downstream impact.

To proceed:
  1. Call Read on this file (the entire file, not just the diff context).
  2. After reading, retry the {tool_name}.

If you are intentionally creating a NEW file, this guard would not have
fired -- it triggers only when the target already exists. The fact that
it fired means there is content here you have not yet examined.

If you have already Read this file in this session but the guard still
denies (Claude Code occasionally short-circuits Read to a result cache
without firing the hook -- a known issue), you can register the file
as read via the v0.4.0 escape hatch. From a Bash tool call:

  # 1. Compute SHA-256 of the file currently on disk:
  HASH=$(python -c 'import hashlib,sys; print(hashlib.sha256(open(sys.argv[1],"rb").read()).hexdigest())' PATH)
  # 2. Register:
  python "${{CLAUDE_PLUGIN_ROOT}}/hooks/scripts/register_read.py" --file PATH --hash "$HASH"

The PreToolUse(Bash) hook recomputes the hash from disk and only
registers if it matches your claim, so the escape hatch cannot itself
be used to bypass the read requirement.
"""


# --------------------------------------------------------------------------- #
# Rolling-patch classification thresholds (v0.13.0 — rule 09 hard layer).
#
# Heuristics — deliberately tunable as module-level constants so they can
# be reviewed in one place:
#
#   "small edit"      = max(|old|, |new|) < SMALL_EDIT_MAX_CHARS chars
#                       AND max(lines(old), lines(new)) ≤ SMALL_EDIT_MAX_LINES
#   "systematic"      = max chars ≥ SYSTEMATIC_MIN_CHARS
#                       OR  max lines ≥ SYSTEMATIC_MIN_LINES
#   "medium"          = neither (no counter change)
#
# DENY fires when the predicted next small-edit count would be ≥
# ROLLING_PATCH_THRESHOLD. The recorded count is *not* incremented on
# DENY (a denied edit never landed; counting it would double-count and
# silently disable the threshold). Recovery: do one systematic edit to
# reset the counter to 0.
# --------------------------------------------------------------------------- #
SMALL_EDIT_MAX_CHARS = 200
SMALL_EDIT_MAX_LINES = 10
SYSTEMATIC_MIN_CHARS = 1500
SYSTEMATIC_MIN_LINES = 50
ROLLING_PATCH_THRESHOLD = 4


def _lines(text: str) -> int:
    """Line count of `text`. Treats empty string as 0 lines, not 1."""
    if not text:
        return 0
    return text.count("\n") + 1


def _classify_change(old_string: str, new_string: str) -> str:
    """Return 'systematic' / 'small' / 'medium' for an edit's footprint.

    For Edit, both old and new are meaningful. For Write, callers pass
    old_string="" so the classification falls back to new_string alone.
    For Edit-with-empty-old_string (rare insertion case) the same applies.
    """
    old = old_string or ""
    new = new_string or ""
    max_chars = max(len(old), len(new))
    max_lines = max(_lines(old), _lines(new))
    if max_chars >= SYSTEMATIC_MIN_CHARS or max_lines >= SYSTEMATIC_MIN_LINES:
        return "systematic"
    if max_chars < SMALL_EDIT_MAX_CHARS and max_lines <= SMALL_EDIT_MAX_LINES:
        return "small"
    return "medium"


ROLLING_PATCH_DENY_TEMPLATE = """cc-enslaver · rule 09 violation (rolling-patch interception)

Tool: {tool_name}
Target: {file_path}
Rolling-patch counter: {current_count} small edit(s) already applied
this session; this would be attempt #{attempt_count} — at or above the
threshold of {threshold}.

Per rule 09 (rules/09-systematic-modification.md), the cumulative
pattern of repeated **small** edits to the same file without a single
**systematic** rewrite is forbidden as "rolling patches":

> 同一文件本会话 ≥ 4 次小幅 Edit 而没有一次系统性重写，属于反应式累加。

Each small edit fixes one symptom in isolation; the aggregate signal
is that you have not re-engaged with the file's overall structure or
identified the root cause.

Classification used here:
  small      = max(|old_string|, |new_string|) < {small_chars} chars
               AND max line count ≤ {small_lines}
  systematic = max chars ≥ {sys_chars} OR max line count ≥ {sys_lines}
               (resets the counter to 0)
  medium     = anything in between (does not count, does not reset)

To proceed, do one of:

  (1) **Systematic rewrite**: combine your pending small fixes into a
      single Edit (or Write) of ≥ {sys_lines} lines / ≥ {sys_chars}
      chars on `new_string` / `content`. This counts as systematic and
      resets the counter to 0 for this file.

  (2) **Batch multiple typo-class fixes**: if you genuinely have several
      independent small unrelated changes, expand the surrounding context
      so each individual Edit clears the small-edit threshold (≥ 10
      lines / ≥ 200 chars), or use Write to replace the whole file at
      once.

  (3) **Stop and surface**: tell the user "this file needs a systematic
      rewrite; please review my plan before I continue". Let them
      decide whether to relax the constraint or refactor the approach.

Note: this is NOT the patch-marker check — your new_string is clean of
try/except: pass, # noqa, @ts-ignore, etc. It is the AGGREGATE PATTERN
check: too many small fixes signal a comprehension gap, not a
suppression.
"""


PATCH_DENY_TEMPLATE = """cc-enslaver · rule 09 violation (patch-style new_string)

Tool: {tool_name}
Target: {file_path}
Pattern matched: {pattern_label}

Snippet (the offending segment in your new_string):
{snippet}

Per rule 09 (rules/09-systematic-modification.md), the modification
you are trying to commit contains a "patch marker" that silences
type / lint / test / error handling **without justifying why**.

Allowed forms require a why-comment on the same line or an
immediately adjacent line, containing one of: `because`, `原因`,
`why`, `正当`, or a concrete justification (issue id / spec ref /
clear technical rationale). Bare suppressions are not allowed.

Examples of acceptable forms:

  # noqa: E501  -- URL string exceeds 100 chars; splitting hurts readability
  LONG_URL = "https://..."

  // @ts-ignore: third-party lib has incomplete type, see issue #1234
  const result = legacy.foo();

If you actually meant to fix the underlying issue (rule 03), do that
instead of suppressing the signal. If the suppression is truly
warranted, add the rationale comment and retry. If you genuinely need
to bypass this guard, surface the deny to the user and let them edit
manually -- the discipline exists to flag laziness, not block you.
"""


HARDCODE_DENY_TEMPLATE = """cc-enslaver · rule 10 violation (non-essential hardcoding)

Tool: {tool_name}
Target: {file_path}
Pattern matched: {pattern_label}

Snippet (the offending segment in your content):
{snippet}

Per rule 10 (rules/10-no-hardcoding.md), a value that by design should
be externalized -- read from configuration, an environment variable, a
secret manager, or a function parameter -- has been lazily inlined as a
literal. This is the "设计上应该是变量却被偷懒塞成硬编码" antipattern:
credentials, API keys, tokens, and private-key material must never be
baked into source.

To proceed, do one of:

  (1) **Externalize it** (preferred, rule 03 root cause): read the value
      from the environment or a config / secret store, e.g.
        api_key = os.environ["API_KEY"]          # not a literal
      and keep the real value only in an untracked .env / secret store.

  (2) **If this is genuinely a non-secret placeholder / example / test
      fixture**, make it distinguishable: use an obvious placeholder
      value (containing `example`, `changeme`, `your-`, `<...>`,
      `${{...}}`, `dummy`, `redacted`) OR add an adjacent why-comment
      stating it is essential / a fixture / an example (a token from:
      essential / 必须 / example / fixture / placeholder / 占位 /
      sample / test data).

  (3) **Stop and surface**: if you believe the hardcoding is truly
      unavoidable, tell the user and let them decide -- do not silently
      commit a secret.

Note: prose docs (.md / .rst / .txt / .adoc) and lockfiles are exempt
from this detector; it targets freshly authored *code*.
"""


PATHDEP_DENY_TEMPLATE = """cc-enslaver · rule 11 violation (non-essential path dependency)

Tool: {tool_name}
Target: {file_path}
Pattern matched: {pattern_label}

Snippet (the offending segment in your content):
{snippet}

Per rule 11 (rules/11-no-path-dependency.md), a machine-specific
absolute filesystem path -- a user-home directory, a hardcoded drive
root, or a shell home variable baked into a string literal -- has been
committed into code. This breaks portability the moment the code runs on
another machine, another OS, or in CI. (This repo itself shipped v0.21.1
to fix exactly such a Windows path-portability bug in its own hook.)

To proceed, do one of:

  (1) **Derive the path at runtime** (preferred, rule 03 root cause):
        from pathlib import Path
        base = Path(__file__).resolve().parent          # module-relative
        base = Path(os.environ["CLAUDE_PLUGIN_DATA"])    # from a config var
      Use a project-root marker, an env var, tempfile, or a passed-in
      argument instead of a literal user directory.

  (2) **If the path is genuinely essential** (a fixed OS location that is
      identical on every target machine), add an adjacent why-comment
      saying so (a token from: essential / 必须 / 必需 / example /
      fixture / sample).

  (3) **Stop and surface**: if portability truly cannot be achieved, tell
      the user rather than silently hardcoding your own machine.

Note: prose docs (.md / .rst / .txt / .adoc) and lockfiles are exempt
from this detector; it targets freshly authored *code*.
"""


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


def _scan_bare_try_except_pass(text: str) -> tuple[int, int] | None:
    """Linear, regex-free scan for the bare ``try/except/pass`` antipattern.

    Returns ``(char_start, char_end)`` of the offending ``pass`` line on
    hit, matching the span contract that ``_line_window`` expects; ``None``
    on clean.

    Pattern detected (single-level — nested try blocks are not parsed;
    the goal is to flag the laziness signature, not to be a Python
    parser)::

        <indent>try:
        ... any body lines ...
        <same indent>except[ ...]:
        <deeper indent>pass        # alone on its line

    Why this replaces a regex (root cause — fixed in v0.18.1):
      The earlier ``PATCH_MARKERS[0]`` used a multi-line regex of the form
      ``try:\\n(?:[ \\t]+[^\\n]*\\n)+?except...pass``. The ``(?:...)+?``
      non-greedy line repeater combined with the later anchor caused
      **catastrophic backtracking** (ReDoS) on any healthy Python source
      that contained a ``try:`` block without the bare-pass closure ---
      i.e. essentially all real code. Measured locally:

        N=10 body lines, no matching except/pass: ~0.07 s
        N=20 body lines, no matching except/pass: > 60 s (timed out)

      The exponent factor (>1000× per 10 lines) explained user-reported
      hangs of 10 minutes to 1 hour every time the agent tried to
      ``Edit``/``Write`` a non-trivial ``.py`` file containing ``try:``.
      A single-pass line scanner is O(N) lines, has no backtracking, and
      preserves the existing detection semantics (same DENY message, same
      rationale-window check via ``_line_window`` on the returned span).
    """
    if "try:" not in text and "try :" not in text:
        # Fast path: no possible ``try:`` header. Cheap pre-filter that
        # makes the scanner free on the overwhelming majority of edits.
        return None

    lines = text.split("\n")
    # Cumulative line-start offsets so the returned span lines up with
    # the original string indices that ``_line_window`` slices into.
    starts = [0]
    for ln in lines[:-1]:
        starts.append(starts[-1] + len(ln) + 1)

    pending_try_indent: str | None = None
    n = len(lines)
    i = 0
    while i < n:
        line = lines[i]
        body = line.lstrip(" \t").rstrip()
        if not body:
            i += 1
            continue
        indent = line[: len(line) - len(line.lstrip(" \t"))]

        if pending_try_indent is None:
            # ``try:`` (allow trailing whitespace, no comment / no body
            # on the same line; ``try: ... ; pass`` is one-liner and not
            # the antipattern we target).
            if body == "try:" or body == "try :":
                pending_try_indent = indent
            i += 1
            continue

        # Inside a pending try-block. Look for ``except`` at the same
        # indent column.
        if indent == pending_try_indent and (
            body == "except:"
            or body == "except"
            or body.startswith("except ")
            or body.startswith("except(")
        ):
            # ``except`` header at matching indent: check whether the
            # next non-blank line is a ``pass`` indented deeper.
            j = i + 1
            while j < n and lines[j].lstrip(" \t").rstrip() == "":
                j += 1
            if j < n:
                nxt = lines[j]
                nxt_body = nxt.lstrip(" \t").rstrip()
                nxt_indent = nxt[: len(nxt) - len(nxt.lstrip(" \t"))]
                # v0.25 — compare the CODE on the line, not the raw line.
                # Requiring an exactly-bare ``pass`` meant any trailing
                # comment defeated rule 09's flagship detector outright:
                # ``pass  # TODO later`` was ALLOWED. Worse, it made the
                # documented escape hatch unreachable — a rationale
                # comment on the pass line silenced the detector by
                # changing the string, so ``_has_rationale`` was never
                # consulted and the "why-comment" contract was vacuous.
                # Now the comment is stripped, the marker still fires,
                # and the ±1-line rationale window decides.
                nxt_code = nxt_body.split("#", 1)[0].rstrip()
                nxt_code = nxt_code.rstrip(";").rstrip()
                if nxt_code == "pass" and len(nxt_indent) > len(indent):
                    return starts[j], starts[j] + len(lines[j])
            # v0.25 — do NOT drop the watch here. A try statement may have
            # several ``except`` clauses, and the canonical antipattern is
            # a narrow handler followed by a catch-all that swallows
            # everything:
            #     try: … / except ValueError: log() / except Exception: pass
            # Clearing the watch after the first clause made exactly that
            # shape invisible. Leaving it set lets each subsequent clause
            # at the same indent be inspected; the dedent branch below
            # still ends the watch when a non-``except`` statement returns
            # to (or below) the ``try:`` column.
            i += 1
            continue

        # Dedent to or below the ``try:`` indent without seeing an
        # ``except`` header: the try block has been closed (or is
        # malformed). Drop the watch and re-process this line in the
        # outer state — it may itself open a new ``try:`` block.
        if len(indent) <= len(pending_try_indent):
            pending_try_indent = None
            continue

        # Still inside the try body at deeper indent: keep scanning.
        i += 1

    return None


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
PATCH_MARKERS: list[tuple[str, re.Pattern[str]]] = [
    (
        "Python: # noqa without rationale",
        re.compile(r"#[ \t]*noqa(?::[ \t]*[A-Z]+\d+(?:[ \t]*,[ \t]*[A-Z]+\d+)*)?[ \t]*(?:\n|$)"),
    ),
    (
        "Python: # type: ignore without rationale",
        re.compile(r"#[ \t]*type:[ \t]*ignore(?:\[[^\]]*\])?[ \t]*(?:\n|$)"),
    ),
    (
        "TypeScript: // @ts-ignore without rationale",
        re.compile(r"//[ \t]*@ts-ignore[ \t]*(?:\n|$)"),
    ),
    (
        "TypeScript: // @ts-expect-error without rationale",
        re.compile(r"//[ \t]*@ts-expect-error[ \t]*(?:\n|$)"),
    ),
    (
        "JavaScript/TypeScript: // eslint-disable[-next-line] without rationale",
        re.compile(
            r"//[ \t]*eslint-disable(?:-next-line|-line)?"
            r"(?:[ \t]+[a-zA-Z0-9/_-]+(?:[ \t]*,[ \t]*[a-zA-Z0-9/_-]+)*)?[ \t]*(?:\n|$)"
        ),
    ),
    (
        "Python: time.sleep used to mask a race/wait/workaround",
        re.compile(
            r"\btime\.sleep\([^)]*\)[ \t]*#[ \t]*(?:wait|race|workaround|hack|fix(?:me)?)\b",
            re.IGNORECASE,
        ),
    ),
]

# Rationale keywords. The line containing a patch marker, or its immediate
# neighbours (±1 line), must contain at least one of these tokens (case-
# insensitive) for the marker to be considered justified.
RATIONALE_TOKENS = (
    "because", "原因", "why", "正当", "rationale", "reason",
    # Common justification leads
    "see issue", "see pr", "see comment", "see ticket", "tracking",
    "intentional", "intentionally", "deliberate", "deliberately",
    # Third-party-lib excuse (acceptable as a stated reason)
    "third-party", "third party", "vendor",
    # Spec / standard reference
    "per spec", "per rfc", "per standard",
)


def _line_window(text: str, span_start: int, span_end: int) -> str:
    """Return the line containing [span_start, span_end] plus ±1 line.

    Used to look for a "why" rationale in the immediate neighbourhood of
    a suppression marker.
    """
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


def _has_rationale(
    snippet: str, tokens: tuple[str, ...] = RATIONALE_TOKENS
) -> bool:
    snippet_lc = snippet.lower()
    return any(tok in snippet_lc for tok in tokens)


def _find_unjustified_patch_marker(new_string: str) -> tuple[str, str] | None:
    """Scan `new_string` for the first unjustified patch marker.

    Returns (label, surrounding_snippet) on hit, or None on clean.

    Order of checks:
      1. Linear (regex-free) scan for bare ``try/except: pass``. Run
         first because it is the only intrinsically multi-line pattern
         and replaced a catastrophic-backtracking regex in v0.18.1.
      2. Single-line, anchored regexes in ``PATCH_MARKERS``. All O(N)
         safe by construction.

    Both stages reuse the same ``_line_window`` + ``_has_rationale``
    rationale-allowance check, so adjacent ``because`` / ``原因`` / etc.
    comments suppress the DENY exactly as before the refactor.
    """
    if not new_string:
        return None

    # Stage 1: bare try/except/pass via linear scan (no ReDoS).
    bare_hit = _scan_bare_try_except_pass(new_string)
    if bare_hit is not None:
        start, end = bare_hit
        window = _line_window(new_string, start, end)
        if not _has_rationale(window):
            short = window if len(window) <= 240 else window[:237] + "..."
            return BARE_TRY_EXCEPT_PASS_LABEL, short

    # Stage 2: single-line patch markers.
    for label, pat in PATCH_MARKERS:
        for m in pat.finditer(new_string):
            window = _line_window(new_string, m.start(), m.end())
            if not _has_rationale(window):
                # Trim snippet to a reasonable size for the deny message.
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
_SECRET_ASSIGN = re.compile(
    r"\b(?:password|passwd|pwd|secret|api[_-]?key|access[_-]?key"
    r"|secret[_-]?key|auth[_-]?token|client[_-]?secret|private[_-]?key"
    r"|bearer)\b['\"]?[ \t]*[:=][ \t]*(['\"])(?P<val>[^'\"\n]{8,})\1",
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
        re.compile(r"[A-Za-z]:[\\/](?:Users|home)[\\/][^\\/\s'\"<>|]+", re.IGNORECASE),
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


def _find_hardcoded_secret(text: str) -> tuple[str, str] | None:
    """Scan `text` for the first unjustified hardcoded secret (rule 10).

    Returns (label, surrounding_snippet) on hit, or None on clean. A
    match is suppressed when the value is an obvious placeholder / env-
    read or when an adjacent line carries an essential / example
    rationale (HARDCODE_RATIONALE_TOKENS).
    """
    if not text:
        return None
    for m in _SECRET_ASSIGN.finditer(text):
        val_lc = m.group("val").lower()
        if any(ph in val_lc for ph in _SECRET_PLACEHOLDERS):
            continue
        if _TYPE_NAME_VALUE.match(m.group("val")):
            # Forward-reference type annotation, not a credential
            # (v0.24 — see _TYPE_NAME_VALUE).
            continue
        window = _line_window(text, m.start(), m.end())
        if _has_rationale(window, HARDCODE_RATIONALE_TOKENS):
            continue
        short = window if len(window) <= 240 else window[:237] + "..."
        return (
            "Hardcoded credential: secret-named variable assigned a literal",
            short,
        )
    for label, pat in _SECRET_LITERAL_PATTERNS:
        for m in pat.finditer(text):
            window = _line_window(text, m.start(), m.end())
            if _has_rationale(window, HARDCODE_RATIONALE_TOKENS):
                continue
            short = window if len(window) <= 240 else window[:237] + "..."
            return label, short
    return None


def _find_path_dependency(text: str) -> tuple[str, str] | None:
    """Scan `text` for the first unjustified machine-specific path (rule 11).

    Returns (label, surrounding_snippet) on hit, or None on clean. A
    match is suppressed when an adjacent line carries an essential
    rationale (HARDCODE_RATIONALE_TOKENS).
    """
    if not text:
        return None
    for label, pat in _PATH_DEP_PATTERNS:
        for m in pat.finditer(text):
            window = _line_window(text, m.start(), m.end())
            if _has_rationale(window, HARDCODE_RATIONALE_TOKENS):
                continue
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
        hit = _find_hardcoded_secret(content)
        if hit is not None:
            _emit_deny(
                HARDCODE_DENY_TEMPLATE,
                tool_name=tool,
                file_path=file_path,
                pattern_label=hit[0],
                snippet=hit[1],
            )
            return  # unreachable; _emit_deny exits
        hit = _find_path_dependency(content)
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
        hit = _find_unjustified_patch_marker(content)
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

    def _check_rolling_patch(old_string: str, new_string: str) -> None:
        """Rule-09 rolling-patch counter (v0.13; atomic since v0.24).

        Classify the change and either DENY (small-edit threshold met),
        reset the counter (systematic rewrite), or record-and-allow
        (small edit under threshold). Medium-sized changes are a no-op:
        too big to count as "rolling" but too small to count as a
        re-engagement reset. The decide-and-record step is a single
        locked state operation (try_record_small_edit) — the previous
        read-count-then-increment pair let two parallel hooks both see
        count=2 and both allow, landing the forbidden 4th small edit.
        """
        kind = _classify_change(old_string, new_string)
        if kind == "systematic":
            state_lib.reset_edit_count(session_id, file_path)
            return
        if kind != "small":
            return  # "medium" — leave counter untouched
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
                small_chars=SMALL_EDIT_MAX_CHARS,
                small_lines=SMALL_EDIT_MAX_LINES,
                sys_chars=SYSTEMATIC_MIN_CHARS,
                sys_lines=SYSTEMATIC_MIN_LINES,
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
        # Rolling-patch check (v0.13). A Write to an existing file is
        # effectively a full-file replacement; classify by `content`
        # alone (old_string="" yields the right small/systematic split).
        _check_rolling_patch("", content)
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
        # Rolling-patch check (v0.13).
        _check_rolling_patch(old_string, new_string)
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
        raw = sys.stdin.read()
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
        sys.stderr.write("[cc-enslaver] read_guard exception:\n")
        sys.stderr.write(traceback.format_exc())
    return 0


if __name__ == "__main__":
    sys.exit(main())
