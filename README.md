# cc-enslaver

> A Claude Code plugin and LLM-agnostic rule pack that **eliminates lazy AI behavior** — reactive patches, guessed citations, surface-level "fixes", half-finished work — by enforcing systematic thinking, verification, and root-cause analysis at every layer of the agent loop.

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Plugin Version](https://img.shields.io/badge/version-0.12.0-blue.svg)](CHANGELOG.md)
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

`cc-enslaver` ships a **layered defense** against all six, currently 9 built-in rules + user-defined 圣旨 + 6 Stop-hook gates (v0.12.0):

> **New in v0.12** — 🏛️ **圣旨 (Imperial Edicts)**: user-defined per-project hard rules loaded from `.claude/cc-enslaver/edicts.toml`. Define a regex, set `severity = "must"`, and the `PreToolUse(Edit|Write|Bash)` hook will physically DENY any matching tool call. See [`docs/EDICTS.md`](docs/EDICTS.md). Stop-hook block reasons now render as uniform **6-row status tables** so the failed layer is obvious at a glance. Soft-layer prompts thinned 54% into high-density tables that survive context compaction better.


1. **Soft layer (prompt injection)** — at session start and before every user prompt, the plugin injects a concise reminder of the 9 discipline rules into the agent's context. v0.11 adds a **standard response skeleton** (5-stage template: pre-edit / mid-edit / rule-06 / rule-07 / rule-08+09 closing) and a **9-item per-turn self-check checklist** with a physical-enforcement table mapping each lazy attempt to the specific hook that catches it.
2. **Hard layer (PreToolUse blocks)** — at the moment the agent calls `Edit`, `Write`, or `Bash`, the plugin gates the call:
   - **Edit/Write read-before-edit** (rule 04 + rule 08): denied if the target file already exists but has not been `Read` in this session. New file creation is allowed.
   - **Edit/Write patch-style content** (rule 09, **v0.11**): denied if `new_string` (Edit) or `content` (Write) contains an *unjustified* suppression marker — `try / except: pass`, `# noqa`, `# type: ignore`, `// @ts-ignore`, `// @ts-expect-error`, `// eslint-disable[-next-line]`, `time.sleep(...) # race/wait/workaround`. Each marker is allowed when accompanied by a why-comment on the same or adjacent line containing `because`, `原因`, `why`, `正当`, `rationale`, `see issue/pr/ticket`, `intentional[ly]`, `deliberate[ly]`, `third-party`, or `per spec/rfc/standard`.
   - **Bash bypass patterns** (rule 03 + rule 09): denied if the command contains `--no-verify`, `--no-gpg-sign`, `git push --force` (without `--force-with-lease`), or `chmod 777`. Each deny includes a precise recovery instruction.
   - **Read-cache escape hatch** (v0.4.0): when Claude Code's harness short-circuits a `Read` to its result cache without invoking the tool, the file never enters session state and a subsequent `Edit` is falsely denied. Agents can call `register_read.py --file ABS --hash SHA256` from Bash; `bash_guard.py` recomputes the hash from disk and only registers on match, so the hatch can't itself be used as a bypass.
   - **Edit-turn stamping** (**v0.11**): every accepted Edit/Write records `last_edit_turn = turn_count` in session state. The Stop-hook layers (e)+(f) consult this to scope themselves to edit turns only.
3. **Hard layer (Stop hook, v0.6.0 → v0.7.0 → v0.8.0 → v0.11.0)** — at every `Stop` event, `stop_guard.py` inspects the agent's last assistant message and applies **six** layered checks:
   - **(a) v0.6.0** — done-claim with **no evidence** (no `$ ` shell prompt, no test counts, no `重触发`/`pytest`/`unittest` keyword, no fenced code block) → block.
   - **(b) v0.7.0** — done-claim with **hedge near it** (`我觉得` / `I think` / `应该是` / `probably` / `maybe` within ~50 chars) → block (rule 01 cross-enforcement). Confident verification cannot coexist with hedged language.
   - **(c) v0.7.0** — done-claim with evidence but **no rule-06 marker** (`rule 06` / `自答` / `收敛` / `重触发` / `边界用例`) and **fewer than 2 of 4 self-quiz questions** detected (真解决? 更好方案? 哪些没验? 验证合理?) → block. Tests passing alone is not convergence.
   - **(d) v0.8.0** — passes (a)(b)(c) but **no rule-07 fidelity marker** (`rule 07` / `任务忠实` / `请求覆盖` / `原始请求` / `无降级` / `无遗漏` / `task fidelity` / `request coverage` / `no degradation` / `no omission` / `no scope creep` / `covered all` / `all requested` / ✅ 完成 checklist row) and **fewer than 2 of 3 fidelity questions** detected (覆盖性 / 标准性 / 忠实性) → block.
   - **(e) v0.11.0** — **fires only on edit turns** (`last_edit_turn == turn_count`). No **rule-08 marker** (`rule 08` / `改前必读` / `写前必想` / `read-before-edit` / `think-before-write` / `系统式自答`) AND fewer than 3 of 6 rule-02 keywords (架构 / 职责 / 根源 / 方案 / 连带 / 风险) → block. Read-only / analysis turns never trip this layer.
   - **(f) v0.11.0** — also **edit-turns-only**. No **rule-09 marker** (`rule 09` / `系统式修改` / `打补丁` / `systematic modification` / `patch-style` / `non-patch` / `反补丁`) AND incomplete triplet (root-cause + impact + solution) → block. Demands the systematic-modification triplet on every edit-bearing closing.

   A one-shot guard (`last_blocked_turn` in session state, with a 3-turn grace window) prevents infinite loops. Each layer has its own block-reason text so the agent sees exactly which discipline gate failed.
4. **Active layer (slash commands)** — `/cc-enslaver:checklist`, `/cc-enslaver:verify`, and `/cc-enslaver:gc` (v0.6.1) let the user (or the agent) trigger a structured 6-section checklist (A pre-edit / B post-edit / C convergence / D fidelity / E rule-08 read-before-edit·think-before-write / F rule-09 systematic-modification), an independent verification pass, or session-state cleanup on demand.
5. **Subagent layer** — the `verifier` subagent independently re-reads any file:line citations the agent has produced and reports whether they're real.
6. **Skill layer** — `systematic-debug` auto-invokes when debugging language is detected, forcing a root-cause walk-through before any fix is proposed (v0.10 adds Step 0 = build a reproducible feedback loop with 10 concrete loop patterns).
7. **LLM-agnostic core** — every rule lives as plain Markdown in [`rules/`](rules/) (Chinese) and [`rules/en/`](rules/en/) (English mirror, synced through rule 09), so the same discipline pack works as a system-prompt fragment for ChatGPT, Gemini, local models, or anything else.

> **Future (roadmap):** Deep file-claim verification ("I edited X" → `git diff` / mtime check); rolling-patch PreToolUse hard interception (rule 09 second axis); auto-GC on SessionStart; English `prompts/`.

---

## Repository structure

```
cc-enslaver/
├── .claude-plugin/plugin.json   # Plugin manifest (Claude Code adapter)
├── CLAUDE.md                    # Project-level instructions (loaded by Claude Code)
├── docs/
│   ├── ARCHITECTURE.md          # How the layers fit together
│   └── RULES.md                 # Catalog of every rule
├── rules/                       # ★ LLM-agnostic source of truth (plain Markdown)
├── prompts/                     # Distilled injection text (consumed by hooks)
├── hooks/
│   ├── hooks.json               # Hook registration
│   └── scripts/inject_context.py
├── commands/                    # /cc-enslaver:checklist, /cc-enslaver:verify, /cc-enslaver:gc
├── agents/verifier.md           # Independent citation verifier subagent
└── skills/systematic-debug/     # Auto-invoked debug discipline skill
```

See [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) for a layer-by-layer walkthrough.

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
| `SessionStart` | — | Inject full 9-rule discipline summary + standard response skeleton | [`hooks/scripts/inject_context.py`](hooks/scripts/inject_context.py) |
| `UserPromptSubmit` | — | Inject 9-item per-turn self-check + physical-enforcement table | [`hooks/scripts/inject_context.py`](hooks/scripts/inject_context.py) |
| `PreToolUse` | `Read\|Edit\|Write` | Record on Read/Write; deny Edit/Write of unread existing file (rule 04 + 08); deny Edit/Write with unjustified patch-style `new_string` (rule 09, v0.11); stamp `last_edit_turn` for Stop layers (e)+(f) | [`hooks/scripts/read_guard.py`](hooks/scripts/read_guard.py) |
| `PreToolUse` | `Bash` | Deny on bypass patterns (rule 03 + 09); also process `register_read.py` invocations (validate hash, register state) | [`hooks/scripts/bash_guard.py`](hooks/scripts/bash_guard.py) |
| `Stop` | — | Six-layer decision (v0.11.0): (a) no-evidence / (b) hedged-completion / (c) missing rule-06 quiz / (d) missing rule-07 fidelity / (e) missing rule-08 system-thinking (edit turns only) / (f) missing rule-09 triplet (edit turns only) | [`hooks/scripts/stop_guard.py`](hooks/scripts/stop_guard.py) |

Five scripts:

- **`inject_context.py`** — soft layer. Emits `hookSpecificOutput.additionalContext` from prompt files in [`prompts/`](prompts/). Always allows.
- **`read_guard.py`** — hard layer (file context). Maintains per-session state at `${CLAUDE_PLUGIN_DATA}/sessions/<sid>.json` (Windows-safe path normalization). In v0.11 also performs `new_string` content scanning for rule-09 patch-style markers and stamps `last_edit_turn` on every accepted Edit/Write. Failing-open.
- **`bash_guard.py`** — hard layer (command discipline). Bypass-pattern catalog + register_read.py interception. Failing-open.
- **`register_read.py`** — user-facing CLI for the read-cache escape hatch (v0.4.0). State mutation lives in `bash_guard.py`; this script verifies its own hash check.
- **`stop_guard.py`** — hard layer (rule 06 + 07 + 08 + 09 enforcement at turn boundary, v0.6.0 → v0.7.0 → v0.8.0 → v0.11.0). Six-layer decision tree + one-shot guard via `last_blocked_turn` in session state. Layers (e)+(f) are scoped to edit turns via `did_edit_this_turn(...)` so read-only / analysis turns are never blocked. Failing-open.

All scripts are covered by black-box subprocess tests in [`tests/`](tests/) — run with `python -m unittest discover tests`.

See [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) §2 for the full hook output contracts.

### User-invokable

| Surface | Purpose |
|---|---|
| `/cc-enslaver:checklist` | Print the pre-action / pre-finish checklist on demand. |
| `/cc-enslaver:verify`    | Ask the agent to re-verify recent claims with `file:line` citations. |
| `verifier` subagent        | Independently re-reads cited locations and reports drift. |
| `systematic-debug` skill   | Auto-triggered on bug-fix language; forces root-cause walk before any fix. |

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

### 防御分层

1. **软提醒层**：会话启动 + 每轮用户提问前，把纪律规则注入 agent 上下文。
2. **硬拦截层**：agent 调用 `Edit` / `Write` / `Bash` 或 Stop 时，插件在工具/回合边界做拦截：
   - **Edit/Write 改前必读**（v0.2.0 + v0.11 rule 08）：若目标文件已存在但本会话尚未 `Read` 过 → deny + "先 Read 再重试"。新文件创建放行。
   - **Edit/Write 反补丁内容拦截**（**v0.11 rule 09**）：new_string 含未带 why 注释的 `try/except: pass` / `# noqa` / `# type: ignore` / `// @ts-ignore` / `// @ts-expect-error` / `// eslint-disable[-next-line]` / `time.sleep(...) # race/wait/workaround` → deny + 给出可接受形式样例。
   - **Bash**（v0.3.0）：命令包含 `--no-verify` / `--no-gpg-sign` / `git push --force`（不含 `--force-with-lease`） / `chmod 777` 等绕过模式 → deny + 给出符合规则 03 的根因式建议。
   - **Read 缓存逃生口**（v0.4.0）：`register_read.py` + bash_guard 重算 SHA-256 闸门。
   - **Edit-turn 标记**（**v0.11**）：每次成功 Edit/Write 在 session state 写 `last_edit_turn = turn_count`，给 Stop layer (e)(f) 提供"本轮做了 Edit 吗？"判定。
   - **Stop 钩子**（v0.6.0 → v0.7.0 → v0.8.0 → **v0.11.0**）：每次 Stop **六层**决策：(a) done-claim + 无 evidence → 拒；(b) done-claim + 50 字内 hedge（`我觉得`/`I think`/`probably` 等）→ 拒（rule 01 投影）；(c) done-claim + evidence 但缺 rule-06 收敛标记**且** 4 题匹配 < 2 → 拒；(d) 通过 (a)(b)(c) 但缺 rule-07 忠实标记**且** 3 题匹配 < 2 → 拒；**(e) v0.11.0** —— 仅当本轮做了 Edit（`last_edit_turn == turn_count`）且缺 rule-08 标记**且** 6 个 rule-02 关键词（架构/职责/根源/方案/连带/风险）命中 < 3 → 拒；**(f) v0.11.0** —— 仅当本轮做了 Edit 且缺 rule-09 标记**且** 三件套（根源 + 影响 + 方案）不全 → 拒。一次性守卫 + 3-turn 宽限窗口避免死循环。
3. **主动调用层**：`/cc-enslaver:checklist`、`/cc-enslaver:verify`、`/cc-enslaver:gc`（v0.6.1，状态文件清理）等 slash 命令。
4. **子代理验证层**：`verifier` 独立重读 agent 给出的 `file:line` 引用，检查是否真实。
5. **技能层**：`systematic-debug` 在 debug 语境下自动唤起，强制走根因分析流程。
6. **LLM-agnostic 核心**：所有规则以纯 Markdown 形式存放在 [`rules/`](rules/)，可作为任意 LLM 的 system prompt 片段使用。

> **路线图**：Stop 钩子深度文件声明验证（"我修改了 X" → 验 mtime / git diff）、rolling-patch PreToolUse 硬拦截（rule 09 第二轴）、SessionStart 上的自动 GC、`prompts/` 的英文镜像。

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
- 变更日志与路线图 → [`CHANGELOG.md`](CHANGELOG.md)
