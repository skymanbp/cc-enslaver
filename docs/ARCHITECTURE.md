# Architecture

> Audience: developers extending or auditing the plugin.
> Companion docs: [`../CLAUDE.md`](../CLAUDE.md) (project-level rules),
> [`./RULES.md`](./RULES.md) (catalog of every rule).

---

## 1. Why a layered design

A single mechanism can never enforce discipline reliably. Prompt injection can be
ignored by a confident-and-wrong agent; a hard tool block can be bypassed by
re-phrasing; a subagent verifier only fires when invoked. We therefore stack
**five independent layers**, each catching a different failure mode:

```
┌─────────────────────────────────────────────────────────────┐
│  Layer 5 — LLM-agnostic core (rules/ — plain Markdown)      │  source of truth
├─────────────────────────────────────────────────────────────┤
│  Layer 4 — Skill (auto-invoked on debugging language)       │  contextual nudge
├─────────────────────────────────────────────────────────────┤
│  Layer 3 — Verifier subagent (independent re-reader)        │  citation audit
├─────────────────────────────────────────────────────────────┤
│  Layer 2 — Slash commands (user/agent-triggered)            │  on-demand
├─────────────────────────────────────────────────────────────┤
│  Layer 1 — Hooks (always-on prompt injection)               │  always-on
└─────────────────────────────────────────────────────────────┘
```

Failure of any one layer does not collapse the system; the next layer still
catches the lazy behaviour, often via a different signal.

---

## 2. Layer 1 — Hooks (always-on)

**Wired in:** [`../hooks/hooks.json`](../hooks/hooks.json).
**Implementations:**
- Soft injection: [`../hooks/scripts/inject_context.py`](../hooks/scripts/inject_context.py)
- Read-before-edit guard: [`../hooks/scripts/read_guard.py`](../hooks/scripts/read_guard.py) + [`../hooks/scripts/lib/state.py`](../hooks/scripts/lib/state.py)
- Bash bypass guard: [`../hooks/scripts/bash_guard.py`](../hooks/scripts/bash_guard.py)

Five hook entries across four events:

| Event | Matcher | Script | Purpose |
|---|---|---|---|
| `SessionStart` | — | `inject_context.py` | Inject full discipline summary at session boot |
| `UserPromptSubmit` | — | `inject_context.py` | Inject compact per-turn reminder |
| `PostToolUse` | `Read\|Write` | `read_guard.py` | Record touched file in session state |
| `PreToolUse` | `Edit\|Write` | `read_guard.py` | Deny edit if target exists but unread |
| `PreToolUse` | `Bash` | `bash_guard.py` | Deny on bypass patterns (`--no-verify`, force-push, `chmod 777`, …) |

#### Why three scripts (not one)

Each script has a different responsibility and a different failure mode:
- `inject_context.py` is purely additive: always exit 0, only emit
  `additionalContext`. Never reads or writes disk state.
- `read_guard.py` owns per-session disk state (PostToolUse Read/Write +
  PreToolUse Edit/Write). Its failure mode is state-file corruption.
- `bash_guard.py` is stateless string inspection. Its failure mode is regex
  bug.

Collapsing them into one script would chain three independent failure modes
behind a single try/except — a bug in any one would mask the others. Keeping
them separate also lets each script load only the imports it actually needs.

#### Soft-layer output contract (`inject_context.py`)

Always exit 0. Emits:

```json
{
  "hookSpecificOutput": {
    "hookEventName": "SessionStart",
    "additionalContext": "<contents of prompts/session-start.md>"
  }
}
```

Never blocks; only injects.

#### Hard-layer output contract (`read_guard.py`)

`PostToolUse` (record): exit 0 silently. State written to disk.

`PreToolUse` (allow): exit 0 silently. (Allow is the default with no output.)

`PreToolUse` (deny): exit 0, emits

```json
{
  "hookSpecificOutput": {
    "hookEventName": "PreToolUse",
    "permissionDecision": "deny",
    "permissionDecisionReason": "anti-laziness · rule 04 violation ..."
  }
}
```

The reason text tells the agent precisely how to recover (Read first, then retry).

#### Per-session state storage

The guard uses **session_id** from the hook payload as the state key. Storage
location resolves in this order:

1. `${CLAUDE_PLUGIN_DATA}/sessions/<sid>.json` — preferred, set by Claude Code
   for plugin hooks.
2. `${CLAUDE_PROJECT_DIR}/.claude/local/anti-laziness/sessions/<sid>.json` —
   per-project fallback.
