#!/usr/bin/env python3
"""cc-enforcer — markdown line context for the Stop hook.

Root cause this module exists to kill (v0.26.0 audit, root cause α, and
its sibling β "each site re-implements the same judgement"): the Stop
hook repeatedly asks "is this line something the AGENT is asserting, or
is it quoted / illustrative material?" — and every caller answered it
differently and partially.

The concrete failure: layer (h) has two halves, a presence check
(`_has_tldr`) and a length check (`_tldr_items`). They disagreed.

  * `_tldr_items` correctly measured only the canonical ```yaml block and
    skipped every other fence as fixture/example text.
  * `_has_tldr` accepted a `tldr:` marker in ANY fence, so quoting the
    schema in a ```text block satisfied the gate while the length half
    then measured nothing.
  * `_has_tldr` recognised a blockquote only as `>` at the start of the
    stripped line, so `- > tldr: …` (a quote nested in a list item) read
    as the agent's own takeaway.

One model, consumed by both halves, is the fix. `countable` encodes the
single question "would a reader attribute this line to the agent?".

Public API
----------
``lines(text)``        -> list[LineCtx], one per physical line
``has_substance(s)``   -> True when `s` carries more than punctuation
"""

from __future__ import annotations

import re
from typing import NamedTuple


class LineCtx(NamedTuple):
    """One physical line's attribution context.

    Two verdicts, deliberately asymmetric (v0.27.0):

    ``attributable`` — could a reader plausibly read this as the agent's
    own words? Used by the PRESENCE half of layer (h). Generous, because
    a false negative there blocks a reply for a "missing" tldr that is
    visibly present, which the agent cannot diagnose.

    ``countable`` — is this definitely the agent's own words, safe to
    MEASURE against the 160-char cap? Conservative, because a false
    positive there blocks a reply for the length of text it merely
    quoted.

    They differ only on CommonMark *lazy continuation*: an unprefixed
    line following `> quoted text` is inside the blockquote by the spec,
    so it is not countable — but it is still attributable, so writing a
    tldr immediately under a quote satisfies presence instead of
    mystifying the author. Collapsing the two into one predicate is what
    forced v0.26 to skip lazy continuation entirely.
    """
    index: int
    raw: str
    in_fence: bool
    fence_info: str
    is_fence_delim: bool
    quoted: bool
    countable: bool
    attributable: bool = True


def fence_marker(stripped_line: str) -> str | None:
    """Return the full fence run (e.g. '```' / '````'), or None.

    CommonMark: a closing fence must use the same character and be at
    least as long as the opener. Truncating every fence to three
    characters (the pre-v0.25 bug) made an inner ``` close an outer ````,
    after which the outer block's body was scanned as prose.
    """
    for ch in ("`", "~"):
        if stripped_line.startswith(ch * 3):
            run = len(stripped_line) - len(stripped_line.lstrip(ch))
            return ch * run
    return None


# A list-item marker that may precede a blockquote arrow: `- > quoted`.
# Ordered (`1.`) and bulleted forms both count; several may nest.
_LIST_MARKER = re.compile(r"^(?:[-*+]|\d{1,9}[.)])\s+")


def _is_quoted(line: str) -> bool:
    """True when THIS physical line carries a blockquote marker."""
    s = line.strip()
    # Peel list markers, then look for the quote arrow. Bounded so a
    # pathological line cannot spin.
    for _ in range(8):
        if s.startswith(">"):
            return True
        m = _LIST_MARKER.match(s)
        if not m:
            return False
        s = s[m.end():].lstrip()
    return s.startswith(">")


# The canonical reply schema is a ```yaml block; every other fence —
# including an INFO-LESS bare ``` — is quoted/illustrative material rather
# than the agent's own assertion.
#
# The bare-fence case was deliberated and pinned in v0.23
# (`test_non_yaml_fence_fixture_is_not_measured`): quoting someone else's
# overlong tldr as a counter-example inside a bare fence must not make the
# reply self-trip. A v0.26 attempt to make bare fences count — on the
# theory that an untagged schema block would otherwise be missed — broke
# that test and was reverted. The canonical form is documented as ```yaml;
# tagging it is the agent's job, and the existing contract wins over a
# speculative false-positive.
_MEASURABLE_FENCE_PREFIXES = ("yaml", "yml")


def _fence_is_measurable(info: str) -> bool:
    # Compare the LANGUAGE WORD exactly. A prefix test let ```yaml-not and
    # ```yamlish pass as the canonical schema block, so illustrative
    # content could satisfy layer (h). An info string may still carry
    # attributes after the language (```yaml linenums), so only the first
    # whitespace-delimited word is compared.
    return info.split()[0] in _MEASURABLE_FENCE_PREFIXES if info else False


