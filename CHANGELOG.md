# Changelog

All notable changes to **anti-laziness** are documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and
this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [Unreleased]

### Planned (roadmap)

- **Additional bypass patterns**
  - Evaluate adding `git reset --hard` (if uncommitted changes), `git rebase
    --skip`, `pip install --break-system-packages`, etc. — currently held back
    on false-positive concerns.

---

## [0.6.2] — 2026-04-29

English mirror of `rules/`. Adds `rules/en/00-index.md` plus
`01-verify-dont-guess.md` through `06-verify-convergence.md`. The
Chinese sources remain canonical; the English mirror is best-effort
and intended for two use cases:

1. Non-CJK readers who want to read the discipline pack.
2. Using anti-laziness as an LLM-agnostic system-prompt fragment with
   non-Claude agents (OpenAI / Gemini / local models). Concatenate
   `rules/en/*.md` and prepend to your agent's system prompt.

### Added

- `rules/en/00-index.md` — index parallel to `rules/00-index.md`.
- `rules/en/01-verify-dont-guess.md`
- `rules/en/02-systematic-not-reactive.md`
- `rules/en/03-root-cause.md`
- `rules/en/04-full-context.md`
- `rules/en/05-cite-sources.md`
- `rules/en/06-verify-convergence.md`

### Changed

- `.claude-plugin/plugin.json` + `marketplace.json` — version bumped
  0.6.1 → 0.6.2 (patch: documentation only, no behavioural change).
- `CLAUDE.md` §6 — flips English mirror from roadmap to implemented.
- `README.md` — install section's "as a rule pack for any other LLM"
  now points at `rules/en/`.
- `docs/ARCHITECTURE.md` — Layer 5 description mentions both the
  Chinese sources and the English mirror.
- `docs/RULES.md` — adds a "Languages" pointer to `rules/en/`.

### Removed (Unreleased roadmap)

- "English mirror of `rules/`" — implemented here.

### Verified

- 60/60 unit tests pass (no executable code added; rules are static
  Markdown). CI matrix re-verifies on push.
- All 7 English files have valid YAML frontmatter and parallel
  structure to their Chinese counterparts.

---

## [0.6.1] — 2026-04-29

Session state GC. Manual-only (no auto-trigger) — invokable from a
Bash tool call or via the new `/anti-laziness:gc` slash command.

### Why

Each session writes one JSON file to `${CLAUDE_PLUGIN_DATA}/sessions/<sid>.json`.
Files are KB-sized but sessions accumulate without bound across
months of use. v0.6.1 adds the manual cleanup path. Auto-on-
SessionStart was deferred to keep the hot SessionStart hook lean
and to avoid a code path running on every cold start.

### Added

- **`hooks/scripts/gc_state.py`** — standalone CLI:
  - Required: exactly one of `--dry-run` / `--apply` (refuses to
    proceed if both or neither are given — prevents accidental
    deletion).
  - `--older-than DAYS` (default 30) — files newer than the threshold
    are never touched.
  - Prints `state_dir`, `scanned`, `threshold`, `eligible` count,
    per-file age and size, and either `[dry-run] would delete` or
    `deleted: N / bytes_freed: B` summary.
  - Only globs `<state_dir>/*.json`; refuses to touch anything outside.
- **`commands/gc.md`** — `/anti-laziness:gc` slash command. Defaults
  to `--dry-run`; invokes the script with whatever argument shape
  the user requested. Documents safe-default semantics.
- **`tests/test_gc_state.py`** (9 cases):
  - Arg validation (no flags, both flags, negative threshold)
  - Dry-run lists without deleting; "nothing to do" path
  - Apply deletes + prints summary; no-eligible is no-op
  - Threshold boundary tests (higher threshold keeps more files)

### Changed

- `.claude-plugin/plugin.json` + `marketplace.json` — version bumped
  0.6.0 → 0.6.1 (patch: new tooling, no behavioural change to the
  hook layer).
- Test count 51 → **60 pass** (+9 gc cases).

### Removed (Unreleased roadmap)

- "Session state GC" — implemented here (manual flavour). Auto-GC
  on SessionStart is now a v0.7+ candidate.

### Verified

```
$ python -m unittest discover tests
............................................................
Ran 60 tests in <X>s
OK
```

Self-applied rule 06 convergence check; full report in commit / release notes.

