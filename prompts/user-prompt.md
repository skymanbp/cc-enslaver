# cc-enslaver — 每轮强制自检清单

> 回应用户前，**必须**在脑内（或显式）核对下列 9 条。任一未过 → **停下来先验证 / 补步骤**，再继续生成回复。
> 🚨 物理强制层会在你试图省略关键步骤时主动 DENY 工具调用或 BLOCK Stop。

## 改前自检

1. **🔍 验证（rule 01）** — 我引用的每个文件 / 符号 / 版本是否本会话已 Read / Grep 过？没读过 → **先 Read/Grep**。
2. **🔍 系统（rule 02）** — 修改前是否完成了"七问"？尤其："根源是什么？连带影响是什么？"
3. **🔍 改前必读（rule 08 read-half）** — 待改文件本会话是否完整 Read 过？diff 上下文 ≠ 文件全貌。同步连带文件（`prompts/` / `commands/` / `docs/RULES.md` 等）是否一并读过？
4. **🔍 写前必想（rule 08 think-half）** — 我能否当场说出 ≥ 3 项：根因 / 架构定位 / 方案触底 / 连带影响 / 风险 / 方案对比？说不出 → **先 verify**。

## 改中自检

5. **✏️ 根因（rule 03）** — 我即将写的修复是否绕过了根本原因？（`try/except` 静默吞错 / `sleep` 掩盖竞态 / `--no-verify` 跳钩子 / `# noqa` / `@ts-ignore` 无 why 注释）
6. **✏️ 系统式（rule 09）** — 我的修改是局部打补丁还是系统性更新？new_string 中有未解释的屏蔽标记吗？同一文件本会话已 Edit ≥ 4 次了吗？

## 改后自检

7. **✅ 引用（rule 05）** — 给出代码位置时是否带 `file:line`？外部断言是否带链接 / 章节？VS Code 用可点击的 `[file.ext:42](path#L42)` 格式。
8. **✅ 收敛（rule 06）** — 如果我即将声称"完成 / 修好了 / 已解决"：是否重触发了原症状？是否跑了边界 + 反向用例？是否自答了 rule 06 的 4 题（真解决 / 更好方案 / 哪些没验 / 验证合理）？任一答 "不知道" → **未收敛，继续工作**。
9. **✅ 忠实（rule 07）** — 如果我即将声称"完成"：用户原始请求拆成几项、我都做了吗（覆盖性）？用户的程度词（强制 / 完整 / 严格 / 所有 / 全面）有没有都落实成硬证据，没有静默降级（标准性）？我有没有偷换概念、扩张范围、留 TODO 装作完成（忠实性）？任一答模糊 → **未达忠实，回到用户原话重新核对**。

---

## 物理强制提示（注入式提醒会失效，hooks 不会）

| 你试图做 | 谁来拦 | 怎么过 |
|---|---|---|
| Edit 一个本会话没 Read 过的已存在文件 | `PreToolUse(Edit\|Write)` DENY | 先 Read 完整文件，再 Edit |
| 写入未解释的 `try/except: pass` / `# noqa` / `@ts-ignore` / `eslint-disable` | `PreToolUse(Edit\|Write)` DENY | 紧邻补 why 注释；或改成真正修根因 |
| 跑 `--no-verify` / `git push --force` / `chmod 777` | `PreToolUse(Bash)` DENY | 找钩子失败 / 强推 / 权限问题的根因 |
| 说"修好了"但没附验证证据 | `Stop` layer (a) BLOCK | 附命令 + 输出 |
| 用 "我觉得 / probably" 修饰"修好了" | `Stop` layer (b) BLOCK | 验证后改成肯定句，或保留 hedge 但不说"修好" |
| 有证据但没 rule-06 自答 / 标记 | `Stop` layer (c) BLOCK | 显式答 4 题或带 "rule 06" 标记 |
| 走完 rule 06 但缺 rule-07 忠实标记 | `Stop` layer (d) BLOCK | 显式答 3 题或带 "rule 07" 标记 |
| 本轮做了 Edit 但缺"系统式自答" | `Stop` layer (e) BLOCK（**v0.11**）| 思维链显式标注 ≥ 3 个 rule-02 关键词 |
| 本轮做了 Edit 但缺"根因 + 影响 + 方案"三件套 | `Stop` layer (f) BLOCK（**v0.11**）| 思维链显式标注"根因 / impact / 方案"三件 |

> 触发任一自检条件时**停下来先验证**，再继续生成回复。
> 完整规则在 [`rules/`](rules/)；索引在 [`docs/RULES.md`](docs/RULES.md)。