3. `~/.claude/local/anti-laziness/sessions/<sid>.json` — final fallback.

State files are git-ignored (`.gitignore` line 26). Paths within state are
canonicalised via `os.path.realpath` + `os.path.normcase` so case-insensitive
filesystems (Windows) compare correctly.

#### Failing-open

Any unhandled exception in `read_guard.py` is caught, logged to stderr, and
the script exits 0 (allow). A bug in the guard cannot be permitted to brick
the agent — anti-laziness must never become anti-progress.

#### Why `Stop` is not yet wired

`Stop` would loop forever without a stateful one-shot guard. Documented as a
roadmap item in [`../CHANGELOG.md`](../CHANGELOG.md).

#### `Bash` bypass-pattern blocking

`bash_guard.py` (matcher `Bash`) inspects the `tool_input.command` string and
denies four patterns:

| Pattern (regex) | Why |
|---|---|
| `--no-verify` (whitespace-bounded) | Skipping commit/push hooks ships unchecked code. Rule 03. |
| `--no-gpg-sign` | Skipping commit signature verification. Rule 03. |
| `git push --force` / `-f`, *not* `--force-with-lease` | Force-push is irreversible and can overwrite teammates' work. Rule 03. The safer `--force-with-lease` variant is allowed. |
| `chmod (-R)? 0?777` | World-writable permissions never solve the underlying access issue and create security risk. Rule 03. |

Each match emits the same deny shape as `read_guard.py`, with a reason that
explains the rule violation and how to address the real underlying problem.

Word-boundary care: `--no-verify-extra` (longer flag) does not match;
`echo --force >> notes.txt` (no `git push`) does not match;
`git push --force-with-lease` is stripped before the `--force` check, so it
also does not match.

If the user has explicitly authorised a bypass, `bash_guard` will still deny.
The agent should surface the deny reason to the user and let the user run the
command manually — that is the intended discipline (no AI-mediated bypassing).

---

## 3. Layer 2 — Slash commands (on-demand)

**Wired in:** [`../commands/`](../commands/).

Two user-invokable surfaces:

| Command | Source | Use case |
|---|---|---|
| `/anti-laziness:checklist` | [`../commands/checklist.md`](../commands/checklist.md) | Print the pre-action / pre-finish discipline checklist. |
| `/anti-laziness:verify`    | [`../commands/verify.md`](../commands/verify.md)    | Trigger a re-verification pass on the agent's recent claims. |

Slash commands in Claude Code are flat Markdown files in `commands/`. Their YAML
frontmatter declares the command's behaviour; the body is the prompt the agent
receives when invoked.

---

## 4. Layer 3 — Verifier subagent

**Wired in:** [`../agents/verifier.md`](../agents/verifier.md).

A read-only subagent. Given a list of `file:line` citations the main agent
produced, the verifier independently:

1. Reads each cited file.
2. Confirms the line number exists and the cited content matches.
3. Reports `intact` / `drift` / `missing` per citation.

It carries `Read`, `Grep`, `Glob` tools — explicitly **no** `Edit`, `Write`, or
`Bash`. It cannot mutate state; its only output is a verdict.

---

## 5. Layer 4 — Skill (contextually auto-invoked)

**Wired in:** [`../skills/systematic-debug/SKILL.md`](../skills/systematic-debug/SKILL.md).

Skills are auto-invoked by Claude Code based on the YAML `description` matching
the user's prompt. `systematic-debug` triggers on debugging language ("debug",
"why is this failing", "fix this bug", error/stack-trace patterns) and forces
the agent through the seven systematic-thinking questions from
[`../rules/02-systematic-not-reactive.md`](../rules/02-systematic-not-reactive.md)
**before** proposing any code change.

---

## 6. Layer 5 — LLM-agnostic core

**Source of truth:** [`../rules/`](../rules/).

Each rule is plain Markdown with a small YAML frontmatter (`id`, `title`,
`severity`). Every other layer in this plugin **derives from** these files —
the prompt injections in `prompts/` are distillations, the slash commands and
skill reference rule IDs, the verifier checks compliance with rule 05.

This separation is what makes the plugin **LLM-agnostic**: any agent runtime
that does not speak Claude Code's plugin protocol can still consume the rules
directly:

```bash
# OpenAI / generic
cat rules/*.md > /tmp/anti-laziness-system-prompt.txt
# then prepend to your system prompt

# Cursor / Cline / Aider
# Symlink rules/ into the project's rule directory or copy the index.
```

---

## 7. Data flow at a glance

