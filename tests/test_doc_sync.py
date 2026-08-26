"""Doc-drift gate: every documented count / inventory must agree with the code.

Why this file exists
--------------------
The v0.26.0 documentation audit returned 41 confirmed defects spread across
README.md, CLAUDE.md, docs/, rules/, prompts/, commands/ and skills/. A large
share of them — the ones this file can mechanise — are hand-maintained
enumerations: how many rules exist, how many slash commands, how many Bash
patterns the guard denies, which lib modules live under hooks/scripts/lib/,
how many tests the suite runs, with nothing in the build deriving any of it
back from the code.

Not all 41 were of that kind, and an earlier draft of this docstring claimed
they were. Several were prose describing behaviour that had changed (the
rule-10 escape hatch, bash_guard's check ordering, a citation pointing at the
wrong rule). Those are not counts and this gate does not catch them. The
overstatement is called out here rather than quietly corrected because it was
the same failure the gate exists to prevent — a claim outrunning what was
actually built.

Nor were the numbers "last correct at v0.24.0": `git show v0.24.0:README.md`
already said "9-rule discipline summary" while twelve rules shipped. Some of
this drift is older than the audit found.

This repo has already solved this exact problem once, for versions. v0.22.1
shipped with a stale ``marketplace.json`` and the fix was a *gate*
(``test_version_sync.py``), not a corrected number, precisely because a
corrected number decays again on the next release. Documentation had no
equivalent gate. This is it.

There is a second, sharper reason. Rule 09 tells contributors to write
closed-set guards — "enumerate the legal set and reject the rest, because
blacklisting the shapes you have seen lets the next shape walk past". The
documentation surface is the one place in this repo that never followed its
own advice.

Design notes (mirrors test_version_sync.py deliberately)
--------------------------------------------------------
1. **Values are derived from code, never from another doc.** Every expected
   number and inventory is computed at runtime from the filesystem or by
   importing the module that owns the fact. Nothing is compared doc-to-doc:
   two docs can drift together, and in this repo they demonstrably did.
2. **Registered sites cannot go stale silently.** Each site carries a regex
   that must match; a regex matching nothing fails as "stale registration"
   rather than passing vacuously, so rewording a pinned sentence breaks the
   build instead of escaping the gate.

   This is NOT the same as "every claim in the docs is registered". The
   `CLAIMS` tuple, the surface lists and `EXTRA_DENY_DOC_TOKENS` are all
   hand-maintained: a NEW numeric claim written somewhere new is not
   discovered by anything here. Closing that would need a scan for
   number-bearing sentences, which is not implemented.
3. **Old release narratives are deliberately NOT pinned; the current one
   is.** A `New in v0.22` block must stay free to say 323. But the newest
   entry describes the release being shipped, and exempting it as "history"
   is how five stale `378 → 474` statements passed a green gate in v0.26.
   `TestCurrentReleaseNarrative` closes that.
4. **Three behavioural claims ARE covered, as of v0.35.1.** Notes 1–3 were
   written when this gate only pinned numbers and inventories, and the
   "does NOT cover" list below said prose behaviour and citation accuracy
   were out of reach wholesale. That is no longer true for three classes
   that turned out to be derivable after all:
   * an advertised *hedge trigger* must be one `_HEDGE_INNER` matches, and a
     token the docs call excluded must be one it does not
     (`TestHedgeExamplesAreReal`);
   * a printed *coverage bar* must equal `editscale.coverage_bar` of the file
     size printed beside it (`TestSampleCoverageBarMatchesEditscale`);
   * a backticked `UPPER_SNAKE` *identifier* must be bound somewhere in this
     repo's Python (`TestDocsCiteOnlyLiveIdentifiers`).

   The lesson generalises: "prose" is not one thing. A sentence naming a
   pattern, an arithmetic result, or an identifier is checkable; only
   sentences making a *judgement* are not. Prefer looking for the derivable
   sub-class over recording the whole surface as uncoverable.

5. **What this gate still does NOT cover** — stated explicitly because rule
   06 check 2b forbids letting a green gate stand in for the parts it never
   opened:
   * judgement prose — how the rationale hatch decides, what order
     bash_guard's checks run in, whether an explanation is *right*;
   * unregistered numeric claims, per note 2;
   * anchors — a link to `docs/RULES.md#rule-99` resolves as long as the file
     exists;
   * reference-style markdown links, which `_LINK` does not parse;
   * the Stop-layer count, the architecture-layer count, and the exact
     command/prompt/rule filename sets.

   A green run means the registered numbers, inventories, and the three
   derivable claim classes above agree with the code. It means nothing about
   the judgement prose around them.
"""

from __future__ import annotations

import importlib.util
import json
import re
import unittest
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

REPO_ROOT = Path(__file__).resolve().parents[1]


# --------------------------------------------------------------------------- #
# v0.38.2 — CLAUDE.md is no longer tracked (it carried the maintainer's mail
# address and machine paths, and it is agent instructions rather than reader
# documentation). It stays on disk and Claude Code still loads it, so the
# gates below check it WHEN PRESENT and skip it when it is not.
#
# Stated rather than assumed: on CI the file never exists, so its four
# registered claims are verified only where it lives. That is weaker than a
# CI gate and is accepted because the alternative is no check at all — every
# other surface those claims appear on (README.md, README.zh.md, both
# manifests, docs/ARCHITECTURE.md) is still gated on every push.
# --------------------------------------------------------------------------- #
UNTRACKED_LOCAL_DOCS = ("CLAUDE.md",)


def _relative_to_repo(path) -> str:
    """`path` as a repo-relative posix string, or "" if it escapes the repo."""
    try:
        return Path(path).resolve().relative_to(REPO_ROOT).as_posix()
    except (ValueError, OSError):
        return ""


def _present(names):
    """Drop the untracked local docs from a registered surface list.

    The tuples keep naming CLAUDE.md so a reader can see it was
    considered and why it is skipped, rather than finding a list that
    silently does not mention it.
    """
    return tuple(n for n in names if n not in UNTRACKED_LOCAL_DOCS)


RULES_DIR = REPO_ROOT / "rules"
COMMANDS_DIR = REPO_ROOT / "commands"
SCRIPTS_DIR = REPO_ROOT / "hooks" / "scripts"
LIB_DIR = SCRIPTS_DIR / "lib"


