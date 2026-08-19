# Tests — index

**617 tests, 17 files, zero dependencies.** This file is the index: every
test file appears below with what it covers and why it exists. Nothing else
in the repo enumerates the suite — [`CLAUDE.md`](../CLAUDE.md) used to keep a
second, class-by-class copy of this list, and it had been wrong since v0.26.

## Run

```bash
# From the repo root, stdlib only — no pytest needed:
python -m unittest discover tests

# One file:
python -m unittest discover -s tests -p "test_read_guard.py" -v
```

Pytest also works (it runs `unittest` classes natively): `pytest tests/`.

## How the files are named

Each file is named after **the thing it covers**, with two suffix/prefix
conventions layered on top:

| Naming shape | Category | Meaning |
|---|---|---|
| `test_<hook-script>.py` | **hook** | Black-box subprocess test of one registered hook entry point. |
| `test_<module>.py` | **lib / cli** | Unit test of one shared module or auxiliary script. |
| `test_*_sync.py` | **gate** | A CI drift gate — derives its expectations from the code, then fails when a doc, manifest or translation disagrees. |
| `test_audit_*.py` | **audit** | The regression suite of one audit round, pinning the defects that round confirmed. |

## Inventory

### Shared fixture

| File | Tests | Covers |
|---|---:|---|
| [`_helpers.py`](_helpers.py) | — | `run_hook(...)`: launches a script as a real subprocess with a synthetic JSON stdin payload and returns `(returncode, parsed_stdout, stderr)`. Every file below imports it. |

### Hook entry points — black-box subprocess

Each of these invokes the target script the way Claude Code does. That
matters: module-level state, stdin handling, stdout buffering and exit codes
all behave differently when a script is imported instead of executed.

| File | Tests | Covers |
|---|---:|---|
| [`test_inject_context.py`](test_inject_context.py) | 28 | [`inject_context.py`](../hooks/scripts/inject_context.py) — SessionStart / UserPromptSubmit payload shape, language switching, UTF-8 + CJK survival, the YAML reply-schema contract, the 10,000-character output cap, and the v0.34.1 edict-clipping regression (boundary pattern coupled to the real rendered row shape; elision notice must report the true count). |
| [`test_read_guard.py`](test_read_guard.py) | 99 | [`read_guard.py`](../hooks/scripts/read_guard.py) — read-before-edit allow/deny matrix, the rule 09 / 10 / 11 content detectors, the rolling-patch counter, path normalisation, `edited_files` recording, 12-way concurrent state writes, and fail-open. |
| [`test_bash_guard.py`](test_bash_guard.py) | 21 | [`bash_guard.py`](../hooks/scripts/bash_guard.py) — the bypass-pattern catalog, force-push spellings, the register-as-read hatch (including its chaining and command-position rules), event gating, fail-open. |
| [`test_stop_guard.py`](test_stop_guard.py) | 138 | [`stop_guard.py`](../hooks/scripts/stop_guard.py) — all nine layers, the status-table format contract, per-layer grace, production-shape payloads (no `turn_count`), transcript fallback, tldr presence and length. |

### Shared modules and auxiliary scripts

