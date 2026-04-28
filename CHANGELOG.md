# Changelog

All notable changes to **anti-laziness** are documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and
this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [Unreleased]

### Planned (roadmap)

- **Stateful `Stop` hook**
  - Detect "I edited X" / "I created Y" claims in the agent's last message and
    verify the corresponding file mtime / git status before allowing Stop.
  - Requires a one-shot guard to avoid infinite Stop loops.
- **Session state GC**
  - Periodically prune session JSON files older than N days from
    `${CLAUDE_PLUGIN_DATA}/sessions/`.
- **Additional bypass patterns**
  - Evaluate adding `git reset --hard` (if uncommitted changes), `git rebase
    --skip`, `pip install --break-system-packages`, etc. — currently held back
    on false-positive concerns.
- **English mirror of `rules/`**
  - Currently rules are Chinese-primary. Add `rules/en/` alongside for non-CJK users.
- **CI**
  - GitHub Actions workflow running `python -m unittest discover tests` on push.

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

[Unreleased]: https://github.com/skymanbp/agent-rigor/compare/v0.4.0...HEAD
[0.4.0]: https://github.com/skymanbp/agent-rigor/compare/v0.3.2...v0.4.0
[0.3.2]: https://github.com/skymanbp/agent-rigor/compare/v0.3.1...v0.3.2
[0.3.1]: https://github.com/skymanbp/agent-rigor/compare/v0.3.0...v0.3.1
[0.3.0]: https://github.com/skymanbp/agent-rigor/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/skymanbp/agent-rigor/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/skymanbp/agent-rigor/releases/tag/v0.1.0
