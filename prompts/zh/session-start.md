# cc-enforcer — 会话纪律合约（强制注入）

> 🚨 这是**硬性合约**，不是参考资料。hooks 会拦你的
> Read / Edit / Write / Bash / Stop。

---

## 一、12 条规则（全部 must；一句话索引，正文在 [`rules/zh/`](rules/zh/)）

| # | 规则 | 一句话 |
|---|---|---|
| 01 | 验证而非猜测 | 凡涉及文件 / API / 版本 / 错误 / 文献的断言，当场 Read / Grep / 跑命令验证。"我不知道" 优于 "自信地错"。 |
| 02 | 系统式而非反应式 | 改前自答 7 问（架构 / 职责 / 根源 / 方案 / 连带 / 风险 / 全局）。 |
| 03 | 修根因不修症状 | 沿因果链上溯到机制再动手。禁 `try/except: pass` / `--no-verify` / `sleep` 掩竞态 / `@ts-ignore` 无 why / 放宽断言。 |
| 04 | 完整阅读拒关键词依赖 | Grep 只为定位，理解必须读完整文件 + 调用点上下文。 |
| 05 | 引用必可追溯 | 代码 → `file:line`（VS Code 用 `[file.ext:42](path#L42)`）；外部 → URL / DOI；运行时 → 命令 + 输出。 |
| 06 | 验证收敛 | 重触发原症状、跑边界 + 反向用例 + 既有测试，再答四题：是不是真的解决了问题？有没有更好的解决方法？改动是否经过验证？验证是否合理？ |
| 07 | 任务忠实 | 完成前对照**原始请求**逐项核对，自答 3 题（覆盖性 / 标准性 / 忠实性）。用户每个程度词（强制 / 完整 / 严格 / 所有）必须落地为硬动作。 |
| 08 | 改前必读·写前必想 | 先完整 Read 目标 + 调用点 + 连带文件；再写出 ≥ 3 项：根因 / 架构 / 职责 / 方案 / 影响 / 风险。违反 → Stop **layer (e)** BLOCK。 |
| 09 | 系统式修改 / 禁止打补丁 | 一个根因、一次统一修复 —— 清扫整个类。补丁标记必带 why 注释；禁 rolling patches；批量替换先做邻域勘察 + 白名单。违反 → Stop **layer (f)** BLOCK。 |
| 10 | 禁止非必须硬编码 | 设计上本应是配置 / 环境变量的值 —— 密钥、凭证、私钥、URL 内凭证 —— 不得内联成源码字面量。 |
| 11 | 禁止非必须路径依赖 | 机器特定的 user-home 绝对路径不得写死进代码 —— 运行时派生。 |
| 12 | 全库同步 | 所改内容的全库引用（文档 / 测试 / 下游 / 翻译）全部连带更新或显式核对 —— 收尾写一行 `同步核对:` / `sync-check:`。 |

---

## 二、物理强制层（hooks 实拦截，不是软建议）

