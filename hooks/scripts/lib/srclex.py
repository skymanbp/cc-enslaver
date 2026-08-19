#!/usr/bin/env python3
"""cc-enforcer — tolerant source lexer (comments / strings / block shape).

Root cause this module exists to kill (v0.26.0 audit, root cause α):
every content detector in this plugin used *text* as a proxy for a
*lexical* fact, and each audit round produced a fresh crop of the same
defect:

  * "is this ``#`` a comment?"  ->  ``line.find("#")``, which finds the
    ``#`` inside ``"http://host/#frag"`` and inside any string literal.
    A neighbouring URL therefore satisfied the rule-09 / 10 / 11
    rationale hatch and silenced the detector (an adjacent
    ``https://…example.com…`` line disabled the SECRET detector outright).
  * "where does this ``try`` block end?"  ->  indentation of *physical*
    lines, so the body of a multi-line string re-anchored the block and a
    real swallow after it went unseen.
  * "is this an ``except`` clause?"  ->  a single physical line, so
    ``except (\\n    ValueError,\\n):`` was never inspected at all.

The answer to all three is the same primitive: a **lexer**, not a parser.
Whether a ``#`` is a comment is a lexical question, and — unlike parsing
— lexing works on the *fragments* these hooks actually receive (an Edit's
``new_string`` is rarely a syntactically complete module, so
``ast``/``tokenize`` would raise on ordinary input and force a fallback
that recreates the original bug).

Public API
----------
``comment_text(text, lang)``   only the comment portions, one per line
``mask_literals(text, lang)``  string contents blanked, offsets preserved
``logical_lines(text, lang)``  physical lines joined across open brackets

All three are total: any input returns a result, never raises.
"""

from __future__ import annotations

import re

# Languages we lex. "auto" applies both comment styles, which is correct
# for the read-before-edit guard's default (it scans content whose
# language it may not know) and matches the pre-v0.26 behaviour, minus
# the string-blindness that made it wrong.
_HASH_LANGS = {"py", "sh", "yaml", "toml", "rb", "auto"}
_SLASH_LANGS = {"js", "ts", "jsx", "tsx", "c", "cpp", "java", "go", "rs",
                "cs", "swift", "kt", "auto"}

_EXT_LANG = {
    ".py": "py", ".pyi": "py", ".sh": "sh", ".bash": "sh",
    ".yaml": "yaml", ".yml": "yaml", ".toml": "toml", ".rb": "rb",
    ".js": "js", ".mjs": "js", ".cjs": "js", ".jsx": "jsx",
    ".ts": "ts", ".tsx": "tsx", ".c": "c", ".h": "c",
    ".cpp": "cpp", ".hpp": "cpp", ".cc": "cpp",
    ".java": "java", ".go": "go", ".rs": "rs", ".cs": "cs",
    ".swift": "swift", ".kt": "kt",
}


def lang_for_path(file_path: str) -> str:
    """Best-effort language tag from a filename; 'auto' when unknown."""
    lowered = (file_path or "").lower()
    for ext, lang in _EXT_LANG.items():
        if lowered.endswith(ext):
            return lang
    return "auto"


# Span kinds produced by the scanner.
_CODE = "code"
_COMMENT = "comment"
_STRING = "string"
# A triple-quoted block is documentation, not data. It is tracked
# separately so the rationale hatch can accept a why-note written in a
# docstring -- which is what well-documented code actually does -- while
# still refusing a token that merely appears inside a DATA literal such
# as a URL. That distinction is the whole point: the leak being closed
# was `API = "https://api.example.com"` silencing the secret detector,
# and a triple-quoted documentation block is not that.
_DOCSTRING = "docstring"


# A line ends at CR as well as LF. Reading only "\n" meant a lone-CR file
# (old-Mac line endings, and anything a tool emits with `\r` separators)
# let a `#` comment span run to end-of-text, so every credential after it
# was classified as comment prose and the rule-10 detector went silent.
def _line_end(text: str, i: int, n: int) -> int:
    lf = text.find("\n", i)
    cr = text.find("\r", i)
    return min(lf if lf != -1 else n, cr if cr != -1 else n)


def _line_start(text: str, i: int) -> int:
    return max(text.rfind("\n", 0, i), text.rfind("\r", 0, i)) + 1


# Python string prefixes. Scanning starts at the quote, so an `r"""…"""`
# docstring used to look indented-by-`r` and was demoted to a data
# literal — rejecting a rationale written in a raw docstring.
_STRING_PREFIX_CHARS = "rbfuRBFU"
_MAX_STRING_PREFIX = 2

_DEF_OR_CLASS = re.compile(r"^(?:async\s+)?(?:def|class)\b")


def _literal_prefix_start(text: str, i: int) -> int:
    """Offset where a string literal's r/b/f/u prefix begins (else `i`)."""
    j = i
    while j > 0 and (i - j) < _MAX_STRING_PREFIX \
            and text[j - 1] in _STRING_PREFIX_CHARS:
        j -= 1
    return j


