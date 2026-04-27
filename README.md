# anti-laziness

> A Claude Code plugin and LLM-agnostic rule pack that **eliminates lazy AI behavior** — reactive patches, guessed citations, surface-level "fixes", half-finished work — by enforcing systematic thinking, verification, and root-cause analysis at every layer of the agent loop.

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Plugin Version](https://img.shields.io/badge/version-0.1.0-blue.svg)](CHANGELOG.md)
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

`anti-laziness` ships a **layered defense** against all six:

1. **Soft layer (prompt injection)** — at session start and before every user prompt, the plugin injects a concise reminder of the discipline rules into the agent's context.
2. **Active layer (slash commands)** — `/anti-laziness:checklist` and `/anti-laziness:verify` let the user (or the agent itself) trigger a structured checklist or independent verification pass on demand.
3. **Subagent layer** — the `verifier` subagent independently re-reads any file:line citations the agent has produced and reports whether they're real.
4. **Skill layer** — `systematic-debug` auto-invokes when debugging language is detected, forcing a root-cause walk-through before any fix is proposed.
5. **LLM-agnostic core** — every rule lives as plain Markdown in [`rules/`](rules/), so the same discipline pack works as a system-prompt fragment for ChatGPT, Gemini, local models, or anything else.

> **Future (not yet in v0.1):** hard-layer `PreToolUse` blocks — e.g., reject an `Edit` call against a file the agent has not `Read` in this session.

---

## Repository structure

```
anti-laziness/
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
├── commands/                    # /anti-laziness:checklist, /anti-laziness:verify
├── agents/verifier.md           # Independent citation verifier subagent
└── skills/systematic-debug/     # Auto-invoked debug discipline skill
```

See [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) for a layer-by-layer walkthrough.

---

## Installation

### As a Claude Code plugin (recommended)

```bash
# 1) Clone this repo somewhere
git clone https://github.com/skymanbp/agent-rigor.git ~/.claude/plugins/anti-laziness

# 2) In Claude Code, add the plugin via your settings or marketplace mechanism.
#    The manifest is at .claude-plugin/plugin.json — Claude Code will discover it.
#    Note: the GitHub repo is `agent-rigor`, but the plugin's internal name is
#    `anti-laziness` (as declared in plugin.json), so slash commands surface as
#    `/anti-laziness:<command>`.
```

> Hook scripts require `python` on PATH. The plugin is tested with Python 3.13.

### As a rule pack for any other LLM

You don't need Claude Code at all. The actual rules live in [`rules/`](rules/) as plain Markdown.

```bash
# Concatenate every rule into one system-prompt blob:
cat rules/*.md > /tmp/anti-laziness.txt
# Then feed that to your agent of choice as system prompt / pre-context.
```

For specific integration patterns (OpenAI, Gemini, local llama.cpp, etc.) see the **LLM portability** section in [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).

---

## How it works

### Hooks injected (Claude Code only)

| Event | What gets injected | Source |
|---|---|---|
| `SessionStart` | Full discipline summary | [`prompts/session-start.md`](prompts/session-start.md) |
| `UserPromptSubmit` | Compact pre-turn reminder | [`prompts/user-prompt.md`](prompts/user-prompt.md) |

Both hooks call the same Python script with a different `--event` argument:

```bash
python "${CLAUDE_PLUGIN_ROOT}/hooks/scripts/inject_context.py" --event SessionStart
```

The script reads the corresponding prompt file and emits Claude Code's expected
`hookSpecificOutput.additionalContext` JSON. It is the only piece of executable
code in the plugin — everything else is declarative Markdown/JSON.

### User-invokable

| Surface | Purpose |
|---|---|
| `/anti-laziness:checklist` | Print the pre-action / pre-finish checklist on demand. |
| `/anti-laziness:verify`    | Ask the agent to re-verify recent claims with `file:line` citations. |
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

`anti-laziness` 是一个 **Claude Code 插件 + 任意 LLM 通用规则包**。它存在的唯一目的是：**杜绝 AI 编程助手的偷懒行为**。

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
2. **主动调用层**：`/anti-laziness:checklist`、`/anti-laziness:verify` 等 slash 命令。
3. **子代理验证层**：`verifier` 独立重读 agent 给出的 `file:line` 引用，检查是否真实。
4. **技能层**：`systematic-debug` 在 debug 语境下自动唤起，强制走根因分析流程。
5. **LLM-agnostic 核心**：所有规则以纯 Markdown 形式存放在 [`rules/`](rules/)，可作为任意 LLM 的 system prompt 片段使用。

> **未来版本将加入**：`PreToolUse` 硬性拦截（例如：未读过的文件不允许 Edit）。

### 安装

#### 作为 Claude Code 插件

把仓库放进 `~/.claude/plugins/anti-laziness`，Claude Code 会通过 `.claude-plugin/plugin.json` 自动识别。
钩子脚本需要 `python` 在 PATH 上（开发环境为 Python 3.13）。

#### 作为通用 LLM 规则包

```bash
cat rules/*.md > anti-laziness-rules.txt
```

把这段文本作为 system prompt 喂给任何 LLM 即可。

### 详细文档

- 设计原则与项目级指令 → [`CLAUDE.md`](CLAUDE.md)
- 架构说明 → [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md)
- 完整规则目录 → [`docs/RULES.md`](docs/RULES.md)
- 变更日志与路线图 → [`CHANGELOG.md`](CHANGELOG.md)
