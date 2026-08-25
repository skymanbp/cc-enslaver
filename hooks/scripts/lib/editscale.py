#!/usr/bin/env python3
"""cc-enforcer — how big is this change, relative to what it changes?

The rule-09 rolling-patch layer (v0.13.0) asks one question of every
Edit/Write before it lands: *is this another small symptom fix piled onto a
file nobody has re-read?* Until v0.35.0 that question was answered with four
absolute constants and nothing else, and the answer was wrong at both ends
of the file-size range.

Root cause (v0.35.0)
--------------------
"Systematic" meant >= 1500 characters OR >= 50 lines — an ABSOLUTE floor,
compared against a file whose size the classifier never looked at. On any
file smaller than the floor, no edit can ever reach it: a full ``Write`` of
a 30-line, 900-character module lands in "medium", which neither counts nor
resets. Three small edits therefore locked such a file for the rest of the
session, and the only legal move left was to pad it past 1500 characters —
a gate against reactive patching, demanding the file be made bigger.

The fix is a RELATIVE qualifier alongside the absolute one, never instead of
it. ``classify_change`` reaches "systematic" if the change clears either
floor **or** spans ``SYSTEMATIC_COVERAGE_RATIO`` of the target file on
either axis. That is monotone-loosening by construction — every change
classified systematic before is still systematic — which matters, because
the obvious alternative shape (re-scaling both ends, ``max(1500, 30% of
file)``) would have moved the floor UP for large files and recreated the
same unrecoverable lock-in there: one defect traded for its mirror image.

The "small" definition stays absolute for the same reason. Scaling it would
tighten large files, which is again the lock-in, mirrored.

Stated rather than hidden, with the real number: the layer goes inert only on
files of about **five lines or fewer**, where a two-line edit already spans a
third of the file. From six lines up the absolute small-edit definition still
binds — measured, not assumed: a 30-line file still denies its fourth
two-line patch (its coverage bar is 10 lines). That is the intent. "You have
not re-engaged with this file's overall structure" is not a claim anybody can
make about a five-line file.

The two exemptions
------------------
``is_net_reduction`` — a rolling patch is by definition an ACCRETION of
small additions. An edit that leaves the target shorter than it found it
cannot be one, so it is never counted and never denied, at any counter
value. Deleting code is the opposite of the behaviour this layer exists to
stop.

``is_bookkeeping_edit`` — bumping a version string or a date is not a
symptom fix. The test is structural: strip every numeric run out of both
sides and require the remaining SKELETONS to be byte-identical, proving the
edit changed no code, no prose and no punctuation; then every numeric
position that actually moved must carry the same bookkeeping SHAPE on both
sides. The allowlist is shaped rather than "any digit changed" because
``timeout = 30 -> 300`` and ``if n > 3 -> n > 4`` are also small numeric
edits, and rule 09 names lengthening a timeout and loosening an assertion
as forbidden. Bare integers are exempt only where there is no timeout to
lengthen and no assertion to loosen — prose documents, decided by the
caller through ``allow_bare_numbers``.

Both exemptions cover the FREQUENCY layer only. read_guard runs the content
detectors (suppression markers, hardcoded secrets, path dependency, edicts)
before it ever reaches here, so an edit that deletes fifty lines and plants
one unjustified ``# noqa`` is still denied: suppression has nothing to do
with which direction the file grew.

Why this is a module and not four more helpers in read_guard.py
---------------------------------------------------------------
It is a judgement model with its own vocabulary, in the same taxonomy as
``srclex`` (code vs comment vs literal), ``mdctx`` (asserted vs quoted) and
``shellcmd`` (which argv does this flag belong to). Living here means the
classification is unit-testable directly instead of only through a
subprocess hook payload — which is how the small-file lock-in survived
twenty-two releases: every existing test built its fixture large enough that
the defect could not show.

Public API
----------
``classify_change(old, new, scale)``      -> 'systematic' | 'small' | 'medium'
``is_net_reduction(old, new)``            -> bool
``is_bookkeeping_edit(old, new, bare)``   -> bool
``file_text(path)``                       -> str | None
``file_scale(text)``                      -> (chars, lines) | None
``coverage_bar(scale)``                   -> (chars, lines) | None
``line_count(text)``                      -> int
"""

from __future__ import annotations

import math
import os
import re

# --------------------------------------------------------------------------- #
# Thresholds. Deliberately module-level constants so the whole tuning surface
# is reviewable in one place, and so read_guard's DENY message quotes the
# live values instead of a hand-copied second set that can drift from them.
# --------------------------------------------------------------------------- #
SMALL_EDIT_MAX_CHARS = 200
SMALL_EDIT_MAX_LINES = 10
SYSTEMATIC_MIN_CHARS = 1500
SYSTEMATIC_MIN_LINES = 50
SYSTEMATIC_COVERAGE_RATIO = 0.30

# Upper bound on what this layer reads from disk to measure a file's scale.
# Past it, measurement is skipped and the absolute thresholds stand alone: a
# PreToolUse hook must not stall a tool call reading a multi-megabyte blob.
SCALE_READ_MAX_BYTES = 2_000_000


def line_count(text: str) -> int:
    """Line count of `text`. Treats the empty string as 0 lines, not 1."""
    if not text:
        return 0
    return text.count("\n") + 1


