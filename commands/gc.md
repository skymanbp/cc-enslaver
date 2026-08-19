---
description: 列出（或删除）超过 N 天未被触碰的 cc-enforcer 会话状态文件。本命令默认替你传 --dry-run（仅打印），加 --apply 才真正删除；脚本本身要求 --dry-run / --apply 恰好传一个。
argument-hint: "[--apply] [--older-than DAYS]   (本命令默认补 --dry-run + 30 天)"
---

# /cc-enforcer:gc

> 长期使用插件后，`${CLAUDE_PLUGIN_DATA}/sessions/` 下会累积每会话一个 JSON
> 状态文件。每个文件几 KB，但数量积起来值得清理。本命令调用
> [`hooks/scripts/gc_state.py`](hooks/scripts/gc_state.py) 按 mtime 阈值
> 列出 / 删除老旧 state。

## 安全默认

**本命令默认替你补 `--dry-run`**（只打印不删除），要真正删除必须显式改成
`--apply`。注意"默认"只存在于本命令这一层：`gc_state.py` 自己要求
`--dry-run` / `--apply` **恰好传一个**，一个都不传（或两个都传）它会打印
`gc_state: pass exactly one of --dry-run or --apply` 并 exit 1，而不是退回
dry-run —— 无标志时永不删除，是靠"拒绝执行"实现的。
mtime 是该会话状态**最近一次被写入**的时间戳 —— 不只是 Read：记录编辑、
Stop 拦截、滚动补丁计数、mtime 基线、同步 ack 等九个以上的 mutator 都会
刷新它。所以一个只改文件、不读新文件的会话同样是"活跃"的。30 天没有任何
写入的，几乎肯定是已死会话。

## 你（receiving agent）要做的

按用户传入的参数构造 Bash 调用：

```bash
python "${CLAUDE_PLUGIN_ROOT}/hooks/scripts/gc_state.py" --dry-run --older-than 30
```

或：

```bash
python "${CLAUDE_PLUGIN_ROOT}/hooks/scripts/gc_state.py" --apply --older-than 30
```

参数解释：
- `--dry-run` / `--apply`：互斥，且**必须恰好传一个**；都不传 → exit 1（不是
  隐式 dry-run）。用户没说要删时，本命令替他传 `--dry-run`。
- `--older-than DAYS`：阈值（天数）。默认 30。

## 输出契约

脚本始终打印：

```
state_dir: <path>
scanned:   <N>
threshold: <M> days
eligible:  <K>
  [dry-run] would delete: <name>  (<age>d old, <size>B)   |   deleted: <name>
  ...
deleted: <K>     |   would delete: <K>
bytes_freed: <B> |   would free: <B>B
```

## 用户场景

```
用户："/gc 看看"          → dry-run, 默认 30 天
用户："/gc 看看 90 天的"   → dry-run, --older-than 90
用户："/gc 真的删 30 天的" → --apply --older-than 30
```

如果 `eligible` 为 0 → 报告 "nothing to do" 即可。

## 禁止

- ❌ 不传任何参数就直接 `--apply` —— 始终先 dry-run 让用户看清楚再问。
- ❌ 删除 `${CLAUDE_PLUGIN_DATA}/sessions/` 之外的任何文件 —— 脚本本身有
  这道防线（只 glob `<state_dir>/*.json`），不要绕过它。

## 自动 GC（v0.18 · opt-in）

设置环境变量 `CC_ENFORCER_AUTO_GC_DAYS=N`（正整数）即可让 SessionStart
钩子在每次开会话时自动删除 ≥ N 天未触碰的 state 文件。受 24h 速率限制
（marker 文件 `<state_dir>/_auto_gc.json`），不会每次开会话都重扫。

```bash
# Bash / Linux / macOS
export CC_ENFORCER_AUTO_GC_DAYS=30

# PowerShell
$env:CC_ENFORCER_AUTO_GC_DAYS = "30"
[Environment]::SetEnvironmentVariable("CC_ENFORCER_AUTO_GC_DAYS", "30", "User")  # 持久化
```

未设置 / 设为 `0` / 设为非数字 → 自动 GC 完全禁用（默认）。失败 →
silent stderr，永不阻塞 SessionStart 注入。`/cc-enforcer:gc` 手动命令
仍然完全可用，两个入口共用同一份 `prune_old_sessions()`。
