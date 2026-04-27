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
**Implementation:** [`../hooks/scripts/inject_context.py`](../hooks/scripts/inject_context.py).

Two events are subscribed to. Both invoke the same Python script with a
different `--event` argument; the script reads the corresponding file from
`prompts/` and emits the JSON shape Claude Code expects.

| Event | Source prompt | Purpose |
|---|---|---|
| `SessionStart` | [`../prompts/session-start.md`](../prompts/session-start.md) | Full discipline summary at fresh-session boot |
| `UserPromptSubmit` | [`../prompts/user-prompt.md`](../prompts/user-prompt.md) | Compact per-turn reminder |

### Why one script, not three

Per [`../CLAUDE.md`](../CLAUDE.md) §2.6 ("最小有效更改"), three near-identical
hook scripts is duplication. Branching on `--event` keeps the executable surface
to a single file the reviewer can audit in one read.

### Hook output contract

The script writes a JSON object to stdout matching Claude Code's hook spec:

```json
{
  "hookSpecificOutput": {
    "hookEventName": "SessionStart",
    "additionalContext": "<contents of prompts/session-start.md>"
  }
}
```

Exit code `0` always. The script never blocks; it only injects.

### Why `Stop` and `PreToolUse` are not yet wired

- **`Stop`** would loop forever without a stateful one-shot guard. Documented
  as a roadmap item in [`../CHANGELOG.md`](../CHANGELOG.md).
- **`PreToolUse`** for "Edit-without-Read" requires tracking the set of files
  the agent has `Read` during the session. This needs persistent state across
  hook invocations (Claude Code hooks are stateless processes). Roadmap item.

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
SessionStart hook fires
    │
    ▼
inject_context.py --event SessionStart
    │   reads prompts/session-start.md (which references rules/*.md)
    ▼
Claude Code injects full discipline summary into context

User submits prompt
    │
    ▼
UserPromptSubmit hook fires
    │
    ▼
inject_context.py --event UserPromptSubmit
    │   reads prompts/user-prompt.md (compact reminder)
    ▼
Claude Code injects pre-turn reminder

   ─── if user/agent invokes /anti-laziness:verify ───
                       │
                       ▼
            verifier subagent runs
                       │
                       ▼
            re-reads cited file:line
                       │
                       ▼
            returns drift/missing/intact verdict

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
| `hooks/scripts/inject_context.py` | `hooks/hooks.json` (registration), `.claude-plugin/plugin.json` (hooks pointer) |
| `.claude-plugin/plugin.json` | `README.md` (install steps), `CHANGELOG.md` |
| `commands/*.md` | `.claude-plugin/plugin.json` (commands path), this doc, `README.md` |
| `agents/verifier.md` | `commands/verify.md` (invocation), this doc |
| `skills/systematic-debug/SKILL.md` | `rules/02-systematic-not-reactive.md`, `rules/03-root-cause.md`, this doc |
