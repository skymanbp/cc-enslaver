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
- Bash guard (bypass patterns + register-as-read): [`../hooks/scripts/bash_guard.py`](../hooks/scripts/bash_guard.py)
- Register stub (v0.4.0): [`../hooks/scripts/register_read.py`](../hooks/scripts/register_read.py)
- Stop guard (v0.6.0 → v0.7.0 → v0.8.0, rule 06 + rule 07 enforcement): [`../hooks/scripts/stop_guard.py`](../hooks/scripts/stop_guard.py)

Five hook entries across four events:

| Event | Matcher | Script | Purpose |
|---|---|---|---|
| `SessionStart` | — | `inject_context.py` | Inject full discipline summary at session boot |
| `UserPromptSubmit` | — | `inject_context.py` | Inject compact per-turn reminder |
| `PreToolUse` | `Read\|Edit\|Write` | `read_guard.py` | Record on Read/Write; deny Edit/Write of unread existing file (rule 04 + 08); deny Edit/Write with unjustified patch-style new_string (rule 09); stamp `last_edit_turn` for Stop layers (e)+(f) |
| `PreToolUse` | `Bash` | `bash_guard.py` | Deny on bypass patterns (rule 03 + 09); also register file-as-read on `register_read.py` invocation |
| `Stop` | — | `stop_guard.py` | Six-layer block: (a) no-evidence / (b) hedged-completion / (c) missing rule-06 quiz / (d) missing rule-07 fidelity / (e) missing rule-08 system-thinking (edit turns only) / (f) missing rule-09 triplet (edit turns only) |

#### Why everything in `PreToolUse` (and not split with `PostToolUse`)

v0.3.1 split recording (PostToolUse) and gating (PreToolUse). v0.3.2 unified
both into PreToolUse because **`PostToolUse` does not fire for tool calls
whose `tool_input.file_path` lies outside the current project working
directory, while `PreToolUse` does**. The mismatch caused false-positive
denies on out-of-project files (e.g., per-project memory files in
`~/.claude/projects/<project>/memory/`): the agent would Read X, no record,
then Edit X → DENY. v0.3.2 records on PreToolUse(Read) and gates on
PreToolUse(Edit/Write); both share a scope by construction.

The trade-off: recording in Pre is speculative (happens before the tool
result is known). A Read of a non-existent path leaves a phantom record,
but Edit's `os.path.exists` short-circuit covers it (Edit on a missing
file is allowed and Claude Code rejects it downstream).

#### Why three scripts (not one)

Each script has a different responsibility and a different failure mode:
- `inject_context.py` is purely additive: always exit 0, only emit
  `additionalContext`. Never reads or writes disk state.
- `read_guard.py` owns per-session disk state, with both recording and
  gating in PreToolUse (Read/Write/Edit). Its failure mode is state-file
  corruption.
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

`PreToolUse` (record): on Read/Write, `state_lib.add_read` is called and the
script exits 0 silently with state written to disk.

`PreToolUse` (allow): exit 0 silently. (Allow is the default with no output.)

`PreToolUse` (deny): exit 0, emits

```json
{
  "hookSpecificOutput": {
    "hookEventName": "PreToolUse",
    "permissionDecision": "deny",
    "permissionDecisionReason": "cc-enslaver · rule 04 violation ..."
  }
}
```

The reason text tells the agent precisely how to recover (Read first, then retry).

#### Per-session state storage

The guard uses **session_id** from the hook payload as the state key. Storage
location resolves in this order:

1. `${CLAUDE_PLUGIN_DATA}/sessions/<sid>.json` — preferred, set by Claude Code
   for plugin hooks.
2. `${CLAUDE_PROJECT_DIR}/.claude/local/cc-enslaver/sessions/<sid>.json` —
   per-project fallback.
3. `~/.claude/local/cc-enslaver/sessions/<sid>.json` — final fallback.

State files are git-ignored (`.gitignore` line 26). Paths within state are
canonicalised via `os.path.realpath` + `os.path.normcase` so case-insensitive
filesystems (Windows) compare correctly.

#### Failing-open

Any unhandled exception in `read_guard.py` is caught, logged to stderr, and
the script exits 0 (allow). A bug in the guard cannot be permitted to brick
the agent — discipline enforcement must never become an obstacle to actual work.

#### `Stop` guard (rule 06 + rule 07 enforcement, v0.6.0 → v0.7.0 → v0.8.0)

`stop_guard.py` (event `Stop`, no matcher — Stop fires unconditionally per
Claude Code spec) inspects `payload.assistant_message` (or falls back to
the last assistant entry in `payload.transcript_path`).

