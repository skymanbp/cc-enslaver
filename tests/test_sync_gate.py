"""Unit tests for hooks/scripts/lib/sync_gate.py (rule 12, v0.23).

Unlike the hook tests (black-box subprocess), these import the library
directly: sync_gate is a pure library (no stdin/stdout hook contract),
and its edge cases — config resolution, TOML coercion, glob semantics,
project-relative path math — are much cheaper to pin at the function
level. The end-to-end Stop-layer behavior is covered by
tests/test_stop_guard.py::TestSyncGateLayerI.
"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

# The sys.path.insert must run before importing sync_gate, so the import
# cannot sit at module top — E402 is silenced because the path bootstrap
# is a precondition of the import.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "hooks" / "scripts"))
from lib import sync_gate  # noqa: E402 -- see path-bootstrap note above


def _norm(p: str) -> str:
    return os.path.normcase(os.path.realpath(p))


class _SyncGateBase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="ccens-sg-")
        self.root = Path(self._tmp.name)
        # Isolate from the surrounding environment: this repo itself has
        # a sync-gate.toml, and CLAUDE_PROJECT_DIR may point at it.
        self._saved_proj = os.environ.get("CLAUDE_PROJECT_DIR")
        os.environ["CLAUDE_PROJECT_DIR"] = str(self.root)

    def tearDown(self) -> None:
        if self._saved_proj is None:
            os.environ.pop("CLAUDE_PROJECT_DIR", None)
        else:
            os.environ["CLAUDE_PROJECT_DIR"] = self._saved_proj
        self._tmp.cleanup()

    def _write_config(self, text: str, base: Path | None = None) -> Path:
        base = base or self.root
        d = base / ".claude" / "cc-enslaver"
        d.mkdir(parents=True, exist_ok=True)
        p = d / "sync-gate.toml"
        p.write_text(text, encoding="utf-8")
        return p

    def _touch(self, rel: str) -> str:
        p = self.root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("x\n", encoding="utf-8")
        return _norm(str(p))


class TestConfigPath(_SyncGateBase):
    def test_cwd_candidate_wins(self) -> None:
        other = Path(tempfile.mkdtemp(prefix="ccens-sg2-"))
        try:
            expected = self._write_config("groups = []\n")
            self._write_config("groups = []\n", base=other)
            os.environ["CLAUDE_PROJECT_DIR"] = str(other)
            got = sync_gate.config_path(cwd=str(self.root))
            self.assertEqual(got, expected, "explicit cwd must outrank the env var")
        finally:
            import shutil
            shutil.rmtree(other, ignore_errors=True)

    def test_env_var_fallback(self) -> None:
        expected = self._write_config("groups = []\n")
        empty = Path(tempfile.mkdtemp(prefix="ccens-sg3-"))
        try:
            got = sync_gate.config_path(cwd=str(empty))
            self.assertEqual(got, expected, "env var must be the second candidate")
        finally:
            import shutil
            shutil.rmtree(empty, ignore_errors=True)

    def test_no_config_returns_none(self) -> None:
        # env pinned to an empty root; cwd candidate empty too. The
        # process-cwd fallback only applies when the process cwd carries
        # a project marker AND has a config — chdir to the bare tmp root
        # so it cannot resolve to this repo's own dogfood config.
        prev = os.getcwd()
        os.chdir(self.root)
        try:
            self.assertIsNone(sync_gate.config_path(cwd=str(self.root)))
        finally:
            os.chdir(prev)


class TestLoadCoercion(_SyncGateBase):
    def test_group_without_require_is_skipped(self) -> None:
        self._write_config(
            '[[groups]]\nname = "a"\nwhen = ["x/*.py"]\n'
        )
        loaded = sync_gate.load(cwd=str(self.root))
        self.assertIsNotNone(loaded)
        self.assertEqual(loaded[1], [], "when-only group must be skipped")

    def test_duplicate_names_keep_first(self) -> None:
        self._write_config(
            '[[groups]]\nname = "a"\nwhen = ["x/*"]\nrequire = ["y/*"]\n'
            '[[groups]]\nname = "a"\nwhen = ["z/*"]\nrequire = ["w/*"]\n'
        )
        _, groups = sync_gate.load(cwd=str(self.root))
        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0].when, ("x/*",))

    def test_dot_slash_glob_prefix_is_normalized(self) -> None:
        # Project-relative paths never start with "./"; an unnormalized
        # "./"-prefixed require glob would be permanently unsatisfiable
        # (the group would violate forever). The loader must strip it.
        self._write_config(
            '[[groups]]\nname = "a"\nwhen = ["./x/*"]\nrequire = ["./y/*"]\n'
        )
        _, groups = sync_gate.load(cwd=str(self.root))
        self.assertEqual(groups[0].when, ("x/*",))
        self.assertEqual(groups[0].require, ("y/*",))

    def test_invalid_mode_falls_back_to_any(self) -> None:
        self._write_config(
            '[[groups]]\nname = "a"\nwhen = ["x/*"]\nrequire = ["y/*"]\n'
            'mode = "bogus"\n'
        )
        _, groups = sync_gate.load(cwd=str(self.root))
        self.assertEqual(groups[0].mode, "any")

    def test_malformed_toml_returns_none(self) -> None:
        self._write_config("this is [[ not toml\n")
        self.assertIsNone(sync_gate.load(cwd=str(self.root)))


class TestEvaluate(_SyncGateBase):
    ANY_CFG = (
        '[[groups]]\nname = "g"\nwhen = ["rules/*.md"]\n'
        'require = ["prompts/*.md", "docs/*.md"]\n'
    )
    ALL_CFG = (
        '[[groups]]\nname = "g"\nwhen = ["rules/*.md"]\n'
        'require = ["prompts/*.md", "docs/*.md"]\nmode = "all"\n'
    )

    def test_any_mode_one_require_suffices(self) -> None:
        self._write_config(self.ANY_CFG)
        edited = [self._touch("rules/06.md"), self._touch("prompts/p.md")]
        self.assertEqual(sync_gate.evaluate(edited, cwd=str(self.root)), [])

    def test_any_mode_unmet_reports_violation(self) -> None:
        self._write_config(self.ANY_CFG)
        edited = [self._touch("rules/06.md")]
        v = sync_gate.evaluate(edited, cwd=str(self.root))
        self.assertEqual(len(v), 1)
        self.assertEqual(v[0].group.name, "g")
        self.assertTrue(v[0].when_hits)

    def test_all_mode_partial_require_still_violates(self) -> None:
        # The v0.22.1 failure shape: one lock-step sibling updated, the
        # other stale. any-of would go green; all-of must not.
        self._write_config(self.ALL_CFG)
        edited = [self._touch("rules/06.md"), self._touch("prompts/p.md")]
        v = sync_gate.evaluate(edited, cwd=str(self.root))
        self.assertEqual(len(v), 1, "mode=all with a stale sibling must violate")

    def test_all_mode_every_require_satisfies(self) -> None:
        self._write_config(self.ALL_CFG)
        edited = [
            self._touch("rules/06.md"),
            self._touch("prompts/p.md"),
            self._touch("docs/d.md"),
        ]
        self.assertEqual(sync_gate.evaluate(edited, cwd=str(self.root)), [])

    def test_outside_project_edits_are_ignored(self) -> None:
        self._write_config(self.ANY_CFG)
        outside = tempfile.mkdtemp(prefix="ccens-sg4-")
        try:
            f = Path(outside) / "rules" / "06.md"
            f.parent.mkdir(parents=True)
            f.write_text("x\n", encoding="utf-8")
            self.assertEqual(
                sync_gate.evaluate([_norm(str(f))], cwd=str(self.root)), [],
            )
        finally:
            import shutil
            shutil.rmtree(outside, ignore_errors=True)

    def test_dotdot_named_dir_inside_project_is_inside(self) -> None:
        # A directory literally named "..data" is inside the project even
        # though its relpath starts with the characters "..".
        rel = sync_gate._project_relative(
            _norm(str(self.root / "..data" / "x.py")), str(self.root),
        )
        self.assertIsNotNone(rel, '"..data" dir must not be treated as outside')

    def test_parent_path_is_outside(self) -> None:
        parent_file = _norm(str(self.root.parent / "x.py"))
        self.assertIsNone(
            sync_gate._project_relative(parent_file, str(self.root)),
        )


class TestConfigEncodingRobustness(_SyncGateBase):
    """v0.25 — a mis-encoded config must degrade, never crash.

    `tomllib.load(fileobj)` decodes the stream itself and raises
    `UnicodeDecodeError` (a `ValueError`), which neither the `OSError`
    nor the `TOMLDecodeError` clause caught. It escaped `load()` and
    crashed stop_guard's layer-(i) evaluation — which also skipped the
    turn-boundary `clear_edit_flag`. A UTF-8 BOM (what several standard
    Windows save paths emit) made the first `[[groups]]` an invalid
    statement, silently dropping every group.
    """

    def _write_bytes(self, data: bytes) -> None:
        d = self.root / ".claude" / "cc-enslaver"
        d.mkdir(parents=True, exist_ok=True)
        (d / "sync-gate.toml").write_bytes(data)

    def _body(self) -> str:
        nl = chr(10)
        return (
            "[[groups]]" + nl
            + 'name = "g"' + nl
            + 'when = ["a/*.md"]' + nl
            + 'require = ["b/*.md"]' + nl
            + 'note = "中文说明"' + nl
        )

    def test_utf8_control_loads(self) -> None:
        self._write_bytes(self._body().encode("utf-8"))
        loaded = sync_gate.load(str(self.root))
        self.assertIsNotNone(loaded)
        self.assertEqual([g.name for g in loaded[1]], ["g"])

    def test_bom_prefixed_config_still_loads(self) -> None:
        self._write_bytes(b"\xef\xbb\xbf" + self._body().encode("utf-8"))
        loaded = sync_gate.load(str(self.root))
        self.assertIsNotNone(loaded, msg="BOM made the config unparseable")
        self.assertEqual([g.name for g in loaded[1]], ["g"])

    def test_non_utf8_config_degrades_without_raising(self) -> None:
        self._write_bytes(self._body().encode("gbk"))
        # Must not raise — the whole Stop layer (i) runs inside this call.
        self.assertIsNone(sync_gate.load(str(self.root)))
        self.assertEqual(
            sync_gate.evaluate([str(self.root / "a" / "x.md")], str(self.root)),
            [],
        )


if __name__ == "__main__":
    unittest.main()