| File | Tests | Covers |
|---|---:|---|
| [`test_envfile.py`](test_envfile.py) | 11 | [`lib/envfile.py`](../hooks/scripts/lib/envfile.py) (v0.34) — the pure dedupe model (last-occurrence wins, order survives, refusal twins for non-export lines and open quotes) plus black-box SessionStart runs proving a duplicated `CLAUDE_ENV_FILE` shrinks and a refused one stays byte-identical. |
| [`test_edicts.py`](test_edicts.py) | 64 | [`lib/edicts.py`](../hooks/scripts/lib/edicts.py) loading / injection / DENY / severity gating **and** the [`manage_edicts.py`](../hooks/scripts/manage_edicts.py) CLI, including its TOML round-trip, cwd fallback, and the v0.33 single-definition pin on the `--global` path (write target must be the loader's `global_path()`, which must derive from `_PLUGIN_NAME`). |
| [`test_sync_gate.py`](test_sync_gate.py) | 19 | [`lib/sync_gate.py`](../hooks/scripts/lib/sync_gate.py) — config resolution order, TOML tolerance, any-vs-all mode, `./` glob normalisation, project-relative boundaries. |
| [`test_gc_state.py`](test_gc_state.py) | 19 | [`gc_state.py`](../hooks/scripts/gc_state.py) — argument validation, dry-run vs apply, threshold semantics, and auto-GC on SessionStart. |
| [`test_register_read.py`](test_register_read.py) | 5 | [`register_read.py`](../hooks/scripts/register_read.py) — the user-facing stub's own hash verification and exit codes. (The authoritative check lives in `bash_guard`, so it is tested there.) |
| [`test_manage_sync_gate.py`](test_manage_sync_gate.py) | 28 | [`manage_sync_gate.py`](../hooks/scripts/manage_sync_gate.py) — the rule-12 config CLI, plus the shared primitives it forced out of hiding (`sync_gate.default_project_path` / `load_file` / `matches_any`, `tomlio.basic_string` / `dumps_check`). Its star test is a **regression**: the CLI's first draft picked its write target with the READ resolver and wrote two groups into this repository's own config. Both directions are pinned — a write lands in the named project, and the read resolver keeps the fallback the hook path depends on. v0.33 adds the sibling pin: `path` prints through the same deterministic write resolver, never a cwd-derived hand-join. |

### CI drift gates

These are the reason documentation claims in this repo do not rot. Each
derives its expectation **from the code at test time** and never compares one
document against another — two documents can drift together, and here they
demonstrably did.

| File | Tests | Guards against |
|---|---:|---|
| [`test_version_sync.py`](test_version_sync.py) | 5 | A version pointer that does not match `plugin.json`. The set of version-bearing JSON pointers is *closed*, so a newly added field fails until registered. Born from v0.22.1, which shipped with a stale `marketplace.json`. |
| [`test_doc_sync.py`](test_doc_sync.py) | 12 | Stale counts and inventories: rule count, command count, test count, the Bash deny set on every surface that claims to list it, the `lib/` module inventory in all three structure trees (README.zh.md joined in v0.34.1, closing the mirror-coverage class for the third time), and every repo-relative markdown link. |
| [`test_i18n_sync.py`](test_i18n_sync.py) | 9 | Translation drift: file-set parity, ATX heading-level sequence, and enforcement-token parity (a `zh` session must not be promised a smaller deny set than an `en` one). |

### Audit-round regressions

House rule, followed throughout: **every "this is allowed" assertion has a
twin that removes the reason and requires a DENY.** An allow-only test cannot
tell a working escape hatch from a deleted detector — four such tests shipped
in v0.25.1 and passed on the unfixed tree.

Second house rule: fixtures containing suppression markers, credentials or
home paths are **assembled at runtime**. This plugin scans its own test files;
a literal fixture would make the module unwritable by any agent running it.

| File | Tests | Round |
|---|---:|---|
| [`test_audit_v026_models.py`](test_audit_v026_models.py) | 93 | v0.26 round 4 — the shared judgement models (`TestSrclex` / `TestMdctx` / `TestShellcmd`) plus one regression class per confirmed defect. Every test here is red on the pre-fix tree. |
| [`test_audit_v026_round2.py`](test_audit_v026_round2.py) | 54 | v0.26 round 5 — 16 parallel read-only reviews; each test pins a defect reproduced against the real code before anything was changed. |
| [`test_audit_v027_contracts.py`](test_audit_v027_contracts.py) | 12 | v0.27 — the three items v0.26 recorded as "known, not fixed", each closed as a deliberate contract change. |

## Adding a test case

1. Add the **positive case** (the new pattern the guard should catch).
2. Add a **nearby negative case** that is similar but must *not* trigger, so
   the boundary is visible to the next contributor.
3. If the case asserts that something is **allowed**, add the twin that makes
   it denied. Otherwise the test survives the detector being deleted.
4. Update the connected files listed in
   [`../docs/ARCHITECTURE.md`](../docs/ARCHITECTURE.md) §8 — and this index,
   if you added a file.

## What is intentionally NOT tested here

- **End-to-end install.** `/plugin marketplace add` is a Claude Code IDE
  surface, not a CLI one. That the plugin loads is verified by hand after an
  install.
- **Live tool denial inside Claude Code.** These tests prove each script emits
  the documented JSON for the documented stdin shape. Whether Claude Code
  honours a `deny` is Claude Code's contract, not ours.
- **Prose accuracy.** `test_doc_sync.py` pins numbers and inventories. It says
  nothing about whether the paragraphs around them are true — see its module
  docstring, which lists its own blind spots.