**Decision tree (v0.11.0):**

| Step | Condition | Action |
|------|-----------|--------|
| 0 | One-shot guard window (`turn_count` ∈ `[last_blocked + 1, last_blocked + 3]`) | Allow |
| 1 | No done-claim regex matched | Allow |
| 2 | Hedge regex within 50 chars of done-claim (rule 01) | **Block** (`HEDGED_DONE_REASON`) |
| 3 | No evidence regex matched (v0.6.0 base) | **Block** (`NO_EVIDENCE_REASON`) |
| 4 | No convergence marker AND fewer than 2 self-quiz questions (rule 06 deep) | **Block** (`MISSING_QUIZ_REASON`) |
| 5 | No fidelity marker AND fewer than 2 of 3 fidelity questions (rule 07) | **Block** (`MISSING_FIDELITY_REASON`) |
| 6 | `last_edit_turn == turn_count` AND no rule-08 marker AND fewer than 3 of 6 rule-02 keywords (rule 08, **v0.11**) | **Block** (`MISSING_RULE08_REASON`) |
| 7 | `last_edit_turn == turn_count` AND no rule-09 marker AND triplet (root-cause + impact + solution) incomplete (rule 09, **v0.11**) | **Block** (`MISSING_RULE09_REASON`) |
| 8 | All gates passed | Allow |

**Done-claim patterns**: `已解决` / `已修复` / `[修改弄搞]好了` / `完成了` /
`完工` / `搞定` / `\bfixed\b` / `\bdone\b` / `\bcompleted\b` /
`\bresolved\b` / `all set` / `should work now` / `that should do it`.

**Evidence patterns**: shell-prompt lines (`$ ` / `> `), `Ran N tests`,
`N passed/failed`, `pytest` / `unittest`, `重触发` / `边界用例` / `反向用例`
/ `收敛`, `verified` / `re-?ran` / `validated`, fenced code block
of ≥20 chars output.

**v0.7.0 hedge patterns** (must be within 50 chars of a done-claim, in
either order, to fire): `我[记觉]得` / `我相信` / `可能就` / `应该是` /
`大概(是)?` / `I think` / `I believe` / `I guess` / `maybe` / `probably`
/ `kinda` / `sort of`. Generic non-first-person hedges like `通常` or
`should` are intentionally **excluded** — they appear too often in
legitimate technical writing far from the completion claim.

**v0.7.0 convergence markers** (single match suffices to pass the
self-quiz gate): `rule 06` / `自答` / `收敛` / `convergence` /
`self-quiz`, plus the rule-06-specific check names `重触发` / `边界用例`
/ `反向用例`.

**v0.7.0 self-quiz patterns** (≥ 2 of 4 must match, in either Chinese
or English):

| # | Question | Patterns |
|---|----------|----------|
| 1 | Really solved? | `真.*?解决` / `really.*?(?:solv\|fix)` |
| 2 | Better solution? | `更好.*?(?:方案\|方法\|做法)` / `better.*?(?:solut\|approach\|way)` |
| 3 | Unverified parts? | `(?:哪些\|哪里).*?(?:没验\|未验)` / `unverif` |
| 4 | Meaningful verification? | `验证.*?(?:合理\|是否充分)` / `verification.*?(?:meaning\|reasonab)` |

**v0.8.0 fidelity markers** (rule 07; single match suffices to pass
the fidelity gate): `rule 07` / `任务忠实` / `请求覆盖` / `原始请求` /
`无遗漏` / `无降级` / `未降级` / `未遗漏` / `无超范围` / `未超范围` /
`task fidelity` / `request coverage` / `request fidelity` /
`no degradation` / `no omission` / `no scope creep` / `covered all` /
`all requested`, plus the `[✅⚠️❌] … (完成|done|完工)` checklist-row
pattern (the agent enumerated original-request items with check
marks).

**v0.8.0 fidelity self-quiz patterns** (rule 07; ≥ 2 of 3 must match,
in either Chinese or English):

