"""The sync-gate authoring CLI, and the defect it was born with (v0.31).

House rules (see tests/README.md): every "this is allowed" assertion has a
twin that makes it fail, and the star test here is a REGRESSION — the first
draft of `manage_sync_gate.py` wrote two groups into this repository's own
config while under test against a scratch repo, because it picked its write
target with the resolver built for READING.

That bug is the reason `sync_gate.default_project_path` and
`sync_gate.load_file` exist, so both directions are pinned:

  * a write must land in the project that was named, even when that project
    has no config yet and the process cwd has one;
  * a read of a specific file must not fall through to a different file.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
# because the sys.path bootstrap above must run before this import
from _helpers import SCRIPTS_DIR  # noqa: E402

sys.path.insert(0, str(SCRIPTS_DIR))
# because the scripts-dir bootstrap above must precede this lib import
from lib import sync_gate as sg  # noqa: E402
# because of that same bootstrap, this import cannot sit at the top either
from lib import tomlio  # noqa: E402

CLI = str(SCRIPTS_DIR / "manage_sync_gate.py")
REPO_ROOT = SCRIPTS_DIR.parent.parent

_GROUP = """[[groups]]
name = "%s"
when = ["%s"]
require = ["%s"]
"""


def _run(args, *, cwd, project_dir=None):
    """Invoke the CLI as a real subprocess; returns (rc, stdout, stderr)."""
    env = os.environ.copy()
    env.pop("CLAUDE_PROJECT_DIR", None)
    if project_dir is not None:
        env["CLAUDE_PROJECT_DIR"] = str(project_dir)
    p = subprocess.run(
        [sys.executable, CLI, *args],
        capture_output=True, cwd=str(cwd), env=env,
    )
    return (p.returncode,
            p.stdout.decode("utf-8", errors="replace"),
            p.stderr.decode("utf-8", errors="replace"))


class _RepoBase(unittest.TestCase):
    """Two throwaway repos: `a` (the target) and `b` (the shell's cwd)."""

    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="ccens-msg-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.a = self._mkrepo("a")
        self.b = self._mkrepo("b")

    def _mkrepo(self, name: str) -> Path:
        root = self.tmp / name
        (root / ".git").mkdir(parents=True)      # project-root marker
        (root / "src").mkdir()
        (root / "docs").mkdir()
        (root / "src" / "m.py").write_text("x = 1\n", encoding="utf-8")
        (root / "docs" / "m.md").write_text("# m\n", encoding="utf-8")
        return root

    def _cfg(self, root: Path) -> Path:
        return root / ".claude" / "cc-enforcer" / "sync-gate.toml"

    def _seed(self, root: Path, name="seeded", when="src/*.py",
              require="docs/*.md") -> Path:
        p = self._cfg(root)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(_GROUP % (name, when, require), encoding="utf-8")
        return p


class TestWriteTargetIsNotASearch(_RepoBase):
    """The v0.31 birth defect: a write resolved like a read."""

    def test_add_writes_to_the_named_project_not_the_process_cwd(self) -> None:
        """Repo `a` is named and has NO config; repo `b` (cwd) has one.

        The original code called `config_path()`, which tests each candidate
        with `.is_file()`. `a`'s candidate did not exist, so resolution fell
        through to the process cwd and the group landed in `b`.
        """
        self._seed(self.b, name="b-own")
        b_before = self._cfg(self.b).read_text(encoding="utf-8")

        rc, out, err = _run(
            ["add", "mine", "--when", "src/*.py", "--require", "docs/*.md"],
            cwd=self.b, project_dir=self.a,
        )
        self.assertEqual(rc, 0, msg=f"stdout={out!r} stderr={err!r}")
        self.assertTrue(self._cfg(self.a).is_file(),
                        "the named project got no config at all")
        self.assertIn("mine", self._cfg(self.a).read_text(encoding="utf-8"))
        self.assertEqual(
            self._cfg(self.b).read_text(encoding="utf-8"), b_before,
            "the CLI modified the repo the shell happened to be in — this is "
            "the exact defect the write/read resolver split exists to stop",
        )

    def test_init_also_targets_the_named_project(self) -> None:
        self._seed(self.b, name="b-own")
        rc, _, err = _run(["init"], cwd=self.b, project_dir=self.a)
        self.assertEqual(rc, 0, msg=err)
        self.assertTrue(self._cfg(self.a).is_file())

    def test_default_project_path_ignores_an_unrelated_existing_config(
        self,
    ) -> None:
        """Unit-level twin: the resolver itself, not just the CLI."""
        self._seed(self.b)
        target = sg.default_project_path(str(self.a))
        self.assertEqual(target, self._cfg(self.a))

    def test_config_path_still_searches_because_reading_must(self) -> None:
        """The counterpart contract: the READ resolver keeps its fallback.

        Without this, "fixing" the write bug by making both deterministic
        would break the hook path, which must find whatever config governs
        the session even when CLAUDE_PROJECT_DIR is missing.
        """
        seeded = self._seed(self.b)
        self.assertEqual(sg.config_path(str(self.b)), seeded)


class TestLoadFileDoesNotFallThrough(_RepoBase):
    """Second instance of the same root cause."""

    def test_load_file_of_a_missing_path_is_none_not_someone_elses(
        self,
    ) -> None:
        self._seed(self.b, name="b-own")
        groups = sg.load_file(self._cfg(self.a))
        self.assertIsNone(
            groups,
            "load_file answered with another repo's config; verifying a "
            "freshly written file that way could report on the wrong one",
        )

    def test_load_file_reads_exactly_the_given_file(self) -> None:
        self._seed(self.a, name="a-own")
        groups = sg.load_file(self._cfg(self.a))
        self.assertEqual([g.name for g in groups or []], ["a-own"])


class TestInit(_RepoBase):
    def test_init_creates_an_inert_template(self) -> None:
        rc, out, err = _run(["init"], cwd=self.a, project_dir=self.a)
        self.assertEqual(rc, 0, msg=err)
        self.assertIn("0 group(s)", out)
        self.assertEqual(sg.load_file(self._cfg(self.a)), [],
                         "a template must parse and hold no groups")

    def test_init_refuses_to_clobber(self) -> None:
        self._seed(self.a, name="precious")
        before = self._cfg(self.a).read_text(encoding="utf-8")
        rc, _, err = _run(["init"], cwd=self.a, project_dir=self.a)
        self.assertEqual(rc, 1)
        self.assertIn("refusing to overwrite", err)
        self.assertEqual(self._cfg(self.a).read_text(encoding="utf-8"), before)


class TestAddRefusesInertGroups(_RepoBase):
    """A group that PARSES but the loader DROPS enforces nothing."""

    def test_empty_require_is_refused_and_the_file_is_untouched(self) -> None:
        self._seed(self.a, name="keeper")
        before = self._cfg(self.a).read_text(encoding="utf-8")
        rc, _, err = _run(
            ["add", "bad", "--when", "src/*.py", "--require", ""],
            cwd=self.a, project_dir=self.a,
        )
        self.assertEqual(rc, 2)
        self.assertIn("DROPPED by the loader", err)
        self.assertEqual(
            self._cfg(self.a).read_text(encoding="utf-8"), before,
            "a refused write must leave the previous config byte-identical",
        )

    def test_a_well_formed_group_is_accepted(self) -> None:
        """Twin: without it, a detector that refuses everything would pass."""
        self._seed(self.a, name="keeper")
        rc, _, err = _run(
            ["add", "good", "--when", "src/*.py", "--require", "docs/*.md"],
            cwd=self.a, project_dir=self.a,
        )
        self.assertEqual(rc, 0, msg=err)
        names = [g.name for g in sg.load_file(self._cfg(self.a)) or []]
        self.assertEqual(names, ["keeper", "good"])

    def test_refusal_removes_a_file_it_created_rather_than_leaving_debris(
        self,
    ) -> None:
        rc, _, _ = _run(
            ["add", "bad", "--when", "src/*.py", "--require", ""],
            cwd=self.a, project_dir=self.a,
        )
        self.assertEqual(rc, 2)
        self.assertFalse(self._cfg(self.a).exists())

    def test_duplicate_name_is_refused(self) -> None:
        self._seed(self.a, name="dup")
        rc, _, err = _run(
            ["add", "dup", "--when", "src/*.py", "--require", "docs/*.md"],
            cwd=self.a, project_dir=self.a,
        )
        self.assertEqual(rc, 1)
        self.assertIn("already exists", err)


class TestCheck(_RepoBase):
    """`check` is the answer to failing-open: a broken gate looks healthy."""

    def test_clean_config_exits_zero(self) -> None:
        self._seed(self.a, when="src/*.py", require="docs/*.md")
        rc, out, err = _run(["check"], cwd=self.a, project_dir=self.a)
        self.assertEqual(rc, 0, msg=f"{out}{err}")
        self.assertIn("OK", out)

    def test_a_glob_matching_nothing_is_reported_and_exits_one(self) -> None:
        self._seed(self.a, when="src/*.py", require="nowhere/*.rst")
        rc, out, _ = _run(["check"], cwd=self.a, project_dir=self.a)
        self.assertEqual(rc, 1)
        self.assertIn("nowhere/*.rst", out)
        self.assertIn("matches NO file", out)

    def test_a_group_the_loader_drops_is_reported(self) -> None:
        """Declared-but-dropped is invisible everywhere else."""
        cfg = self._cfg(self.a)
        cfg.parent.mkdir(parents=True, exist_ok=True)
        cfg.write_text(
            '[[groups]]\nname = "ghost"\nwhen = ["src/*.py"]\nrequire = []\n',
            encoding="utf-8",
        )
        rc, out, _ = _run(["check"], cwd=self.a, project_dir=self.a)
        self.assertEqual(rc, 1)
        self.assertIn("ghost", out)
        self.assertIn("DROPPED by the loader", out)

    def test_no_config_is_not_an_error(self) -> None:
        """Layer (i) is opt-in; having no config is the normal case."""
        rc, out, _ = _run(["check"], cwd=self.a, project_dir=self.a)
        self.assertEqual(rc, 0)
        self.assertIn("inert", out)


class TestListAndRemove(_RepoBase):
    def test_list_reports_what_the_loader_kept(self) -> None:
        self._seed(self.a, name="alpha")
        rc, out, _ = _run(["list"], cwd=self.a, project_dir=self.a)
        self.assertEqual(rc, 0)
        self.assertIn("alpha", out)
        self.assertIn("1 group(s) loaded", out)

    def test_remove_drops_only_the_named_group(self) -> None:
        self._seed(self.a, name="alpha")
        _run(["add", "beta", "--when", "src/*.py", "--require", "docs/*.md"],
             cwd=self.a, project_dir=self.a)
        rc, _, err = _run(["remove", "alpha"], cwd=self.a, project_dir=self.a)
        self.assertEqual(rc, 0, msg=err)
        names = [g.name for g in sg.load_file(self._cfg(self.a)) or []]
        self.assertEqual(names, ["beta"])

    def test_remove_of_an_absent_group_fails_loudly(self) -> None:
        self._seed(self.a, name="alpha")
        rc, _, err = _run(["remove", "nope"], cwd=self.a, project_dir=self.a)
        self.assertEqual(rc, 1)
        self.assertIn("No group named", err)


class TestModeAllRoundTrips(_RepoBase):
    def test_mode_all_survives_a_write_and_reload(self) -> None:
        rc, _, err = _run(
            ["add", "lockstep", "--when", "src/*.py",
             "--require", "docs/*.md", "--all"],
            cwd=self.a, project_dir=self.a,
        )
        self.assertEqual(rc, 0, msg=err)
        groups = sg.load_file(self._cfg(self.a)) or []
        self.assertEqual([g.mode for g in groups], ["all"])

    def test_default_mode_is_any_and_is_not_written_out(self) -> None:
        """Twin: proves the `mode` line above is not always emitted."""
        _run(["add", "plain", "--when", "src/*.py", "--require", "docs/*.md"],
             cwd=self.a, project_dir=self.a)
        text = self._cfg(self.a).read_text(encoding="utf-8")
        # Only the emitted GROUP body — the template header documents both
        # modes in prose, so scanning the whole file would always match.
        emitted = "[[groups]]" + text.split("[[groups]]")[-1]
        self.assertNotIn("mode =", emitted)
        groups = sg.load_file(self._cfg(self.a)) or []
        self.assertEqual([g.mode for g in groups], ["any"])


class TestThisRepoConfigIsHealthy(unittest.TestCase):
    """v0.32 — cc-enforcer's OWN sync-gate config is checked in CI.

    v0.31.0 shipped `check` on the argument that an unenforced gate you
    still trust is worse than none, and exited 1 specifically so it could
    run in CI — and then this repository never ran it on itself. The same
    defect one level up: a diagnostic nobody runs is a diagnostic that
    reports nothing.

    Wired as a test rather than a workflow step, matching
    `test_i18n_sync.py`, which calls `check_sync()` on the real tree. That
    way `python -m unittest discover tests` covers it locally too — a
    workflow-only step is invisible until push.
    """

    def test_check_passes_on_this_repository(self) -> None:
        rc, out, err = _run(["check"], cwd=REPO_ROOT, project_dir=REPO_ROOT)
        self.assertEqual(
            rc, 0,
            f"this repo's own .claude/cc-enforcer/sync-gate.toml has a "
            f"problem — a dropped group or a glob matching no file means "
            f"Stop layer (i) is silently not guarding what the config "
            f"claims.\n\nstdout:\n{out}\nstderr:\n{err}",
        )

    def test_the_check_is_actually_armed_here(self) -> None:
        """Twin: a green `check` must mean groups exist, not that none do.

        Without this, deleting every group from the config would make the
        assertion above pass — the "0 items, therefore no failures" shape
        that `test_doc_sync` calls a vacuous green.
        """
        groups = sg.load_file(
            REPO_ROOT / ".claude" / "cc-enforcer" / "sync-gate.toml")
        self.assertTrue(groups, "this repo dogfoods rule 12; groups vanished")
        _, out, _ = _run(["check"], cwd=REPO_ROOT, project_dir=REPO_ROOT)
        self.assertIn(f"{len(groups)} group(s) loaded", out)


class TestSharedPrimitives(unittest.TestCase):
    """One definition, several consumers — pinned so a copy cannot reappear."""

    def test_the_matcher_is_shared_with_the_gate(self) -> None:
        self.assertTrue(sg.matches_any("rules/zh/01-x.md", ("rules/*.md",)),
                        "fnmatch `*` must cross path separators")
        self.assertFalse(sg.matches_any("docs/x.md", ("rules/*.md",)))

    def test_the_toml_encoder_is_shared_with_manage_edicts(self) -> None:
        import manage_edicts
        self.assertIs(manage_edicts._toml_basic_string, tomlio.basic_string)

    def test_encoder_escapes_what_broke_configs_before(self) -> None:
        self.assertEqual(tomlio.basic_string("a\nb"), "a\\nb")
        self.assertEqual(tomlio.basic_string("\x7f"), "\\u007F")

    def test_dumps_check_accepts_valid_and_names_invalid(self) -> None:
        self.assertIsNone(tomlio.dumps_check('a = "b"\n'))
        self.assertIsNotNone(tomlio.dumps_check("a = \n"))


class TestPathPrintsTheWriteTarget(_RepoBase):
    """v0.33 — `path` must print where `add` would WRITE, not the cwd.

    The old `cmd_path` derived its would-be path from the process cwd with
    a hand-joined copy of the plugin-name literal, while `add` / `init`
    write through `sg.default_project_path()` — which honours
    CLAUDE_PROJECT_DIR first. With the env naming repo `a` and the shell
    sitting in repo `b`, `path` printed a location in `b` that no write
    would ever touch: the same print-vs-write divergence class as the
    v0.31 birth defect this file's star test pins. Found during the
    cc-enslaver → cc-enforcer rename.
    """

    def test_path_with_no_config_prints_the_named_projects_target(self) -> None:
        rc, out, err = _run(["path"], cwd=self.b, project_dir=self.a)
        self.assertEqual(rc, 0, msg=f"stdout={out!r} stderr={err!r}")
        self.assertIn(str(self._cfg(self.a)), out,
                      "path must print the deterministic write target")
        self.assertNotIn(str(self._cfg(self.b)), out,
                         "path printed a location in the repo the shell "
                         "happened to be in — no write would land there")


if __name__ == "__main__":
    unittest.main()
