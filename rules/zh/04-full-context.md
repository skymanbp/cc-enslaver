---
id: "04"
title: "完整阅读，拒绝关键词依赖"
severity: must
---

# 规则 04 — 完整阅读，拒绝关键词依赖

## 原则

编辑或编写新内容前，**必须真实探索整个相关架构、完整阅读所有相关文件**。

- 关键词检索（`Grep`）的作用是 **定位**，不是 **理解**。
- 找到匹配后必须 `Read` 上下文，否则等于盲改。
- 记忆是**过去某时刻的快照**；当前文件状态才是权威。

## 必须做（MUST）

修改任何文件前：

1. `Read` 该文件**完整内容**（除非文件 > 2000 行，此时分段读完所有相关函数/区段）。
2. 用 `Grep` 找出文件被引用的所有位置（导入、调用、字符串匹配）。
3. 对所有调用点 `Read` 上下文（至少前后 20 行）。
4. 对配置/manifest 文件，读取**整个 JSON/YAML**，理解每个 key 的作用。
5. 对修改新文件中已存在的概念（变量名、函数名、类名）：先 grep 全仓库，确认命名约定。

## 禁止做（MUST NOT）

- ❌ 只看 diff 上下文就开始改（diff 上下文 ≠ 文件全貌）。
- ❌ 看到 grep 命中第一行就动手（没看到第二行可能是函数定义、第三行是反例）。
- ❌ 凭"上次会话里我读过"作为不重读的理由（当前状态可能已变）。
- ❌ 只读 README / 注释，不读源码本身（注释可能过时）。

## 例子：grep + 完整阅读

**反面：只 grep**
```
> grep "session_token" src/
src/auth.py:42:    session_token = generate_token()
> 在 src/auth.py:42 上加锁
```
这是错的：不知道 `session_token` 在文件其他位置如何被使用，
不知道有没有 `tests/test_auth.py` 在依赖这个行为。

**正面：grep → 完整 Read → 影响分析**
```
> grep -rn "session_token" .
src/auth.py:42:    session_token = generate_token()
src/auth.py:88:    return session_token
src/session.py:14:    def store(self, session_token): ...
tests/test_auth.py:55:    assert session_token in cache
> Read src/auth.py 全文
> Read src/session.py 全文
> Read tests/test_auth.py 与 session_token 相关的整块
> 综合 4 处用法后再决定如何修改
```

## 自检触发器

下列任一情况出现，agent 应主动自检本规则：

- 即将 `Edit` 一个本会话**未 Read** 过的文件；
- 即将引用一个本会话**未 Grep** 过的符号；
- 即将基于"上次会话的记忆"做修改而未重新读取；
- 看到 grep 结果只浏览了文件名/行号，未读上下文。
