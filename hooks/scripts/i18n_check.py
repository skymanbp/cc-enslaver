#!/usr/bin/env python3
"""cc-enforcer — i18n sync checker (language version control).

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
  3. **Enforcement-token parity** — on any line stating a physical
     enforcement outcome (``DENY`` / ``BLOCK`` / ``拒绝`` / ``拦截``),
     every backtick code span that *looks like a command an agent would
     type* must also appear in the translation (``enforcement_tokens``).
     Prose is translated and structure is compared above, but the
     **tokens an agent is told will be denied are not prose — they are
     the contract**. Until v0.26.0 the Chinese injections listed four of
     the seven patterns bash_guard denies, so a zh session was handed a
     strictly smaller deny set than an en session on every turn, and
     checks 1 and 2 could not see it.

     Two deliberate bounds, both measured rather than guessed: the check
     looks only at enforcement lines (comparing *all* code spans flags 24
     legitimate translation differences in ``rules/``), and only at
     machine-shaped tokens (a first cut demanded translators reproduce
     English prose examples such as ``I created Y.md``). What it does NOT
     do is verify that the enforcement SENTENCE survived translation —
     only that its tokens appear somewhere in the file.

Usage::

    python hooks/scripts/i18n_check.py           # report + exit 1 on drift
    python hooks/scripts/i18n_check.py --quiet    # exit code only

No third-party deps (CLAUDE.md contract). Importable: ``check_sync()``
returns a ``list[Drift]``; an empty list means fully in sync.
"""

from __future__ import annotations

import argparse
import importlib.util
import re
import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib import mdctx  # noqa: E402
# noqa: E402 above because the lib import must follow the sys.path bootstrap

# Plugin root = two levels up from hooks/scripts/i18n_check.py
PLUGIN_ROOT = Path(__file__).resolve().parents[2]

# Skeleton roots whose root-level ``*.md`` files are the English source
# of truth and whose immediate subdirectories are translations.
SKELETON_ROOTS = ("rules", "prompts")


@dataclass(frozen=True)
class Drift:
    """One structural mismatch between a translation and the skeleton."""
    root: str      # "rules" / "prompts" / "messages"
    lang: str      # translation subdir name, e.g. "zh"
    file: str      # filename, or "" for a dir-level drift
    kind: str      # "missing_file" | "orphan_file" | "header_structure"
                   # | "enforcement_tokens" | "missing_key"
                   # | "orphan_key" | "placeholder_fields"
                   # | "empty_value"  (v0.38 message catalogs)
    detail: str

    def __str__(self) -> str:
        loc = f"{self.root}/{self.lang}"
        if self.file:
            loc += f"/{self.file}"
        return f"[{self.kind}] {loc}: {self.detail}"


# v0.30 — the fence-run helper is `mdctx.fence_marker`, imported above.
# It used to be copied here verbatim under the comment "Mirrors
# stop_guard._fence_marker — both files track markdown fences and must
# agree, so the contract lives in both with the same shape." Writing that
# down is not the same as enforcing it: there were three copies, and the
# v0.25 CommonMark fix (a closing fence must be at least as long as its
# opener) had to be applied to each one separately. One definition, three
# consumers.
_fence_run = mdctx.fence_marker


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


_CODE_SPAN = re.compile(r"`([^`\n]+)`")

# Words that mark a line as stating a physical enforcement consequence.
#
# v0.26.0 audit — the first cut matched only the literal ``DENY``, which
# left NINE of the thirteen English rule files contributing zero tokens.
# Rule 12's entire contract is a Stop-layer ``BLOCK``, so the check passed
# it vacuously: "no enforcement statements found" was indistinguishable
# from "all enforcement statements translated". The Chinese verbs are
# included because a translation states its consequence in its own
# language while keeping the code spans verbatim.
_ENFORCEMENT_WORDS = ("DENY", "BLOCK", "拒绝", "拒絕", "拦截", "攔截")

# Not every code span on an enforcement line is part of the deny set: the
# line also carries the explicitly-ALLOWED exception, tool names, and
# prose examples. A blacklist of those was tried first and immediately
# leaked (`I created Y.md`, `$ command + output`, `tldr: "<one plain
# sentence>"` all became mandatory vocabulary for translators), so the
# test is positive instead: a required token must LOOK like something an
# agent types at a shell — lowercase words and flags, at most three of
# them. Prose, placeholders and capitalised tool names fall out by
# construction.
_MACHINE_WORD = re.compile(r"^[-+]{0,2}[a-z0-9][\w./\\-]*$")
_MAX_MACHINE_WORDS = 3