def file_text(path: str) -> str | None:
    """On-disk text of `path`, or None when it cannot be measured.

    None means "fall back to the absolute thresholds" — exactly the
    v0.13-v0.34 behaviour. Every failure mode (unreadable, not UTF-8, past
    SCALE_READ_MAX_BYTES) therefore leaves this layer STRICTER than it would
    otherwise be, never looser, so a measurement problem can never quietly
    widen the gate. That is the opposite of the plugin's usual failing-open
    posture and it is the right direction here: failing open on a GUARD means
    allowing one call, while failing open on a THRESHOLD would mean handing
    out counter resets nobody earned.
    """
    try:
        if os.path.getsize(path) > SCALE_READ_MAX_BYTES:
            return None
        with open(path, "r", encoding="utf-8") as handle:
            return handle.read()
    except (OSError, ValueError, UnicodeDecodeError):
        return None


def file_scale(text: str | None) -> tuple[int, int] | None:
    """(chars, lines) for `text`, or None when it was unmeasurable."""
    if text is None:
        return None
    return len(text), line_count(text)


def coverage_bar(scale: tuple[int, int] | None) -> tuple[int, int] | None:
    """(chars, lines) a change must reach to qualify by SPANNING `scale`.

    The ratio arithmetic has exactly one owner so the DENY message can
    quote the same bar the classifier applies. ``ceil`` because the test is
    ``>=`` on integers: truncating would advertise a bar one unit below the
    one actually enforced, which is the kind of off-by-one a reader has no
    way to detect from the message alone.
    """
    if scale is None:
        return None
    chars, lines = scale
    return (
        math.ceil(SYSTEMATIC_COVERAGE_RATIO * chars),
        math.ceil(SYSTEMATIC_COVERAGE_RATIO * lines),
    )


def classify_change(
    old_string: str,
    new_string: str,
    scale: tuple[int, int] | None = None,
) -> str:
    """Return 'systematic' / 'small' / 'medium' for one change's footprint.

    `old_string` / `new_string` are the two sides of the change. For Edit
    they are the tool's own arguments; for Write the caller passes the
    file's current on-disk text as the old side, because a Write replaces
    the whole file and that text IS what is being replaced.

    `scale` is the target's (chars, lines) on disk, or None when it could
    not be measured. It only ever ADDS a route to 'systematic', so passing
    None reproduces the pre-v0.35 absolute-only classification exactly —
    which is what makes the None fallback safe rather than merely quiet.
    """
    old = old_string or ""
    new = new_string or ""
    max_chars = max(len(old), len(new))
    max_lines = max(line_count(old), line_count(new))
    if max_chars >= SYSTEMATIC_MIN_CHARS or max_lines >= SYSTEMATIC_MIN_LINES:
        return "systematic"
    bar = coverage_bar(scale)
    if bar is not None:
        chars_bar, lines_bar = bar
        if chars_bar > 0 and max_chars >= chars_bar:
            return "systematic"
        if lines_bar > 0 and max_lines >= lines_bar:
            return "systematic"
    if max_chars < SMALL_EDIT_MAX_CHARS and max_lines <= SMALL_EDIT_MAX_LINES:
        return "small"
    return "medium"


def is_net_reduction(old_string: str, new_string: str) -> bool:
    """True when the change leaves the target shorter than it found it."""
    return len(new_string or "") < len(old_string or "")


# A numeric run: digits, optionally joined by INTERNAL dots or hyphens.
# Requiring digits after every separator keeps trailing punctuation out of
# the token, so `617.` ending a sentence yields `617` and the full stop stays
# in the skeleton, where a change to it would still be caught.
_NUM_RUN = re.compile(r"\d+(?:[.\-]\d+)*")
_VERSION_SHAPE = re.compile(r"^\d+\.\d+(?:\.\d+)*$")
_DATE_SHAPE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_BARE_NUMBER = re.compile(r"^\d+$")

# Stands in for an elided numeric run while the two skeletons are compared.
# NUL cannot occur in the source and prose these tools handle, so it can
# never be mistaken for real content.
_NUM_SENTINEL = "\x00"


def _bookkeeping_shape(token: str, allow_bare: bool) -> str | None:
    """Name the bookkeeping shape of one numeric token, else None."""
    if _VERSION_SHAPE.match(token):
        return "version"
    if _DATE_SHAPE.match(token):
        return "date"
    if allow_bare and _BARE_NUMBER.match(token):
        return "number"
    return None


def is_bookkeeping_edit(
    old_string: str, new_string: str, allow_bare_numbers: bool = False
) -> bool:
    """True when the change only restates bookkeeping literals.

    `allow_bare_numbers` widens the allowlist from version/date shapes to any
    integer. The caller owns that decision because it is a question about the
    TARGET, not about the text: read_guard passes True exactly for the
    prose-doc and lockfile set rules 10 and 11 already exempt, where there is
    no timeout to lengthen and no assertion to loosen, and where updating
    "617 tests" to "619 tests" across six documents is the most common
    legitimate small edit this repository performs.

    Requiring the SAME shape on both sides (version -> version, date -> date)
    is what stops `1 -> 1.2.3` and similar reshaping from riding in on a
    position that merely happens to be numeric at both ends.
    """
    old = old_string or ""
    new = new_string or ""
    old_nums = _NUM_RUN.findall(old)
    new_nums = _NUM_RUN.findall(new)
    # Equal skeletons already imply equal run counts; the explicit check is
    # kept so the zip() below cannot silently truncate a mismatched pair.
    if len(old_nums) != len(new_nums):
        return False
    if _NUM_RUN.sub(_NUM_SENTINEL, old) != _NUM_RUN.sub(_NUM_SENTINEL, new):
        return False
    for before, after in zip(old_nums, new_nums):
        if before == after:
            continue
        shape = _bookkeeping_shape(before, allow_bare_numbers)
        if shape is None or shape != _bookkeeping_shape(after, allow_bare_numbers):
            return False
    return True