def _is_docstring_position(text: str, quote_start: int) -> bool:
    """True when a triple-quoted block sits where a docstring may appear.

    "Starts its own line" is not sufficient, and treating it as such was a
    rationale bypass: a bare

        x = 1
        \"\"\"because upstream requires it\"\"\"
        password = "…"

    is a discarded string *expression*, not documentation, yet it silenced
    the adjacent secret detector. A docstring is the first statement of a
    module, class or function, which is decidable lexically: nothing but
    blank/comment lines before it (module docstring), or the previous
    statement is a `def`/`class` header. Anything else is data.
    """
    start = _literal_prefix_start(text, quote_start)
    ls = _line_start(text, start)
    if text[ls:start].strip():
        return False
    k = ls
    while k > 0:
        prev_end = k - 1
        prev_start = _line_start(text, prev_end)
        prev = text[prev_start:prev_end].strip()
        if prev and not prev.startswith("#"):
            return bool(_DEF_OR_CLASS.match(prev)) and prev.endswith(":")
        if prev_start == 0:
            break
        k = prev_start
    # Only blanks and comments precede it: a module docstring.
    return True


def _scan(text: str, lang: str) -> list[tuple[str, int, int]]:
    """Classify `text` into (kind, start, end) spans.

    A hand-rolled single pass rather than `tokenize`: it must not raise on
    a fragment, an unterminated literal, or a language it guessed wrong.
    Unterminated constructs simply run to end-of-text, which keeps the
    conservative direction (their content is not mistaken for code).
    """
    hash_comments = lang in _HASH_LANGS
    slash_comments = lang in _SLASH_LANGS
    # Backtick template literals exist in JS/TS; in Python a backtick is
    # not a string delimiter, so only enable it for slash-comment langs.
    quotes = "'\"`" if slash_comments and not hash_comments else "'\""

    spans: list[tuple[str, int, int]] = []
    n = len(text)
    i = 0
    seg_start = 0

    def close_code(upto: int) -> None:
        if upto > seg_start:
            spans.append((_CODE, seg_start, upto))

    while i < n:
        ch = text[i]

        # --- line comment -------------------------------------------- #
        if hash_comments and ch == "#":
            close_code(i)
            end = _line_end(text, i, n)
            spans.append((_COMMENT, i, end))
            i = seg_start = end
            continue
        if slash_comments and ch == "/" and text.startswith("//", i):
            close_code(i)
            end = _line_end(text, i, n)
            spans.append((_COMMENT, i, end))
            i = seg_start = end
            continue

        # --- block comment ------------------------------------------- #
        if slash_comments and ch == "/" and text.startswith("/*", i):
            close_code(i)
            end = text.find("*/", i + 2)
            end = n if end == -1 else end + 2
            spans.append((_COMMENT, i, end))
            i = seg_start = end
            continue

        # --- string literal ------------------------------------------ #
        if ch in quotes:
            close_code(i)
            triple = text[i:i + 3]
            kind = _STRING
            if hash_comments and len(triple) == 3 and triple in ('"""', "'''"):
                # An ESCAPED delimiter does not close the block. Searching
                # for the bare run terminated the docstring early, and
                # everything after it was then reclassified as code and
                # comments — so a `#` line that is really string content
                # became rationale text and silenced an adjacent marker.
                # Backslashes are counted because `\\` is itself escaped:
                # an even run leaves the quote unescaped.
                j = i + 3
                end = n
                while True:
                    k = text.find(triple, j)
                    if k == -1:
                        break
                    b = 0
                    while k - 1 - b >= 0 and text[k - 1 - b] == "\\":
                        b += 1
                    if b % 2 == 0:
                        end = k + 3
                        break
                    j = k + 1
                # Documentation only in DOCSTRING POSITION. `SQL = """…"""`
                # is data that happens to be triple-quoted, and so is a
                # bare string expression in the middle of a function;
                # treating either as documentation reopens the very leak
                # this module exists to close, just with a wider quote.
                if _is_docstring_position(text, i):
                    kind = _DOCSTRING
            else:
                j = i + 1
                end = n
                # POSIX single quotes take NO escapes: `'a\'` ends at that
                # quote and the rest of the line is a real comment. Honouring
                # the backslash swallowed the comment and rejected a valid
                # adjacent rationale.
                raw_single = (lang == "sh" and ch == "'")
                while j < n:
                    c = text[j]
                    if c == "\\" and not raw_single:
                        j += 2
                        continue
                    if c == ch:
                        end = j + 1
                        break
                    # A single-quoted literal does not span lines (except
                    # via a backslash continuation, handled above). Stop
                    # at the line break -- CR as well as LF -- so an
                    # apostrophe in a prose line cannot swallow the file.
                    if c in "\n\r" and ch != "`":
                        end = j
                        break
                    j += 1
            spans.append((kind, i, end))
            i = seg_start = end
            continue

        i += 1

    close_code(n)
    return spans


