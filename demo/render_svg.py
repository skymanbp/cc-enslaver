"""Render a captured transcript as a terminal-style SVG.

Why SVG and not a screenshot: a screenshot is a picture of a claim. This is
generated from the transcript `run_demo.py` just captured, so re-running the
demo re-renders the image, and `tests/test_demo.py` fails if the committed
image no longer matches what the hooks produce. An image that cannot go
stale is worth more than one that merely looks authentic.

Zero dependencies — the SVG is assembled as text, the same way everything
else in this repo avoids adding a package to draw a box.
"""
from __future__ import annotations

import unicodedata
from pathlib import Path

FONT = ("ui-monospace, SFMono-Regular, 'SF Mono', Menlo, Consolas, "
        "'DejaVu Sans Mono', monospace")
FONT_SIZE = 13
LINE_H = 19
CHAR_W = 7.82          # advance width of FONT_SIZE 13 in a monospace face
PAD_X, PAD_TOP, PAD_BOT = 18, 46, 18

BG = "#0d1117"
CHROME = "#161b22"
FG = "#c9d1d9"
DIM = "#8b949e"
CMD = "#58a6ff"
AGENT = "#d2a8ff"
DENY = "#ff7b72"
GOOD = "#3fb950"
WARN = "#d29922"


def _cols(text: str) -> int:
    """Display columns: an East-Asian wide character occupies two."""
    width = 0
    for ch in text:
        if unicodedata.combining(ch):
            continue
        width += 2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1
    return width


def _colour(line: str) -> tuple[str, bool]:
    """(fill, bold) for one transcript line, decided by its shape."""
    s = line.strip()
    if line.startswith("$ "):
        return CMD, True
    if line.startswith("agent>"):
        return AGENT, False
    if s.startswith("cc-enforcer ·"):
        return DENY, True
    if s.startswith(("LOUD:", "SILENT:", "FAILED", "AssertionError", "KeyError")):
        return DENY, False
    if s.startswith(("HANDLED:", "OK", "applied")):
        return GOOD, False
    if "FAIL" in s or "DENY" in s or "Pattern matched" in s:
        return DENY, False
    if s.startswith(("...", "  The ", "The ")):
        return DIM, False
    if s.startswith(("|", "Tool:", "Target:", "Rolling-patch", "Done-claim",
                     "[Recovery", "大白话", "Snippet", "Per rule", ">")):
        return WARN, False
    return FG, False


def _esc(text: str) -> str:
    return (text.replace("&", "&amp;").replace("<", "&lt;")
                .replace(">", "&gt;").replace('"', "&quot;"))


def render(lines: list[str], out: Path, title: str) -> Path:
    body = [l.rstrip() for l in lines]
    cols = max([_cols(l) for l in body] + [_cols(title) + 8])
    width = int(cols * CHAR_W) + PAD_X * 2
    height = len(body) * LINE_H + PAD_TOP + PAD_BOT

    head_fill = GOOD if "WITH cc" in title and "WITHOUT" not in title else DENY
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" '
        f'height="{height}" viewBox="0 0 {width} {height}" '
        f'font-family="{FONT}" font-size="{FONT_SIZE}">',
        f'<rect width="{width}" height="{height}" rx="8" fill="{BG}"/>',
        f'<rect width="{width}" height="30" rx="8" fill="{CHROME}"/>',
        f'<rect y="22" width="{width}" height="8" fill="{CHROME}"/>',
        '<circle cx="18" cy="15" r="5" fill="#ff5f56"/>',
        '<circle cx="36" cy="15" r="5" fill="#ffbd2e"/>',
        '<circle cx="54" cy="15" r="5" fill="#27c93f"/>',
        f'<text x="72" y="19" fill="{head_fill}" font-weight="700">'
        f'{_esc(title)}</text>',
    ]
    for i, line in enumerate(body):
        if not line:
            continue
        fill, bold = _colour(line)
        weight = ' font-weight="700"' if bold else ""
        y = PAD_TOP + i * LINE_H
        parts.append(
            f'<text x="{PAD_X}" y="{y}" fill="{fill}"{weight} '
            f'xml:space="preserve">{_esc(line)}</text>'
        )
    parts.append("</svg>")
    out.write_text("\n".join(parts) + "\n", encoding="utf-8")
    return out