| # | Question | Patterns |
|---|----------|----------|
| 1 | Coverage — did I do every sub-item? | `(?:用户\|原始).*?(?:请求\|要求).*?(?:拆\|列\|包含\|分成\|项\|子项)` / `decompos.*?request` / `sub-?item` / `coverage.*?(?:check\|complete)` |
| 2 | Standard — did each modifier word land as hard action? | `(?:强制\|必须\|完整\|严格\|全面\|所有).*?(?:落实\|硬动作\|硬证据\|拦截\|断言\|实现\|生效)` / `(?:mandator\|strict\|comprehensive\|all\|every\|hard).*?(?:enforced\|verifi\|hook\|assert\|land)` |
| 3 | Fidelity — concept-swap / scope creep / buried TODO? | `偷换\|降级\|超范围\|额外的?(?:改\|修)\|遗漏\|裁剪` / `concept.?swap\|degrad\|scope.?creep\|omission\|trim\|drive-?by` |

Layer (d) fires only when (a)(b)(c) all pass, so the agent has
already shown it both has evidence and engaged with the rule-06
self-quiz; the fidelity layer adds the orthogonal "did you deliver
everything the user asked for?" check before allowing the Stop.

**v0.11.0 rule-08 closing markers** (layer (e); single match
suffices to pass the gate): `rule 08` / `改前必读` / `写前必想` /
`read-before-edit` / `think-before-write` / `系统式自答`.

**v0.11.0 rule-02 systematic-thinking keywords** (layer (e)
fallback; ≥ 3 of 6 must match):

| # | Keyword (CN / EN) |
|---|-------------------|
| 1 | 架构 / architecture / architectural |
| 2 | 职责 / responsibility |
| 3 | 根源 / 根因 / root-cause |
| 4 | 方案 / solution / approach |
| 5 | 连带 / 下游 / 影响范围 / downstream / impact / connected |
| 6 | 风险 / 不变量 / invariant / risk |

**v0.11.0 rule-09 closing markers** (layer (f); single match
suffices to pass the gate): `rule 09` / `系统式修改` / `打补丁` /
`systematic modification` / `patch-style` / `non-patch` / `反补丁`.

**v0.11.0 rule-09 triplet keywords** (layer (f) fallback; **all
three** must match):

| # | Triplet axis (CN / EN) |
|---|-------------------------|
| 1 | 根源 / 根因 / root-cause |
| 2 | 连带 / 影响范围 / impact / blast-radius / downstream |
| 3 | 方案 / solution / approach / alternative |

**Why layers (e)+(f) are scoped to edit turns**: a pure analysis /
answer turn should not be forced to surface think-before-write or
root-cause/impact/solution markers — there was nothing modified for
those to apply to. `read_guard.py` stamps `state.last_edit_turn =
turn_count` on every accepted Edit / Write; layer (e) and (f) check
`state_lib.did_edit_this_turn(session_id, turn_count)` and silently
allow on read-only turns. The one-shot guard still applies.

**Why detection is heuristic and lightweight**: same rationale as
layers (c)(d). A careful agent who genuinely did the rule-08/09
work will naturally use these keywords in their own phrasing;
demanding a verbatim formula would false-positive on legitimate
prose. The single-marker escape (`rule 08` / `rule 09`) lets an
agent who used non-keyword phrasing still flag they did the work.
The one-shot guard caps false-positive cost at exactly 1 corrective
turn per block.

**One-shot guard**: `state_lib.record_stop_block(session_id, turn_count)`
on every block; `state_lib.was_just_blocked(session_id, turn_count)`
returns True for `turn_count ∈ [last + 1, last + 3]` so the agent has a
multi-turn grace window to recover. After the grace expires, fresh
blocks resume.

**Block output is asymmetric**: Stop hook uses **top-level**
`{"decision": "block", "reason": ...}`, NOT the `hookSpecificOutput`
envelope used by `PreToolUse`. Verified against
https://code.claude.com/docs/en/hooks.md.

**Why heuristic, not file-claim verification**: deep "I edited X" →
`git diff` / mtime verification was the original roadmap idea. v0.6.0
deliberately ships the lighter heuristic — natural-language file-path
extraction is fragile (high false positives), while done-claim-without-
evidence is robust (a careful agent always cites evidence per rule 05,
so this only fires on actual laziness). v0.7.0 deepened the rule-06
side (hedge + self-quiz); v0.8.0 added the rule-07 fidelity layer.
File-claim verification is now a v0.9+ candidate.

#### `Edit` / `Write` patch-style content blocking (v0.11.0)

`read_guard.py` gains a second responsibility beyond read-before-edit:
the `new_string` (Edit) or `content` (Write) is scanned for **patch-
style markers** — `try / except: pass`, `# noqa`, `# type: ignore`,
`// @ts-ignore`, `// @ts-expect-error`, `// eslint-disable[-next-
line]`, `time.sleep(...) # race/wait/workaround` — and DENY-ed when
present **without an adjacent rationale comment** (the line itself or
±1 line must contain one of: `because`, `原因`, `why`, `正当`,
`rationale`, `see issue/pr/comment/ticket`, `intentional`,
`deliberate`, `third-party`, `per spec/rfc/standard`).