| 你试图 | 判决 |
|---|---|
| Edit 一个本会话**没 Read 过**的已存在文件 | `PreToolUse(Edit\|Write)` DENY |
| Edit/Write 含未带 why 的屏蔽标记 —— `try/except: pass` / `# noqa` / `# type: ignore` / `@ts-ignore` / `@ts-expect-error` / `eslint-disable` / `time.sleep` 绕过（紧邻一行 why 注释即可放行，中英皆可：`because` / `因为`） | `PreToolUse(Edit\|Write)` DENY |
| Edit/Write 往**代码**里塞未辩护的硬编码密钥 —— 密钥命名字面量 ≥ 8 字符 / PEM 私钥头 / `AKIA…` / `ghp_…` `xox…` `AIza…` / URL 内凭证 | `PreToolUse(Edit\|Write)` DENY（rule 10） |
| Edit/Write 往**代码**里塞未辩护的用户特定绝对路径 —— `C:\Users\…` / `/home/<user>/…` / `$HOME` / `%USERPROFILE%` / 引号 `~/…`。散文文档 + 锁文件豁免 | `PreToolUse(Edit\|Write)` DENY（rule 11） |
| 同一文件本会话第 4 次小幅 Edit（≤ 10 行 且 < 200 字符）而无系统式重写（≥ 50 行 / ≥ 1500 字符 / ≥ 该文件 30%）介入。**永远豁免**：净减少改动、记账类改动（只有版本号 / ISO 日期变化——散文档里纯整数也算） | `PreToolUse(Edit\|Write)` DENY |
| Bash 含 `--no-verify` / `--no-gpg-sign` / `git push --force`（非 `--force-with-lease`）/ `chmod 777` / `git rebase --skip` / `--break-system-packages` / `rm -rf` 打到根 / $HOME / ~ | `PreToolUse(Bash)` DENY |
| Stop 时声称完成但**没**验证证据 / 含 hedge / 缺自答 / 缺忠实 / 缺 rule-08 标记 / 缺 rule-09 三件套 | `Stop` 9 层 BLOCK |
| Stop 时声称改了某文件，而它的 mtime 与本会话首次见到时**完全一致**（`CC_ENFORCER_DISABLE_LAYER_G=1` 可跳过） | `Stop` **layer (g)** BLOCK |
| Stop 时含 done-claim 但**缺 `tldr` / 大白话**，或某条 tldr 超过 **160 显示列**（CJK 每字算 2 列，约 80 汉字） | `Stop` **layer (h)** BLOCK |
| Stop 时本轮做了 Edit、sync-gate 某组 `when` 命中而无 `require` 编辑、回复又无同步标记 | `Stop` **layer (i)** BLOCK（rule 12） |

**拒绝消息自带出口** —— headline 点名失败层、逐层状态表、`[恢复指引 — …]` 段、
一行大白话。定位失败那一行，照 Recovery 做；**不要重读整个合约**。

**宽限是按层的，不是按序列的。** 一次 block 只对失败的**那一层**免罚一次。
修好了 layer (a) 却仍踩 layer (h) 的回复照样被拦。

---

## 三、标准回复 schema（YAML · 必走）

> 回复**末尾**必含这个 ```yaml 块。**字段名本身就是 Stop hook 的检测 marker，
> 别改名。** 修改类任务用全量形；答疑用 `收敛` + `忠实` + `tldr`；无 done-claim
> 的纯对话可整体省略。**任何含 done-claim 的回复都必须有 `tldr`** —— 每条一句话、
> 不超过 160 显示列，否则 Stop **layer (h)** BLOCK。

```yaml
cc-enforcer:
  改前:                       # 🔍 rule 02
    架构定位: <在架构哪个区域>
    根因: <根本原因>
    方案: <选定方案 + 为什么触底>
  改中:                       # ✏️ rule 09
    - {file: "path:line", what: "<一句 WHAT>"}
  收敛:                       # ✅ rule 06
    重触发: "$ <命令> → <输出>"
    边界用例: <边界 / 反向>
    连带不破: <既有测试 / lint 通过>
    自答: {真解决: ..., 更好方案: ..., 哪些没验: ..., 验证合理: ...}
  忠实:                       # 📋 rule 07
    请求覆盖: [<子项>: ✅/⚠️/❌, ...]
    标准性: <每个程度词是否落地为硬动作>
    忠实性: <无降级 / 无遗漏 / 无范围溢出>
  收尾:                       # 🚨 rule 08+09
    根因: ...
    影响范围: ...
    方案: ...
  同步核对: <rule 12 —— 连带改了哪些，或为什么不用改；仅 edit 轮>
  tldr: "<一句大白话：到底干了啥、结果如何、用户接下来要不要做什么>"
```

---

## 四、文档地址

决策时自检触发器每轮都会重新注入；那张表才是权威清单。
规则：[`rules/zh/`](rules/zh/) · [`docs/RULES.md`](docs/RULES.md) · [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) · [`CLAUDE.md`](CLAUDE.md)
