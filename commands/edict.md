---
description: 管理 cc-enslaver 圣旨（用户自定义硬规则；项目级 + 全局；list / add / remove / reload / path）。
argument-hint: "list | add ID \"TEXT\" [--must|--should] [--deny-edit REGEX]* [--deny-bash REGEX]* [--note ...] [--global] | remove ID [--global] | reload | path"
---

# /cc-enslaver:edict

> 圣旨 = 用户为本项目自定义的硬规则，优先级高于通用 9 条。
> 默认文件：`${CLAUDE_PROJECT_DIR}/.claude/cc-enslaver/edicts.toml`（项目级，可入 git 团队共享）。
> `--global`（v0.14）：写入 `~/.claude/cc-enslaver/edicts.toml`（个人全局，跨项目生效）。

## 子命令

| 子命令 | 行为 |
|---|---|
| `list` | 列出当前所有圣旨（来源文件 / id / severity / 硬拦截规则数）。优先 project，无则 fallback 到 global |
| `add ID "TEXT" [...]` | 追加一条圣旨。默认 `--must`，支持 `--deny-edit` / `--deny-bash` 多次 + `--note` + `--global` |
| `remove ID [--global]` | 删除圣旨。默认先找 project 再 fallback global；`--global` 限定只删 global 文件 |
| `reload` | 重读并打印当前生效圣旨（验证配置） |
| `path` | 打印 edicts.toml 实际/将创建的路径 |

## 用法（agent 应当如此执行）

请把用户的 `$ARGUMENTS` 传给 manage_edicts.py：

```bash
python "${CLAUDE_PLUGIN_ROOT}/hooks/scripts/manage_edicts.py" $ARGUMENTS
```

执行后向用户报告：
1. 该操作是否成功；
2. 圣旨文件路径；
3. 当前生效圣旨数量与 id 列表（运行 `list` 子命令获取）。

## 示例

```
/cc-enslaver:edict list
/cc-enslaver:edict add E01 "禁止使用 mongoose，统一用 prisma" --must --deny-edit 'from\s+["'"'"']mongoose["'"'"']' --deny-bash 'npm\s+(i|install)\s+mongoose'
/cc-enslaver:edict add E02 "所有 API 必须经过 src/api/client.ts" --should --note "见 PR #142"
/cc-enslaver:edict add G01 "永不 sudo rm -rf root paths" --must --global --deny-bash 'rm\s+-rf?\s+/'
/cc-enslaver:edict remove E01
/cc-enslaver:edict path
```

## 设计契约

- **必须（must）**：违反即被 `PreToolUse(Edit|Write|Bash)` 物理 DENY。
- **建议（should）**：仅注入软提醒，不 DENY。
- 圣旨**不能**绕过插件内置的 9 条规则；内置守卫先跑、圣旨后跑。
- 文件改动**即时生效**（hooks 每次重读）。

完整设计 → [`docs/EDICTS.md`](docs/EDICTS.md)。