---

## [0.6.0] — 2026-04-29

**Stop hook lands.** Rule 06 (`验证收敛`) was a soft rule until now —
v0.5.0 surfaced it via prompt injection, checklist, and skill, but
nothing prevented an agent from typing `已解决` and walking away. v0.6.0
adds a `Stop` hook that catches done-claim-without-evidence at turn
boundary and forces one corrective turn.

### How it works

Every Stop event, `stop_guard.py` inspects the agent's last message:

- **Done-claim detected** (`已解决` / `修好了` / `改好了` / `fixed` /
  `done` / etc.) and **no evidence** (no `$ ` shell prompt, no test
  output, no `重触发`, no `pytest`/`unittest`/`Ran N tests`, no fenced
  code block of output) → return
  `{"decision": "block", "reason": <rule-06 reminder>}`. Claude Code
  forces the agent to take another turn.
- **No done-claim** OR **claim plus evidence** → silent allow.

### One-shot guard

A Stop hook that always blocks would loop forever. We persist
`last_blocked_turn` in the per-session state file alongside
`read_files`. If the current `turn_count` is within 3 turns of the
last block, we skip the heuristic. The agent gets the corrective
turn (and a small grace window in case the recovery itself spans
multiple messages); after the grace expires, fresh blocks resume.

### Why heuristic, not file-claim verification

Originally roadmap-described as "verify mtime / git status of files
the agent claims to have edited". We deliberately scope down to the
done-claim heuristic for v0.6.0 because:

- Natural-language extraction of file paths from arbitrary phrasings
  is fragile and produces high false positives.
- The done-without-evidence heuristic is robust: a careful agent
  always cites evidence per rule 05, so this only fires on actual
  laziness.
- The one-shot guard caps the false-positive cost at exactly one
  extra turn per session.

Deep file-claim verification is a v0.7+ candidate — would parse
"I edited X" patterns and check `git diff` / mtime against
session-start baseline.

### Added

- **`hooks/scripts/stop_guard.py`** — Stop event handler. Done-claim +
  evidence patterns documented inline; transcript fallback if
  `assistant_message` is missing from the payload (parses
  `transcript_path` JSONL). Failing-open on exception.
- **`hooks/scripts/lib/state.py`** — `record_stop_block(session_id,
  turn_count)` and `was_just_blocked(session_id, turn_count)` helpers.
  `was_just_blocked` returns True when current turn is within
  `[last + 1, last + 3]` (grace window).
- **`tests/test_stop_guard.py`** — 16 cases:
  - Done-claim Chinese (incl. `改好了` idiom regression case)
  - Done-claim English
  - Block records `last_blocked_turn`
  - Done + evidence (command output / test count / `重触发` keyword)
  - No done-claim allows
  - One-shot guard (turn N+1, turn N+3, turn N+4)
  - Event gating (SubagentStop / PreToolUse → no-op)
  - Empty payload allows
  - Transcript fallback
  - Malformed stdin → fail-open
- **`hooks/hooks.json`** — registers `Stop` event (no `matcher` since
  Stop fires unconditionally per Claude Code spec).

### Changed

- `.claude-plugin/plugin.json` + `marketplace.json` — version bumped
  0.5.1 → 0.6.0.
- Test count 35 → **51 pass** (+16 stop_guard cases).

### Removed (Unreleased roadmap)

- "Stateful `Stop` hook" — implemented here (heuristic flavour). The
  deeper "verify file claims via mtime/git" version is now an
  Unreleased v0.7 candidate.

### Verified

```
$ python -m unittest discover tests
...................................................
----------------------------------------------------------------------
Ran 51 tests in <X>s

OK
```

Self-applied rule 06 convergence check before commit; full report in
the commit message + GitHub release notes.

---

## [0.5.1] — 2026-04-28

CI infrastructure. No plugin behavioural change — adds GitHub Actions
to run the existing test suite on every push and PR. The 35 unit tests
that v0.5.0 ships were previously only verified on the maintainer's
machine; from this release onward, every commit to `main` and every
pull request is gated by a green run on Linux + Windows.

### Added

