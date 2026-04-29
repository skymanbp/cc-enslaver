---
id: "00"
title: "规则索引"
severity: info
---

# anti-laziness 规则索引

> 本文件是 [`rules/`](.) 目录下所有规则的**程序可读索引**。
> 钩子脚本与子代理依靠它发现可加载的规则。
>
> 规则的人类可读说明见 [`../docs/RULES.md`](../docs/RULES.md)。

## 规则清单

| ID  | 文件                                  | 标题                  | severity |
|----:|---------------------------------------|-----------------------|----------|
| 01  | `01-verify-dont-guess.md`             | 验证而非猜测           | must     |
| 02  | `02-systematic-not-reactive.md`       | 系统式而非反应式       | must     |
| 03  | `03-root-cause.md`                    | 修根因，不修症状       | must     |
| 04  | `04-full-context.md`                  | 完整阅读，拒绝关键词依赖 | must     |
| 05  | `05-cite-sources.md`                  | 引用必须可追溯         | must     |
| 06  | `06-verify-convergence.md`            | 验证收敛               | must     |

## 编号规则

- 编号格式 `<两位数>-<kebab-case>.md`；
- 一旦发布**永不复用**编号；
- 废弃的规则保留文件，frontmatter 加 `status: deprecated` 字段。