# The allowed exception and the rationale tokens are lowercase machine-ish
# words that are nonetheless NOT denied; they stay excluded by name.
_ENFORCEMENT_TOKEN_EXCLUDE = {
    "--force-with-lease", "because", "essential", "new_string", "content",
}


def _is_machine_token(tok: str) -> bool:
    words = tok.split()
    if not words or len(words) > _MAX_MACHINE_WORDS:
        return False
    return all(_MACHINE_WORD.match(w) for w in words)


def _enforcement_tokens(text: str) -> set[str]:
    """Backtick code spans on lines stating a physical enforcement outcome.

    Scoped to those lines deliberately: comparing *every* code span across
    languages flags 24 legitimate translation differences in ``rules/``,
    which would make the check unusable.
    """
    out: set[str] = set()
    for line in text.splitlines():
        if any(w in line for w in _ENFORCEMENT_WORDS):
            out.update(t for t in _CODE_SPAN.findall(line)
                       if _is_machine_token(t))
    return out - _ENFORCEMENT_TOKEN_EXCLUDE


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
                sk_text = (root / name).read_text(encoding="utf-8")
                tr_text = (tdir / name).read_text(encoding="utf-8")
                sk = _header_levels(sk_text)
                tr = _header_levels(tr_text)
                if sk != tr:
                    drifts.append(Drift(
                        root_name, lang, name, "header_structure",
                        f"skeleton has {len(sk)} headers {sk}, "
                        f"{lang} has {len(tr)} {tr}",
                    ))
                # 3. Enforcement-token parity. Compared against the whole
                # translation, not line-for-line: a translation may lay the
                # table out differently, but it may not drop a token.
                absent = sorted(t for t in _enforcement_tokens(sk_text)
                                if t not in tr_text)
                if absent:
                    drifts.append(Drift(
                        root_name, lang, name, "enforcement_tokens",
                        f"{lang} never mentions {absent} — the skeleton "
                        f"states these are DENIED, so this translation "
                        f"promises a smaller deny set than the skeleton",
                    ))
    return drifts


# --------------------------------------------------------------------------- #
# v0.38 — message-catalog parity.
#
# The guards' user-facing text lives in `lib/messages_en.py` (skeleton) and
# `lib/messages_<lang>.py` (translations). Those are Python dicts rather than
# markdown, so the structural comparison is different from the one above — and
# strictly stronger. A markdown translation can only be checked on heading
# shape; a dict can be checked on the exact key set AND on the format fields
# each value carries.
#
# The placeholder check is the one that matters at runtime: a translation that
# drops `{file_path}` silently tells the user less than the skeleton does, and
# one that invents a field raises KeyError inside `str.format` — in the hook,
# in front of the user, at the moment they are already being denied.
# --------------------------------------------------------------------------- #
# Split across concatenation so this file does not contain the phrase it
# searches for — the same self-scan technique read_guard and bash_guard use
# on their own literals. Spelling it whole made THIS module look like a
# catalog consumer, which un-skipped it and made the docstring example
# above read as a real request. (See `_keys_the_guards_ask_for`.)
_CATALOG_IMPORT = "from lib " + "import messages"

_CATALOG_DIR = ("hooks", "scripts", "lib")
_SKELETON_CATALOG = "messages_en.py"
_CATALOG_GLOB = "messages_*.py"

# `{field}` but not `{{escaped}}` — the doubled form is a literal brace in the
# rendered message and carries no field.
_FIELD = re.compile(r"(?<!\{)\{([a-zA-Z_][a-zA-Z0-9_]*)")


def _load_catalog(path: Path) -> dict[str, str]:
    spec = importlib.util.spec_from_file_location(f"_i18n_{path.stem}", path)
    if spec is None or spec.loader is None:
        return {}
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    got = getattr(mod, "MESSAGES", None)
    return got if isinstance(got, dict) else {}


