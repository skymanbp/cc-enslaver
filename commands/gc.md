---
description: 列出（或删除）超过 N 天未被触碰的 cc-enslaver 会话状态文件。默认 dry-run（仅打印），加 --apply 才真正删除。
argument-hint: "[--apply] [--older-than DAYS]   (默认 dry-run + 30 天)"
---

# /cc-enslaver:gc

> 长期使用插件后，`${CLAUDE_PLUGIN_DATA}/sessions/` 下会累积每会话一个 JSON
> 状态文件。每个文件几 KB，但数量积起来值得清理。本命令调用
> [`hooks/scripts/gc_state.py`](hooks/scripts/gc_state.py) 按 mtime 阈值
> 列出 / 删除老旧 state。

## 安全默认

**默认 `--dry-run` 模式**（只打印不删除）。要真正删除必须显式加 `--apply`。
mtime 是最近一次 `state_lib.add_read` 的时间戳；30 天没活动的几乎肯定
是已死会话。

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
- `--dry-run` / `--apply`：互斥，必须传一个。无参数默认走 `--dry-run`。
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