| Pattern | Why |
|---|---|
| `try:\n …\nexcept …:\npass` (multi-line, bare) | Silent exception swallow (rule 03 + 09) |
| `# noqa` without rationale | Lint suppression without justification (rule 03 + 09) |
| `# type: ignore` without rationale | Type-checker suppression (rule 03 + 09) |
| `// @ts-ignore` / `// @ts-expect-error` without rationale | TS suppression (rule 03 + 09) |
| `// eslint-disable[-next-line\|-line]` without rationale | Lint suppression (rule 03 + 09) |
| `time.sleep(...) # race/wait/workaround` | Sleep masking a race (rule 03 + 09) |

This is the **physical-enforcement** half of rule 09. The
soft-layer half (the `rules/09-systematic-modification.md`
discipline + Stop layer (f) closing check) covers the cases the
regex set cannot catch (rolling patches, loosened assertions, etc.).

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

#### Read-cache escape hatch (v0.4.0)

A second responsibility of `bash_guard.py`: detect invocations of
`register_read.py` and, only when valid, register the target file in
session state. Motivation:

- Claude Code's harness has a Read result cache. Repeated `Read` of the
  same file within a session may be served from cache *without invoking
  the Read tool*. When that happens, neither `PreToolUse(Read)` nor
  `PostToolUse(Read)` fires, the file never enters session state, and a
  later `Edit` is falsely denied.
- We can't fix the harness from a plugin. We can provide an explicit
  registration path: `register_read.py --file ABS_PATH --hash SHA256`.
- The hash is the laziness gate. `bash_guard.py` recomputes SHA-256 of
  the file on disk and only registers if it matches the agent's claim.
  An agent that has not actually opened the file can't produce the
  current on-disk hash, so the hatch can't be abused.

Flow:

```
agent computes SHA-256 of file --> agent runs `python register_read.py --file ABS --hash SHA`
                                              │
                                              ▼
                  PreToolUse(Bash) fires → bash_guard.py
                  ├─ recognises register_read.py invocation
                  ├─ recomputes SHA-256 from disk
                  ├─ if match: state_lib.add_read(session_id, path); ALLOW
                  └─ if mismatch / file missing / bad path / bad hash: DENY
                                              │
                  ALLOW lets register_read.py run as a no-op CLI that prints
                  confirmation and exits 0. The state mutation has already
                  happened in the hook.
```

The contract is asymmetric on purpose: the user-facing script
(`register_read.py`) verifies its own hash for command-line UX, but
the *authoritative* hash check + state mutation lives in the hook,
because only the hook payload exposes `session_id`.

---

## 3. Layer 2 — Slash commands (on-demand)

**Wired in:** [`../commands/`](../commands/).

Two user-invokable surfaces:

| Command | Source | Use case |
|---|---|---|
| `/cc-enslaver:checklist` | [`../commands/checklist.md`](../commands/checklist.md) | Print the pre-action / pre-finish discipline checklist. |
| `/cc-enslaver:verify`    | [`../commands/verify.md`](../commands/verify.md)    | Trigger a re-verification pass on the agent's recent claims. |

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

**Source of truth:** [`../rules/`](../rules/) (Chinese, canonical) +
[`../rules/en/`](../rules/en/) (English mirror, v0.6.2).

Each rule is plain Markdown with a small YAML frontmatter (`id`, `title`,
`severity`). Every other layer in this plugin **derives from** the Chinese
files — the prompt injections in `prompts/` are distillations, the slash
commands and skill reference rule IDs, the verifier checks compliance with
rule 05. The English mirror at `rules/en/` is provided for non-CJK readers
and for use as a system-prompt fragment with non-Claude agents; if the two
ever drift, the Chinese version wins.

This separation is what makes the plugin **LLM-agnostic**: any agent runtime
that does not speak Claude Code's plugin protocol can still consume the rules
directly:

