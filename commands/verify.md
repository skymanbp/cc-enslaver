---
description: 让 agent 重新核对最近回复中的所有 file:line 引用与事实性陈述，并报告漂移/缺失。
argument-hint: "[要核对的回复编号或'last'(默认)]"
---

# /anti-laziness:verify

> 触发独立验证流程。要求 receiving agent 把"自己刚才说过的话"当作不可信输入重新核对。

## 你（receiving agent）要做的事

针对最近一次回复中**所有**事实性陈述，逐条执行下列流程：

### 第 1 步 · 列出所有"声明"

提取最近回复中的每一条**事实性断言**，并按下面四类分桶：

1. **代码位置断言**（如 "auth.py:142 加了锁"）
2. **代码行为断言**（如 "调用 X 会触发 Y"）
3. **外部资源断言**（如 "PEP 484 规定…"、"该库版本 1.2.0 引入了…"）
4. **运行结果断言**（如 "测试通过"、"命令输出 …"）

### 第 2 步 · 逐条核对

| 类别 | 核对方式 |
|------|---------|
| 代码位置 | 委派 `verifier` 子代理 (`Agent` tool, subagent_type="verifier") 重读 `file:line` 并比对内容 |
| 代码行为 | `Read` 完整函数 + 调用链；如必要 `Grep` 调用方；不能仅凭函数名推断 |
| 外部资源 | 如有 URL：`WebFetch`；如有 DOI/章节：用户授权后访问；不能凭记忆 |
| 运行结果 | **重新运行同样的命令**并粘贴新输出；不能复述"上次运行的结果" |

### 第 3 步 · 报告

输出一份结构化报告：

```
## Verify report

### 代码位置（共 N 条）
- [✅ intact ] auth.py:142 — 内容与声明一致 (verifier 已确认)
- [⚠ drift  ] session.py:88 — 行号已变成 91 (代码近期被修改)
- [❌ missing] db.py:200 — 文件只有 178 行

### 代码行为（共 M 条）
- [✅ verified] login(...) 确实在失败时抛 AuthError (auth.py:155-160)
- [❓ unverified] "session_token 全局唯一" 这一断言我无法在代码中找到证据 — 撤回该断言

### 外部资源（共 K 条）
- [✅ verified] PEP 484 §"Type aliases" 确实如所述
- [❌ guessed] "redis-py 5.0 默认开启 connection pooling" — 我没有验证；撤回

### 运行结果（共 L 条）
- [✅ rerun] pytest tests/test_auth.py: 21 passed (粘贴新输出)
- [⚠ stale] 我之前说"npm test 通过"，但本次重跑前我没有再次确认 — 现在重跑：[结果]
```

### 第 4 步 · 修正

报告里任何 **drift / missing / unverified / guessed / stale** 条目：

- 如果是事实错误 → 立即在后续回复中**明确撤回**并提供正确版本；
- 如果是行号漂移 → 给出新行号；
- 如果原本就无法验证 → 明确说明"该断言无法验证，撤回"。

---

## 禁止行为

- ❌ 把 `/anti-laziness:verify` 当成形式主义、所有条目都标 ✅ 而不真做工具调用。
- ❌ 用"我相信刚才说的没问题"当作核对结果。
- ❌ 跳过"重新运行命令"那一步。

> 详见 `rules/01-verify-dont-guess.md` 与 `rules/05-cite-sources.md`。
