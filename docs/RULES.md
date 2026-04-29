# Rule Catalog

> 索引版本。每条规则的**完整正文**位于 [`../rules/`](../rules/) 目录下；
> 本文档仅做摘要、severity、关联组件指引。
>
> 修改任意一条规则时，请按 [`../docs/ARCHITECTURE.md`](./ARCHITECTURE.md) §8
> 表格同步检查所有连带文件。

---

## 规则编号约定

- 编号格式：`<两位数>-<kebab-case-名>.md`
- 编号一旦发布**不再回收**（即使规则被废弃，也不复用编号）。
- 当前编号区间：`01–06`。

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
       ┌──────────────────────────────────────┐
       │   03 修根因                            │
       └─────────────────┬────────────────────┘
                         │
                         ▼
       ┌──────────────────────────────────────┐
       │   06 验证收敛                          │
       └──────────────────────────────────────┘
```

- **01 / 04 / 05** 是**输入端**约束：决定 agent 如何获取与陈述事实。
- **02** 是**思考过程**约束：决定 agent 如何把事实组织成方案。
- **03** 是**输出端 (改什么)** 约束：决定 agent 修改代码时是否触达根因。
- **06** 是**输出端 (改完之后)** 约束：决定 agent 是否真的把根因解决到收敛、是否经得起验证。

---

## 各组件如何引用这些规则

| 组件 | 引用方式 |
|------|---------|
| [`../prompts/session-start.md`](../prompts/session-start.md) | 全部 6 条规则的浓缩版 |
| [`../prompts/user-prompt.md`](../prompts/user-prompt.md) | 6 条规则的一行式提醒 |
| [`../commands/checklist.md`](../commands/checklist.md) | 把 6 条规则映射成可勾选的检查项（A 改前 / B 改后 / C 收敛验证） |
| [`../agents/verifier.md`](../agents/verifier.md) | 主要执行规则 05（引用可追溯）+ 规则 01 的事后验证 |
| [`../skills/systematic-debug/SKILL.md`](../skills/systematic-debug/SKILL.md) | 主要执行规则 02 + 03 + 06 |

---

## 添加新规则的流程

1. 在 [`../rules/`](../rules/) 下创建 `07-xxx.md`，保留前 6 条编号不变。
2. 文件必须包含 YAML frontmatter（参考现有任意规则的开头）：
   ```yaml
   ---
   id: "07"
   title: "<规则标题>"
   severity: must
   ---
   ```
3. 同步更新：
   - 本文档（`docs/RULES.md`）的"规则一览"表格 + "规则之间的关系"图
   - [`../prompts/session-start.md`](../prompts/session-start.md)
   - [`../prompts/user-prompt.md`](../prompts/user-prompt.md)
   - [`../commands/checklist.md`](../commands/checklist.md) 的检查项
   - [`../rules/00-index.md`](../rules/00-index.md) 程序可读索引
4. 在 [`../CHANGELOG.md`](../CHANGELOG.md) "Unreleased" 段记录新增规则。
