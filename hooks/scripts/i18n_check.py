#!/usr/bin/env python3
"""cc-enslaver — i18n sync checker (language version control).

English is the *skeleton* (source-of-truth) language: the root ``.md``
files under ``rules/`` and ``prompts/`` define the canonical structure.
Every translation lives in a language-code subdirectory (``rules/zh/``,
``prompts/zh/``, ``rules/<code>/``, …) and must track the skeleton
section-for-section.

This script enforces that contract as a *hard* check (CLAUDE.md §2.9 /
rule 07 — "every modifier word lands as a hard action, not soft docs").
It is wired into CI via ``tests/test_i18n_sync.py``, so any structural
drift between a translation and the English skeleton fails the build.

What it checks, for each translation subdir under each skeleton root:

  1. **File-set parity** — every skeleton ``*.md`` has a same-named
     translation (``missing_file``), and the translation has no file
     absent from the skeleton (``orphan_file``).
  2. **Section-structure parity** — for each shared file, the sequence
     of ATX markdown header levels (e.g. ``[1, 2, 2, 3]``) must be
     identical. Header *text* is intentionally NOT compared (it is
     translated); only the structural skeleton (how many sections, at
     what nesting depth, in what order) must match. Fenced code blocks
     are skipped so ``#`` comments inside ```` ```bash ```` / ```` ```yaml ````
     blocks are not mistaken for headers.

Usage::

    python hooks/scripts/i18n_check.py           # report + exit 1 on drift
    python hooks/scripts/i18n_check.py --quiet    # exit code only

No third-party deps (CLAUDE.md contract). Importable: ``check_sync()``
returns a ``list[Drift]``; an empty list means fully in sync.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path

# Plugin root = two levels up from hooks/scripts/i18n_check.py
PLUGIN_ROOT = Path(__file__).resolve().parents[2]

# Skeleton roots whose root-level ``*.md`` files are the English source
# of truth and whose immediate subdirectories are translations.
SKELETON_ROOTS = ("rules", "prompts")


@dataclass(frozen=True)
class Drift:
    """One structural mismatch between a translation and the skeleton."""
    root: str      # "rules" / "prompts"
    lang: str      # translation subdir name, e.g. "zh"
    file: str      # filename, or "" for a dir-level drift
    kind: str      # "missing_file" | "orphan_file" | "header_structure"
    detail: str

    def __str__(self) -> str:
        loc = f"{self.root}/{self.lang}"
        if self.file:
            loc += f"/{self.file}"
        return f"[{self.kind}] {loc}: {self.detail}"


def _fence_run(stripped_line: str) -> str | None:
    """Return the full fence run (e.g. '```' / '````'), or None.

    Mirrors stop_guard._fence_marker — both files track markdown fences
    and must agree, so the contract lives in both with the same shape.
    """
    for ch in ("`", "~"):
        if stripped_line.startswith(ch * 3):
            run = len(stripped_line) - len(stripped_line.lstrip(ch))
            return ch * run
    return None


def _header_levels(text: str) -> list[int]:
    """Return the ATX header level of every heading outside code fences.

    A markdown ATX header is 1-6 leading ``#`` followed by whitespace or
    end-of-line. Fenced code blocks (```` ``` ```` / ``~~~``) are skipped so
    ``#`` comments inside code samples do not register as headers.
    """
    out: list[int] = []
    in_fence = False
    fence_marker = ""
    for line in text.splitlines():
        stripped = line.lstrip()
        # Toggle fenced code blocks. A fence closes only on the same
        # character AND a run at least as long as the opener — per
        # CommonMark, a ``` line inside a ```` block is content, not a
        # closing fence. (v0.25: the old 3-char truncation let a nested
        # fence close its parent, after which the parent's remaining body
        # was scanned as prose and any `#` comment in it registered as a
        # phantom ATX header, corrupting the header-level sequence this
        # checker compares across languages.)
        marker = _fence_run(stripped)
        if marker is not None:
            if not in_fence:
                in_fence = True
                fence_marker = marker
            elif marker[0] == fence_marker[0] and len(marker) >= len(fence_marker):
                in_fence = False
                fence_marker = ""
            continue
        if in_fence:
            continue
        # Count leading '#'.
        i = 0
        while i < len(line) and line[i] == "#":
            i += 1
        if 1 <= i <= 6 and (i == len(line) or line[i] in " \t"):
            out.append(i)
    return out


def _md_files(d: Path) -> set[str]:
    """Names of ``*.md`` files directly in ``d`` (non-recursive)."""
    if not d.is_dir():
        return set()
    return {p.name for p in d.iterdir() if p.is_file() and p.suffix == ".md"}


def _translation_dirs(root: Path) -> list[Path]:
    """Immediate subdirs of ``root`` holding translations.

    Every immediate subdirectory counts as a translation (so a new
    language is discovered automatically — no allow-list to maintain).
    Hidden dirs and ``__pycache__`` are skipped.
    """
    if not root.is_dir():
        return []
    out: list[Path] = []
    for p in sorted(root.iterdir()):
        if not p.is_dir():
            continue
        if p.name.startswith(".") or p.name == "__pycache__":
            continue
        out.append(p)
    return out


def check_sync(plugin_root: Path | None = None) -> list[Drift]:
    """Compare every translation subdir against its English skeleton root.

    Returns a list of ``Drift`` records (empty list = fully in sync).
    """
    base = plugin_root or PLUGIN_ROOT
    drifts: list[Drift] = []
    for root_name in SKELETON_ROOTS:
        root = base / root_name
        skeleton_files = _md_files(root)
        for tdir in _translation_dirs(root):
            lang = tdir.name
            trans_files = _md_files(tdir)
            # 1. File-set parity.
            for missing in sorted(skeleton_files - trans_files):
                drifts.append(Drift(
                    root_name, lang, missing, "missing_file",
                    "skeleton file has no translation here",
                ))
            for orphan in sorted(trans_files - skeleton_files):
                drifts.append(Drift(
                    root_name, lang, orphan, "orphan_file",
                    "translation file has no matching skeleton file",
                ))
            # 2. Section-structure parity for shared files.
            for name in sorted(skeleton_files & trans_files):
                sk = _header_levels((root / name).read_text(encoding="utf-8"))
                tr = _header_levels((tdir / name).read_text(encoding="utf-8"))
                if sk != tr:
                    drifts.append(Drift(
                        root_name, lang, name, "header_structure",
                        f"skeleton has {len(sk)} headers {sk}, "
                        f"{lang} has {len(tr)} {tr}",
                    ))
    return drifts


def _out(s: str) -> None:
    """Write UTF-8 to stdout regardless of the platform code page.

    On Windows the default stdout encoding is the system code page
    (e.g. cp936), which would mangle the ``rules/`` paths' non-ASCII and
    any CJK in a detail message. Emit UTF-8 bytes directly.
    """
    sys.stdout.buffer.write(s.encode("utf-8"))
    sys.stdout.buffer.flush()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="cc-enslaver i18n sync checker (English is the skeleton)",
    )
    parser.add_argument(
        "--quiet", action="store_true",
        help="exit code only; suppress the report",
    )
    args = parser.parse_args(argv)

    drifts = check_sync()
    if not drifts:
        if not args.quiet:
            _out("cc-enslaver i18n: all translations in sync with the "
                 "English skeleton.\n")
        return 0
    if not args.quiet:
        _out(f"cc-enslaver i18n: {len(drifts)} drift(s) vs the English "
             f"skeleton:\n\n")
        for d in drifts:
            _out(f"  {d}\n")
        _out("\nEnglish is the skeleton (source of truth). On drift, update "
             "the translation to match the skeleton — see docs/I18N.md.\n")
    return 1


if __name__ == "__main__":
    sys.exit(main())
