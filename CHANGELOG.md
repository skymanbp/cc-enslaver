# Changelog

All notable changes to **anti-laziness** are documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and
this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [Unreleased]

### Planned (roadmap)

- **Hard-layer `PreToolUse` blocks**
  - Reject `Edit` / `Write` against a file the agent has not `Read` in this session.
  - Reject `Bash` commands containing `--no-verify`, `git push --force`, `rm -rf /`,
    `chmod -R 777`, or other documented bypass patterns unless an explicit
    justification is supplied.
- **Stateful `Stop` hook**
  - Detect "I edited X" / "I created Y" claims in the agent's last message and
    verify the corresponding file mtime / git status before allowing Stop.
  - Requires a one-shot guard to avoid infinite Stop loops.
- **Verification trace persistence**
  - Persist the set of files the agent has actually read across sessions
    (per-project `.claude/local/anti-laziness/read-trace.json`).
- **English mirror of `rules/`**
  - Currently rules are Chinese-primary. Add `rules/en/` alongside for non-CJK users.
- **Marketplace manifest**
  - Add `.claude-plugin/marketplace.json` so the repo can be installed directly via
    Claude Code's marketplace mechanism without a separate marketplace repo.

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

[Unreleased]: https://github.com/skymanbp/anti-laziness/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/skymanbp/anti-laziness/releases/tag/v0.1.0