# --------------------------------------------------------------------------
# Derived facts. Each function answers one question by asking the code.
# --------------------------------------------------------------------------

def _rule_count() -> int:
    """Numbered rule files, excluding the 00-index."""
    return len([p for p in RULES_DIR.glob("[0-9][0-9]-*.md")
                if not p.name.startswith("00-")])


def _rule_numbers() -> set[str]:
    return {p.name[:2] for p in RULES_DIR.glob("[0-9][0-9]-*.md")
            if not p.name.startswith("00-")}


def _command_count() -> int:
    return len(list(COMMANDS_DIR.glob("*.md")))


def _lib_modules() -> set[str]:
    """Shared library module stems under hooks/scripts/lib/."""
    return {p.stem for p in LIB_DIR.glob("*.py") if p.stem != "__init__"}


def _hook_script_files() -> set[str]:
    return {p.name for p in SCRIPTS_DIR.glob("*.py")}


def _hooks_config() -> dict:
    return json.loads((REPO_ROOT / "hooks" / "hooks.json").read_text("utf-8"))


def _registered_hook_scripts() -> set[str]:
    """Script filenames actually wired into hooks/hooks.json.

    Parsed as JSON, not scraped with a regex. The regex version had a
    character class that silently dropped any script name containing a
    dash, and would have returned an EMPTY set for a Windows-separator
    path — and the only assertion using it was a subset check, which an
    empty set satisfies trivially. A derivation that can quietly return
    nothing is not a derivation.
    """
    found: set[str] = set()

    def walk(node) -> None:
        if isinstance(node, dict):
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)
        elif isinstance(node, str):
            for part in re.split(r"[\s\"']+", node):
                base = part.replace("\\", "/").rsplit("/", 1)[-1]
                if base.endswith(".py"):
                    found.add(base)

    walk(_hooks_config())
    return found


def _registered_hook_events() -> set[str]:
    """Hook event names wired in hooks.json (keys under "hooks")."""
    cfg = _hooks_config()
    events = cfg.get("hooks", cfg)
    return {k for k, v in events.items() if isinstance(v, list)}


# Registered deliberately, so an accidental deletion fails loudly rather
# than shrinking a subset check into triviality.
EXPECTED_REGISTERED_HOOK_SCRIPTS = {
    "inject_context.py", "read_guard.py", "bash_guard.py", "stop_guard.py",
}
EXPECTED_HOOK_EVENTS = {
    "SessionStart", "UserPromptSubmit", "PreToolUse", "Stop",
}


