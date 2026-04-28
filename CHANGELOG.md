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

[Unreleased]: https://github.com/skymanbp/agent-rigor/compare/v0.3.1...HEAD
[0.3.1]: https://github.com/skymanbp/agent-rigor/compare/v0.3.0...v0.3.1
[0.3.0]: https://github.com/skymanbp/agent-rigor/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/skymanbp/agent-rigor/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/skymanbp/agent-rigor/releases/tag/v0.1.0
