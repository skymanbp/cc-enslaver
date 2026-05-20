# Rule Catalog

> 索引版本。每条规则的**完整正文**位于 [`../rules/`](../rules/) 目录下；
> 本文档仅做摘要、severity、关联组件指引。
>
> 修改任意一条规则时，请按 [`../docs/ARCHITECTURE.md`](./ARCHITECTURE.md) §8
> 表格同步检查所有连带文件。

## 语言

- **中文（canonical）** — [`../rules/01-*.md` ~ `../rules/09-*.md`](../rules/)。所有钩子注入（`prompts/`）、命令、skill 都基于中文。
- **English mirror（v0.6.2 + v0.11）** — [`../rules/en/`](../rules/en/)。best-effort 翻译，与中文 1-1 对应；如出现 drift，中文版优先。供非 CJK 读者 / 非 Claude agent system prompt 使用。

---

## 规则编号约定

- 编号格式：`<两位数>-<kebab-case-名>.md`
- 编号一旦发布**不再回收**（即使规则被废弃，也不复用编号）。
- 当前编号区间：`01–09`。

---

## 规则一览

| ID  | 标题 | Severity | 完整文件 | 主要适用场景 |
|----:|------|---------|----------|--------------|
| 01 | 验证而非猜测 | **must** | [`../rules/01-verify-dont-guess.md`](../rules/01-verify-dont-guess.md) | 任何关于文件、API、版本、文献、报错信息的断言 |
| 02 | 系统式而非反应式 | **must** | [`../rules/02-systematic-not-reactive.md`](../rules/02-systematic-not-reactive.md) | 修 bug、改架构、重构、添加功能 |
| 03 | 修根因，不修症状 | **must** | [`../rules/03-root-cause.md`](../rules/03-root-cause.md) | 异常处理、测试失败、CI 失败、竞态、钩子失败 |
| 04 | 完整阅读，拒绝关键词依赖 | **must** | [`../rules/04-full-context.md`](../rules/04-full-context.md) | 编辑文件前、跨文件影响分析 |
| 05 | 引用必须可追溯 | **must** | [`../rules/05-cite-sources.md`](../rules/05-cite-sources.md) | 任何对外陈述（PR 描述、回复用户、报告） |
| 06 | 验证收敛 | **must** | [`../rules/06-verify-convergence.md`](../rules/06-verify-convergence.md) | 任何修复 / 更新 / 补丁完成后的强制收敛验证 |
| 07 | 任务忠实 | **must** | [`../rules/07-task-fidelity.md`](../rules/07-task-fidelity.md) | 任何任务声称完成前的请求覆盖、无降级、无遗漏二次确认 |
| 08 | 改前必读，写前必想 | **must** | [`../rules/08-read-before-edit-think-before-write.md`](../rules/08-read-before-edit-think-before-write.md) | 任何 `Edit` / `Write` 前的前置硬纪律（v0.11 物理强制）|
| 09 | 系统式修改，禁止打补丁 | **must** | [`../rules/09-systematic-modification.md`](../rules/09-systematic-modification.md) | 修改过程中的反补丁内容拦截（v0.11 物理强制）|

---

## Severity 等级

| Severity | 含义 |
|----------|------|
| **must** | 强制规则。违反即被视为"偷懒"。当前所有规则均为此级别。 |
| should   | 强烈建议；除非有明确理由，否则遵守。（v0.1 暂未启用） |
| info     | 信息性提醒；agent 应了解但无强制义务。（v0.1 暂未启用） |

---

## 规则之间的关系

```
            01 验证                      05 引用
              │                            │
              ▼                            ▼
       ┌──────────────────────────────────────┐
       │   04 完整阅读                          │
       └─────────────────┬────────────────────┘
                         │
                         ▼
       ┌──────────────────────────────────────┐
       │   02 系统式思维                        │
       └─────────────────┬────────────────────┘
                         │
                         ▼
       ╔══════════════════════════════════════╗
       ║ 08 改前必读 / 写前必想（前置硬纪律 · 物理强制）║
       ╚═════════════════┬════════════════════╝
                         │
                         ▼
       ┌──────────────────────────────────────┐
       │   03 修根因                            │
       └─────────────────┬────────────────────┘
                         │
                         ▼
       ╔══════════════════════════════════════╗
       ║ 09 系统式修改 / 反补丁（内容硬纪律 · 物理强制）║
       ╚═════════════════┬════════════════════╝
                         │
                         ▼
       ┌──────────────────────────────────────┐
       │   06 验证收敛                          │
       └─────────────────┬────────────────────┘
                         │
                         ▼
       ┌──────────────────────────────────────┐
       │   07 任务忠实                          │
       └──────────────────────────────────────┘
```

