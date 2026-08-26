# Tests — index

**733 tests, 21 files, zero dependencies.** This file is the index: every
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
| [`_helpers.py`](_helpers.py) | — | `run_hook(...)`: launches a script as a real subprocess with a synthetic JSON stdin payload and returns `(returncode, parsed_stdout, stderr)`. Every file below imports it. **It serialises with `ensure_ascii=False`, and that is load-bearing** (v0.37): the `json.dumps` default escaped every non-ASCII character before the bytes existed, so the wire was pure ASCII and the encoding boundary was unreachable from any test here — which is how a defect that silently disabled every CJK detector survived 691 tests. |

### Hook entry points — black-box subprocess

Each of these invokes the target script the way Claude Code does. That
matters: module-level state, stdin handling, stdout buffering and exit codes
all behave differently when a script is imported instead of executed.

| File | Tests | Covers |
|---|---:|---|
| [`test_inject_context.py`](test_inject_context.py) | 28 | [`inject_context.py`](../hooks/scripts/inject_context.py) — SessionStart / UserPromptSubmit payload shape, language switching, UTF-8 + CJK survival, the YAML reply-schema contract, the 10,000-character output cap, and the v0.34.1 edict-clipping regression (boundary pattern coupled to the real rendered row shape; elision notice must report the true count). |
| [`test_read_guard.py`](test_read_guard.py) | 108 | [`read_guard.py`](../hooks/scripts/read_guard.py) — read-before-edit allow/deny matrix, the rule 09 / 10 / 11 content detectors, the rolling-patch counter, path normalisation, `edited_files` recording, 12-way concurrent state writes, and fail-open. v0.35 adds the end-to-end wiring for `lib/editscale`: a sub-floor file reaching a reset, net reductions and version bumps passing at the threshold, and each of those with the twin that still denies. **Its fixture matters** — the rolling-patch cases need a target large enough that the ABSOLUTE bounds bind, because the one-line fixture used from v0.13 to v0.34 is why the small-file lock-in was invisible. |
| [`test_bash_guard.py`](test_bash_guard.py) | 21 | [`bash_guard.py`](../hooks/scripts/bash_guard.py) — the bypass-pattern catalog, force-push spellings, the register-as-read hatch (including its chaining and command-position rules), event gating, fail-open. |
| [`test_stop_guard.py`](test_stop_guard.py) | 148 | [`stop_guard.py`](../hooks/scripts/stop_guard.py) — all nine layers, the status-table format contract, per-layer grace, production-shape payloads (no `turn_count`), transcript fallback, tldr presence and length. v0.35 adds `TestTldrDisplayWidth`: the cap counts display columns, so 100 汉字 (200 columns) now blocks while 75 (150 columns) still passes and every ASCII boundary is unmoved — the strictness increase and the no-op asserted in both directions. |

### Shared modules and auxiliary scripts