- **`.github/workflows/test.yml`** — `tests` workflow:
  - Triggers: `push` to `main`, `pull_request` to `main`,
    `workflow_dispatch` (manual re-run from the Actions tab).
  - Matrix: `ubuntu-latest` + `windows-latest`, Python `3.13`. The
    Windows runner exists because `state.py` and the path-normalization
    paths in `read_guard.py` specifically handle Windows quirks; testing
    on POSIX alone would miss regressions there.
  - Steps: checkout → setup-python@v5 → `python -m unittest discover
    tests -v`.
  - `concurrency` cancels stale runs when new commits land on the same
    ref, so a rapid chain of pushes doesn't burn matrix minutes.
  - `permissions: contents: read` keeps the runner principle-of-least.
- **README.md** — `tests` status badge added to the badge row.

### Changed

- `.claude-plugin/plugin.json` + `marketplace.json` — version bumped
  0.5.0 → 0.5.1 (patch: no behavioural change to plugin users).
- `CLAUDE.md` §6 — `v0.5.0 → v0.5.1` and the line about CI flips from
  unimplemented to implemented.

### Removed (from Unreleased roadmap)

- "CI" — implemented here.

### Verified (rule 06 self-applied)

- **C1 重触发原症状**: "no CI" was the failure mode → workflow file now
  exists at `.github/workflows/test.yml` and parses as valid YAML.
- **C2 边界 + 反向**: YAML triggers cover push/PR/manual; matrix covers
  Linux + Windows; python `3.13` matches the reference environment;
  cancellation policy covers rapid-push edge case. First actual CI run
  on push will be the live integration test.
- **C3 连带不破坏**: `python -m unittest discover tests` locally
  produces `Ran 35 tests in 4.312s — OK` with no regressions.
- **C4 自答**:
  1. *真解决?* — Yes for the project-internal failure mode (silent
     test regressions). Caveat: CI green only proves the suite passes;
     it doesn't prove tests cover the right behaviour.
  2. *更好方案?* — Could matrix wider Python (3.11/3.12), could add
     pre-commit hooks locally too, could enable required-status-check
     branch protection. All deferred — minimum effective change is one
     workflow file, single Python version, observe one run, expand if
     needed.
  3. *改动经过验证?* — YAML syntax validated locally via `yaml.safe_load`;
     test suite confirmed green locally. Live workflow run on push is
     the final verification gate (visible from the Actions tab and the
     README badge).
  4. *验证合理?* — The check chain is "YAML parses → workflow runs →
     unittest passes on two OSes". This matches the failure-mode causal
     chain (broken test → silent regression in main).
- **C5 量化**: test count unchanged at 35 (CI doesn't add tests, just
  enforces them); matrix expansion = 1 OS → 2 OSes.

---

## [0.5.0] — 2026-04-28

New core rule 06 — **验证收敛 / verify-convergence**. Promotes the
"after-fix verification" discipline from an implicit habit into a
first-class rule with mandatory checks at every layer.

### Motivation

The first 5 rules covered specific lazy patterns: guessing (01),
reactive thinking (02), root-cause bypass (03), keyword-only edits (04),
unverifiable citations (05). They did not cover **premature
declaration of done** — the meta-failure where an agent claims "fixed"
without verifying the fix actually root-cured the problem and didn't
introduce regressions. Real incidents in this project (the
`fixture.bin` smoke test that revealed v0.3.1's PostToolUse scope bug;
the cache short-circuit only surfacing in production) all share that
shape: a fix shipped, then a test run later showed the original
failure still latent. Rule 06 makes that explicit.

### Added

- **`rules/06-verify-convergence.md`** — defines the convergence
  contract:
  1. **重触发原症状** — re-run the exact failing command/input
  2. **边界 + 反向用例** — at least 1 edge case + 1 negative case
  3. **连带不破坏** — full test/lint/typecheck pass
  4. **强制自答 4 题** —
     - 是不是真的解决了？（具体证据）
     - 有没有更好的解决方法？（与替代方案对比）
     - 改动是否经过验证？（哪些没验？为什么不需要？）
     - 验证是否合理？（是否覆盖了 rule 03 的根因因果链？）
  5. **量化优于定性** — for performance/race/compat: numbers, repeat
     counts, test matrices.
  Convergence terminates *only* when 1–5 are all backed by traceable
  evidence; otherwise → loop back to rule 02.
- Cross-references documented: 06 vs 02 (pre- vs post-action global
  check), 06 vs 03 (what to fix vs whether the fix actually rooted),
  06 vs 01 (input-side vs output-side anti-guessing), 06 vs 05
  (evidence form).
