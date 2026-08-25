"""Read a hook payload off stdin as UTF-8, whatever the host codepage is.

Every hook entry point receives its payload the same way: Claude Code
writes JSON bytes to the script's stdin. Reading that with the text-mode
``sys.stdin.read()`` is where the payload stops being what was sent.

Why the obvious spelling is wrong
---------------------------------
``sys.stdin`` is a ``TextIOWrapper`` built from the *locale* encoding —
``cp936`` on a Chinese Windows install, ``cp1252`` on a Western one — and
its error handler for the standard streams is ``surrogateescape``, not
``strict``. So a UTF-8 payload is decoded with the wrong table and the
bytes that do not fit are turned into lone surrogates **without raising
anything**. The guard then scans a string that differs from what the
agent actually wrote, and it does so silently: no exception, no stderr,
no failing test.

Measured on Windows 11 / cp936, the em-dash ``—`` (U+2014, bytes
``E2 80 94``) arrives as ``鈥`` + ``\\udc94`` — one character longer than
it left. That single extra character pushed an inline comment past
``read_guard._MIN_INLINE_REASON_CHARS`` and turned a rule-09 DENY into an
ALLOW. Chinese fares worse: ``大白话``, ``同步核对``, ``我觉得`` and every
other CJK marker this plugin looks for decode to mojibake, so on the
repo's primary platform the whole Chinese detection surface matched
nothing at all.

The failure mode is the one this plugin exists to catch — a loud failure
(wrong encoding) quietly converted into a plausible-looking success.

The rule
--------
JSON interchange text is UTF-8 (RFC 8259 §8.1); the hook contract carries
no encoding negotiation. So read **bytes** and decode them **strictly**.
A payload that genuinely is not UTF-8 raises here and hits the caller's
fail-open handler, which writes a traceback to stderr — loud and
diagnosable, rather than silently mangled and scanned anyway.

This is the input-side twin of a convention the emitters have had since
v0.3: they all write through ``sys.stdout.buffer`` with an explicit
``.encode("utf-8")`` for exactly this reason. Only the direction whose
damage was visible got hardened; this module closes the other one.
"""

from __future__ import annotations

import sys

# RFC 8259 §8.1 — JSON exchanged between systems is encoded in UTF-8.
PAYLOAD_ENCODING = "utf-8"


def read_payload_text(stream: object | None = None) -> str:
    """Return the hook payload on `stream` (default stdin) as text.

    Reads the underlying binary buffer and decodes it as UTF-8 with the
    strict error handler, so a malformed payload raises instead of being
    quietly rewritten into something that still parses.

    `stream` is for tests; production always passes nothing.

    A text stream with no `.buffer` (a `StringIO` swapped in by a
    harness) is read directly: nothing was ever encoded there, so there
    is no codepage decision to undo.
    """
    src = sys.stdin if stream is None else stream
    binary = getattr(src, "buffer", None)
    if binary is None:
        return src.read()  # type: ignore[union-attr]  # because a bufferless stream is already text
    return binary.read().decode(PAYLOAD_ENCODING)
