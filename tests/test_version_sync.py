"""Version-drift gate: every version-bearing site must agree with plugin.json.

Why this file exists
--------------------
v0.22.1 was released with `.claude-plugin/plugin.json` at `0.22.1` while
`.claude-plugin/marketplace.json` still said `0.22.0` in **two** places. The
marketplace manifest is what the Claude Code plugin installer reads, so the
user's installed plugin reported the *previous* version — the release was
invisible to the only surface a user actually looks at. Nothing failed: the
tests were green, CI was green, the tag was pushed.

That is a textbook rule 06 Check 2b failure ("scope of evidence != scope of
claim"): a green suite proved nothing about the manifests it never opened.
The sibling project cc-memory has exactly this gate and it caught the same
`marketplace.json` in the same week. This repo did not have it. Now it does.

Design notes
------------
1. `.claude-plugin/plugin.json` is the single authority. Every other site is
   compared to it; nothing is compared site-to-site (that would let a pair
   drift together).
2. The site list is a **closed set**, not a pattern scan (rule 09,
   "closed-set guards", added in v0.22.1). Both manifests are walked
   recursively for *every* `"version"` key and the discovered JSON-pointer
   set must equal the expected set exactly. Adding a new version field to a
   manifest therefore fails this test until the field is registered here —
   which is the only way a future site cannot silently escape the gate.
   A blacklist ("check these two paths") would have let it through.
3. Prose is deliberately NOT pinned. The README's "New in vX.Y.Z" narrative
   and the CHANGELOG bodies are history and must be allowed to name old
   versions. Only the machine-readable manifests, the README's shields badge
   (which asserts a current fact to the reader) and the CHANGELOG's newest
   *released* heading are pinned.
4. The newest heading is not the whole claim. Every released heading states
   that a version shipped, and a version ships as a `v<version>` git tag, so
   the whole released set is compared against `git tag` rather than
   `released[0]` alone. v0.38.2 carries a heading, a `release:` commit and a
   paragraph of the plugin description while `git tag -l v0.38.2` is empty
   and `gh release view v0.38.2` answers "release not found" — pinning only
   the newest heading leaves that class invisible to CI for every release
   after it. A version that ships inside another one says so in its own
   entry and is registered in UNTAGGED_BY_RECORD, which the entry itself
   has to back up.
5. The tag half needs a tag list to read, and `actions/checkout` is
   depth-1 by default. `TestCIGivesTheTagGateItsInput` reads
   `fetch-depth: 0` out of the workflow: `_git_tags` answers None on a
   shallow clone and the tag check skips itself, which is right for a
   downloaded tarball and would otherwise let a depth-1 CI run stay green
   over a gate that inspected nothing.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

PLUGIN_MANIFEST = REPO_ROOT / ".claude-plugin" / "plugin.json"
# `MARKETPLACE_MANIFEST` used to sit here and was referenced by nothing:
# the marketplace file is reached through EXPECTED_VERSION_POINTERS below,
# which addresses every manifest by repo-relative path so the pointer set
# stays the single closed registry. (v0.30)
README = REPO_ROOT / "README.md"
CHANGELOG = REPO_ROOT / "CHANGELOG.md"
WORKFLOWS = REPO_ROOT / ".github" / "workflows"

# The closed set of JSON pointers that carry a version, per manifest.
# Registering a pointer here is the ONLY way a version field becomes legal.
EXPECTED_VERSION_POINTERS = {
    ".claude-plugin/plugin.json": {"/version"},
    ".claude-plugin/marketplace.json": {"/metadata/version", "/plugins/0/version"},
}

_BADGE_RE = re.compile(r"img\.shields\.io/badge/version-([0-9][^-]*)-")
_CHANGELOG_HEADING_RE = re.compile(r"^## \[([^\]]+)\]", re.MULTILINE)

# Versions that ship inside another release and therefore have no tag of
# their own. This is not a waiver list: `test_untagged_registry_is_backed_
# by_the_changelog` re-derives the declaration from CHANGELOG.md, so an
# entry only becomes registrable after it says in public that no separate
# tag exists — and it must stop being registered the day a tag appears.
UNTAGGED_BY_RECORD: dict[str, str] = {
    "0.8.0": "rolled into the v0.9.0 commit before either was tagged",
    "0.25.1": "released inside the v0.26.0 commit 3486c2c, which is also "
              "the commit that wrote its heading; plugin.json went 0.25.0 "
              "-> 0.26.0 and never carried 0.25.1",
}

# What a registered entry has to say, with `*`, backticks and blockquote
# markers stripped and whitespace collapsed first.
_NO_TAG_DECLARATION = "no separate v{version} git tag"


def _changelog_text() -> str:
    return CHANGELOG.read_text(encoding="utf-8")


def _released_headings(text: str | None = None) -> list[str]:
    """Every `## [x.y.z]` heading, newest first, minus `[Unreleased]`."""
    headings = _CHANGELOG_HEADING_RE.findall(
        _changelog_text() if text is None else text)
    return [h for h in headings if h.lower() != "unreleased"]


def _changelog_entry(version: str) -> str:
    """The body of `## [version]`, up to the next `## [` heading."""
    parts = _CHANGELOG_HEADING_RE.split(_changelog_text())
    for index in range(1, len(parts), 2):
        if parts[index] == version:
            return parts[index + 1]
    return ""


def _normalise(text: str) -> str:
    """Drop markdown emphasis / quoting so a wrapped sentence is one string."""
    return " ".join(re.sub(r"[*`>]", "", text).split())


def _git_tags() -> set[str] | None:
    """The repository's tag names, or None when git cannot answer here.

    None is reserved for an environment that genuinely holds no answer: no
    git on PATH, not a work tree (a downloaded tarball), or a shallow clone
    that was never given the tags. An empty tag set in a full checkout is an
    answer, and a failing one — CI checks out with `fetch-depth: 0` for
    exactly that reason.
    """
    git = shutil.which("git")
    if git is None:
        return None

    def run(*args: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [git, "-C", str(REPO_ROOT), *args],
            capture_output=True, text=True, check=False,
        )

    work_tree = run("rev-parse", "--is-inside-work-tree")
    if work_tree.returncode != 0 or work_tree.stdout.strip() != "true":
        return None
    shallow = run("rev-parse", "--is-shallow-repository")
    if shallow.returncode == 0 and shallow.stdout.strip() == "true":
        return None
    listing = run("tag", "--list")
    if listing.returncode != 0:
        return None
    return {line.strip() for line in listing.stdout.splitlines() if line.strip()}


_CHECKOUT_RE = re.compile(r"uses:\s*actions/checkout@")
_SUITE_RE = re.compile(r"unittest\s+discover")
_BULLET_RE = re.compile(r"^(\s*)-\s")


def _yaml_list_items(text: str) -> list[str]:
    """Split a workflow into its list items — one `- ` bullet each.

    An item runs from its bullet to the next bullet at the same or a
    shallower indent, so a nested list cannot end its parent early.
    """
    lines = text.splitlines()
    bullets = [(index, len(match.group(1)))
               for index, line in enumerate(lines)
               if (match := _BULLET_RE.match(line))]
    items: list[str] = []
    for position, (start, indent) in enumerate(bullets):
        end = len(lines)
        for later_start, later_indent in bullets[position + 1:]:
            if later_indent <= indent:
                end = later_start
                break
        items.append(chr(10).join(lines[start:end]))
    return items


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _walk_version_pointers(node, prefix: str = "") -> dict[str, str]:
    """Return {json_pointer: value} for every "version" key, at any depth."""
    found: dict[str, str] = {}
    if isinstance(node, dict):
        for key, value in node.items():
            pointer = f"{prefix}/{key}"
            if key == "version" and isinstance(value, str):
                found[pointer] = value
            else:
                found.update(_walk_version_pointers(value, pointer))
    elif isinstance(node, list):
        for index, value in enumerate(node):
            found.update(_walk_version_pointers(value, f"{prefix}/{index}"))
    return found


class TestVersionSync(unittest.TestCase):
    def setUp(self) -> None:
        self.authoritative = _load(PLUGIN_MANIFEST)["version"]

    def test_authoritative_version_is_semver(self) -> None:
        self.assertRegex(
            self.authoritative, r"^\d+\.\d+\.\d+$",
            f"plugin.json version {self.authoritative!r} is not MAJOR.MINOR.PATCH",
        )

    def test_manifest_version_sites_are_a_closed_set(self) -> None:
        """A new version field anywhere in a manifest must be registered here."""
        for rel, expected in EXPECTED_VERSION_POINTERS.items():
            with self.subTest(manifest=rel):
                found = _walk_version_pointers(_load(REPO_ROOT / rel))
                self.assertEqual(
                    set(found), expected,
                    f"{rel}: version-bearing pointers changed. Found "
                    f"{sorted(found)}, registered {sorted(expected)}. Register "
                    f"the new pointer in EXPECTED_VERSION_POINTERS so it is "
                    f"pinned — do not delete it from the manifest to pass.",
                )

    def test_every_manifest_version_matches_plugin_json(self) -> None:
        drifted: dict[str, str] = {}
        for rel in EXPECTED_VERSION_POINTERS:
            for pointer, value in _walk_version_pointers(_load(REPO_ROOT / rel)).items():
                if value != self.authoritative:
                    drifted[f"{rel}{pointer}"] = value
        self.assertEqual(
            drifted, {},
            f"version drift: plugin.json says {self.authoritative}, but {drifted}. "
            f"marketplace.json is what the plugin installer reads — drift here "
            f"means users see the previous version after a release.",
        )

    def test_readme_badge_matches_plugin_json(self) -> None:
        """EVERY README's badge, not just the English one.

        v0.31.1 — this pinned `README.md` alone, and `README.zh.md` had
        drifted two releases behind (still showing 0.29.0 at 0.31.1) with
        every gate green. Same closed-set lesson as
        EXPECTED_VERSION_POINTERS above: checking the site you happened to
        think of lets its mirror rot. The set is discovered from disk, so a
        `README.<lang>.md` added later is pinned the day it appears rather
        than the day someone remembers to register it.
        """
        readmes = sorted(REPO_ROOT.glob("README*.md"))
        self.assertGreaterEqual(
            len(readmes), 2,
            "expected at least README.md and one translation; if a README "
            "was removed, this count is the wrong kind of green",
        )
        drifted: dict[str, str] = {}
        for path in readmes:
            match = _BADGE_RE.search(path.read_text(encoding="utf-8"))
            self.assertIsNotNone(
                match, f"{path.name} has no shields.io version badge")
            if match.group(1) != self.authoritative:
                drifted[path.name] = match.group(1)
        self.assertEqual(
            drifted, {},
            f"README badge drift: plugin.json says {self.authoritative}, "
            f"but {drifted}. A translated README is the first thing a "
            f"Chinese-reading user sees.",
        )

    def test_changelog_newest_release_matches_plugin_json(self) -> None:
        released = _released_headings()
        self.assertTrue(released, "CHANGELOG.md has no released version heading")
        self.assertEqual(
            released[0], self.authoritative,
            f"CHANGELOG newest release is [{released[0]}], plugin.json says "
            f"{self.authoritative} — a bump without a changelog entry (or an "
            f"entry without a bump)",
        )


class TestReleaseTagCoverage(unittest.TestCase):
    """A released heading is a claim that the version shipped. Check it.

    The version gate above pins the *newest* heading to `plugin.json`, which
    is the bump-vs-entry question. It says nothing about the released
    headings under it, so a release that got its CHANGELOG entry and its
    `release:` commit but never got tagged stays green forever. v0.38.2 is
    that case in this repository, and README's release checklist names the
    same family (v0.22.1: the tag existed while the GitHub release did not,
    so the front page kept showing an older version as Latest).

    Scope is deliberately the git tag, not the GitHub release object: a tag
    is answerable offline from the checkout CI already has, while the
    release object needs the network and a token. The release checklist owns
    the second half.
    """

    def test_every_released_heading_has_a_git_tag(self) -> None:
        tags = _git_tags()
        if tags is None:
            self.skipTest(
                "no git tags available here (no git, not a work tree, or a "
                "shallow clone) — this gate needs the tag list to answer"
            )
        missing = [
            version for version in _released_headings()
            if f"v{version}" not in tags and version not in UNTAGGED_BY_RECORD
        ]
        self.assertEqual(
            missing, [],
            f"released CHANGELOG headings with no git tag: {missing}. The "
            f"entry says the version shipped; without `v<version>` there is "
            f"nothing to install at that point in history, `gh release view` "
            f"answers 'release not found', and the repository front page "
            f"keeps naming an older version as Latest. Fix it forwards — tag "
            f"the release commit (`git tag -a v<version> <commit>`, push it, "
            f"create the release). If the version shipped inside another one, "
            f"say so in its CHANGELOG entry and register it in "
            f"UNTAGGED_BY_RECORD. Deleting the heading to go green removes "
            f"the record instead of the gap.",
        )

    def test_untagged_registry_is_backed_by_the_changelog(self) -> None:
        """Registering a version requires the entry to declare it, and no tag.

        Both halves matter. Without the first, the registry is a mute
        allowlist anyone can grow; without the second, a version stays
        excused after it is finally tagged, and the gate quietly shrinks by
        one every time somebody forgets to unregister.
        """
        tags = _git_tags()
        for version in sorted(UNTAGGED_BY_RECORD):
            with self.subTest(version=version):
                self.assertIn(
                    version, _released_headings(),
                    f"UNTAGGED_BY_RECORD registers {version}, which has no "
                    f"CHANGELOG heading — a stale registration excuses "
                    f"nothing and hides that it is stale",
                )
                declaration = _NO_TAG_DECLARATION.format(version=version)
                self.assertIn(
                    declaration, _normalise(_changelog_entry(version)),
                    f"the [{version}] entry does not say "
                    f"'{declaration}'. A version is only excused from the "
                    f"tag gate by admitting the gap where readers see it, "
                    f"not by an entry in this file.",
                )
                if tags is not None:
                    self.assertNotIn(
                        f"v{version}", tags,
                        f"v{version} is tagged, so it no longer belongs in "
                        f"UNTAGGED_BY_RECORD — unregister it and let the "
                        f"gate cover it like every other release",
                    )


class TestCIGivesTheTagGateItsInput(unittest.TestCase):
    """The workflow line the tag gate reads through.

    `_git_tags` returns None for a shallow checkout and
    `test_every_released_heading_has_a_git_tag` skips itself. That is the
    right answer for a downloaded tarball, and the wrong one for CI:
    `actions/checkout` is depth-1 by default, so dropping `fetch-depth: 0`
    would leave the gate reporting nothing while the run stayed green — an
    inert gate, which is what this repository's own sync-gate config warns
    about ("a glob that matches nothing is silently inert"). Nothing else
    reads that line, so it is read here.
    """

    def _suite_workflows(self) -> list[Path]:
        return sorted([path for pattern in ("*.yml", "*.yaml")
                       for path in WORKFLOWS.glob(pattern)
                       if _SUITE_RE.search(path.read_text(encoding="utf-8"))])

    def test_a_workflow_runs_the_suite(self) -> None:
        """Twin: the check below must not pass on an empty list."""
        self.assertTrue(
            self._suite_workflows(),
            f"no workflow under {WORKFLOWS} runs `unittest discover`, so "
            f"the checkout check below inspects nothing and passes — the "
            f"vacuous green it exists to prevent. Point it at the renamed "
            f"workflow rather than letting it stand.",
        )

    def test_every_suite_workflow_checks_out_full_history(self) -> None:
        shallow: list[str] = []
        for path in self._suite_workflows():
            steps = [item for item
                     in _yaml_list_items(path.read_text(encoding="utf-8"))
                     if _CHECKOUT_RE.search(item)]
            self.assertTrue(
                steps,
                f"{path.name} runs the suite without checking the "
                f"repository out",
            )
            shallow += [f"{path.name} checkout #{number}"
                        for number, item in enumerate(steps, start=1)
                        if "fetch-depth: 0" not in item]
        self.assertEqual(
            shallow, [],
            f"checkout steps without `fetch-depth: 0`: {shallow}. "
            f"actions/checkout is depth-1 by default and brings no tags, so "
            f"TestReleaseTagCoverage would answer with a skip and CI would "
            f"stay green over a gate that read nothing.",
        )


if __name__ == "__main__":
    unittest.main()
