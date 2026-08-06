# cc-enslaver

> A Claude Code plugin and LLM-agnostic rule pack that **eliminates lazy AI behavior** — reactive patches, guessed citations, surface-level "fixes", half-finished work — by enforcing systematic thinking, verification, and root-cause analysis at every layer of the agent loop.

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Plugin Version](https://img.shields.io/badge/version-0.22.1-blue.svg)](CHANGELOG.md)
[![Tests](https://github.com/skymanbp/cc-enslaver/actions/workflows/test.yml/badge.svg)](https://github.com/skymanbp/cc-enslaver/actions/workflows/test.yml)
[![Claude Code Plugin](https://img.shields.io/badge/Claude%20Code-plugin-purple.svg)](https://code.claude.com/docs/en/plugins.md)

中文用户请直接看 → [中文说明](#中文说明)

---

## What is this?

LLM coding agents (Claude Code, Cursor, Copilot, Cline, Aider, etc.) frequently fall into predictable lazy patterns:

| Lazy pattern | What it looks like |
|---|---|
| **Reactive patching** | Sees a bug, slaps a try/except around it, declares done. |
| **Guessed citations** | Cites file paths, line numbers, or APIs that don't exist. |
| **Keyword-search-only** | Greps once, edits, never reads the surrounding architecture. |
| **Memory dependence** | Acts on stale recollection instead of re-reading the current file. |
| **Root-cause bypass** | Adds `sleep` for races, `--no-verify` for hooks, swallows exceptions. |
| **Half-finished work** | Stops at "should work", leaves TODOs, doesn't verify the whole flow. |
| **Premature done-claim** | Claims "fixed" without re-running the original failing case, no edge cases, no comparison evidence. |

`cc-enslaver` ships a **layered defense** against all seven, currently **11 built-in rules + user-defined Imperial Edicts (圣旨) + 8 Stop-hook gates** (v0.22.1):

> **New in v0.22.1** — 🔬 **Two rules sharpened from real field failures** (no new detector, no new Stop layer — which is why it is a patch). **rule 06 gains Check 2b — "aggregate-equal is not unchanged"**: any *unchanged / no-regression* claim must compare the **item set** (category names, test IDs, failing-assertion identities, per-file hashes), never a matching **total**. Field evidence: a validator printed `Total issues: 754` both before and after a ~9,500-substitution refactor — byte-identical — while a per-category diff showed one category had flipped `OK …: INFO:1` → `X …: CRITICAL:1`. The check carries the corollary **scope of evidence ≠ scope of claim**: a gate that validates part of an artifact proves nothing about the rest. **rule 09 gains a bulk-mechanical-edit discipline** for renames / codemods / sed: survey what actually surrounds every occurrence *before* writing the rule, rewrite only allowlisted forms, emit a **refusal report**, reconcile `total = rewritten + skipped + refused`, expect shapes the pattern is structurally blind to (the token inside a regex alternation, as a standalone argument, and the symbol named after it), and **never rewrite a path that addresses history** (`git show <fixed-rev>:<path>`). Plus **closed-set guards**: enumerate the legal set instead of blacklisting stray shapes. See [`rules/06-verify-convergence.md`](rules/06-verify-convergence.md) + [`rules/09-systematic-modification.md`](rules/09-systematic-modification.md).
>
> **New in v0.22** — 🔒 **Two new write-time content detectors (rules 10 + 11)**: `PreToolUse(Edit|Write)` now physically **DENY**s writing *non-essential* hardcoding or machine-specific path dependencies into code. **Rule 10 (no hardcoding)** flags an unjustified hardcoded secret — a secret-named literal (`password` / `api_key` / `token` / … ≥ 8 chars), a PEM `-----BEGIN … PRIVATE KEY-----` header, an `AKIA…` AWS access key, or credentials embedded in a connection URL. **Rule 11 (no path dependency)** flags a user-home absolute path baked into code (`C:\Users\…`, `/home/…` or `/Users/…`, `$HOME`, `%USERPROFILE%`, a quoted `~/…`). Both share the rule-09 **why-comment escape hatch** — an adjacent `because` / `原因` / `essential` / `fixture` / `placeholder` justification allows the write, which is exactly how "*non-essential*" is operationalized — and both **exempt prose-doc + lockfile targets** (`.md` / `.rst` / `.txt` / `.adoc`, `*.lock`, `package-lock.json`) so this repo's own example-laden docs never self-trip. Like the other content detectors they are **PreToolUse-only** (no Stop layer). See [`rules/10-no-hardcoding.md`](rules/10-no-hardcoding.md) + [`rules/11-no-path-dependency.md`](rules/11-no-path-dependency.md).
>
> **New in v0.21** — 🌍 **English is now the skeleton language**: the plugin's rule + prompt surface flipped from Chinese-canonical to **English-as-source-of-truth**. English lives at the root (`rules/*.md`, `prompts/*.md`); each translation lives in a language subdir (`rules/zh/`, `prompts/zh/`, and any `rules/<code>/`). Injection defaults to English (`CC_ENSLAVER_LANG` unset / `en`); set `CC_ENSLAVER_LANG=zh` for Chinese, or any code for a partial translation (missing files fall back to the English skeleton). **Language version control is a hard, CI-enforced gate**: [`hooks/scripts/i18n_check.py`](hooks/scripts/i18n_check.py) (run via `/cc-enslaver:i18n`) asserts every translation tracks the skeleton file-for-file and section-for-section; [`tests/test_i18n_sync.py`](tests/test_i18n_sync.py) turns CI red on any drift. **On drift, English wins.** See [`docs/I18N.md`](docs/I18N.md).
>
> **New in v0.20** — 📋 **Structured YAML reporting + plain-language TL;DR**: every reply now ends with a fixed ```yaml `cc-enslaver:` block (`改前 / 改中 / 收敛 / 忠实 / 收尾 / tldr`; English mirror `before / edits / convergence / fidelity / closing / tldr`) — the audit trail is **scannable at a glance** instead of drifting free-form prose. A new **Stop layer (h)** hard-enforces a one-sentence `tldr` (大白话总结) on every done-claim reply, and every block reason now carries a `大白话:` takeaway. The schema's field names ARE the existing Stop-hook detection markers, so no detector changed — old emoji-markdown and new YAML reply forms both pass.
>
> **From v0.18** — 🧹 **Opt-in auto-GC on SessionStart**: set `CC_ENSLAVER_AUTO_GC_DAYS=30` and the SessionStart hook automatically prunes session-state files older than N days. Rate-limited to once per 24h via a marker file so rapid session restarts don't re-scan. Default off (backward-compatible); the manual `/cc-enslaver:gc` slash command still works and shares the same `prune_old_sessions()` deletion routine.
>
> **From v0.17** — 🌐 **Imperial Edicts go bilingual**: with `CC_ENSLAVER_LANG=en`, the soft-layer injection and the PreToolUse DENY reason both flip to English ("Imperial Edicts" / "Imperial Edict E01 violation"). Default Chinese ("圣旨") preserved. Plus Windows portability fixes: file-claim regex now matches drive-letter paths (`C:\Users\...\x.py`), and `manage_edicts.py` forces UTF-8 stdout.
>
> **From v0.16** — 🕵️ **Stop Layer (g) file-claim verification**: read_guard captures per-file mtime baselines on first encounter; stop_guard parses `I edited X.py` / `我修改了 Y.md` claims and BLOCKs the Stop when the on-disk mtime contradicts. Conservative-by-design (no baseline / any ambiguity → pass). Escape hatch: `CC_ENSLAVER_DISABLE_LAYER_G=1`.
>
> **From v0.15** — 🌍 **Switchable prompt language**: `CC_ENSLAVER_LANG` selects which translation the hook injects. (v0.21 flipped the default — English is now the skeleton at `prompts/{session-start,user-prompt}.md`; `CC_ENSLAVER_LANG=zh` injects the Chinese translation under `prompts/zh/`, and any unknown code falls back to the English skeleton.)
>
> **From v0.14** — ⚡ **Three more Bash bypass patterns** (`git rebase --skip`, `--break-system-packages`, `rm -rf` on root/`$HOME`/`~`) get `PreToolUse(Bash)` DENY. 🏛️ **Edicts `--global` flag**: `add --global` writes to `~/.claude/cc-enslaver/edicts.toml` for personal cross-project rules.
>
> **From v0.13** — 🔁 **Rule-09 rolling-patch hard layer**: `PreToolUse(Edit|Write)` physically DENYs the 4th small Edit (≤ 10 lines AND < 200 chars) to the same file in one session unless a systematic rewrite (≥ 50 lines OR ≥ 1500 chars) resets the counter. See [`rules/09-systematic-modification.md`](rules/09-systematic-modification.md) §"Edit/Write 频率层".
>
> **From v0.12** — 🏛️ **Imperial Edicts (圣旨)**: user-defined per-project hard rules loaded from `.claude/cc-enslaver/edicts.toml` with PreToolUse(Edit|Write|Bash) DENY and `/cc-enslaver:edict` CRUD slash command. See [`docs/EDICTS.md`](docs/EDICTS.md). Stop-hook block reasons render as uniform **status tables**. Soft-layer prompts thinned 54%.


1. **Soft layer (prompt injection)** — at session start and before every user prompt, the plugin injects a concise reminder of the 11 discipline rules into the agent's context. v0.11 added a standard response skeleton; **v0.20 turns it into a fixed YAML reply schema** (`cc-enslaver:` block with `改前 / 改中 / 收敛 / 忠实 / 收尾 / tldr` fields — English mirror uses `before / edits / convergence / fidelity / closing / tldr`) whose field names ARE the Stop-hook detection markers, plus a mandatory plain-language `tldr` (大白话总结) closing line. A **per-turn self-check checklist** with a physical-enforcement table maps each lazy attempt to the specific hook that catches it.
2. **Hard layer (PreToolUse blocks)** — at the moment the agent calls `Edit`, `Write`, or `Bash`, the plugin gates the call:
   - **Edit/Write read-before-edit** (rule 04 + rule 08): denied if the target file already exists but has not been `Read` in this session. New file creation is allowed.
   - **Edit/Write patch-style content** (rule 09, **v0.11**): denied if `new_string` (Edit) or `content` (Write) contains an *unjustified* suppression marker — `try / except: pass`, `# noqa`, `# type: ignore`, `// @ts-ignore`, `// @ts-expect-error`, `// eslint-disable[-next-line]`, `time.sleep(...) # race/wait/workaround`. Each marker is allowed when accompanied by a why-comment on the same or adjacent line containing `because`, `原因`, `why`, `正当`, `rationale`, `see issue/pr/ticket`, `intentional[ly]`, `deliberate[ly]`, `third-party`, or `per spec/rfc/standard`.
   - **Edit/Write hardcoded secret** (rule 10, **v0.22**): denied if `new_string` (Edit) or `content` (Write) targets *code* — not a `.md`/`.rst`/`.txt`/`.adoc` prose doc or a lockfile — and contains an *unjustified* hardcoded secret: a secret-named literal ≥ 8 chars (`password` / `api_key` / `token` / …), a PEM `-----BEGIN … PRIVATE KEY-----` header, an `AKIA…` AWS access key, or credentials embedded in a connection URL. Allowed when an adjacent line carries a why/essential rationale (`because`, `原因`, `essential`, `fixture`, `placeholder`, …) or the value is an obvious placeholder / env-read.
   - **Edit/Write path dependency** (rule 11, **v0.22**): denied if code contains an *unjustified* machine-specific user-home absolute path (`C:\Users\…`, `/home/…` or `/Users/…`, `$HOME`, `%USERPROFILE%`, a quoted `~/…`). Recovery: derive the path at runtime (plugin root / cwd / env / arg), or justify with an adjacent why-comment. Same prose-doc + lockfile exemption as rule 10; deliberately narrow to *user-specific* roots to keep false positives low.
   - **Bash bypass patterns** (rule 03 + rule 09): denied if the command contains `--no-verify`, `--no-gpg-sign`, `git push --force` (without `--force-with-lease`), or `chmod 777`. Each deny includes a precise recovery instruction.
   - **Read-cache escape hatch** (v0.4.0): when Claude Code's harness short-circuits a `Read` to its result cache without invoking the tool, the file never enters session state and a subsequent `Edit` is falsely denied. Agents can call `register_read.py --file ABS --hash SHA256` from Bash; `bash_guard.py` recomputes the hash from disk and only registers on match, so the hatch can't itself be used as a bypass.
   - **Edit-turn stamping** (**v0.11**): every accepted Edit/Write records `last_edit_turn = turn_count` in session state. The Stop-hook layers (e)+(f) consult this to scope themselves to edit turns only.
3. **Hard layer (Stop hook, v0.6.0 → v0.7.0 → v0.8.0 → v0.11.0 → v0.16.0 → v0.20.0)** — at every `Stop` event, `stop_guard.py` inspects the agent's last assistant message and applies **eight** layered checks (v0.12 reformatted the block reason as a uniform status table with the failing row highlighted; v0.20 added an 8th row and a plain-language `大白话` line under each block):
   - **(a) v0.6.0** — done-claim with **no evidence** (no `$ ` shell prompt, no test counts, no `重触发`/`pytest`/`unittest` keyword, no fenced code block) → block.
   - **(b) v0.7.0** — done-claim with **hedge near it** (`我觉得` / `I think` / `应该是` / `probably` / `maybe` within ~50 chars) → block (rule 01 cross-enforcement). Confident verification cannot coexist with hedged language.
   - **(c) v0.7.0** — done-claim with evidence but **no rule-06 marker** (`rule 06` / `自答` / `收敛` / `重触发` / `边界用例`) and **fewer than 2 of 4 self-quiz questions** detected (真解决? 更好方案? 哪些没验? 验证合理?) → block. Tests passing alone is not convergence.
   - **(d) v0.8.0** — passes (a)(b)(c) but **no rule-07 fidelity marker** (`rule 07` / `任务忠实` / `请求覆盖` / `原始请求` / `无降级` / `无遗漏` / `task fidelity` / `request coverage` / `no degradation` / `no omission` / `no scope creep` / `covered all` / `all requested` / ✅ 完成 checklist row) and **fewer than 2 of 3 fidelity questions** detected (覆盖性 / 标准性 / 忠实性) → block.
   - **(e) v0.11.0** — **fires only on edit turns** (`last_edit_turn == turn_count`). No **rule-08 marker** (`rule 08` / `改前必读` / `写前必想` / `read-before-edit` / `think-before-write` / `系统式自答`) AND fewer than 3 of 6 rule-02 keywords (架构 / 职责 / 根源 / 方案 / 连带 / 风险) → block. Read-only / analysis turns never trip this layer.
   - **(f) v0.11.0** — also **edit-turns-only**. No **rule-09 marker** (`rule 09` / `系统式修改` / `打补丁` / `systematic modification` / `patch-style` / `non-patch` / `反补丁`) AND incomplete triplet (root-cause + impact + solution) → block. Demands the systematic-modification triplet on every edit-bearing closing.
   - **(g) v0.16.0** — also **edit-turns-only**. Parses `I edited X.py` / `我修改了 Y.md` / `created Z.js` claims from the message and checks each against a **per-file mtime baseline** captured by `read_guard.py` on first Read / Edit / Write. If the on-disk state **definitively contradicts** a claim (mtime unchanged for "edited" / file still missing for "created"), → block. Conservative: no baseline / any ambiguity → pass. Escape hatch: `CC_ENSLAVER_DISABLE_LAYER_G=1`.
   - **(h) v0.20.0** — fires on **every done-claim turn** (not just edit turns), as the final gate. The reply must surface a plain-language **TL;DR** (`tldr:` schema field / `大白话` / `一句话总结` / `TL;DR`), else block. Enforced as a closing readability convention, deliberately not promoted to a tenth numbered rule.

   A one-shot guard (`last_blocked_turn` in session state, with a 3-turn grace window) prevents infinite loops. Each layer has its own block-reason text so the agent sees exactly which discipline gate failed.
4. **Active layer (slash commands)** — four commands let the user (or the agent) trigger discipline on demand:
   - **`/cc-enslaver:checklist`** — structured 6-section checklist (A pre-edit / B post-edit / C convergence / D fidelity / E rule-08 read-before-edit·think-before-write / F rule-09 systematic-modification).
   - **`/cc-enslaver:verify`** — independent file:line citation re-verification pass.
   - **`/cc-enslaver:gc`** (v0.6.1) — session-state file garbage collection (dry-run by default).
   - **`/cc-enslaver:edict`** (v0.12) — Imperial Edicts CRUD (`list / add / remove / reload / path`); `add --global` (v0.14) writes to `~/.claude` instead of project.
5. **Subagent layer** — the `verifier` subagent independently re-reads any file:line citations the agent has produced and reports whether they're real.
6. **Skill layer** — `systematic-debug` auto-invokes when debugging language is detected, forcing a root-cause walk-through before any fix is proposed (v0.10 adds Step 0 = build a reproducible feedback loop with 10 concrete loop patterns).
7. **LLM-agnostic core** — every rule lives as plain Markdown, with **English as the skeleton (source of truth)** at [`rules/`](rules/) and translations in language subdirs ([`rules/zh/`](rules/zh/), and any `rules/<code>/`). The soft-layer prompts follow the same layout ([`prompts/`](prompts/) = English skeleton, `prompts/<code>/` = translation), so injection can run in any language via `CC_ENSLAVER_LANG` — the switch also covers Imperial Edicts injection + deny reasons. Translations are kept in lock-step with the skeleton by a CI-enforced check ([`docs/I18N.md`](docs/I18N.md)). The discipline pack works as a system-prompt fragment for ChatGPT, Gemini, local models, or anything else.

> **Future (roadmap):** Per-session ephemeral edicts (`/cc-enslaver:edict add --session ...`); Layer (g) content-hash escalation for same-second mtime edge cases. (Auto-GC on SessionStart — delivered in v0.18.)

---

## Repository structure

```
cc-enslaver/
├── .claude-plugin/
│   ├── plugin.json              # Plugin manifest
│   └── marketplace.json         # Single-plugin marketplace entry
├── CLAUDE.md                    # Project-level instructions (loaded by Claude Code)
├── README.md / CHANGELOG.md / LICENSE
├── docs/
│   ├── ARCHITECTURE.md          # How the layers fit together
│   ├── RULES.md                 # Catalog of every rule
│   ├── EDICTS.md                # Imperial Edicts (圣旨) user guide (v0.12)
│   └── I18N.md                  # Language version control — English is the skeleton (v0.21)
├── rules/                       # ★ LLM-agnostic source of truth (plain Markdown)
│   ├── 00-index.md ~ 11-no-path-dependency.md  # English skeleton (source of truth)
│   └── zh/                      # 中文 translation (any rules/<code>/; v0.21)
├── prompts/                     # Distilled injection text (consumed by hooks)
│   ├── session-start.md         # SessionStart injection (English skeleton)
│   ├── user-prompt.md           # UserPromptSubmit injection (English skeleton)
│   └── zh/                      # 中文 translation (CC_ENSLAVER_LANG=zh; v0.21)
├── hooks/
│   ├── hooks.json               # Hook registration (4 events)
│   └── scripts/
│       ├── inject_context.py    # Soft-layer injection (English skeleton; any lang via CC_ENSLAVER_LANG)
│       ├── read_guard.py        # PreToolUse(Read|Edit|Write) — rule 04+08+09+10+11 + edicts + baseline
│       ├── bash_guard.py        # PreToolUse(Bash) — rule 03+09 + edicts
│       ├── stop_guard.py        # Stop — 7-layer status table
│       ├── register_read.py     # Read-cache escape hatch (v0.4)
│       ├── gc_state.py          # Manual session-state GC (v0.6.1)
│       ├── manage_edicts.py     # Imperial Edicts CRUD CLI (v0.12)
│       ├── i18n_check.py        # Language version-control sync check (v0.21)
│       └── lib/
│           ├── state.py         # Per-session JSON state (read_files / edits_per_file / baseline_mtimes / ...)
│           └── edicts.py        # Edicts loader / matcher / bilingual renderer (v0.12 + v0.17)
├── commands/                    # /cc-enslaver:{checklist,verify,gc,edict,i18n}
├── agents/verifier.md           # Independent citation verifier subagent
├── skills/systematic-debug/     # Auto-invoked debug discipline skill
└── tests/                       # 248 black-box subprocess tests (run with python -m unittest discover tests)
```

See [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) for a layer-by-layer walkthrough and [`docs/EDICTS.md`](docs/EDICTS.md) for the Imperial Edicts user guide.

---

## Installation

### As a Claude Code plugin (recommended)

The repo ships with `.claude-plugin/marketplace.json`, so it can be registered as a single-plugin marketplace and installed via Claude Code's `/plugin` UI.

```bash
# 1) Clone this repo somewhere — the path you choose becomes the marketplace root.
git clone https://github.com/skymanbp/cc-enslaver.git /path/to/cc-enslaver
```

Then in any Claude Code session (CLI or IDE):

```
/plugin marketplace add /path/to/cc-enslaver
/plugin install cc-enslaver@cc-enslaver
```

The plugin's internal name is `cc-enslaver` (declared in `plugin.json`), so slash commands surface as `/cc-enslaver:checklist`, `/cc-enslaver:verify`, and the auto-invoked `systematic-debug` skill is available as `systematic-debug`. The GitHub repo name `cc-enslaver` is the marketplace identifier.

To verify: `/plugin` → "Installed" tab should list `cc-enslaver@cc-enslaver`.

> **Requirements:** Python on PATH (tested with Python 3.13). The hook scripts use only the standard library — no third-party packages.

### As a rule pack for any other LLM

You don't need Claude Code at all. The actual rules live in [`rules/`](rules/) as plain Markdown. **English is the skeleton (source of truth)** at [`rules/`](rules/); the Chinese translation lives at [`rules/zh/`](rules/zh/) (any other language goes in `rules/<code>/`, kept in sync with the skeleton — see [`docs/I18N.md`](docs/I18N.md)).

```bash
# English (skeleton / default):
cat rules/*.md > /tmp/cc-enslaver.txt

# Chinese (translation):
cat rules/zh/*.md > /tmp/cc-enslaver.txt

# Then feed that to your agent of choice as system prompt / pre-context.
```

For specific integration patterns (OpenAI, Gemini, local llama.cpp, etc.) see the **LLM portability** section in [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).

---

## How it works

### Hooks (Claude Code only)

| Event | Matcher | Behavior | Implementation |
|---|---|---|---|
| `SessionStart` | — | Inject 9-rule discipline summary + standard response skeleton + Imperial Edicts block (English skeleton by default; any language via `CC_ENSLAVER_LANG`) | [`hooks/scripts/inject_context.py`](hooks/scripts/inject_context.py) |
| `UserPromptSubmit` | — | Re-inject per-turn decision triggers + Imperial Edicts (defends against context compaction) | [`hooks/scripts/inject_context.py`](hooks/scripts/inject_context.py) |
| `PreToolUse` | `Read\|Edit\|Write` | Record on Read/Write; capture mtime baseline (v0.16); deny Edit/Write of unread existing file (rule 04+08); deny patch-style `new_string` (rule 09 v0.11); deny hardcoded secret in code (rule 10 v0.22); deny user-home path dependency in code (rule 11 v0.22); deny 4th small Edit without systematic rewrite (rule 09 v0.13); deny on Imperial Edict `deny_edit` regex hit (v0.12); stamp `last_edit_turn` | [`hooks/scripts/read_guard.py`](hooks/scripts/read_guard.py) |
| `PreToolUse` | `Bash` | Deny on bypass patterns (rule 03+09: `--no-verify` / `--no-gpg-sign` / `git push --force` / `chmod 777` / `git rebase --skip` / `--break-system-packages` / `rm -rf` root paths); process `register_read.py`; deny on Imperial Edict `deny_bash` regex hit | [`hooks/scripts/bash_guard.py`](hooks/scripts/bash_guard.py) |
| `Stop` | — | **Eight-layer decision** (v0.20): (a) no-evidence / (b) hedged-completion / (c) missing rule-06 quiz / (d) missing rule-07 fidelity / (e) missing rule-08 system-thinking / (f) missing rule-09 triplet / (g) file-claim contradicted by disk / (h) missing plain-language TL;DR. Block reason renders as a uniform status table + a `大白话:` line. | [`hooks/scripts/stop_guard.py`](hooks/scripts/stop_guard.py) |

Hook scripts (8 total under [`hooks/scripts/`](hooks/scripts/)):

- **`inject_context.py`** — soft layer. Emits `hookSpecificOutput.additionalContext` from prompt files in [`prompts/`](prompts/) (the English skeleton) — or `prompts/<lang>/` when `CC_ENSLAVER_LANG=<lang>`, falling back to the skeleton for any file a translation is missing; appends Imperial Edicts block via `lib/edicts.render_injection()`. Always allows.
- **`read_guard.py`** — hard layer (file context). Read-before-edit (rule 04+08); patch-style content scan (rule 09 content axis); rolling-patch counter (rule 09 frequency axis, v0.13); Imperial Edicts content scan (v0.12); mtime baseline capture for Stop layer (g) (v0.16); `last_edit_turn` stamp. Failing-open.
- **`bash_guard.py`** — hard layer (command discipline). Static bypass-pattern catalog (rule 03+09); `register_read.py` interception; Imperial Edicts command scan (v0.12). Built-in patterns always run before Edicts so a project edict can't whitelist `--no-verify`. Failing-open.
- **`stop_guard.py`** — hard layer (rule 06+07+08+09+01 at turn boundary). 7-layer decision tree + uniform status-table block reason (v0.12) + file-claim verification (v0.16). One-shot guard via `last_blocked_turn` with 3-turn grace window. Layers (e)+(f)+(g) scoped to edit turns. Failing-open.
- **`register_read.py`** — user-facing CLI for the read-cache escape hatch (v0.4). State mutation lives in `bash_guard.py` after a SHA-256 hash match.
- **`gc_state.py`** — manual garbage collection of stale session state files (v0.6.1; dry-run by default).
- **`manage_edicts.py`** — Imperial Edicts CRUD CLI (v0.12; `--global` flag v0.14; UTF-8 stdout v0.17). Used by the `/cc-enslaver:edict` slash command and directly from the shell.
- **`lib/state.py`** + **`lib/edicts.py`** — shared per-session-state library and Imperial Edicts loader / matcher / **multilingual renderer** (English default; `zh` — or any code — via `CC_ENSLAVER_LANG`, with English fallback for unknown codes; v0.17 + v0.21).

All scripts are covered by **248 black-box subprocess tests** in [`tests/`](tests/) — run with `python -m unittest discover tests`. CI matrix: ubuntu-latest × windows-latest × Python 3.13.

See [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) §2 for the full hook output contracts.

### User-invokable

| Surface | Purpose |
|---|---|
| `/cc-enslaver:checklist`   | Print the 6-section pre-action / pre-finish checklist on demand. |
| `/cc-enslaver:verify`      | Ask the agent to re-verify recent `file:line` citations and fact claims. |
| `/cc-enslaver:gc`          | List (or `--apply` to delete) session-state files older than N days. |
| `/cc-enslaver:edict`       | Manage Imperial Edicts: `list / add / remove / reload / path` (+ `--global`). |
| `verifier` subagent        | Independently re-reads cited locations and reports drift. |
| `systematic-debug` skill   | Auto-triggered on bug-fix language; forces root-cause walk before any fix. |

### Environment switches

| Variable | Effect |
|---|---|
| `CC_ENSLAVER_LANG=<code>` | Choose the injection language for SessionStart / UserPromptSubmit AND Imperial Edicts injection + deny reason. Default (unset / `en`) = **English skeleton**; `zh` = Chinese; any other code reads `<dir>/<code>/` and falls back to the English skeleton for missing files. |
| `CC_ENSLAVER_DISABLE_LAYER_G=1` | Disable Stop layer (g) file-claim verification (escape hatch for false positives in unusual workflows; the other 6 layers still apply). |
| `CC_ENSLAVER_AUTO_GC_DAYS=N` | **v0.18 opt-in.** Auto-prune session-state files older than N days on SessionStart. Rate-limited to once per 24h via a marker file. Unset / `0` / non-numeric → disabled. |
| `CLAUDE_PLUGIN_DATA` | Session-state base dir. Set by Claude Code; falls back to `${CLAUDE_PROJECT_DIR}/.claude/local/cc-enslaver/` then `~/.claude/local/cc-enslaver/`. |
| `CLAUDE_PROJECT_DIR` | Project root. Used to resolve project-level edicts at `.claude/cc-enslaver/edicts.toml`. |

---

## Contributing

The plugin enforces its own rules on its own development. Read [`CLAUDE.md`](CLAUDE.md)
section 4 ("修改本仓库时的强制流程") before opening a PR. In short:

1. Read every related file end-to-end before editing.
2. Trace downstream impact (e.g., editing a rule file → update the prompt, the
   docs, the checklist command, all in the same change).
3. Cite `file:line` in PR descriptions; never "I think" / "should be".
4. Address root causes, not symptoms. No `--no-verify`, no swallowed errors.

---

## License

MIT — see [`LICENSE`](LICENSE).

---

## 中文说明

`cc-enslaver` 是一个 **Claude Code 插件 + 任意 LLM 通用规则包**。它存在的唯一目的是：**杜绝 AI 编程助手的偷懒行为**。

### "偷懒"具体指什么？

| 偷懒模式 | 表现 |
|---|---|
| 反应式修补 | 看到 bug 就 try/except 包一下，宣告完成 |
| 猜测式引用 | 引用了不存在的 `file:line`、API 或版本号 |
| 关键词检索依赖 | grep 一下就改，从不读上下文 |
| 记忆依赖 | 凭印象答题，不重新读当前文件 |
| 根因绕过 | 用 `sleep` 掩盖竞态、用 `--no-verify` 跳过钩子 |
| 半成品 | 写到"应该能工作"就停手，留 TODO，不验证整条链路 |

### 防御分层（**v0.22.1**：11 内置规则 + 用户自定义圣旨 + Stop 钩子 8 层闸门）

> **v0.22.1 新增** — 🔬 **两条规则按真实翻车现场加厚**（零新检测器、零新 Stop 层，故为补丁级）。**规则 06 加「验证 2b：总量相等 ≠ 没变」**：任何"没变 / 无回归"的声称必须比**集合**（类别名、测试 ID、失败断言身份、逐文件哈希），绝不凭一个相同的**总数**。实证：某校验器在约 9,500 处替换前后都打印 `Total issues: 754`（逐字节相同），而逐类别比对显示一类从 `OK …: INFO:1` 翻成 `X …: CRITICAL:1`。附带推论**证据覆盖面 ≠ 结论覆盖面**：门只对它检查的那部分变绿，其余什么也没证明。**规则 09 加批量机械替换纪律**（改名 / codemod / sed）：先勘察 token 真实上下文再写规则、只改白名单形态、出**拒绝报告**、算术自洽（总数 = 改写 + 跳过 + 拒绝）、预期三种正则天生看不见的形态（藏在正则选择分支里 / 作独立参数 / 以它命名的符号）、**绝不改写寻址历史的路径**（`git show <固定 rev>:<path>`）。另加**封闭集守卫**：不变量若是"只有名单内合法"，就枚举合法集而不是拉黑见过的散件形态。详见 [`rules/zh/06-verify-convergence.md`](rules/zh/06-verify-convergence.md) + [`rules/zh/09-systematic-modification.md`](rules/zh/09-systematic-modification.md)。
>
> **v0.22 新增** — 🔒 **两个写时内容检测器（规则 10 + 11）**：`PreToolUse(Edit|Write)` 现在物理 **DENY** 把*非必须*的硬编码或机器相关路径依赖写进代码。**规则 10（禁止硬编码）** 拦截未经证明的硬编码密钥——secret 命名的字面量（`password` / `api_key` / `token` / … ≥ 8 字符）、PEM `-----BEGIN … PRIVATE KEY-----` 头、`AKIA…` AWS key、或连接串里内嵌的凭证。**规则 11（禁止路径依赖）** 拦截写死进代码的 user-home 绝对路径（`C:\Users\…`、`/home/…` 或 `/Users/…`、`$HOME`、`%USERPROFILE%`、带引号的 `~/…`）。两者共用 rule-09 的 **why 注释逃生口**——相邻一行有 `because` / `原因` / `essential` / `fixture` / `placeholder` 说明即放行，这正是"*非必须*"的落地方式——且都**豁免散文档 + lockfile**（`.md` / `.rst` / `.txt` / `.adoc`、`*.lock`、`package-lock.json`），所以本仓库自己满是示例路径的文档不会自触发。跟其它内容检测器一样是 **PreToolUse-only**（无 Stop 层）。详见 [`rules/10-no-hardcoding.md`](rules/10-no-hardcoding.md) + [`rules/11-no-path-dependency.md`](rules/11-no-path-dependency.md)。
>
> **v0.21 新增** — 🌍 **英文成为骨架语言**：插件的规则 + 注入文案从"中文 canonical"翻转为**英文 = source of truth**。英文放在根层（`rules/*.md`、`prompts/*.md`），每种翻译放语言子目录（`rules/zh/`、`prompts/zh/`、任意 `rules/<code>/`）。注入**默认英文**（`CC_ENSLAVER_LANG` 未设 / `en`）；设 `CC_ENSLAVER_LANG=zh` 用中文，或任意语言码用部分翻译（缺失文件自动回退英文骨架）。**语言版本控制是硬性、CI 强制的闸门**：[`hooks/scripts/i18n_check.py`](hooks/scripts/i18n_check.py)（`/cc-enslaver:i18n` 调用）断言每种翻译逐文件、逐章节跟随骨架；[`tests/test_i18n_sync.py`](tests/test_i18n_sync.py) 一旦漂移就让 CI 变红。**漂移时以英文为准。** 详见 [`docs/I18N.md`](docs/I18N.md)。
>
> **v0.20 新增** — 📋 **结构化 YAML 汇报 + 大白话总结**：每次回复末尾输出固定的 ```yaml `cc-enslaver:` 块（`改前 / 改中 / 收敛 / 忠实 / 收尾 / tldr`），把审计轨迹从飘忽的自由文本变成**一眼可扫的固定 schema**。新增 **Stop layer (h)** 硬强制每条 done-claim 回复必含一句 `tldr`（大白话总结），每条拦截理由也附一行 `大白话:`。schema 的字段名**本身就是**现有 Stop 检测 marker，所以检测层一行未改——新旧两种回复格式都通过。

1. **软提醒层**：会话启动 + 每轮用户提问前，把纪律规则 + 圣旨注入 agent 上下文。**v0.21 起**默认英文骨架（`CC_ENSLAVER_LANG` 未设 / `en`）；设 `CC_ENSLAVER_LANG=zh` 切到中文，或任意语言码用部分翻译、缺失文件回退英文（注入主体 + 圣旨 deny reason 同步切换）。**v0.20** 把"标准回复骨架"改为上面的 YAML schema。
2. **硬拦截层**：agent 调用 `Edit` / `Write` / `Bash` 或 Stop 时，插件在工具/回合边界做拦截：
   - **Edit/Write 改前必读**（v0.2 + v0.11 rule 08）：目标文件已存在但本会话未 `Read` 过 → DENY。新文件创建放行。
   - **Edit/Write 反补丁内容**（**v0.11 rule 09**）：new_string 含未带 why 注释的 `try/except: pass` / `# noqa` / `# type: ignore` / `@ts-ignore` / `// eslint-disable` / `time.sleep(...) # race` → DENY。
   - **Edit/Write rolling-patch 频率**（**v0.13 rule 09**）：同一文件本会话第 4 次小幅 Edit（≤ 10 行 且 < 200 字符）且**无**系统式重写（≥ 50 行 / ≥ 1500 字符）介入 → DENY；不增计数器，需一次系统式 Edit/Write 才能重置。
   - **Edit/Write 禁止非必须硬编码**（**v0.22 rule 10**）：写入*代码*（非 `.md`/`.rst`/`.txt`/`.adoc` 散文档、非 lockfile）的 new_string 含未经证明的硬编码密钥（secret 命名字面量 ≥ 8 字符 / PEM 私钥头 / `AKIA…` / 连接串内嵌凭证）→ DENY。相邻 why 注释（`because` / `原因` / `essential` / `fixture` / `placeholder`）或占位符放行。
   - **Edit/Write 禁止非必须路径依赖**（**v0.22 rule 11**）：写入代码的 user-home 绝对路径（`C:\Users\…` / `/home/…` 或 `/Users/…` / `$HOME` / `%USERPROFILE%` / 带引号 `~/…`）→ DENY。改为运行时派生，或加相邻 why 注释。与 rule 10 同样豁免散文档 + lockfile。
   - **Edit/Write 圣旨**（**v0.12**）：new_string 命中项目 `edicts.toml` 中 `must` 圣旨的 `deny_edit` 正则 → DENY。
   - **Bash 内置绕过**（v0.3 + **v0.14 扩**）：`--no-verify` / `--no-gpg-sign` / `git push --force` / `chmod 777` / `git rebase --skip` / `--break-system-packages` / `rm -rf` 根路径 → DENY。
   - **Bash 圣旨**（v0.12）：命令命中 `must` 圣旨的 `deny_bash` 正则 → DENY。内置先跑、圣旨后跑（圣旨不能 whitelist `--no-verify`）。
   - **Read 缓存逃生口**（v0.4）：`register_read.py` + bash_guard 重算 SHA-256 闸门。
   - **基线 + Edit-turn 标记**（v0.11 + **v0.16**）：每次成功 Read/Edit/Write 捕获 mtime 基线（v0.16）并标 `last_edit_turn`（v0.11），给 Stop 各层提供判定依据。
   - **Stop 钩子**（v0.6 → v0.7 → v0.8 → v0.11 → v0.16 → **v0.20**）：每次 Stop **八层**决策，输出**统一状态表**（✅ Pass / ❌ FAIL / ⏸ pending / — n/a）+ 一行 `大白话:`：(a) done 但无 evidence；(b) done 附近 50 字内含 hedge（rule 01 投影）；(c) 有 evidence 但缺 rule-06 收敛标记 + 4 题命中 < 2；(d) 通过 (a-c) 但缺 rule-07 忠实标记 + 3 题命中 < 2；(e) 本轮做了 Edit 但缺 rule-08 标记 + rule-02 关键词命中 < 3；(f) 本轮做了 Edit 但缺 rule-09 "根因+影响+方案" 三件套；**(g) v0.16** —— 本轮做了 Edit 且解析出 `I edited X.py` / `我修改了 Y.md` 类声明，但磁盘 mtime 与基线一致（claim 被证伪）→ 拒；**(h) v0.20** —— 含 done-claim 的回复缺 `tldr` / `大白话` / `TL;DR` → 拒（在**所有 done-claim 轮**触发，非 edit-only；收尾约定而非第 10 条规则）。一次性守卫 + 3-turn 宽限窗口避免死循环。`CC_ENSLAVER_DISABLE_LAYER_G=1` 可禁用 (g)。
3. **主动调用层**：4 个 slash 命令 —— `/cc-enslaver:checklist`、`/cc-enslaver:verify`、`/cc-enslaver:gc`（v0.6.1）、`/cc-enslaver:edict`（**v0.12** CRUD；**v0.14** 加 `--global` 写到 `~/.claude`）。
4. **子代理验证层**：`verifier` 独立重读 agent 给出的 `file:line` 引用，检查是否真实。
5. **技能层**：`systematic-debug` 在 debug 语境下自动唤起，强制走根因分析流程（v0.10 加 Step 0 = build feedback loop）。
6. **LLM-agnostic 核心**：所有规则以纯 Markdown 形式存放，**英文为骨架（source of truth）**放在 [`rules/`](rules/) 根层，翻译放语言子目录 [`rules/zh/`](rules/zh/) / 任意 `rules/<code>/`；注入文案同布局（[`prompts/`](prompts/) = 英文骨架，`prompts/<code>/` = 翻译）。翻译由 CI 硬门锁定跟随骨架（见 [`docs/I18N.md`](docs/I18N.md)）。整包可作为任意 LLM 的 system prompt 片段使用。

> **当前路线图**：会话级临时圣旨（`--session`）、Layer (g) 的 content-hash 同秒精度升级。（SessionStart 自动 GC 已在 v0.18 交付。）

### 安装

#### 作为 Claude Code 插件

```bash
git clone https://github.com/skymanbp/cc-enslaver.git /path/to/cc-enslaver
```

在 Claude Code 会话内：

```
/plugin marketplace add /path/to/cc-enslaver
/plugin install cc-enslaver@cc-enslaver
```

验证：`/plugin` 命令的 "Installed" 列表中应出现 `cc-enslaver@cc-enslaver`。
钩子脚本要求 `python` 在 PATH 上（在 Python 3.13 上测试过；只用标准库）。

#### 作为通用 LLM 规则包

```bash
# 英文骨架（默认 / source of truth）：
cat rules/*.md > cc-enslaver-rules-en.txt
# 或中文翻译：
cat rules/zh/*.md > cc-enslaver-rules-zh.txt
```

把这段文本作为 system prompt 喂给任何 LLM 即可。

### 详细文档

- 设计原则与项目级指令 → [`CLAUDE.md`](CLAUDE.md)
- 架构说明 → [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md)
- 完整规则目录 → [`docs/RULES.md`](docs/RULES.md)
- 圣旨（Imperial Edicts）使用指南 → [`docs/EDICTS.md`](docs/EDICTS.md)
- 变更日志与路线图 → [`CHANGELOG.md`](CHANGELOG.md)

### 环境变量

| 变量 | 作用 |
|---|---|
| `CC_ENSLAVER_LANG=<code>` | 选择 SessionStart / UserPromptSubmit 注入 + 圣旨注入 + DENY reason 的语言。默认（未设 / `en`）= **英文骨架（source of truth）**；`zh` = 中文翻译；其它语言码读 `<dir>/<code>/`，缺失文件自动回退英文骨架。语言版本控制契约见 [`docs/I18N.md`](docs/I18N.md)。 |
| `CC_ENSLAVER_DISABLE_LAYER_G=1` | 禁用 Stop layer (g) 文件声明验证（false-positive 时的 escape hatch；其余 6 层仍有效） |
| `CC_ENSLAVER_AUTO_GC_DAYS=N` | **v0.18 opt-in**：SessionStart 时自动清理 ≥ N 天未触碰的 state 文件。24h 速率限制。未设置 / `0` / 非数字 → 关闭。 |
