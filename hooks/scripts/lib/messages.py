"""Resolve a user-facing guard message for the session's language.

Until v0.38 the three guards carried their own message text as module
constants, and that text was BILINGUAL: an English body with a Chinese
`大白话` line appended and Chinese phrasings suggested inline. Both
READMEs then showed real samples of it, so both READMEs mixed languages
— and neither could be cleaned without either fabricating output or
dropping the samples. The mixing was never a documentation defect; it
was the product's own output, faithfully quoted.

So the text moved out of the guards and into a catalog with one entry
per language, on the same contract the rest of the plugin already uses:

  * `messages_en.py` is the **skeleton and the source of truth**, the
    same role `rules/` and `prompts/` root files play (docs/I18N.md).
  * `messages_<code>.py` is a translation, selected by
    `CC_ENFORCER_LANG` exactly as the injected prompts already are.
  * Resolution falls back **per key**, not per file: a translation that
    is missing a key yields the English string for that key rather than
    a blank message or a KeyError inside a guard. A partial translation
    is degraded, never broken.

Everything is resolved once at guard-import time and cached, because
these lookups sit in the critical path of every tool call.

What is deliberately NOT translated: the detector tokens a message
quotes. When a recovery blurb says the hedge set contains `我觉得`, that
is data — the string the detector really matches — and it stays as it is
in an English message, the same way a shell flag or a file path does.
Translating it would make the message describe a detector that does not
exist, which is the defect class v0.35.1 was about.
"""

from __future__ import annotations

import importlib
import os
import sys

DEFAULT_LANG = "en"
_MODULE_PREFIX = "messages_"

_cache: dict[str, str] | None = None


def _lang() -> str:
    """The active language code, lower-cased; empty/unset means English.

    Same switch and same defaulting as `inject_context._resolved_lang`,
    deliberately duplicated in spirit rather than imported: that module
    is a hook entry point, and importing an entry point from a shared
    library to read one environment variable would invert the dependency
    direction for no gain.
    """
    return (os.environ.get("CC_ENFORCER_LANG") or "").strip().lower() or DEFAULT_LANG


def _load(lang: str) -> dict[str, str]:
    """Import `messages_<lang>` and return its MESSAGES, or {} if absent.

    Returning {} rather than raising is what makes an unregistered
    language code degrade to English instead of blanking every guard
    message in the session.
    """
    if lang == DEFAULT_LANG:
        from . import messages_en
        return messages_en.MESSAGES
    try:
        mod = importlib.import_module(f".{_MODULE_PREFIX}{lang}", __package__)
    except Exception:
        sys.stderr.write(
            f"[cc-enforcer] CC_ENFORCER_LANG={lang} has no message catalog "
            f"({_MODULE_PREFIX}{lang}.py); guard messages stay English.\n"
        )
        return {}
    got = getattr(mod, "MESSAGES", None)
    return got if isinstance(got, dict) else {}


def catalog() -> dict[str, str]:
    """The resolved catalog: English, overlaid with the active language.

    Overlay rather than replace — see the per-key fallback note above.
    """
    global _cache
    if _cache is None:
        from . import messages_en
        merged = dict(messages_en.MESSAGES)
        lang = _lang()
        if lang != DEFAULT_LANG:
            merged.update(
                {k: v for k, v in _load(lang).items()
                 if isinstance(v, str) and v.strip()}
            )
        _cache = merged
    return _cache


def text(key: str) -> str:
    """The message for `key`, or a visible marker if the key is unknown.

    An unknown key is a bug in the caller, and returning `""` would make
    a guard emit a blank deny reason — a refusal the user cannot act on.
    The marker keeps the failure loud and locatable instead.
    """
    return catalog().get(key, f"<<missing message: {key}>>")


def reset_cache() -> None:
    """Drop the resolved catalog. For tests that switch language in-process."""
    global _cache
    _cache = None