- **`prompts/session-start.md`** — adds the rule 06 summary block
  and converts the workflow constraint from "report with file:line" to
  "execute rule 06 verifications 1-5 + report with file:line +
  evidence".
- **`prompts/user-prompt.md`** — adds a 6th per-turn self-check item:
  "如果即将声称'完成'：是否重触发原症状？是否跑了边界+反向？是否自答了 4 题？"
- **`commands/checklist.md`** — gains a brand-new section **C** with
  C1-C5 (and C4.1-C4.4 for the 4-question self-quiz). Default invocation
  now prints A/B/C; argument-hint extended with `converge`.
- **`skills/systematic-debug/SKILL.md`** — Step 7 rewritten as the
  rule-06 entry point with all 5 sub-steps; output contract now demands
  "convergence verification evidence" not just "verification evidence".
- **`CLAUDE.md`** — new section §2.8 "改完必须收敛验证"; rules tree
  now lists 06; §6 "当前版本" reflects v0.5.0.

### Changed

- `rules/00-index.md` and `docs/RULES.md` — rule count 5 → 6;
  numbering range `01–05` → `01–06`; relationship diagram extended;
  "addition flow" updated for `07-xxx.md`.
- `.claude-plugin/plugin.json` + `marketplace.json` — version bumped
  0.4.0 → 0.5.0.
- `tests/test_inject_context.py` — adds an assertion that
  session-start prompt mentions rule 06 and convergence vocabulary.

### Verified

```
$ python -m unittest discover tests
.................................
----------------------------------------------------------------------
Ran 33 tests in <X>s

OK
```

(Test count unchanged: rules are documentation, not executable code.
The convergence rule's enforcement happens via prompt injection +
human/agent discipline, not via a hook script. Future hardening
options — a Stop-hook claim verifier — are documented in Unreleased
roadmap.)

---

## [0.4.0] — 2026-04-28

Read-cache escape hatch — `register_read.py` + `bash_guard.py` extension.

### Problem

After v0.3.2 fixed the out-of-project scope bug, a second failure mode
surfaced 2026-04-28 in another project (paper-review): `read_guard`
denied `Edit` on `SKILL.md` despite multiple `Read` calls. State file
inspection showed the path **was never recorded**. Root cause:
**Claude Code's harness has a Read result cache. Repeated `Read` of
the same file may be served from cache without invoking the `Read`
tool at all** — so neither `PreToolUse(Read)` (v0.3.2) nor
`PostToolUse(Read)` (earlier) ever fires. The file never enters
session state, and subsequent `Edit` is denied even though the agent
legitimately read the file. This is a Claude Code harness behavior,
not something the plugin can intercept.

### Fix

Provide an explicit "register-as-read" entry that an agent can invoke
when it knows it has read a file but the hook never fired. To prevent
this from itself becoming a laziness vector (agent registers without
actually reading), the entry **requires a SHA-256 of the file's current
on-disk content** — `bash_guard.py` recomputes the hash from disk and
only registers if the agent's claim matches.

### Added

- **`hooks/scripts/register_read.py`** — user-facing CLI stub. Takes
  `--file ABS_PATH --hash SHA256`. Verifies its own hash check (so the
  command line surface is sane) and exits 0/1/2/3 per documented exit
  codes. The actual session-state mutation happens in `bash_guard.py`.
- **`hooks/scripts/bash_guard.py` extension** — when the Bash command
  matches a `register_read.py` invocation, parse `--file` / `--hash`,
  recompute SHA-256 from disk, and:
  - if match: `state_lib.add_read(session_id, file_path)` + ALLOW
  - if mismatch / file missing / bad path / bad hash format: DENY
    with a precise diagnostic
  This is the only place where `session_id` is available, hence the
  registration must happen here (not in the stub script).
- **`hooks/scripts/read_guard.py` deny message** — now points the
  agent at the escape hatch with an inline shell example (SHA-256
  one-liner + register invocation).
- **Tests**:
  - `tests/test_register_read.py` (5 cases): correct hash, mismatch,
    missing file, relative path, uppercase hash normalization.
  - `tests/test_bash_guard.py::TestBashGuardRegisterFlow` (6 cases):
    correct hash allows + records, wrong hash denies + does not record,
    missing file denies, relative path denies, bad hash format denies,
    non-register command falls through to bypass-pattern checks.
  - **Total tests: 22 → 33** (all pass).