```
Session starts
    │
    ▼
SessionStart hook fires → inject_context.py --event SessionStart
    │  reads prompts/session-start.md (distilled from rules/*.md)
    ▼
Claude Code injects full discipline summary into context

User submits prompt
    │
    ▼
UserPromptSubmit hook fires → inject_context.py --event UserPromptSubmit
    │  reads prompts/user-prompt.md (compact reminder)
    ▼
Claude Code injects pre-turn reminder

Agent calls Read or Write (any file)
    │
    ▼
PostToolUse hook fires (matcher Read|Write) → read_guard.py
    │  state_lib.add_read(session_id, file_path)
    ▼
File path appended to ${CLAUDE_PLUGIN_DATA}/sessions/<sid>.json

Agent calls Edit or Write
    │
    ▼
PreToolUse hook fires (matcher Edit|Write) → read_guard.py
    │
    ├─ target file does not exist on disk        → ALLOW (silent exit 0)
    ├─ target file exists, in session state      → ALLOW (silent exit 0)
    └─ target file exists, NOT in session state  → DENY
                                                       └─ permissionDecision: deny
                                                           reason: "rule 04 violation,
                                                                    Read this file first"

Agent calls Bash
    │
    ▼
PreToolUse hook fires (matcher Bash) → bash_guard.py
    │
    ├─ command matches --no-verify                       → DENY (rule 03)
    ├─ command matches --no-gpg-sign                     → DENY (rule 03)
    ├─ command matches git push --force (no --force-with-lease) → DENY (rule 03)
    ├─ command matches chmod 0?777                       → DENY (rule 03)
    └─ no bypass pattern matched                         → ALLOW (silent exit 0)

   ─── if user/agent invokes /anti-laziness:verify ───
                       │
                       ▼
            verifier subagent runs
                       │
                       ▼
            re-reads cited file:line → drift/missing/intact verdict

   ─── if user prompt matches "fix this bug" ───
                       │
                       ▼
            systematic-debug skill auto-invokes
                       │
                       ▼
            forces 7-question root-cause walk
```

---

## 8. Editing this plugin — connected-files map

When you change one component, these are the files that must be re-checked
in the same change. This is enforced by [`../CLAUDE.md`](../CLAUDE.md) §4.

| If you edit… | Also re-check… |
|---|---|
| `rules/<n>-*.md` | `prompts/session-start.md`, `prompts/user-prompt.md`, `docs/RULES.md`, `commands/checklist.md` |
| `prompts/*.md` | `hooks/scripts/inject_context.py` (filename mapping), this doc |
| `hooks/scripts/inject_context.py` | `hooks/hooks.json` (registration), `.claude-plugin/plugin.json` (hooks pointer), `tests/test_inject_context.py` |
| `hooks/scripts/read_guard.py` | `hooks/hooks.json` (event registration + matcher), `hooks/scripts/lib/state.py` (state contract), this doc §2 (deny output contract), `tests/test_read_guard.py` |
| `hooks/scripts/lib/state.py` | `hooks/scripts/read_guard.py` (consumer), `.gitignore` (state dir must stay ignored), this doc §2 (storage location), `tests/test_read_guard.py` |
| `hooks/scripts/bash_guard.py` | `hooks/hooks.json` (matcher entry), this doc §2 (bypass-pattern table), `tests/test_bash_guard.py` (every new pattern needs a positive + nearby negative case) |
| `hooks/hooks.json` | `.claude-plugin/plugin.json` (hooks pointer), this doc §2 (event table) |
| `.claude-plugin/plugin.json` | `README.md` (install steps), `CHANGELOG.md`, `.claude-plugin/marketplace.json` (version sync), version-bump must match an actual change. **Do not** re-add the `commands` / `agents` / `skills` / `hooks` path fields for standard locations: they cause `claude plugin install` to fail with `Duplicate hooks file detected` or `agents: Invalid input` because Claude Code auto-discovers `./commands/`, `./agents/`, `./skills/`, and `./hooks/hooks.json`. Those manifest fields are only for *non-standard* layouts. |
| `.claude-plugin/marketplace.json` | `README.md` (install steps), `.claude-plugin/plugin.json` (version), this doc |
| `commands/*.md` | `.claude-plugin/plugin.json` (commands path), this doc, `README.md` |
| `agents/verifier.md` | `commands/verify.md` (invocation), this doc |
| `skills/systematic-debug/SKILL.md` | `rules/02-systematic-not-reactive.md`, `rules/03-root-cause.md`, this doc |
| `tests/_helpers.py` | every `tests/test_*.py` file (they all import from here) |
