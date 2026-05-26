# cc-enslaver

> A Claude Code plugin and LLM-agnostic rule pack that **eliminates lazy AI behavior** — reactive patches, guessed citations, surface-level "fixes", half-finished work — by enforcing systematic thinking, verification, and root-cause analysis at every layer of the agent loop.

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Plugin Version](https://img.shields.io/badge/version-0.18.0-blue.svg)](CHANGELOG.md)
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

`cc-enslaver` ships a **layered defense** against all seven, currently **9 built-in rules + user-defined Imperial Edicts (圣旨) + 7 Stop-hook gates** (v0.18.0):

> **New in v0.18** — 🧹 **Opt-in auto-GC on SessionStart**: set `CC_ENSLAVER_AUTO_GC_DAYS=30` and the SessionStart hook automatically prunes session-state files older than N days. Rate-limited to once per 24h via a marker file so rapid session restarts don't re-scan. Default off (backward-compatible); the manual `/cc-enslaver:gc` slash command still works and shares the same `prune_old_sessions()` deletion routine.
>
> **From v0.17** — 🌐 **Imperial Edicts go bilingual**: with `CC_ENSLAVER_LANG=en`, the soft-layer injection and the PreToolUse DENY reason both flip to English ("Imperial Edicts" / "Imperial Edict E01 violation"). Default Chinese ("圣旨") preserved. Plus Windows portability fixes: file-claim regex now matches drive-letter paths (`C:\Users\...\x.py`), and `manage_edicts.py` forces UTF-8 stdout.
>
> **From v0.16** — 🕵️ **Stop Layer (g) file-claim verification**: read_guard captures per-file mtime baselines on first encounter; stop_guard parses `I edited X.py` / `我修改了 Y.md` claims and BLOCKs the Stop when the on-disk mtime contradicts. Conservative-by-design (no baseline / any ambiguity → pass). Escape hatch: `CC_ENSLAVER_DISABLE_LAYER_G=1`.
>
> **From v0.15** — 🌍 **English prompts mirror**: set `CC_ENSLAVER_LANG=en` and the hook injects `prompts/en/{session-start,user-prompt}.md` instead of the Chinese canonical.
>
> **From v0.14** — ⚡ **Three more Bash bypass patterns** (`git rebase --skip`, `--break-system-packages`, `rm -rf` on root/`$HOME`/`~`) get `PreToolUse(Bash)` DENY. 🏛️ **Edicts `--global` flag**: `add --global` writes to `~/.claude/cc-enslaver/edicts.toml` for personal cross-project rules.
>
> **From v0.13** — 🔁 **Rule-09 rolling-patch hard layer**: `PreToolUse(Edit|Write)` physically DENYs the 4th small Edit (≤ 10 lines AND < 200 chars) to the same file in one session unless a systematic rewrite (≥ 50 lines OR ≥ 1500 chars) resets the counter. See [`rules/09-systematic-modification.md`](rules/09-systematic-modification.md) §"Edit/Write 频率层".
>
> **From v0.12** — 🏛️ **Imperial Edicts (圣旨)**: user-defined per-project hard rules loaded from `.claude/cc-enslaver/edicts.toml` with PreToolUse(Edit|Write|Bash) DENY and `/cc-enslaver:edict` CRUD slash command. See [`docs/EDICTS.md`](docs/EDICTS.md). Stop-hook block reasons render as uniform **status tables**. Soft-layer prompts thinned 54%.


1. **Soft layer (prompt injection)** — at session start and before every user prompt, the plugin injects a concise reminder of the 9 discipline rules into the agent's context. v0.11 adds a **standard response skeleton** (5-stage template: pre-edit / mid-edit / rule-06 / rule-07 / rule-08+09 closing) and a **9-item per-turn self-check checklist** with a physical-enforcement table mapping each lazy attempt to the specific hook that catches it.
2. **Hard layer (PreToolUse blocks)** — at the moment the agent calls `Edit`, `Write`, or `Bash`, the plugin gates the call:
   - **Edit/Write read-before-edit** (rule 04 + rule 08): denied if the target file already exists but has not been `Read` in this session. New file creation is allowed.
   - **Edit/Write patch-style content** (rule 09, **v0.11**): denied if `new_string` (Edit) or `content` (Write) contains an *unjustified* suppression marker — `try / except: pass`, `# noqa`, `# type: ignore`, `// @ts-ignore`, `// @ts-expect-error`, `// eslint-disable[-next-line]`, `time.sleep(...) # race/wait/workaround`. Each marker is allowed when accompanied by a why-comment on the same or adjacent line containing `because`, `原因`, `why`, `正当`, `rationale`, `see issue/pr/ticket`, `intentional[ly]`, `deliberate[ly]`, `third-party`, or `per spec/rfc/standard`.
   - **Bash bypass patterns** (rule 03 + rule 09): denied if the command contains `--no-verify`, `--no-gpg-sign`, `git push --force` (without `--force-with-lease`), or `chmod 777`. Each deny includes a precise recovery instruction.
   - **Read-cache escape hatch** (v0.4.0): when Claude Code's harness short-circuits a `Read` to its result cache without invoking the tool, the file never enters session state and a subsequent `Edit` is falsely denied. Agents can call `register_read.py --file ABS --hash SHA256` from Bash; `bash_guard.py` recomputes the hash from disk and only registers on match, so the hatch can't itself be used as a bypass.
   - **Edit-turn stamping** (**v0.11**): every accepted Edit/Write records `last_edit_turn = turn_count` in session state. The Stop-hook layers (e)+(f) consult this to scope themselves to edit turns only.
3. **Hard layer (Stop hook, v0.6.0 → v0.7.0 → v0.8.0 → v0.11.0 → v0.16.0)** — at every `Stop` event, `stop_guard.py` inspects the agent's last assistant message and applies **seven** layered checks (v0.12 reformatted the block reason as a uniform **7-row status table** with the failing row highlighted):
   - **(a) v0.6.0** — done-claim with **no evidence** (no `$ ` shell prompt, no test counts, no `重触发`/`pytest`/`unittest` keyword, no fenced code block) → block.
   - **(b) v0.7.0** — done-claim with **hedge near it** (`我觉得` / `I think` / `应该是` / `probably` / `maybe` within ~50 chars) → block (rule 01 cross-enforcement). Confident verification cannot coexist with hedged language.
   - **(c) v0.7.0** — done-claim with evidence but **no rule-06 marker** (`rule 06` / `自答` / `收敛` / `重触发` / `边界用例`) and **fewer than 2 of 4 self-quiz questions** detected (真解决? 更好方案? 哪些没验? 验证合理?) → block. Tests passing alone is not convergence.
   - **(d) v0.8.0** — passes (a)(b)(c) but **no rule-07 fidelity marker** (`rule 07` / `任务忠实` / `请求覆盖` / `原始请求` / `无降级` / `无遗漏` / `task fidelity` / `request coverage` / `no degradation` / `no omission` / `no scope creep` / `covered all` / `all requested` / ✅ 完成 checklist row) and **fewer than 2 of 3 fidelity questions** detected (覆盖性 / 标准性 / 忠实性) → block.
   - **(e) v0.11.0** — **fires only on edit turns** (`last_edit_turn == turn_count`). No **rule-08 marker** (`rule 08` / `改前必读` / `写前必想` / `read-before-edit` / `think-before-write` / `系统式自答`) AND fewer than 3 of 6 rule-02 keywords (架构 / 职责 / 根源 / 方案 / 连带 / 风险) → block. Read-only / analysis turns never trip this layer.
   - **(f) v0.11.0** — also **edit-turns-only**. No **rule-09 marker** (`rule 09` / `系统式修改` / `打补丁` / `systematic modification` / `patch-style` / `non-patch` / `反补丁`) AND incomplete triplet (root-cause + impact + solution) → block. Demands the systematic-modification triplet on every edit-bearing closing.
   - **(g) v0.16.0** — also **edit-turns-only**. Parses `I edited X.py` / `我修改了 Y.md` / `created Z.js` claims from the message and checks each against a **per-file mtime baseline** captured by `read_guard.py` on first Read / Edit / Write. If the on-disk state **definitively contradicts** a claim (mtime unchanged for "edited" / file still missing for "created"), → block. Conservative: no baseline / any ambiguity → pass. Escape hatch: `CC_ENSLAVER_DISABLE_LAYER_G=1`.

   A one-shot guard (`last_blocked_turn` in session state, with a 3-turn grace window) prevents infinite loops. Each layer has its own block-reason text so the agent sees exactly which discipline gate failed.
4. **Active layer (slash commands)** — four commands let the user (or the agent) trigger discipline on demand:
   - **`/cc-enslaver:checklist`** — structured 6-section checklist (A pre-edit / B post-edit / C convergence / D fidelity / E rule-08 read-before-edit·think-before-write / F rule-09 systematic-modification).
   - **`/cc-enslaver:verify`** — independent file:line citation re-verification pass.
   - **`/cc-enslaver:gc`** (v0.6.1) — session-state file garbage collection (dry-run by default).
   - **`/cc-enslaver:edict`** (v0.12) — Imperial Edicts CRUD (`list / add / remove / reload / path`); `add --global` (v0.14) writes to `~/.claude` instead of project.
5. **Subagent layer** — the `verifier` subagent independently re-reads any file:line citations the agent has produced and reports whether they're real.
6. **Skill layer** — `systematic-debug` auto-invokes when debugging language is detected, forcing a root-cause walk-through before any fix is proposed (v0.10 adds Step 0 = build a reproducible feedback loop with 10 concrete loop patterns).
7. **LLM-agnostic core** — every rule lives as plain Markdown in [`rules/`](rules/) (Chinese canonical) and [`rules/en/`](rules/en/) (English mirror, synced through rule 09). v0.15 added matching [`prompts/en/`](prompts/en/) so the soft-layer injection itself can run in English (`CC_ENSLAVER_LANG=en`); v0.17 extended the same switch to cover Imperial Edicts injection + deny reasons. The discipline pack works as a system-prompt fragment for ChatGPT, Gemini, local models, or anything else.

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
│   └── EDICTS.md                # Imperial Edicts (圣旨) user guide (v0.12)
├── rules/                       # ★ LLM-agnostic source of truth (plain Markdown)
│   ├── 00-index.md ~ 09-systematic-modification.md  # Chinese canonical
│   └── en/                      # English mirror (v0.6.2+)
├── prompts/                     # Distilled injection text (consumed by hooks)
│   ├── session-start.md         # SessionStart injection (zh)
│   ├── user-prompt.md           # UserPromptSubmit injection (zh)
│   └── en/                      # English mirror (v0.15; CC_ENSLAVER_LANG=en)
├── hooks/
│   ├── hooks.json               # Hook registration (4 events)
│   └── scripts/
│       ├── inject_context.py    # Soft-layer injection (zh/en switchable)
│       ├── read_guard.py        # PreToolUse(Read|Edit|Write) — rule 04+08+09 + edicts + baseline
│       ├── bash_guard.py        # PreToolUse(Bash) — rule 03+09 + edicts
│       ├── stop_guard.py        # Stop — 7-layer status table
│       ├── register_read.py     # Read-cache escape hatch (v0.4)
│       ├── gc_state.py          # Manual session-state GC (v0.6.1)
│       ├── manage_edicts.py     # Imperial Edicts CRUD CLI (v0.12)
│       └── lib/
│           ├── state.py         # Per-session JSON state (read_files / edits_per_file / baseline_mtimes / ...)
│           └── edicts.py        # Edicts loader / matcher / bilingual renderer (v0.12 + v0.17)
├── commands/                    # /cc-enslaver:{checklist,verify,gc,edict}
├── agents/verifier.md           # Independent citation verifier subagent
├── skills/systematic-debug/     # Auto-invoked debug discipline skill
└── tests/                       # 174 black-box subprocess tests (run with python -m unittest discover tests)
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

You don't need Claude Code at all. The actual rules live in [`rules/`](rules/) as plain Markdown. The Chinese sources at [`rules/`](rules/) are canonical; an English mirror lives at [`rules/en/`](rules/en/) (added in v0.6.2).

```bash
# Chinese (canonical):
cat rules/*.md > /tmp/cc-enslaver.txt

# English (mirror; for non-CJK readers or non-Claude agents):
cat rules/en/*.md > /tmp/cc-enslaver.txt

# Then feed that to your agent of choice as system prompt / pre-context.
```

For specific integration patterns (OpenAI, Gemini, local llama.cpp, etc.) see the **LLM portability** section in [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).

---

## How it works

### Hooks (Claude Code only)

| Event | Matcher | Behavior | Implementation |
|---|---|---|---|
| `SessionStart` | — | Inject 9-rule discipline summary + standard response skeleton + Imperial Edicts block (zh / en switchable via `CC_ENSLAVER_LANG`) | [`hooks/scripts/inject_context.py`](hooks/scripts/inject_context.py) |
| `UserPromptSubmit` | — | Re-inject per-turn decision triggers + Imperial Edicts (defends against context compaction) | [`hooks/scripts/inject_context.py`](hooks/scripts/inject_context.py) |
| `PreToolUse` | `Read\|Edit\|Write` | Record on Read/Write; capture mtime baseline (v0.16); deny Edit/Write of unread existing file (rule 04+08); deny patch-style `new_string` (rule 09 v0.11); deny 4th small Edit without systematic rewrite (rule 09 v0.13); deny on Imperial Edict `deny_edit` regex hit (v0.12); stamp `last_edit_turn` | [`hooks/scripts/read_guard.py`](hooks/scripts/read_guard.py) |
| `PreToolUse` | `Bash` | Deny on bypass patterns (rule 03+09: `--no-verify` / `--no-gpg-sign` / `git push --force` / `chmod 777` / `git rebase --skip` / `--break-system-packages` / `rm -rf` root paths); process `register_read.py`; deny on Imperial Edict `deny_bash` regex hit | [`hooks/scripts/bash_guard.py`](hooks/scripts/bash_guard.py) |
| `Stop` | — | **Seven-layer decision** (v0.16): (a) no-evidence / (b) hedged-completion / (c) missing rule-06 quiz / (d) missing rule-07 fidelity / (e) missing rule-08 system-thinking / (f) missing rule-09 triplet / (g) file-claim contradicted by disk. Block reason renders as a uniform **7-row status table**. | [`hooks/scripts/stop_guard.py`](hooks/scripts/stop_guard.py) |

Hook scripts (8 total under [`hooks/scripts/`](hooks/scripts/)):

- **`inject_context.py`** — soft layer. Emits `hookSpecificOutput.additionalContext` from prompt files in [`prompts/`](prompts/) (or [`prompts/en/`](prompts/en/) when `CC_ENSLAVER_LANG=en`); appends Imperial Edicts block via `lib/edicts.render_injection()`. Always allows.
- **`read_guard.py`** — hard layer (file context). Read-before-edit (rule 04+08); patch-style content scan (rule 09 content axis); rolling-patch counter (rule 09 frequency axis, v0.13); Imperial Edicts content scan (v0.12); mtime baseline capture for Stop layer (g) (v0.16); `last_edit_turn` stamp. Failing-open.
- **`bash_guard.py`** — hard layer (command discipline). Static bypass-pattern catalog (rule 03+09); `register_read.py` interception; Imperial Edicts command scan (v0.12). Built-in patterns always run before Edicts so a project edict can't whitelist `--no-verify`. Failing-open.
- **`stop_guard.py`** — hard layer (rule 06+07+08+09+01 at turn boundary). 7-layer decision tree + uniform status-table block reason (v0.12) + file-claim verification (v0.16). One-shot guard via `last_blocked_turn` with 3-turn grace window. Layers (e)+(f)+(g) scoped to edit turns. Failing-open.
- **`register_read.py`** — user-facing CLI for the read-cache escape hatch (v0.4). State mutation lives in `bash_guard.py` after a SHA-256 hash match.
- **`gc_state.py`** — manual garbage collection of stale session state files (v0.6.1; dry-run by default).
- **`manage_edicts.py`** — Imperial Edicts CRUD CLI (v0.12; `--global` flag v0.14; UTF-8 stdout v0.17). Used by the `/cc-enslaver:edict` slash command and directly from the shell.
- **`lib/state.py`** + **`lib/edicts.py`** — shared per-session-state library and Imperial Edicts loader / matcher / **bilingual renderer** (zh canonical / en when `CC_ENSLAVER_LANG=en`, v0.17).

All scripts are covered by **174 black-box subprocess tests** in [`tests/`](tests/) — run with `python -m unittest discover tests`. CI matrix: ubuntu-latest × windows-latest × Python 3.13.

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
| `CC_ENSLAVER_LANG=en` | Switch SessionStart / UserPromptSubmit injections AND Imperial Edicts injection + deny reason to English. Default (unset / `zh` / unknown) = Chinese canonical. |
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

### 防御分层（**v0.17.0**：9 内置规则 + 用户自定义圣旨 + Stop 钩子 7 层闸门）

1. **软提醒层**：会话启动 + 每轮用户提问前，把纪律规则 + 圣旨注入 agent 上下文。**v0.15 起**默认中文；设 `CC_ENSLAVER_LANG=en` 切到英文（注入主体 + 圣旨 deny reason 同步切换，v0.17 闭环）。
2. **硬拦截层**：agent 调用 `Edit` / `Write` / `Bash` 或 Stop 时，插件在工具/回合边界做拦截：
   - **Edit/Write 改前必读**（v0.2 + v0.11 rule 08）：目标文件已存在但本会话未 `Read` 过 → DENY。新文件创建放行。
   - **Edit/Write 反补丁内容**（**v0.11 rule 09**）：new_string 含未带 why 注释的 `try/except: pass` / `# noqa` / `# type: ignore` / `@ts-ignore` / `// eslint-disable` / `time.sleep(...) # race` → DENY。
   - **Edit/Write rolling-patch 频率**（**v0.13 rule 09**）：同一文件本会话第 4 次小幅 Edit（≤ 10 行 且 < 200 字符）且**无**系统式重写（≥ 50 行 / ≥ 1500 字符）介入 → DENY；不增计数器，需一次系统式 Edit/Write 才能重置。
   - **Edit/Write 圣旨**（**v0.12**）：new_string 命中项目 `edicts.toml` 中 `must` 圣旨的 `deny_edit` 正则 → DENY。
   - **Bash 内置绕过**（v0.3 + **v0.14 扩**）：`--no-verify` / `--no-gpg-sign` / `git push --force` / `chmod 777` / `git rebase --skip` / `--break-system-packages` / `rm -rf` 根路径 → DENY。
   - **Bash 圣旨**（v0.12）：命令命中 `must` 圣旨的 `deny_bash` 正则 → DENY。内置先跑、圣旨后跑（圣旨不能 whitelist `--no-verify`）。
   - **Read 缓存逃生口**（v0.4）：`register_read.py` + bash_guard 重算 SHA-256 闸门。
   - **基线 + Edit-turn 标记**（v0.11 + **v0.16**）：每次成功 Read/Edit/Write 捕获 mtime 基线（v0.16）并标 `last_edit_turn`（v0.11），给 Stop 各层提供判定依据。
   - **Stop 钩子**（v0.6 → v0.7 → v0.8 → v0.11 → **v0.16**）：每次 Stop **七层**决策，输出**统一 7 行状态表**（✅ Pass / ❌ FAIL / ⏸ pending / — n/a）：(a) done 但无 evidence；(b) done 附近 50 字内含 hedge（rule 01 投影）；(c) 有 evidence 但缺 rule-06 收敛标记 + 4 题命中 < 2；(d) 通过 (a-c) 但缺 rule-07 忠实标记 + 3 题命中 < 2；(e) 本轮做了 Edit 但缺 rule-08 标记 + rule-02 关键词命中 < 3；(f) 本轮做了 Edit 但缺 rule-09 "根因+影响+方案" 三件套；**(g) v0.16** —— 本轮做了 Edit 且解析出 `I edited X.py` / `我修改了 Y.md` 类声明，但磁盘 mtime 与基线一致（claim 被证伪）→ 拒。一次性守卫 + 3-turn 宽限窗口避免死循环。`CC_ENSLAVER_DISABLE_LAYER_G=1` 可禁用 (g)。
3. **主动调用层**：4 个 slash 命令 —— `/cc-enslaver:checklist`、`/cc-enslaver:verify`、`/cc-enslaver:gc`（v0.6.1）、`/cc-enslaver:edict`（**v0.12** CRUD；**v0.14** 加 `--global` 写到 `~/.claude`）。
4. **子代理验证层**：`verifier` 独立重读 agent 给出的 `file:line` 引用，检查是否真实。
5. **技能层**：`systematic-debug` 在 debug 语境下自动唤起，强制走根因分析流程（v0.10 加 Step 0 = build feedback loop）。
6. **LLM-agnostic 核心**：所有规则以纯 Markdown 形式存放在 [`rules/`](rules/)（中文 canonical）/ [`rules/en/`](rules/en/)（英文镜像）/ [`prompts/en/`](prompts/en/)（v0.15 英文注入），可作为任意 LLM 的 system prompt 片段使用。

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
cat rules/*.md > cc-enslaver-rules.txt
# 或英文版（v0.6.2 新增）：
cat rules/en/*.md > cc-enslaver-rules-en.txt
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
| `CC_ENSLAVER_LANG=en` | 切换 SessionStart / UserPromptSubmit 注入 + 圣旨注入 + DENY reason 为英文（默认/未知值/`zh` → 中文 canonical） |
| `CC_ENSLAVER_DISABLE_LAYER_G=1` | 禁用 Stop layer (g) 文件声明验证（false-positive 时的 escape hatch；其余 6 层仍有效） |
| `CC_ENSLAVER_AUTO_GC_DAYS=N` | **v0.18 opt-in**：SessionStart 时自动清理 ≥ N 天未触碰的 state 文件。24h 速率限制。未设置 / `0` / 非数字 → 关闭。 |