### Changed

- `.claude-plugin/plugin.json` + `marketplace.json` — version bumped
  0.3.2 → 0.4.0.
- `CLAUDE.md` §6 — adds the escape hatch to the implemented list.
- `docs/ARCHITECTURE.md` — Layer 1 §2 gains a new "Read-cache escape
  hatch" subsection; connected-files matrix gets `register_read.py`.
- `README.md` — version badge and feature list updated.

### Removed (from Unreleased roadmap)

- "Read-cache escape hatch" — implemented here.

### Verified

```
$ python -m unittest discover tests
.................................
----------------------------------------------------------------------
Ran 33 tests in 6.410s

OK
```

---

## [0.3.2] — 2026-04-27

Hotfix for a hook-scope bug discovered during live use of v0.3.1.

### Problem

`read_guard.py` recorded files in `PostToolUse(Read|Write)` and gated
edits in `PreToolUse(Edit|Write)`. Empirically (Claude Code v2.1.x),
**`PostToolUse` does not fire for tool calls whose target file is
outside the current project working directory, but `PreToolUse` does
fire for those calls**. The two hook events had different scopes.

Concrete failure case observed: agent calls `Read X` where X lives at
`C:\Users\<user>\.claude\projects\<project>\memory\file.md` (outside
the project's `cwd`). Read returns content; PostToolUse never fires;
state file unchanged. Agent then calls `Edit X`. PreToolUse fires,
checks state, file not present → DENY, even though the agent literally
just read the file.

### Fix

Move all recording into `PreToolUse`. The Pre handler now covers
`Read | Edit | Write`:

| Tool  | Behavior |
|-------|----------|
| Read  | record `file_path`; allow |
| Write | if file exists and is unrecorded → DENY; else record + allow |
| Edit  | if file exists and is unrecorded → DENY; else allow |

Because both record and gate live in the same hook event, they share
a scope by construction.

### Changed

- **`hooks/scripts/read_guard.py`** — `_handle_post_tool_use` removed.
  `_handle_pre_tool_use` now branches on `Read` / `Write` / `Edit` per
  the table above. Recording on Read is speculative (happens before the
  Read result is known); a Read of a non-existent path leaves a phantom
  record but is harmless because Edit's `os.path.exists` short-circuit
  covers it.
- **`hooks/hooks.json`** — `PostToolUse` block removed entirely.
  `PreToolUse` first matcher widened from `Edit|Write` to
  `Read|Edit|Write`.
- **`tests/test_read_guard.py`** — restructured around the new
  PreToolUse-only contract. New test classes: `TestPreReadRecords`,
  `TestPreWrite` (3 cases), `TestPreEdit` (4 cases incl.
  Write-then-Edit flow), `TestEventGating` (verifies stray PostToolUse
  is a no-op so future regressions can't sneak recording back in).
  Total: **22 tests pass** (up from 18 in v0.3.1).
- **`.claude-plugin/plugin.json`** + **`marketplace.json`** — version
  bumped 0.3.1 → 0.3.2.

### Verified

```
$ python -m unittest discover tests
......................
----------------------------------------------------------------------
Ran 22 tests in 3.047s

OK
```

---

## [0.3.1] — 2026-04-27

Install-time fix. v0.3.0 could not actually be installed via
`claude plugin install` because of two manifest issues that were not
caught by `claude plugin validate`:

1. The `plugin.json` listed `commands`, `skills`, `agents`, and `hooks`
   pointers to standard locations (e.g. `"hooks": "./hooks/hooks.json"`).
   At install time Claude Code rejects this with either
   `agents: Invalid input` or `Hook load failed: Duplicate hooks file
   detected` — the standard locations under `commands/`, `skills/`,
   `agents/`, and `hooks/hooks.json` are **auto-discovered**, and
   listing them in the manifest causes a duplicate-load conflict.
2. The `agents/verifier.md` frontmatter declared `tools: Read, Grep,
   Glob` (CSV string). The install validator expects a YAML list.

### Changed

- **`.claude-plugin/plugin.json`** — removed `commands`, `skills`,
  `hooks` path fields. The `agents` field had already been removed in a
  pre-release attempt. Standard layouts are now fully auto-discovered.
  Manifest `commands`/`skills`/`agents`/`hooks` are reserved for **non-
  standard** layouts (overrides only).
- **`agents/verifier.md`** — `tools` frontmatter converted from CSV
  string to YAML list:
  ```yaml
  tools:
    - Read
    - Grep
    - Glob
  ```
- **`.claude-plugin/plugin.json`** + **`marketplace.json`** — version
  bumped 0.3.0 → 0.3.1.

### Verified

```
$ claude plugin install anti-laziness@agent-rigor
✔ Successfully installed plugin: anti-laziness@agent-rigor (scope: user)
$ claude plugin list
  ❯ anti-laziness@agent-rigor
    Version: 0.3.1
    Scope: user
    Status: ✔ enabled
```

---

## [0.3.0] — 2026-04-27

Bash bypass-pattern guard + a persistent test suite. The hard layer now
extends from "read-before-edit" to "no shortcut bypasses" at the tool boundary,
and every hook script has black-box subprocess tests that reproduce
production-realistic stdin payloads.

### Added

- **`hooks/scripts/bash_guard.py`** — `PreToolUse` matcher `Bash`. Detects:
  - `--no-verify` (skipping commit hooks)
  - `--no-gpg-sign` (skipping commit signature)
  - `git push --force` / `-f` *without* `--force-with-lease`
  - `chmod 777` (and `chmod -R 777`, `chmod 0777`, `chmod -R 0777`)
  Each match emits a structured deny with a recovery instruction citing rule 03
  (rules/03-root-cause.md). Failing-open on exception. Word-boundary aware —
  `--no-verify-extra` and `--force-with-lease` do not false-match.
- **`tests/`** — black-box unittest suite invoking each hook script as a real
  subprocess with synthetic JSON stdin (mirroring Claude Code's runtime). Zero
  third-party deps. Run with `python -m unittest discover tests`. 18 tests:
  - `test_inject_context.py` — soft layer + UTF-8/CJK survival.
  - `test_read_guard.py` — record/allow/deny matrix, fail-open, path
    normalization (forward/backward slash equivalence on Windows).
  - `test_bash_guard.py` — full bypass-pattern matrix, event gating
    (PostToolUse and non-Bash payloads ignored), fail-open.
- **`tests/README.md`** — runner and "how to add a new test case" guide.

### Changed

- `hooks/hooks.json` — `PreToolUse` now has two matcher entries: `Edit|Write`
  routes to `read_guard.py`, `Bash` routes to `bash_guard.py`.
- `.claude-plugin/plugin.json` — version bumped `0.2.0 → 0.3.0`.
- `.claude-plugin/marketplace.json` — version bumped `0.2.0 → 0.3.0`.
- `CLAUDE.md` §6 — reflects v0.3.0 + the new test suite.
- `docs/ARCHITECTURE.md` — Layer 1 table now lists 5 events; data-flow
  diagram updated; connected-files matrix gains entries for `bash_guard.py`
  and `tests/`.
- `README.md` — defense-layer list now includes Bash bypass guard; hook table
  lists 5 events.

### Removed (from Unreleased roadmap)

- "Bash bypass-pattern guard" — implemented here.

---

## [0.2.0] — 2026-04-27

The hard layer goes live. Soft prompt-injection (v0.1.0) is now backed by an
actual gate: the agent cannot Edit a file it has not first Read, and any tool
call against a file is recorded as "known content" for the rest of the session.

### Added

- **`hooks/scripts/lib/state.py`** — per-session JSON state at
  `${CLAUDE_PLUGIN_DATA}/sessions/<session_id>.json` (with documented fallbacks
  to `${CLAUDE_PROJECT_DIR}/.claude/local/anti-laziness/sessions/` and
  `~/.claude/local/anti-laziness/sessions/`). Path normalisation via
  `os.path.realpath` + `os.path.normcase` for case-insensitive Windows
  comparison.
- **`hooks/scripts/read_guard.py`** — single script with two roles:
  - `PostToolUse` matcher `Read|Write`: append touched file to session state.
  - `PreToolUse` matcher `Edit|Write`: emit
    `{"hookSpecificOutput": {"permissionDecision": "deny", ...}}` when the
    target already exists on disk but has not been recorded for this session.
    Allows new-file creation (`os.path.exists` check). Failing-open: any
    exception logs to stderr but lets the tool call proceed.
- **`.claude-plugin/marketplace.json`** — the plugin can now be installed
  locally via `/plugin marketplace add <path-to-repo>` and then
  `/plugin install anti-laziness@<marketplace-name>`.

### Changed

- **`hooks/hooks.json`** — registers four events now: `SessionStart`,
  `UserPromptSubmit`, `PostToolUse` (matcher `Read|Write`), `PreToolUse`
  (matcher `Edit|Write`).
- **`.claude-plugin/plugin.json`** — version bumped `0.1.0 → 0.2.0`.
- **`docs/ARCHITECTURE.md`** — Layer 1 description, data-flow diagram, and the
  connected-files matrix updated to cover `read_guard.py` + `lib/state.py`.
- **`README.md`** — hook table now lists all four events; install section
  documents the `/plugin marketplace add` flow.
- **`CLAUDE.md`** — §6 "当前版本" reflects v0.2.0.

### Removed (from Unreleased roadmap)

- "Hard-layer `PreToolUse` blocks" (read-before-edit half) — implemented here.
- "Marketplace manifest" — implemented here.
- "Verification trace persistence" — replaced by per-session state. Cross-session
  persistence is intentionally out of scope (session boundaries are meaningful).

---

## [0.1.0] — 2026-04-27

Initial skeleton release. Establishes the full layered defense scaffold; only the
soft layer is wired live.

### Added

- **Plugin manifest** — `.claude-plugin/plugin.json` with name, version, author,
  license, and pointers to `commands/`, `agents/`, `skills/`, and
  `hooks/hooks.json`.
- **Project instructions** — formalized `CLAUDE.md` (replaces the original
  free-form `claude.md`), now structured into goals, principles, repo layout,
  contribution flow, metadata, and version status.
- **Rule pack** (`rules/`) — five LLM-agnostic Markdown rule files plus an index:
  - `01-verify-dont-guess.md`
  - `02-systematic-not-reactive.md`
  - `03-root-cause.md`
  - `04-full-context.md`
  - `05-cite-sources.md`
- **Prompt-injection content** (`prompts/`) — `session-start.md` and
  `user-prompt.md`, distilled from the rule pack for in-context use.
- **Hook layer** (`hooks/`) — `hooks.json` registers two events
  (`SessionStart`, `UserPromptSubmit`); `scripts/inject_context.py` emits the
  appropriate `additionalContext` JSON for each event.
- **Slash commands** (`commands/`) — `/anti-laziness:checklist` prints the
  systematic-thinking checklist; `/anti-laziness:verify` prompts a
  re-verification pass.
- **Verifier subagent** (`agents/verifier.md`) — independent `file:line` citation
  re-reader, returns drift/missing/intact verdict.
- **Skill** (`skills/systematic-debug/`) — auto-invokes on debugging language and
  forces a root-cause walk-through before any fix is proposed.
- **Repo-standard files** — `README.md` (bilingual), `LICENSE` (MIT),
  `.gitignore`, this `CHANGELOG.md`, `docs/ARCHITECTURE.md`, `docs/RULES.md`.

### Removed

- Original free-form `claude.md` (replaced by the structured `CLAUDE.md`).

[Unreleased]: https://github.com/skymanbp/agent-rigor/compare/v0.6.2...HEAD
[0.6.2]: https://github.com/skymanbp/agent-rigor/compare/v0.6.1...v0.6.2
[0.6.1]: https://github.com/skymanbp/agent-rigor/compare/v0.6.0...v0.6.1
[0.6.0]: https://github.com/skymanbp/agent-rigor/compare/v0.5.1...v0.6.0
[0.5.1]: https://github.com/skymanbp/agent-rigor/compare/v0.5.0...v0.5.1
[0.5.0]: https://github.com/skymanbp/agent-rigor/compare/v0.4.0...v0.5.0
[0.4.0]: https://github.com/skymanbp/agent-rigor/compare/v0.3.2...v0.4.0
[0.3.2]: https://github.com/skymanbp/agent-rigor/compare/v0.3.1...v0.3.2
[0.3.1]: https://github.com/skymanbp/agent-rigor/compare/v0.3.0...v0.3.1
[0.3.0]: https://github.com/skymanbp/agent-rigor/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/skymanbp/agent-rigor/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/skymanbp/agent-rigor/releases/tag/v0.1.0