- **01 / 04 / 05** 是**输入端**约束：决定 agent 如何获取与陈述事实。
- **02** 是**思考过程**约束：决定 agent 如何把事实组织成方案。
- **08** 是**修改前置硬纪律**：把 04 + 02 折叠成 `Edit` / `Write` 之前的最低必答清单，并由 PreToolUse + Stop layer (e) 物理强制（v0.11）。
- **03** 是**输出端 (改什么)** 约束：决定 agent 修改代码时是否触达根因。
- **09** 是**输出端 (怎么改)** 约束：把 03 的"反偷懒"升级为修改内容层的硬纪律，由 PreToolUse new_string 内容检测 + Stop layer (f) 物理强制（v0.11）。
- **06** 是**输出端 (改完之后 · 技术面)** 约束：决定 agent 是否真的把根因解决到收敛、是否经得起验证。
- **07** 是**输出端 (改完之后 · 契约面)** 约束：决定 agent 是否把用户**要求的全部**按**原标准**交付（无遗漏、无降级、无范围溢出）。06 与 07 互补：06 解决"症状-根因"轴，07 解决"请求-交付"轴。
- **08 与 09 互补**：08 是修改**前**的"准备充分了吗"，09 是修改**内容**的"姿势对了吗"。08 在 PreToolUse 的"已读检查"上 + Stop layer (e) 的"系统式自答"上落地；09 在 PreToolUse 的"new_string 内容检测"上 + Stop layer (f) 的"根因 + 影响 + 方案三件套"上落地。

---

## 各组件如何引用这些规则

| 组件 | 引用方式 |
|------|---------|
| [`../prompts/session-start.md`](../prompts/session-start.md) | 全部 9 条规则的浓缩版（v0.11 加入 rule 08 / 09 + 标准回答骨架） |
| [`../prompts/user-prompt.md`](../prompts/user-prompt.md) | 9 条规则的结构化每轮自检清单（v0.11 重构）|
| [`../commands/checklist.md`](../commands/checklist.md) | 把 9 条规则映射成可勾选的检查项（A 改前 / B 改后 / C 收敛验证 / D 任务忠实 / E 改前必读·写前必想 / F 系统式修改） |
| [`../agents/verifier.md`](../agents/verifier.md) | 主要执行规则 05（引用可追溯）+ 规则 01 的事后验证；同时尊重规则 07 + 08 |
| [`../skills/systematic-debug/SKILL.md`](../skills/systematic-debug/SKILL.md) | 主要执行规则 02 + 03 + 06 + 08 + 09 |
| [`../hooks/scripts/read_guard.py`](../hooks/scripts/read_guard.py) | 规则 04 + 08（read-before-edit）+ 规则 09（new_string 补丁标记物理拦截）|
| [`../hooks/scripts/bash_guard.py`](../hooks/scripts/bash_guard.py) | 规则 03 + 09（bypass 模式拦截）|
| [`../hooks/scripts/stop_guard.py`](../hooks/scripts/stop_guard.py) | 规则 06 layer (a)(c) + 规则 01 layer (b) + 规则 07 layer (d) + 规则 08 layer (e) + 规则 09 layer (f) |

---

## 添加新规则的流程

1. 在 [`../rules/`](../rules/) 下创建 `10-xxx.md`（v0.11 起编号区间是 01–09，新规则从 10 开始）。
2. 文件必须包含 YAML frontmatter（参考现有任意规则的开头）：
   ```yaml
   ---
   id: "10"
   title: "<规则标题>"
   severity: must
   ---
   ```
3. 同步更新：
   - 本文档（`docs/RULES.md`）的"规则一览"表格 + "规则之间的关系"图
   - [`../prompts/session-start.md`](../prompts/session-start.md)
   - [`../prompts/user-prompt.md`](../prompts/user-prompt.md)
   - [`../commands/checklist.md`](../commands/checklist.md) 的检查项
   - [`../rules/00-index.md`](../rules/00-index.md) 程序可读索引（中 + 英）
   - 视情况：物理强制层（hooks/scripts/ + tests/）
4. 在 [`../CHANGELOG.md`](../CHANGELOG.md) "Unreleased" 段记录新增规则。