# CommonMark: a fence may be indented at most 3 spaces (4+ is an indented
# code block), and a CLOSING fence may not carry an info string.
_MAX_FENCE_INDENT = 3

# A tab advances to the next 4-column stop; it is not one column. Counting
# raw characters let a single leading tab read as indent 1, so a
# tab-indented ```text fence opened a block and HID the overlong tldr
# below it (CommonMark makes that line indented code, not a fence).
_TAB_STOP = 4


def _indent_columns(raw: str) -> tuple[int, str]:
    """(column width of the leading whitespace, the rest of the line)."""
    col = 0
    i = 0
    for ch in raw:
        if ch == " ":
            col += 1
        elif ch == "\t":
            col += _TAB_STOP - (col % _TAB_STOP)
        else:
            break
        i += 1
    return col, raw[i:]


def _fence_context(raw: str) -> tuple[int, str]:
    """Indent *inside* any list containers, and the content after them.

    A fence nested directly under a list marker (``- ```text``) is a
    fenced code child of that item. Measuring indent from column 0 missed
    it entirely, so its body was read as the agent's own prose and the
    indented closing delimiter was then mistaken for a NEW opening fence.
    """
    col, rest = _indent_columns(raw)
    for _ in range(8):
        m = _LIST_MARKER.match(rest)
        if not m:
            break
        rest = rest[m.end():]
        col, rest = _indent_columns(rest)
    return col, rest


def lines(text: str) -> list[LineCtx]:
    """Classify every physical line of `text`."""
    out: list[LineCtx] = []
    in_fence = False
    fence_mark = ""
    fence_info = ""
    in_quote = False
    for idx, raw in enumerate(text.splitlines()):
        indent, content = _fence_context(raw)
        stripped = content.strip()
        marker = fence_marker(stripped)
        is_delim = False
        if marker is not None and indent <= _MAX_FENCE_INDENT:
            info = stripped.lstrip("`~").strip().lower()
            # CommonMark forbids a backtick inside a BACKTICK fence's info
            # string, so ```text`bad is not a fence opener at all. Treating
            # it as one hid the following overlong tldr.
            if marker[0] == "`" and "`" in info:
                marker = None
        if marker is not None and indent <= _MAX_FENCE_INDENT:
            if not in_fence:
                is_delim = True
                in_fence = True
                fence_mark = marker
                fence_info = info
            elif (marker[0] == fence_mark[0]
                    and len(marker) >= len(fence_mark)
                    and not info):
                # A closing fence carries NO info string. Accepting
                # trailing text meant ```still-inside closed an enclosing
                # ```text block, after which quoted fixture content below
                # it was measured as the agent's own tldr.
                is_delim = True
                in_fence = False
                fence_mark = ""
                fence_info = ""
        marked_quote = _is_quoted(raw)
        # CommonMark lazy continuation: a non-blank paragraph line
        # directly under a blockquote is still inside it. A blank line, a
        # fence, a heading or a new list item ends the quote.
        blank = not raw.strip()
        starts_new_block = (
            is_delim or in_fence
            or raw.lstrip().startswith("#")
            or bool(_LIST_MARKER.match(raw.lstrip()))
        )
        lazy = (in_quote and not blank and not marked_quote
                and not starts_new_block)
        quoted = marked_quote or lazy
        in_quote = quoted and not blank

        measurable_fence = not in_fence or _fence_is_measurable(fence_info)
        countable = (not is_delim) and (not quoted) and measurable_fence
        # Presence is generous: a lazily-continued line is not measured,
        # but a tldr written there is still the agent's own sentence.
        attributable = (not is_delim) and (not marked_quote) \
            and measurable_fence
        out.append(LineCtx(
            index=idx, raw=raw, in_fence=in_fence, fence_info=fence_info,
            is_fence_delim=is_delim, quoted=quoted, countable=countable,
            attributable=attributable,
        ))
    return out


# Characters that carry no meaning on their own. A "summary" consisting of
# these is the emptiest possible way to satisfy a presence check while
# saying nothing — the same vacuity `tldr:` with no value had.
_PUNCT_ONLY = re.compile(r"^[\s\W_]*$", re.UNICODE)


def has_substance(s: str) -> bool:
    """True when `s` contains at least one letter, digit or CJK character."""
    if not s:
        return False
    return not _PUNCT_ONLY.match(s)