def _load_bash_guard():
    spec = importlib.util.spec_from_file_location(
        "_doc_sync_bash_guard", SCRIPTS_DIR / "bash_guard.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _bash_static_pattern_names() -> set[str]:
    return {p["name"] for p in _load_bash_guard().STATIC_PATTERNS}


def _checklist_section_count() -> int:
    """Lettered sections (## A. … ## H. …) in the checklist command."""
    text = (COMMANDS_DIR / "checklist.md").read_text(encoding="utf-8")
    return len(re.findall(r"^## [A-Z]\.", text, re.MULTILINE))


def _test_count() -> int:
    """Size of the suite, as `python -m unittest discover -s tests` sees it."""
    loader = unittest.TestLoader()
    suite = loader.discover(str(REPO_ROOT / "tests"),
                            top_level_dir=str(REPO_ROOT / "tests"))
    if loader.errors:
        raise AssertionError(
            "test discovery raised; the count cannot be trusted: "
            f"{loader.errors}")
    return suite.countTestCases()


# --------------------------------------------------------------------------
# Registered claim sites. Adding a doc sentence that states one of these
# facts means registering it here; that is the point of the closed set.
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class Claim:
    """One present-tense numeric assertion in a doc, pinned to a derived fact."""
    id: str
    path: str                    # repo-relative
    pattern: str                 # group(1) must capture the asserted number
    expected: Callable[[], int]
    why: str                     # what goes wrong for a reader when it drifts


CLAIMS: tuple[Claim, ...] = (
    Claim(
        "readme-tree-test-count", "README.md",
        r"tests/\s+# (\d+) black-box \+ unit tests",
        _test_count,
        "the structure tree understates the suite a reader is told to run",
    ),
    Claim(
        "readme-howitworks-test-count", "README.md",
        r"covered by \*\*(\d+) tests\*\*",
        _test_count,
        "the coverage claim understates the suite",
    ),
    Claim(
        "readme-slash-command-count", "README.md",
        r"\*\*(\d+) slash commands\*\*",
        _command_count,
        "a reader is told fewer commands exist than are installed",
    ),
    Claim(
        # The Chinese half moved out of README.md into its own
        # README.zh.md (GitHub renders README.md; a full translation buried
        # at the bottom of the English file was neither scannable nor at
        # parity). The claim follows the text — leaving it pointed at
        # README.md would have failed as a stale registration, which is
        # exactly what that check is for.
        "readme-zh-slash-command-count", "README.zh.md",
        r"\*\*(\d+) 个 slash 命令\*\*",
        _command_count,
        "the Chinese README undercounts the installed commands",
    ),
    Claim(
        # v0.34.1 — the zh mirror's test counts were two releases stale
        # (604 at a 615 suite) while CI was green, because only README.md's
        # counts were registered. Same class as the v0.31.1 badge fix.
        "readme-zh-tree-test-count", "README.zh.md",
        r"tests/\s+# (\d+) 个测试（python",
        _test_count,
        "the Chinese structure tree understates the suite",
    ),
    Claim(
        "readme-zh-coverage-test-count", "README.zh.md",
        r"\*\*(\d+) 个测试\*\*覆盖",
        _test_count,
        "the Chinese coverage claim understates the suite",
    ),
    Claim(
        "readme-injected-rule-count", "README.md",
        r"(\d+)-rule discipline summary",
        _rule_count,
        "the hooks table understates what SessionStart injects",
    ),
    Claim(
        "readme-checklist-sections", "README.md",
        r"(\d+)-section checklist",
        _checklist_section_count,
        "a reader walking the checklist stops early",
    ),
    Claim(
        "claude-md-rule-count", "CLAUDE.md",
        r"`rules/` \*\*(\d+)\*\* 条核心规则",
        _rule_count,
        "the feature list contradicts the repo's own rule directory",
    ),
    Claim(
        "claude-md-command-count", "CLAUDE.md",
        r"(\d+) 个 slash 命令",
        _command_count,
        "the feature list omits an installed command",
    ),
    Claim(
        "claude-md-test-count", "CLAUDE.md",
        r"\*\*(\d+) 个\*\*（v",
        _test_count,
        "the feature list understates the suite",
    ),
    Claim(
        "claude-md-tree-test-count", "CLAUDE.md",
        r"# (\d+) 个测试",
        _test_count,
        "the structure tree understates the suite",
    ),
)


# Bash deny patterns are an inventory, not a count: docs must name each one.
# The key set is asserted equal to STATIC_PATTERNS' names, so a new pattern
# fails this file until it is registered — a blacklist would let it through.
# The rm -rf entry's name embeds a home-var literal; it is split so this
# file does not trip the repo's own rule-11 path-dependency detector, the
# same technique read_guard.py uses for its own home-var literals.
_RM_RF_PATTERN_NAME = "rm -rf on root / " + "$" + "HOME / ~"

BASH_PATTERN_DOC_TOKENS: dict[str, str] = {
    "--no-verify (skipping commit hooks)": "--no-verify",
    "--no-gpg-sign (skipping commit signature)": "--no-gpg-sign",
    "chmod 777 (world-writable)": "chmod 777",
    "git rebase --skip (silently abandoning a conflict)": "git rebase --skip",
    "pip install --break-system-packages (bypassing PEP 668)":
        "--break-system-packages",
    _RM_RF_PATTERN_NAME: "rm -rf",
}

# The force-push detector is not in STATIC_PATTERNS (it parses the command
# through lib/shellcmd rather than matching a regex), but it is part of the
# deny set every enforcement table claims to enumerate.
EXTRA_DENY_DOC_TOKENS = ("git push --force",)

# Surfaces that present the Bash deny set as complete. The injected prompts
# are the highest-stakes members: an agent acts on what it was told, and the
# zh mirrors listed strictly fewer patterns than the English skeleton until
# this gate existed.
BASH_DENY_SURFACES = (
    "CLAUDE.md",
    "docs/ARCHITECTURE.md",
    "prompts/session-start.md",
    "prompts/zh/session-start.md",
    "prompts/user-prompt.md",
    "prompts/zh/user-prompt.md",
    # rule 09 owns the Bash interception table; omitting it from this list
    # is why its row still named four patterns after the audit fixed the
    # same row everywhere else. The zh mirror was equally stale, so i18n
    # parity was green — two wrongs agreeing.
    "rules/09-systematic-modification.md",
    "rules/zh/09-systematic-modification.md",
)

# Surfaces whose repository-structure tree claims to enumerate the codebase.
# README.zh.md joined in v0.34.1: the v0.34.0 release added lib/envfile.py to
# both English trees (this gate forced it) while the Chinese tree never got
# the module — the same mirror-coverage hole v0.31.1 closed for the version
# badge, one surface over. A mirror that enumerates the codebase is held to
# the same inventory as the original.
INVENTORY_SURFACES = _present(("README.md", "CLAUDE.md", "README.zh.md"))

# --------------------------------------------------------------------------- #
# The CURRENT release's own narrative is not history yet.
#
# This gate exempts "history" from pinning so a `New in v0.22` block may
# keep saying 323. That exemption had a hole big enough to drive the whole
# v0.26 release through: the newest entry describes the release being
# SHIPPED, and its numbers were stale in five places (`378 → 474` when the
# suite ran 486) while every pinned site was green. The gate stood next to
# the error and said nothing — the exact "claim outran the change" failure
# this release is about.
#
# So: any `N → M tests` statement in a surface that narrates the CURRENT
# version must have M equal to the real suite size. Older entries are
# located by their own version heading and left alone.
# --------------------------------------------------------------------------- #
_TEST_DELTA = re.compile(r"(\d+)\s*(?:→|->)\s*(\d+)\s*(?:tests|个)")

CURRENT_RELEASE_SURFACES = (
    "README.md",
    # The zh mirror narrates releases too; v0.34.1 added it after its test
    # counts sat two releases stale behind a green gate (mirror-coverage
    # class, third instance: badge v0.31.1, counts v0.34.1).
    "README.zh.md",
    "CLAUDE.md",
    ".claude-plugin/plugin.json",
    ".claude-plugin/marketplace.json",
)


def _current_version() -> str:
    return json.loads(
        (REPO_ROOT / ".claude-plugin" / "plugin.json").read_text("utf-8")
    )["version"]


def _current_release_sections(text: str, version: str) -> list[str]:
    """Chunks of `text` that narrate `version` (up to the next version)."""
    out: list[str] = []
    marker = re.escape(version)
    for m in re.finditer(marker, text):
        start = m.start()
        nxt = re.search(r"v?\d+\.\d+\.\d+", text[m.end():])
        end = m.end() + (nxt.start() if nxt else len(text))
        out.append(text[start:end])
    return out


def _read(rel: str) -> str:
    return (REPO_ROOT / rel).read_text(encoding="utf-8")


def _structure_tree_blocks(text: str) -> list[str]:
    """Fenced blocks that draw the repository tree.

    Scoped deliberately. The first draft of this file searched the whole
    document for ``srclex.py`` and passed — because README names the new
    modules in its "New in v0.26.0" prose while its structure tree still
    omitted them. That check confirmed a spelling *somewhere in the file*
    rather than the concept "the tree enumerates the codebase", which is
    the exact failure mode this release exists to fix. The search is
    therefore confined to the fenced blocks that actually draw the tree.
    """
    blocks: list[str] = []
    current: list[str] | None = None
    for line in text.splitlines():
        if line.lstrip().startswith("```"):
            if current is None:
                current = []
            else:
                blocks.append("\n".join(current))
                current = None
            continue
        if current is not None:
            current.append(line)
    # Identify a tree by its drawing glyphs, not by a path spelling: the
    # first attempt filtered on the literal "hooks/scripts" and matched
    # nothing, because a tree renders that as "hooks/" on one line and
    # "scripts/" on the next. The vacuity guard in _tree_text caught it.
    return [b for b in blocks
            if ("├──" in b or "└──" in b) and "hooks" in b]


# Links that are format *examples*, not citations: rule 05 defines the
# citation format and necessarily shows a template that resolves to nothing.
# Registered individually — a closed set — so a genuinely broken link can
# never hide among them, and so deleting an example fails here rather than
# quietly shrinking what this gate covers.
EXAMPLE_LINKS: dict[str, str] = {
    # The injected prompt is read inside whatever repository cc-enforcer is
    # installed into, so this link resolves against the CONSUMING project's
    # own instruction file. It has never referred to this repository's — and
    # since v0.38.2 this repository does not track one.
    "prompts/session-start.md -> CLAUDE.md":
        "points at the consuming project's own CLAUDE.md, not this repo's",
    "prompts/zh/session-start.md -> CLAUDE.md":
        "same as prompts/session-start.md, zh mirror",
    "prompts/session-start.md -> path#L42":
        "citation-format template in the injected prompt",
    "prompts/zh/session-start.md -> path#L42":
        "citation-format template, zh mirror",
    "rules/05-cite-sources.md -> path/to/file.ext#LLINE":
        "the format spec's own template",
    "rules/05-cite-sources.md -> src/auth.py#L142":
        "worked example in the format spec",
    "rules/zh/05-cite-sources.md -> path/to/file.ext#LLINE":
        "the format spec's own template, zh mirror",
    "rules/zh/05-cite-sources.md -> src/auth.py#L142":
        "worked example in the format spec, zh mirror",
}


class TestRegisteredCounts(unittest.TestCase):
    """Each pinned sentence still exists, and still states the right number."""

    def test_every_claim_site_still_matches(self) -> None:
        """A reworded sentence must fail loudly, not escape the gate."""
        for claim in CLAIMS:
            if claim.path in UNTRACKED_LOCAL_DOCS:
                continue
            with self.subTest(claim=claim.id):
                found = re.findall(claim.pattern, _read(claim.path))
                self.assertTrue(
                    found,
                    f"stale registration: {claim.id} matches nothing in "
                    f"{claim.path}. The sentence was reworded or removed. "
                    f"Update the pattern here — do not delete the claim to "
                    f"go green, or the fact stops being checked.",
                )

    def test_every_claim_matches_the_code(self) -> None:
        drifted: dict[str, str] = {}
        for claim in CLAIMS:
            if claim.path in UNTRACKED_LOCAL_DOCS:
                continue
            expected = claim.expected()
            for stated in re.findall(claim.pattern, _read(claim.path)):
                if int(stated) != expected:
                    drifted[claim.id] = (
                        f"{claim.path} says {stated}, code says {expected} "
                        f"({claim.why})")
        self.assertEqual(
            drifted, {},
            "documentation drift against the code:\n  " +
            "\n  ".join(f"{k}: {v}" for k, v in sorted(drifted.items())),
        )


class TestCurrentReleaseNarrative(unittest.TestCase):
    """The newest release's own numbers are current facts, not history."""

    def test_test_count_deltas_in_current_release_are_accurate(self) -> None:
        version = _current_version()
        expected = _test_count()
        wrong: list[str] = []
        for surface in _present(CURRENT_RELEASE_SURFACES):
            text = _read(surface)
            for section in _current_release_sections(text, version):
                for before, after in _TEST_DELTA.findall(section):
                    if int(after) != expected:
                        wrong.append(
                            f"{surface}: '{before} → {after} tests' in the "
                            f"v{version} narrative, but the suite runs "
                            f"{expected}")
        self.assertEqual(
            sorted(set(wrong)), [],
            "the current release describes its own suite size wrongly:\n  "
            + "\n  ".join(sorted(set(wrong)))
            + "\nOlder release narratives are exempt; this one is not "
              "history yet.",
        )


class TestBashDenySetIsFullyDocumented(unittest.TestCase):
    """Every pattern the guard denies is named on every surface that lists them."""

    def test_doc_token_registry_is_a_closed_set(self) -> None:
        self.assertEqual(
            set(BASH_PATTERN_DOC_TOKENS), _bash_static_pattern_names(),
            "bash_guard.STATIC_PATTERNS changed. Register the new pattern's "
            "documentation token in BASH_PATTERN_DOC_TOKENS so it is pinned "
            "on every surface — an unregistered pattern is exactly how the "
            "v0.14 additions stayed undocumented for eleven releases.",
        )

    def test_every_surface_names_every_denied_pattern(self) -> None:
        tokens = tuple(BASH_PATTERN_DOC_TOKENS.values()) + EXTRA_DENY_DOC_TOKENS
        missing: dict[str, list[str]] = {}
        for surface in _present(BASH_DENY_SURFACES):
            text = _read(surface)
            absent = [t for t in tokens if t not in text]
            if absent:
                missing[surface] = absent
        self.assertEqual(
            missing, {},
            "enforcement surfaces understate the Bash deny set:\n  " +
            "\n  ".join(f"{k} omits {v}" for k, v in sorted(missing.items())) +
            "\nAn agent acts on what it was told; a zh session must not be "
            "given a smaller deny set than an en session.",
        )


class TestModuleInventoriesAreComplete(unittest.TestCase):
    """Structure trees that enumerate the codebase must enumerate all of it."""

    def _tree_text(self, surface: str) -> str:
        blocks = _structure_tree_blocks(_read(surface))
        self.assertTrue(
            blocks,
            f"{surface} has no fenced repository-structure tree; the "
            f"inventory checks below would pass vacuously.",
        )
        return "\n".join(blocks)

    def test_lib_modules_are_listed(self) -> None:
        missing: dict[str, list[str]] = {}
        for surface in INVENTORY_SURFACES:
            tree = self._tree_text(surface)
            absent = sorted(f"{m}.py" for m in _lib_modules()
                            if f"{m}.py" not in tree)
            if absent:
                missing[surface] = absent
        self.assertEqual(
            missing, {},
            "structure trees omit shared library modules:\n  " +
            "\n  ".join(f"{k} omits {v}" for k, v in sorted(missing.items())),
        )

    def test_hook_scripts_are_listed(self) -> None:
        missing: dict[str, list[str]] = {}
        for surface in INVENTORY_SURFACES:
            tree = self._tree_text(surface)
            absent = sorted(s for s in _hook_script_files() if s not in tree)
            if absent:
                missing[surface] = absent
        self.assertEqual(
            missing, {},
            "structure trees omit hook scripts:\n  " +
            "\n  ".join(f"{k} omits {v}" for k, v in sorted(missing.items())),
        )

    def test_trees_do_not_list_files_that_no_longer_exist(self) -> None:
        """The other direction: a stale entry is drift too.

        Both inventory checks were `code ⊆ doc`, so deleting a module and
        leaving it in the tree passed silently. A tree that lists a file
        which is not there misleads exactly as much as one that omits a
        file which is.
        """
        on_disk = {p.name for p in REPO_ROOT.rglob("*.py")}
        ghosts: dict[str, list[str]] = {}
        for surface in INVENTORY_SURFACES:
            tree = self._tree_text(surface)
            named = set(re.findall(r"\b([a-z_][a-z0-9_]*\.py)\b", tree))
            absent = sorted(named - on_disk)
            if absent:
                ghosts[surface] = absent
        self.assertEqual(
            ghosts, {},
            "structure trees list files that do not exist:\n  " +
            "\n  ".join(f"{k}: {v}" for k, v in sorted(ghosts.items())),
        )

    def test_registered_hooks_exist_and_every_hook_script_is_registered(
        self,
    ) -> None:
        """hooks.json is checked in BOTH directions.

        The subset-only assertion it replaces was satisfied by the empty
        set, so deleting the entire Stop registration — which would
        disable nine enforcement layers — passed.
        """
        registered = _registered_hook_scripts()
        self.assertLessEqual(
            registered, _hook_script_files(),
            "hooks.json registers a script that is not in hooks/scripts/",
        )
        self.assertEqual(
            registered, EXPECTED_REGISTERED_HOOK_SCRIPTS,
            "the set of hook-registered scripts changed. Update "
            "EXPECTED_REGISTERED_HOOK_SCRIPTS deliberately — an accidental "
            "deletion here silently disables a whole enforcement layer.",
        )
        self.assertEqual(
            _registered_hook_events(), EXPECTED_HOOK_EVENTS,
            "the set of registered hook EVENTS changed; register the "
            "change here so a dropped event cannot pass unnoticed.",
        )

    def test_rules_index_lists_every_rule(self) -> None:
        index = _read("docs/RULES.md")
        missing = sorted(n for n in _rule_numbers()
                         if not re.search(rf"\b{n}[-\s]", index))
        self.assertEqual(
            missing, [],
            f"docs/RULES.md is the rule index but never mentions rule(s) "
            f"{missing}",
        )


# --------------------------------------------------------------------------- #
# v0.35.1 — three classes this gate could not see, each found by a live probe
# rather than by reading.
#
# (1) Both READMEs advertised hedge triggers the detector does not match. The
#     layer-(b) row named "should be fine" / "应该", the before/after demo was
#     built on "Should be stable now", and the sample output claimed
#     `Hedge matched: 'Should be'`. stop_guard's own comment says bare `should`
#     is deliberately excluded — so the English demo's OUTPUT could not have
#     come from its own INPUT, and the zh demo likewise. v0.34.1 aligned the
#     injected PROMPTS down to the implementation and scoped the sweep to
#     prompts/; the READMEs describe the same detector and were not in it.
#
# (2) The rolling-patch sample printed "37 of 121 lines or 1104 of 3672 chars"
#     where `editscale.coverage_bar((3672, 122))` yields (1102, 37). Numbers a
#     reader would take for captured output, written by hand.
#
# (3) docs/ARCHITECTURE.md's decision table cited `HEDGED_DONE_REASON`,
#     `NO_EVIDENCE_REASON`, `MISSING_QUIZ_REASON` and `MISSING_FIDELITY_REASON`
#     — four identifiers deleted in v0.12.0 (a37eb3c) and cited for the
#     twenty-three releases since.
# --------------------------------------------------------------------------- #

def _load_stop_guard():
    spec = importlib.util.spec_from_file_location(
        "_doc_sync_stop_guard", SCRIPTS_DIR / "stop_guard.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_editscale():
    spec = importlib.util.spec_from_file_location(
        "_doc_sync_editscale", LIB_DIR / "editscale.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _python_identifiers() -> set[str]:
    """UPPER_SNAKE names bound anywhere in this repo's Python.

    Union of module-level assignments and def/class names across hooks/ and
    tests/, so a doc may cite a constant that lives in a test as readily as
    one in a hook.
    """
    names: set[str] = set()
    roots = (SCRIPTS_DIR, REPO_ROOT / "tests")
    for root in roots:
        for path in root.rglob("*.py"):
            text = path.read_text(encoding="utf-8")
            names |= set(re.findall(r"^(_?[A-Z][A-Z0-9_]{2,})\s*[:=]",
                                    text, re.MULTILINE))
            names |= set(re.findall(r"^(?:def|class)\s+(_?[A-Z][A-Z0-9_]{2,})\b",
                                    text, re.MULTILINE))
    return names


# Each entry captures, in group(1), the span where a surface ENUMERATES the
# hedge triggers. Only the positive enumeration is captured: the sentence that
# follows it names `should` / `通常` precisely to say they are NOT hedges, and
# feeding that clause in would invert the check.
HEDGE_ENUMERATION_SITES: tuple[tuple[str, str, str], ...] = (
    ("readme-layer-b-row", "README.md",
     r"\*\*first-person hedge\*\* \(([^)]*)\)"),
    ("readme-hedge-prose", "README.md",
     r"first-person uncertainty only\*\* —(.*?)\. A bare"),
    ("readme-zh-layer-b-row", "README.zh.md",
     r"\*\*第一人称 hedge\*\*（([^）]*)）"),
    ("readme-zh-hedge-prose", "README.zh.md",
     r"只收第一人称的不确定\*\*——(.*?)。裸的"),
)

# Tokens the docs present as deliberately EXCLUDED. Derived-side assertion:
# the pattern must genuinely not match them, or the docs are promising a
# narrower detector than ships.
HEDGE_NON_TRIGGERS = ("should", "should be fine", "通常", "应该", "Should be")

_QUOTED_ITEM = re.compile(r"`([^`]+)`|\"([^\"]+)\"|“([^”]+)”")

# Backticked UPPER_SNAKE tokens that legitimately have no Python definition.
# Closed set with a reason each, mirroring EXAMPLE_LINKS: without it this gate
# would either be silent or noisy, and a silent gate is the worse failure.
DOC_ONLY_IDENTIFIERS: dict[str, str] = {
    "CC_ENFORCER_LANG": "environment variable read via os.environ.get, not a constant",
    "CLAUDE_ENV_FILE": "environment variable set by Claude Code",
    "CLAUDE_PLUGIN_DATA": "environment variable set by Claude Code",
    "CLAUDE_PROJECT_DIR": "environment variable set by Claude Code",
    "FILE_SHARE_DELETE": "Win32 API flag named in prose, not bound in Python",
    "AKIA": "the literal AWS key prefix, quoted as a pattern in rule 10",
    "V3_DIR": "an illustrative identifier inside rule 09's worked example",
    "TODO": "prose marker",
    "FIXME": "prose marker",
    "HACK": "prose marker",
    "DENY": "prose term for the verdict",
    "BLOCK": "prose term for the verdict",
    "LICENSE": "a filename",
    "TLDR_MAX_ITEM_CHARS": (
        "historical: renamed to TLDR_MAX_ITEM_COLUMNS in v0.35 and cited in "
        "ARCHITECTURE only to say so"
    ),
    "UPPER_SNAKE": (
        "a naming SHAPE, not an identifier — the gate below describes what it "
        "scans for using the shape's own name"
    ),
    "HANDLED": (
        "an outcome label demo/paygate/probe.py PRINTS, not a name it binds; "
        "demo/README.md quotes the printed word"
    ),
}

# CHANGELOG is history: an entry describing v0.12 may name a v0.12 identifier.
IDENTIFIER_SCAN_SKIP = {"CHANGELOG.md"}


class TestHedgeExamplesAreReal(unittest.TestCase):
    """No surface may advertise a hedge trigger the hook does not match."""

    def setUp(self) -> None:
        self.hedge = re.compile(_load_stop_guard()._HEDGE_INNER, re.IGNORECASE)

    def _items(self, span: str) -> list[str]:
        return [next(g for g in m.groups() if g)
                for m in _QUOTED_ITEM.finditer(span)]

    def test_every_enumeration_site_still_matches(self) -> None:
        """A reworded sentence fails loudly rather than escaping the gate."""
        for site_id, path, pattern in HEDGE_ENUMERATION_SITES:
            with self.subTest(site=site_id):
                found = re.findall(pattern, _read(path), re.DOTALL)
                self.assertTrue(
                    found,
                    f"stale registration: {site_id} matches nothing in {path}. "
                    f"Update the pattern here — deleting the registration "
                    f"stops the fact being checked.",
                )
                items = self._items(found[0])
                self.assertGreaterEqual(
                    len(items), 3,
                    f"{site_id} captured {len(items)} example(s); the check "
                    f"would be near-vacuous. Widen the capture.",
                )

    def test_advertised_examples_all_match_the_detector(self) -> None:
        bogus: list[str] = []
        for site_id, path, pattern in HEDGE_ENUMERATION_SITES:
            for span in re.findall(pattern, _read(path), re.DOTALL):
                for item in self._items(span):
                    if not self.hedge.search(item):
                        bogus.append(f"{path} ({site_id}) advertises {item!r}")
        self.assertEqual(
            sorted(set(bogus)), [],
            "surfaces advertise hedge triggers stop_guard does not match:\n  "
            + "\n  ".join(sorted(set(bogus)))
            + "\nA documented detection that does not happen is worse than an "
              "undocumented one: the reader stops checking for it.",
        )

    def test_the_documented_exclusions_are_genuinely_excluded(self) -> None:
        """The other direction: docs say bare `should` is not a hedge."""
        wrongly_matched = [t for t in HEDGE_NON_TRIGGERS if self.hedge.search(t)]
        self.assertEqual(
            wrongly_matched, [],
            f"docs state {wrongly_matched} are NOT hedges, but _HEDGE_INNER "
            f"matches them. Either the pattern widened or the docs are stale — "
            f"fix whichever is wrong, but they cannot both stand.",
        )


class TestSampleCoverageBarMatchesEditscale(unittest.TestCase):
    """The rolling-patch sample's per-file bar is arithmetic, so derive it."""

    _BAR = re.compile(
        r"(\d+) of (\d+) lines or (\d+) of (\d+) chars")
    SURFACES = ("README.md", "README.zh.md")

    def test_every_sample_bar_is_what_editscale_computes(self) -> None:
        coverage_bar = _load_editscale().coverage_bar
        wrong: list[str] = []
        found_any = False
        for surface in self.SURFACES:
            for lines_bar, lines_total, chars_bar, chars_total in \
                    self._BAR.findall(_read(surface)):
                found_any = True
                expected = coverage_bar((int(chars_total), int(lines_total)))
                actual = (int(chars_bar), int(lines_bar))
                if expected != actual:
                    wrong.append(
                        f"{surface}: sample prints {actual} for a "
                        f"{chars_total}-char / {lines_total}-line file; "
                        f"editscale.coverage_bar says {expected}")
        self.assertTrue(
            found_any,
            "no rolling-patch sample bar found in either README; this check "
            "would pass vacuously. If the sample moved, re-point SURFACES.",
        )
        self.assertEqual(
            sorted(wrong), [],
            "README samples print a coverage bar the code would never emit:\n  "
            + "\n  ".join(sorted(wrong))
            + "\nThe sample is presented as captured output. Capture it.",
        )


class TestDocsCiteOnlyLiveIdentifiers(unittest.TestCase):
    """A backticked constant in a doc must exist, or be a registered exception."""

    _TOKEN = re.compile(r"`(_?[A-Z][A-Z0-9_]{2,})`")

    def _doc_files(self) -> list[Path]:
        skip_dirs = {".git", ".ce", "memory", "node_modules", "__pycache__"}
        return [p for p in REPO_ROOT.rglob("*.md")
                if not skip_dirs & set(p.relative_to(REPO_ROOT).parts)
                and p.name not in IDENTIFIER_SCAN_SKIP
                and p.relative_to(REPO_ROOT).as_posix()
                not in UNTRACKED_LOCAL_DOCS]

    def _undefined(self) -> dict[str, list[str]]:
        defined = _python_identifiers()
        out: dict[str, list[str]] = {}
        for path in self._doc_files():
            rel = path.relative_to(REPO_ROOT).as_posix()
            for token in set(self._TOKEN.findall(
                    path.read_text(encoding="utf-8"))):
                if token not in defined:
                    out.setdefault(token, []).append(rel)
        return out

    def test_no_doc_cites_a_constant_that_does_not_exist(self) -> None:
        unknown = {k: v for k, v in self._undefined().items()
                   if k not in DOC_ONLY_IDENTIFIERS}
        self.assertEqual(
            unknown, {},
            "docs cite identifiers with no definition in this repo:\n  "
            + "\n  ".join(f"{k} in {v}" for k, v in sorted(unknown.items()))
            + "\nEither the name is stale (rename it) or it is legitimately "
              "doc-only (register it in DOC_ONLY_IDENTIFIERS with a reason). "
              "Four such names were cited for twenty-three releases after "
              "being deleted in v0.12.0.",
        )

    def test_the_exception_registry_is_not_stale(self) -> None:
        """A registered exception that is now defined must be de-registered."""
        present = set(self._undefined())
        vanished = sorted(set(DOC_ONLY_IDENTIFIERS) - present)
        self.assertEqual(
            vanished, [],
            f"DOC_ONLY_IDENTIFIERS registers {vanished}, which no longer "
            f"need an exemption (either now defined in Python, or no longer "
            f"cited). Remove them so the list stays a closed set.",
        )


class TestMarkdownCitationsResolve(unittest.TestCase):
    """Rule 05: a citation a reader cannot follow is not a citation.

    Only repo-relative links are checked. URLs, mail links, bare anchors and
    absolute/drive-letter paths are somebody else's problem and are skipped.
    """

    _LINK = re.compile(r"\]\(([^)\s]+)\)")
    _SKIP_PREFIX = ("http://", "https://", "mailto:", "#", "/")

    def _markdown_files(self) -> list[Path]:
        skip_dirs = {".git", ".ce", "node_modules", "__pycache__"}
        return [p for p in REPO_ROOT.rglob("*.md")
                if not skip_dirs & set(p.relative_to(REPO_ROOT).parts)
                and p.relative_to(REPO_ROOT).as_posix()
                not in UNTRACKED_LOCAL_DOCS]

    def _unresolvable_links(self) -> list[str]:
        out: list[str] = []
        for path in self._markdown_files():
            rel = path.relative_to(REPO_ROOT).as_posix()
            for target in self._LINK.findall(path.read_text(encoding="utf-8")):
                if target.startswith(self._SKIP_PREFIX):
                    continue
                if re.match(r"^[A-Za-z]:[\\/]", target):   # drive-letter path
                    continue
                cleaned = target.split("#", 1)[0]
                if not cleaned:
                    continue
                # An untracked local doc does not resolve, even though it
                # is sitting right there on this disk: a clone will not
                # have it, and a link that only works on the maintainer's
                # machine is the local-versus-CI split this gate must not
                # develop. Resolve against the repository, not the disk.
                if _relative_to_repo(path.parent / cleaned) \
                        in UNTRACKED_LOCAL_DOCS or \
                        cleaned in UNTRACKED_LOCAL_DOCS:
                    out.append(f"{rel} -> {target}")
                elif not (path.parent / cleaned).exists() and \
                        not (REPO_ROOT / cleaned).exists():
                    out.append(f"{rel} -> {target}")
        return out

    def test_relative_links_point_at_something_that_exists(self) -> None:
        broken = [x for x in self._unresolvable_links()
                  if x not in EXAMPLE_LINKS]
        self.assertEqual(
            broken, [],
            "markdown links resolve to nothing:\n  " + "\n  ".join(broken) +
            "\nIf a link is a deliberate format example, register it in "
            "EXAMPLE_LINKS with the reason.",
        )

    def test_example_link_registry_is_not_stale(self) -> None:
        """A registered example that no longer exists must be de-registered.

        Without this, the exemption list only ever grows, and a future
        genuinely-broken link that happens to match a dead entry would be
        waved through.
        """
        present = set(self._unresolvable_links())
        vanished = sorted(set(EXAMPLE_LINKS) - present)
        self.assertEqual(
            vanished, [],
            f"EXAMPLE_LINKS registers link(s) that no longer exist: "
            f"{vanished}. Remove them so the exemption list stays a closed "
            f"set of things actually present.",
        )


# --------------------------------------------------------------------------- #
# v0.38 — one document, one language.
#
# The repo writes some documents in English and some in Chinese, on purpose
# (CLAUDE.md section 5). What it must not do is mix them *inside* one file:
# a Chinese phrase sitting beside its own English translation for flavour.
#
# CJK is still allowed where it is DATA — inside a backtick code span, where
# it is a literal token the reader must type or that a detector literally
# matches. Removing those would make the document false; `test_doc_sync`'s
# own hedge gate would fail on the very next run.
#
# Correcting the words alone would decay on the next release, which is why
# this is a gate rather than a cleanup.
# --------------------------------------------------------------------------- #
ENGLISH_DOCS: tuple[str, ...] = (
    "README.md",
    "demo/README.md",
    "docs/ARCHITECTURE.md",
    "docs/EDICTS.md",
    "docs/I18N.md",
    "docs/README.md",
    "tests/README.md",
) + tuple(f"rules/{p.name}" for p in sorted((REPO_ROOT / "rules").glob("*.md")))

# Documents written in Chinese by project decision (CLAUDE.md section 5:
# commands / skills / this document are written in Chinese). Registered so
# the completeness check below can prove nothing is simply unclassified.
CHINESE_DOCS: tuple[str, ...] = _present((
    "CLAUDE.md",
    "README.zh.md",
    "docs/RULES.md",
    "agents/verifier.md",
)) + tuple(
    f"commands/{q.name}"
    for q in sorted((REPO_ROOT / "commands").glob("*.md"))
) + tuple(
    d.relative_to(REPO_ROOT).as_posix()
    for d in sorted((REPO_ROOT / "skills").rglob("SKILL.md"))
)

# Neither, each for a stated reason.
UNSCANNED_DOCS: dict[str, str] = {
    "CHANGELOG.md": (
        "a dated record. Entries quote the output and wording of the release "
        "they describe; rewriting them to read better today is the same "
        "falsification the v0.33.0 rename entry refused to commit."
    ),
    "prompts/session-start.md": (
        "an injected payload, not documentation — budgeted against Claude "
        "Code's 10,000-character cap, so adding backticks for tidiness has a "
        "real cost. Its CJK is detector tokens quoted as examples."
    ),
    "prompts/user-prompt.md": "same as prompts/session-start.md",
}

# CJK outside a code span that is nonetheless correct. Closed set, reason each.
CJK_PROSE_ALLOWED: dict[str, str] = {
    "README.md": (
        "the language-switcher link `[中文文档 →](README.zh.md)` — an English "
        "reader needs the Chinese doc labelled in Chinese to recognise it"
    ),
}

_CODE_SPAN_RE = re.compile(r"`[^`]*`")


def _cjk_outside_code(text: str) -> list[tuple[int, str]]:
    """Lines carrying CJK outside a backtick span. Fences are scanned too.

    A fenced block in an English document is a file tree or a config
    sample: its comments are prose, and its sample VALUES are what a user
    would type. A Chinese sample rule in an English doc reads as if the
    feature only accepts Chinese.
    """
    out: list[tuple[int, str]] = []
    for i, line in enumerate(text.splitlines(), 1):
        if line.lstrip().startswith("```"):
            continue
        stripped = _CODE_SPAN_RE.sub("", line)
        if _CJK_CHAR.search(stripped):
            out.append((i, line.strip()[:100]))
    return out


_CJK_CHAR = re.compile(r"[㐀-䶿一-鿿]")


class TestEnglishDocsAreEnglish(unittest.TestCase):
    """No Chinese prose in an English document, and vice versa."""

    def test_every_markdown_file_is_classified(self) -> None:
        """The registries above must cover every tracked markdown file.

        Without this, adding a new English doc and forgetting to register
        it means the gate silently does not cover it — which is how the
        READMEs kept their glosses through v0.37 while the class was
        supposedly closed.
        """
        tracked = set()
        for path in REPO_ROOT.rglob("*.md"):
            rel = path.relative_to(REPO_ROOT).as_posix()
            if rel.startswith((".git/", "memory/", "node_modules/",
                                ".pytest_cache/")):
                continue
            if rel in UNTRACKED_LOCAL_DOCS:
                continue
            if "/zh/" in rel:
                continue          # translations, by definition Chinese
            tracked.add(rel)
        classified = set(ENGLISH_DOCS) | set(CHINESE_DOCS) | set(UNSCANNED_DOCS)
        unclassified = sorted(tracked - classified)
        self.assertEqual(
            unclassified, [],
            "markdown files not registered as English, Chinese or "
            f"deliberately unscanned: {unclassified}",
        )
        stale = sorted(classified - tracked)
        self.assertEqual(stale, [], f"registered but absent: {stale}")

    def test_english_docs_carry_no_cjk_prose(self) -> None:
        offenders: dict[str, list[tuple[int, str]]] = {}
        for rel in ENGLISH_DOCS:
            if rel in CJK_PROSE_ALLOWED:
                continue
            hits = _cjk_outside_code(
                (REPO_ROOT / rel).read_text(encoding="utf-8"))
            if hits:
                offenders[rel] = hits
        self.assertEqual(
            offenders, {},
            "Chinese prose in an English document — backtick it if it is a "
            "detector token, translate it if it is prose:\n" + "\n".join(
                f"  {rel}:{ln} {txt}"
                for rel, hits in sorted(offenders.items()) for ln, txt in hits),
        )

    def test_the_allowlist_is_still_needed(self) -> None:
        """A registered exemption that no longer has CJK must be dropped.

        The twin of the check above: an exemption list that only grows
        eventually covers a real defect.
        """
        unnecessary = sorted(
            rel for rel in CJK_PROSE_ALLOWED
            if not _cjk_outside_code((REPO_ROOT / rel).read_text(encoding="utf-8"))
        )
        self.assertEqual(
            unnecessary, [],
            f"CJK_PROSE_ALLOWED exempts file(s) with no CJK prose left: "
            f"{unnecessary}. De-register them.",
        )

    def test_untracked_local_docs_are_actually_untracked(self) -> None:
        """They must be out of the index AND ignored, or they come back.

        `git rm --cached` alone leaves the file untracked but not ignored,
        so the next `git add -A` re-commits it — the maintainer's mail
        address included — and every gate above starts skipping a file
        that IS in the repository. The two halves have to hold together.
        """
        import subprocess
        for rel in UNTRACKED_LOCAL_DOCS:
            with self.subTest(doc=rel):
                tracked = subprocess.run(
                    ["git", "ls-files", "--error-unmatch", rel],
                    cwd=REPO_ROOT, capture_output=True, text=True,
                )
                self.assertNotEqual(
                    tracked.returncode, 0,
                    f"{rel} is tracked again — the doc gates skip it, so it "
                    f"would ship unchecked",
                )
                if not (REPO_ROOT / rel).is_file():
                    continue      # nothing on disk here; nothing to ignore
                ignored = subprocess.run(
                    ["git", "check-ignore", "-q", rel],
                    cwd=REPO_ROOT, capture_output=True,
                )
                self.assertEqual(
                    ignored.returncode, 0,
                    f"{rel} is on disk but not ignored — the next "
                    f"`git add -A` puts it back in the repository",
                )

    def test_chinese_docs_are_still_chinese(self) -> None:
        """The other direction, so the registry cannot be used to dodge.

        Registering an English document as Chinese would exempt it from
        the check above; this makes that lie visible.
        """
        wrong = []
        for rel in CHINESE_DOCS:
            text = (REPO_ROOT / rel).read_text(encoding="utf-8")
            if len(_CJK_CHAR.findall(text)) < 50:
                wrong.append(rel)
        self.assertEqual(
            wrong, [],
            f"registered as Chinese but barely contains any: {wrong}",
        )


if __name__ == "__main__":
    unittest.main()