```bash
# OpenAI / generic — Chinese:
cat rules/*.md > /tmp/cc-enslaver-system-prompt.txt

# OpenAI / generic — English (v0.6.2):
cat rules/en/*.md > /tmp/cc-enslaver-system-prompt.txt

# Cursor / Cline / Aider — symlink rules/ or rules/en/ into the project's
# rule directory or copy the index.
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

Agent calls Read, Edit, or Write
    │
    ▼
PreToolUse hook fires (matcher Read|Edit|Write) → read_guard.py
    │
    ├─ tool=Read                                   → record path, ALLOW (silent)
    ├─ tool=Write, target does not exist on disk   → record path, ALLOW (new file)
    ├─ tool=Write, target exists & is recorded     → record (no-op), ALLOW
    ├─ tool=Write, target exists but unrecorded    → DENY (rule 04)
    ├─ tool=Edit,  target does not exist on disk   → ALLOW (Claude Code rejects)
    ├─ tool=Edit,  target exists & is recorded     → ALLOW (silent)
    └─ tool=Edit,  target exists but unrecorded    → DENY (rule 04)

State file: ${CLAUDE_PLUGIN_DATA}/sessions/<sid>.json (or fallback paths)

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

   ─── if user/agent invokes /cc-enslaver:verify ───
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
| `rules/<n>-*.md` | `rules/en/<n>-*.md` (English mirror), `prompts/session-start.md`, `prompts/user-prompt.md`, `docs/RULES.md`, `commands/checklist.md`, `rules/00-index.md` + `rules/en/00-index.md` (program-readable index), `tests/test_inject_context.py` (the prompt-content assertion list) |
| `prompts/*.md` | `hooks/scripts/inject_context.py` (filename mapping), this doc |
| `hooks/scripts/inject_context.py` | `hooks/hooks.json` (registration), `.claude-plugin/plugin.json` (hooks pointer), `tests/test_inject_context.py` |
| `hooks/scripts/read_guard.py` | `hooks/hooks.json` (event registration + matcher), `hooks/scripts/lib/state.py` (state contract + `record_edit_turn`), this doc §2 (deny output contract + patch-style table), `tests/test_read_guard.py` (read-before-edit cases + patch-style positive/negative cases + record_edit_turn cases) |
| `hooks/scripts/lib/state.py` | `hooks/scripts/read_guard.py` (consumer of `record_edit_turn`), `hooks/scripts/stop_guard.py` (consumer of `did_edit_this_turn`), `.gitignore` (state dir must stay ignored), this doc §2 (storage location), `tests/test_read_guard.py` + `tests/test_stop_guard.py` |
| `hooks/scripts/bash_guard.py` | `hooks/hooks.json` (matcher entry), this doc §2 (bypass-pattern table + register-flow), `tests/test_bash_guard.py` (positive + nearby negative for every new pattern; register-flow regression cases) |
| `hooks/scripts/stop_guard.py` | `hooks/hooks.json` (event registration; no matcher), `hooks/scripts/lib/state.py` (one-shot guard helpers + `did_edit_this_turn`), this doc §2 ("`Stop` guard" subsection), `tests/test_stop_guard.py` (every new done-claim or evidence pattern needs both directions; one-shot guard regression cases; rule 08 / rule 09 layer (e)+(f) cases) |
| `hooks/scripts/gc_state.py` | `commands/gc.md` (`/cc-enslaver:gc` slash command), `hooks/scripts/lib/state.py` (consumes `state_dir()` to scope the GC), `tests/test_gc_state.py` (arg validation + dry-run + apply + threshold semantics) |
| `hooks/scripts/register_read.py` | `hooks/scripts/bash_guard.py` (the actual register handling lives there), this doc §2 "Read-cache escape hatch", `tests/test_register_read.py` |
| `hooks/hooks.json` | `.claude-plugin/plugin.json` (hooks pointer), this doc §2 (event table) |
| `.claude-plugin/plugin.json` | `README.md` (install steps), `CHANGELOG.md`, `.claude-plugin/marketplace.json` (version sync), version-bump must match an actual change. **Do not** re-add the `commands` / `agents` / `skills` / `hooks` path fields for standard locations: they cause `claude plugin install` to fail with `Duplicate hooks file detected` or `agents: Invalid input` because Claude Code auto-discovers `./commands/`, `./agents/`, `./skills/`, and `./hooks/hooks.json`. Those manifest fields are only for *non-standard* layouts. |
| `.claude-plugin/marketplace.json` | `README.md` (install steps), `.claude-plugin/plugin.json` (version), this doc |
| `commands/*.md` | `.claude-plugin/plugin.json` (commands path), this doc, `README.md` |
| `agents/verifier.md` | `commands/verify.md` (invocation), this doc |
| `skills/systematic-debug/SKILL.md` | `rules/02-systematic-not-reactive.md`, `rules/03-root-cause.md`, this doc |
| `tests/_helpers.py` | every `tests/test_*.py` file (they all import from here) |