def _keys_the_guards_ask_for(base: Path) -> set[str]:
    """Every catalog key the hook scripts request, literal or computed.

    Literal `messages.text("a.b")` calls are read straight out of the
    source. The two computed families cannot be — they are f-strings over
    a layer letter or a pattern slug — so their generators are read from
    the same source and expanded here. Without this, a renamed key would
    only surface at runtime, as `<<missing message: …>>` inside a deny the
    user is already annoyed by.
    """
    scripts = base / "hooks" / "scripts"
    wanted: set[str] = set()
    for path in sorted(scripts.glob("*.py")):
        text = path.read_text(encoding="utf-8")
        # Only files that actually consume the catalog. Without this the
        # scan reads its own prose: the docstring above names a
        # `messages.text("a.b")` example, and the first run of this check
        # duly reported that a guard requests a key called `a.b`. A file
        # that never imports the catalog cannot be asking it for anything.
        if _CATALOG_IMPORT not in text:
            continue
        wanted |= set(re.findall(r'messages\.text\(\s*"([a-z0-9_.]+)"', text))
        # stop_guard's per-layer families: `messages.text(f"stop.x.{c}")`
        for fam in re.findall(r'messages\.text\(f"([a-z_.]+)\.\{c\}"\)', text):
            ids = re.search(r'_LAYER_IDS\s*=\s*"([a-z]+)"', text)
            for ch in (ids.group(1) if ids else ""):
                wanted.add(f"{fam}.{ch}")
        # bash_guard's per-pattern families.
        if re.search(r'messages\.text\(f"bash\.pattern\.', text):
            slugs = re.findall(r'^\s*\("([a-z0-9_]+)",', text, re.M)
            for slug in slugs:
                wanted.add(f"bash.pattern.{slug}.name")
                wanted.add(f"bash.pattern.{slug}.explanation")
    return wanted


def check_message_catalogs(plugin_root: Path | None = None) -> list[Drift]:
    """Key-set + placeholder parity for the guard message catalogs."""
    base = plugin_root or PLUGIN_ROOT
    lib = base.joinpath(*_CATALOG_DIR)
    skeleton_path = lib / _SKELETON_CATALOG
    drifts: list[Drift] = []
    if not skeleton_path.is_file():
        return [Drift("messages", "-", _SKELETON_CATALOG, "missing_file",
                      "the English message skeleton is absent")]
    skeleton = _load_catalog(skeleton_path)

    # 1. Every key a guard asks for must exist in the skeleton.
    for key in sorted(_keys_the_guards_ask_for(base) - set(skeleton)):
        drifts.append(Drift(
            "messages", "en", _SKELETON_CATALOG, "missing_key",
            f"a guard requests `{key}` but the skeleton has no such key — "
            f"it would render as a <<missing message>> marker",
        ))

    for path in sorted(lib.glob(_CATALOG_GLOB)):
        if path.name == _SKELETON_CATALOG:
            continue
        lang = path.stem[len("messages_"):]
        trans = _load_catalog(path)
        # 2. Key-set parity, both directions.
        for missing in sorted(set(skeleton) - set(trans)):
            drifts.append(Drift(
                "messages", lang, path.name, "missing_key",
                f"`{missing}` is untranslated (it falls back to English, "
                f"so the session would mix languages)",
            ))
        for orphan in sorted(set(trans) - set(skeleton)):
            drifts.append(Drift(
                "messages", lang, path.name, "orphan_key",
                f"`{orphan}` has no skeleton counterpart — nothing reads it",
            ))
        # 3. Placeholder parity per shared key.
        for key in sorted(set(skeleton) & set(trans)):
            sk = set(_FIELD.findall(skeleton[key]))
            tr = set(_FIELD.findall(trans[key]))
            if sk != tr:
                drifts.append(Drift(
                    "messages", lang, path.name, "placeholder_fields",
                    f"`{key}`: skeleton has {sorted(sk)}, {lang} has "
                    f"{sorted(tr)} — dropped fields silently say less, "
                    f"invented ones raise inside str.format at deny time",
                ))
            if not trans[key].strip():
                drifts.append(Drift(
                    "messages", lang, path.name, "empty_value",
                    f"`{key}` is blank — a guard would emit an empty message",
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
        description="cc-enforcer i18n sync checker (English is the skeleton)",
    )
    parser.add_argument(
        "--quiet", action="store_true",
        help="exit code only; suppress the report",
    )
    args = parser.parse_args(argv)

    drifts = check_sync() + check_message_catalogs()
    if not drifts:
        if not args.quiet:
            _out("cc-enforcer i18n: all translations in sync with the "
                 "English skeleton.\n")
        return 0
    if not args.quiet:
        _out(f"cc-enforcer i18n: {len(drifts)} drift(s) vs the English "
             f"skeleton:\n\n")
        for d in drifts:
            _out(f"  {d}\n")
        _out("\nEnglish is the skeleton (source of truth). On drift, update "
             "the translation to match the skeleton — see docs/I18N.md.\n")
    return 1


if __name__ == "__main__":
    sys.exit(main())