def comment_text(text: str, lang: str = "auto",
                 include_docstrings: bool = True) -> str:
    """Return the human-documentation portions of `text`, one per line.

    This is what the rule-09 / 10 / 11 rationale hatch searches. Its own
    deny message promises a "why-**comment**", so a token sitting in
    executable code — or, the leak this replaces, inside a DATA literal
    such as a URL — must not satisfy it.

    Triple-quoted blocks are included by default: a module or function
    docstring explaining why a suppression is warranted is exactly the
    documentation the rule asks for, and excluding it would reject
    well-documented code. Single-quoted literals stay excluded, which is
    where the leak actually lived.
    """
    if not text:
        return ""
    wanted = {_COMMENT}
    if include_docstrings:
        wanted.add(_DOCSTRING)
    out: list[str] = []
    for kind, start, end in _scan(text, lang):
        if kind in wanted:
            out.append(text[start:end])
    return "\n".join(out)


def doc_spans(text: str, lang: str = "auto",
              include_docstrings: bool = True) -> list[tuple[int, int]]:
    """Return (start, end) char spans of comments (and docstrings).

    Exists so a caller can ask "is THIS range documentation?" against the
    lexical state of the WHOLE text. Re-lexing a small window in isolation
    gets the wrong answer: a three-line window inside a docstring contains
    no `\"\"\"` delimiter, so the window alone looks like bare code. The
    rationale hatch reads a +/-1 line window, which is almost never big
    enough to contain its own opener.
    """
    if not text:
        return []
    wanted = {_COMMENT}
    if include_docstrings:
        wanted.add(_DOCSTRING)
    return [(s, e) for kind, s, e in _scan(text, lang) if kind in wanted]


def comment_text_in_range(text: str, lo: int, hi: int,
                          lang: str = "auto") -> str:
    """Documentation text of `text[lo:hi]`, judged by the whole text.

    The companion to `doc_spans`: the classification comes from lexing
    everything, the extraction is clipped to the requested range.
    """
    if not text or hi <= lo:
        return ""
    out: list[str] = []
    for start, end in doc_spans(text, lang):
        s, e = max(start, lo), min(end, hi)
        if s < e:
            out.append(text[s:e])
    return "\n".join(out)


def mask_literals(text: str, lang: str = "auto") -> str:
    """Blank out string bodies, preserving length, offsets and newlines.

    Block-structure analysis runs on the masked text so that the *content*
    of a multi-line string can never be mistaken for code at column 0.
    Newlines inside the literal are preserved so line numbering — and
    therefore every reported offset — stays identical to the original.
    """
    if not text:
        return ""
    buf = list(text)
    for kind, start, end in _scan(text, lang):
        # Both literal kinds are masked. Docstrings are split out only for
        # the rationale search; for BLOCK STRUCTURE they are just as much
        # a literal, and their body is precisely what used to re-anchor
        # indentation and hide a later swallow.
        if kind not in (_STRING, _DOCSTRING):
            continue
        for k in range(start, end):
            if buf[k] != "\n":
                buf[k] = " "
    return "".join(buf)


_OPENERS = {"(": ")", "[": "]", "{": "}"}
_CLOSERS = {")", "]", "}"}


def logical_lines(text: str, lang: str = "auto") -> list[tuple[int, str]]:
    """Join physical lines into logical ones across open brackets.

    Returns ``(first_physical_index, joined_code)`` pairs, where the code
    has string bodies masked and comments stripped. A multi-line
    ``except (\\n    ValueError,\\n):`` header therefore arrives at the
    caller as the single logical line it actually is.

    Trailing-backslash continuations are joined too.
    """
    if not text:
        return []
    masked = mask_literals(text, lang)
    # Normalise line breaks before splitting. `split("\n")` alone turns a
    # lone-CR file into ONE logical line, which collapses all block
    # structure -- every try/except shape becomes invisible. CRLF already
    # worked (the stray CR was rstripped); CR alone did not. Indices stay
    # correct because both forms collapse to exactly one break.
    masked = masked.replace("\r\n", "\n").replace("\r", "\n")
    # Strip comments after masking so a `#` inside a literal is safe.
    lines: list[str] = []
    for raw in masked.split("\n"):
        cut = len(raw)
        if lang in _HASH_LANGS:
            k = raw.find("#")
            if k != -1:
                cut = min(cut, k)
        if lang in _SLASH_LANGS:
            k = raw.find("//")
            if k != -1:
                cut = min(cut, k)
        lines.append(raw[:cut])

    out: list[tuple[int, str]] = []
    depth = 0
    start_idx = 0
    buf: list[str] = []
    for idx, line in enumerate(lines):
        if not buf:
            start_idx = idx
        stripped = line.rstrip()
        continued = stripped.endswith("\\")
        body = stripped[:-1] if continued else stripped
        buf.append(body if depth == 0 and not buf else body.strip())
        for ch in body:
            if ch in _OPENERS:
                depth += 1
            elif ch in _CLOSERS:
                depth = max(0, depth - 1)
        if depth == 0 and not continued:
            out.append((start_idx, " ".join(p for p in buf if p != "").rstrip()
                        if len(buf) > 1 else buf[0]))
            buf = []
    if buf:
        out.append((start_idx, " ".join(p for p in buf if p != "")
                    if len(buf) > 1 else buf[0]))
    return out
