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
"""

from __future__ import annotations

import json
import re
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

# The closed set of JSON pointers that carry a version, per manifest.
# Registering a pointer here is the ONLY way a version field becomes legal.
EXPECTED_VERSION_POINTERS = {
    ".claude-plugin/plugin.json": {"/version"},
    ".claude-plugin/marketplace.json": {"/metadata/version", "/plugins/0/version"},
}

_BADGE_RE = re.compile(r"img\.shields\.io/badge/version-([0-9][^-]*)-")
_CHANGELOG_HEADING_RE = re.compile(r"^## \[([^\]]+)\]", re.MULTILINE)


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
        headings = _CHANGELOG_HEADING_RE.findall(CHANGELOG.read_text(encoding="utf-8"))
        released = [h for h in headings if h.lower() != "unreleased"]
        self.assertTrue(released, "CHANGELOG.md has no released version heading")
        self.assertEqual(
            released[0], self.authoritative,
            f"CHANGELOG newest release is [{released[0]}], plugin.json says "
            f"{self.authoritative} — a bump without a changelog entry (or an "
            f"entry without a bump)",
        )


if __name__ == "__main__":
    unittest.main()