| File | Tests | Covers |
|---|---:|---|
| [`test_hookio.py`](test_hookio.py) | 21 | [`lib/hookio.py`](../hooks/scripts/lib/hookio.py) (v0.37) — the payload-decoding boundary, plus the encoding contract at all four hook entries end to end. The unit half asserts CJK markers survive **by identity** (mojibake also raises nothing, which is the whole problem) and ships the refusal twin: non-UTF-8 bytes must raise, not be rewritten into something that still parses. The end-to-end half forces `PYTHONIOENCODING=cp936:surrogateescape` so a defect that only appears on a non-UTF-8 host is reproducible on the ubuntu runner too — a gate that can only fail on one laptop is not a gate — and `TestReproductionIsLive` fails if that reproduction ever stops biting, so a future Python cannot turn the file green for the wrong reason. Five cases were verified RED pre-fix; the rest are labelled as controls, because an allow-only test cannot tell a working hatch from a deleted detector. |
| [`test_messages.py`](test_messages.py) | 17 | [`lib/messages.py`](../hooks/scripts/lib/messages.py) + the two catalogs (v0.38) — the guards' user-facing text, once it stopped being bilingual constants inside the guards. Three properties a reviewer cannot eyeball across 27 KB of prose: the English catalog carries **zero CJK** on every value (the user-visible requirement, as an assertion); the Chinese catalog is **actually translated**, not the English strings copied across, which would satisfy a key-set check while leaving the output in English; and `CC_ENFORCER_LANG` really changes what a guard PRINTS, proven end to end through hook subprocesses. Every language case ships its English twin — "the output is Chinese" means nothing without "and the default is not". Key-set and placeholder parity live in `test_i18n_sync.py` instead, against the real repo, and are not duplicated here. |
| [`test_envfile.py`](test_envfile.py) | 11 | [`lib/envfile.py`](../hooks/scripts/lib/envfile.py) (v0.34) — the pure dedupe model (last-occurrence wins, order survives, refusal twins for non-export lines and open quotes) plus black-box SessionStart runs proving a duplicated `CLAUDE_ENV_FILE` shrinks and a refused one stays byte-identical. |
| [`test_edicts.py`](test_edicts.py) | 64 | [`lib/edicts.py`](../hooks/scripts/lib/edicts.py) loading / injection / DENY / severity gating **and** the [`manage_edicts.py`](../hooks/scripts/manage_edicts.py) CLI, including its TOML round-trip, cwd fallback, and the v0.33 single-definition pin on the `--global` path (write target must be the loader's `global_path()`, which must derive from `_PLUGIN_NAME`). |
| [`test_sync_gate.py`](test_sync_gate.py) | 19 | [`lib/sync_gate.py`](../hooks/scripts/lib/sync_gate.py) — config resolution order, TOML tolerance, any-vs-all mode, `./` glob normalisation, project-relative boundaries. |
| [`test_editscale.py`](test_editscale.py) | 40 | [`lib/editscale.py`](../hooks/scripts/lib/editscale.py) (v0.35) — the change-scale model: that `scale=None` reproduces the pre-v0.35 absolute classifier exactly (which is what makes the unmeasurable-file fallback safe), the 30%-coverage route with both axes isolated and both boundaries inclusive-checked, net reduction, and the bookkeeping allowlist in code vs prose. It exists **because** the end-to-end tests could not reach the defect: a classifier only reachable through a hook payload, with every fixture one line long, has a whole region of its input space no test can enter. Every exemption ships its refusal twin — `timeout = 30 → 300` and `assertEqual(x, 617 → 619)` must still be refused, or the allowlist would be "any digit". |
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
| [`test_doc_sync.py`](test_doc_sync.py) | 18 | Stale counts and inventories: rule count, command count, test count, the Bash deny set on every surface that claims to list it, the `lib/` module inventory in all three structure trees (README.zh.md joined in v0.34.1, closing the mirror-coverage class for the third time), and every repo-relative markdown link. **v0.35.1 adds three gates over things a doc can only get wrong by hand:** advertised hedge triggers are re-derived from `stop_guard._HEDGE_INNER` (both READMEs named `should be fine` / `应该`, which the detector deliberately ignores — so the layer-(b) demo's output could not have come from its own input); sample coverage bars are re-derived from `editscale.coverage_bar` (the sample printed `1104` where the code computes `1102`); and every backticked `UPPER_SNAKE` identifier in a non-CHANGELOG doc must resolve to a real Python definition or be registered in `DOC_ONLY_IDENTIFIERS` with a reason (ARCHITECTURE cited four block-reason constants deleted in v0.12.0 for the twenty-three releases since). All three were checked RED against the pre-fix tree before being committed. |
| [`test_i18n_sync.py`](test_i18n_sync.py) | 13 | Translation drift: file-set parity, ATX heading-level sequence, and enforcement-token parity (a `zh` session must not be promised a smaller deny set than an `en` one). **v0.38 adds the message-catalog half**, which is stronger because a dict admits comparisons markdown does not: exact key sets both directions, per-key `str.format` field parity, and a check that every key a guard asks for exists at all. The placeholder check is the runtime one — a dropped field renders fine and says less, an invented one raises inside the hook mid-deny. Ships the boundary case that proves the checker can return clean, so the two drift cases are not passing on a checker that always reports. |
| [`test_demo.py`](test_demo.py) | 9 | The before/after images both READMEs embed (v0.36). Re-runs [`demo/run_demo.py`](../demo/run_demo.py) and compares against the committed `demo/out/*.svg` byte for byte, so a change to any hook's wording fails CI instead of leaving a stale picture on the front page — the v0.35.1 class applied to an image. **The equality check is only half of it:** it would also be satisfied by a demo that stopped denying anything, as long as somebody re-rendered afterwards, so each of the three verdicts is additionally asserted by content and the unguarded run is asserted to still end in a silent failure. This is the one gate whose expectation is a *recorded artefact* rather than a value derived at test time — which is why the artefact is regenerated from the live hooks on every run rather than trusted. |

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
- **Judgement prose.** `test_doc_sync.py` pins numbers, inventories, and — as
  of v0.35.1 — three derivable *behavioural* claim classes: advertised hedge
  triggers, printed coverage bars, and backticked identifiers. It still says
  nothing about whether an explanation is right, what order a guard's checks
  run in, or whether a rationale is sound. See its module docstring, notes 4
  and 5, which separate what became checkable from what did not.
