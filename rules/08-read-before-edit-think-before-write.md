---
id: "08"
title: "改前必读，写前必想"
severity: must
---

# 规则 08 — 改前必读，写前必想（read-before-edit · think-before-write）

## 原则

> **"改"和"写"必须分别被前置纪律约束。**
>
> - **改前必读** — 任何 `Edit` 之前，必须**完整 Read** 目标文件、`Read` 其调用点上下文、`Grep` 影响面。
> - **写前必想** — 任何 `Edit` / `Write` 之前，必须在思维链或最终回复里**显式回答**"我为什么这样写"（根因 + 影响 + 方案对比）。

rule 04 已经规定了"完整阅读"；rule 02 已经规定了"七问"。rule 08 把它们**合并为一条修改前置硬纪律**，并附**物理强制**（hooks）：

- `PreToolUse(Read|Edit|Write)` 已强制"目标已 Read"才允许 Edit/Write（v0.3.2+）。
- `PreToolUse(Edit|Write)` 内容层检测"补丁标记"（rule 09）。
- **Stop hook layer (e)** 在收尾时检查：本轮如果做过 `Edit`/`Write`，最终回复中**必须有"系统式自答"标记**（根因 / 影响 / 方案 至少 3 个 rule-02 七问关键词）—— 否则 block。

## 必须做（MUST）

### 改前（read-before-edit）

1. **完整 Read 目标文件** — 不是 diff 上下文、不是 grep 命中行，是**整个文件**。文件过大时分段读完所有相关函数/区段。
2. **完整 Read 调用点** — `Grep` 找到目标符号被引用的所有位置，对每个引用点 `Read` 至少前后 20 行上下文。
3. **完整 Read 同步文件** — 修改 rules/*.md → 必须同时 Read `prompts/`、`commands/`、`docs/ARCHITECTURE.md` §8 表格里列出的所有连带文件。
4. **核对当前状态而非记忆** — 上次会话读过的版本可能已变；Edit 前确认本会话已 Read 当前内容。

### 写前（think-before-write）

任何 `Edit` / `Write` 提交前，**在思维链或最终回复中显式回答**：

1. **根因** — 我为什么要做这次修改？问题/需求的机理是什么？（rule 02 第 3 问）
2. **架构定位** — 待改部分在架构哪个区域？职责是什么？（rule 02 第 1-2 问）
3. **方案触底** — 我的修改是否真的从底层解决问题？还是只是掩盖症状？（rule 02 第 4 问）
4. **连带影响** — 哪些下游/调用点/测试需要同步改？（rule 02 第 5 问）
5. **风险** — 可能破坏哪些既有不变量、合约、测试？（rule 02 第 6 问）
6. **方案对比** — 我考虑过哪些替代方案？为什么选这个？

> 上述任意一项答 **"不知道 / 凭感觉 / 应该是"** → **先 Read / Grep / 验证**，再回到本规则。

## 物理强制（hooks）

| 阶段 | 钩子 | 触发条件 | 动作 |
|---|---|---|---|
| 改前 | `PreToolUse(Edit\|Write)` | 目标文件存在但本会话未 Read | **DENY**（v0.3.2 read_guard） |
| 写前（new_string 内容层） | `PreToolUse(Edit\|Write)` | new_string 含未注释的 `try:...except:pass` / `# noqa` / `@ts-ignore` 等补丁标记 | **DENY**（v0.11 patch-style detector，参见 rule 09） |
| 写后收尾 | `Stop` layer (e) | 本轮 `turn_count == last_edit_turn` 但 last assistant message 缺"系统式自答"标记（< 3 个 rule-02 关键词）| **BLOCK**（v0.11） |

## 禁止做（MUST NOT）

- ❌ **看到 grep 命中就改**：grep 是定位工具，不是理解工具。
- ❌ **凭记忆改**："上次会话里我读过" / "我记得这里是这样写的" ≠ "本会话已经 Read 过当前内容"。
- ❌ **不读连带文件就改**：改 `rules/0X-*.md` 但没读 `prompts/` 与 `docs/RULES.md`，会立即破坏同步契约。
- ❌ **写完不答"为什么"**：交出 `Edit` / `Write` 时，思维链或最终回复里没有根因 / 影响 / 方案的显式记录，违反"写前必想"。
- ❌ **绕过 read_guard 的 DENY 然后用 register_read 注册一个并未真读的文件**：这违背 hash 闸门设计本意，参见 [`../docs/ARCHITECTURE.md`](../docs/ARCHITECTURE.md) §2 read-cache escape hatch。

## 与其他规则的关系

| 关系 | 说明 |
|---|---|
| 08 vs 04 | 04 描述"完整阅读"的语义层要求；08 是其**前置物理强制**入口（read-before-edit 钩子）。 |
| 08 vs 02 | 02 是修改前的"七问"完整版；08 是其**最低必答子集**（六问），并把"必须显式记录"硬性化。 |
| 08 vs 09 | 08 解决"改之前/写之前要走完前置纪律"；09 解决"改的内容本身不能是补丁式"。两者前置 / 内容两轴互补。 |
| 08 vs 06 | 06 是改完后的收敛验证；08 是改之前的准备纪律。`修改前 → 修改中 → 修改后` 三段都被规则覆盖。 |
| 08 vs 07 | 07 在收尾验"用户要的全做了吗"；08 在前置验"我为这次改进做的准备够吗"。 |

## 自检触发器

下列任一情况出现，agent 必须主动自检本规则：

- 即将 `Edit` 一个本会话**未 Read 过完整内容**的文件；
- 即将 `Edit` 但**没** Grep 影响面 / 没读调用点；
- 即将提交 `Edit` 但思维链里**没有写明根因 + 影响 + 方案**；
- 改 `rules/*.md` 但没 Read `prompts/session-start.md` 与 `prompts/user-prompt.md`；
- 改 hook 脚本但没 Read `hooks/hooks.json`、`docs/ARCHITECTURE.md` §8、对应 `tests/test_*.py`；
- 即将做"快速修复"且 < 5 行（容易跳过前置纪律）。

## 终止条件

只有当下面**全部**成立时，才允许 `Edit` / `Write`：

1. 目标文件本会话已 `Read`（read_guard 不 DENY）；
2. 所有调用点 / 连带文件已 Read（人工自查 + Stop layer (e) 兜底）；
3. 思维链或最终回复中已显式回答根因 / 架构定位 / 方案触底 / 连带 / 风险 / 方案对比中**至少 3 项**；
4. new_string 中无补丁式标记（参见 rule 09 物理拦截）。

否则 → **未达"改前必读 / 写前必想"**，回到 Read / Grep / 验证步骤。
