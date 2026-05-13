---
name: systematic-debug
description: 在 debug / 修 bug / 异常排查 / "为什么不工作" 等语境下自动唤起。强制 agent 先走完根因分析的 7 问与 5 步骤，禁止直接给出反应式修补。当用户描述：bug、错误、stack trace、异常行为、"为什么 X 失败"、"为什么 Y 不工作"、"修一下这个"、"测试不过"、"500 报错"、"突然就坏了" 等情形时使用。
---

# systematic-debug — 系统式 debug 流程

> 你（主代理）已被本 skill 接管。在解决用户描述的问题前，**必须**按以下流程进行根因分析。
> 这个 skill 是 [`rules/02-systematic-not-reactive.md`](rules/02-systematic-not-reactive.md) 与 [`rules/03-root-cause.md`](rules/03-root-cause.md) 的强制执行入口。

## 强制流程（按顺序执行，不允许跳步）

### Step 0 · 构建可复现信号（feedback loop）

> **这是本 skill 最核心的一步。** 借鉴 `mattpocock-skills:diagnose` 的 Phase-1 原则：
> "If you have a fast, deterministic, agent-runnable pass/fail signal for the bug, you will find the cause."
> 没有可复现信号，后续 Step 3 / Step 4 的"假设 → 证伪"全是空中楼阁——你只能凭印象写"应该是 X"。
>
> **未建立可复现信号前，禁止进入 Step 3。** 反复试图绕开 Step 0 跳到 Step 3 是本 skill 的高频违规。

**0.1 · 选一种 loop 形态（按优先级试 10 种）**

按下面顺序尝试，先选满足"快 + 确定 + agent 可跑"三条的最高优先级：

1. **Failing test** —— 在合适的层（unit / integration / e2e）写一个最小测试，断言 bug 行为。最佳。
2. **Curl / HTTP script** —— 对运行中的 dev server 发请求，把响应跟期望 diff。
3. **CLI invocation + snapshot diff** —— 用 fixture 输入跑 CLI，跟已知正确输出 byte-diff。
4. **Headless browser 脚本** —— Playwright / Puppeteer 驱动 UI，断言 DOM / console / network。
5. **Replay captured trace** —— 把真实 request / payload / event log 存盘，在隔离环境里重放。
6. **Throwaway harness** —— 起一个最小子集（单 service + mocked deps），单函数调用触发 bug 路径。
7. **Property / fuzz loop** —— bug 是 "sometimes wrong" 时，跑 1000 个随机输入找失败模式。
8. **Bisection harness** —— bug 出现在已知两个状态间（commit / dataset / version）→ "boot at state X, check, repeat" 自动化，让 `git bisect run` 直接跑。
9. **Differential loop** —— 同一输入分别跑 old vs new（或两个 config），diff 输出。
10. **HITL bash 脚本** —— 最后兜底；若必须人手点击，至少用脚本驱动人，捕获输出回喂给你。

**0.2 · 把 loop 当成产品迭代**

选定后立即问：
- 能不能更快？（缓存 setup、跳无关 init、缩窄测试范围）
- signal 能不能更尖锐？（断言具体症状，而不是"没崩"）
- 能不能更确定？（pin 时间、seed RNG、isolate fs、freeze network）

**30 秒间歇 flaky loop 比没 loop 强不了多少；2 秒确定 loop 就是 debug 超能力。**

**0.3 · 非确定性 bug：提高复现率而不是要"干净 repro"**

50% flake 可 debug；1% 不可。Loop 触发器 100×、并行、加压、缩窄时间窗、注入 sleep——把命中率拉高到能 debug 为止。**目标不是 "能必定复现"，是 "够频繁能落到 trace"。**

**0.4 · 真的造不出 loop —— 显式停下**

不允许"造不出 loop 就直接猜"。必须：
- 列出已尝试的 loop 形态 + 各自失败原因
- 向用户索取：(a) 能复现的环境访问，或 (b) 抓到的 artifact（HAR / log dump / core dump / 带时间戳的录屏），或 (c) 在生产临时加 instrumentation 的授权
- **绝对禁止**：在没 loop 的状态下进 Step 3 假设根源——这等于规则 01 "凭印象断言" 的违规。

**0.5 · loop 建立确认（强制 checkpoint）**

进入 Step 1 前必须能回答：
1. loop 是什么？（贴一行命令 / 一段脚本 / 一个测试名）
2. 跑一次多少秒？
3. 跑 N 次有几次命中 bug？（确定性 = N/N；非确定性 = 给比例）
4. signal 长什么样？（具体 stdout / 错误码 / 截图 / DOM 状态——不允许 "好像不对"）

任一答不出来 → loop 不算建立 → 不允许进 Step 1。

### Step 1 · 复述与边界

用一两句话**复述**用户描述的问题，并明确：

- 什么是已知症状？（具体报错信息、行为差异、影响范围）
- 什么是**未知**？（哪些信息你目前没有，需要去看/去问）
- 什么**不是**这个问题？（明确排除范围以避免漫无目的探索）

⚠️ 如果用户给的信息不足以让你写出"已知/未知"清单，**先问用户**或**先读相关文件/日志**，不要立即开始修。

### Step 2 · 架构定位（七问之 1-2）

回答：

1. 这个问题出现的代码区域在**整个项目架构**中的哪个位置？
2. 那块代码的当前职责是什么？上游调用方是谁？下游被谁调用？

⚠️ 如果你尚未 `Read` 过涉事文件的完整内容，**现在就读**（规则 04）。

### Step 3 · 假设根源（七问之 3）

提出 **2-3 个可能的根源假设**（不要只想一个 → 容易锚定）。每个假设要：

- 描述机理（**为什么**这个原因会导致观察到的症状）
- 列出可证伪的预测（"如果是这个原因，那么我应该看到 X / 不应该看到 Y"）

### Step 4 · 验证假设（规则 01）

针对每个假设：

- 设计一个**可执行的验证步骤**：读哪个文件的哪几行 / 跑哪条命令 / 检查哪个 commit。
- 实际执行验证（用 `Read` / `Grep` / `Bash`）。
- 收集证据（粘贴 `file:line` 内容或命令输出）。
- 判定：confirmed / refuted / inconclusive。

⚠️ 不允许凭"看起来应该是 X"就跳到 Step 5。

### Step 5 · 确认根源 + 评估方案（七问之 4-5-6）

- 哪个假设被证据 confirmed？描述完整因果链：**根源 → 中间机理 → 观察到的症状**。
- 拟提出的修复方案：是否触达根源（不是 try/except、不是 sleep、不是 --no-verify）？
- 连带影响：哪些下游/测试/文档需要同步改？
- 风险：可能破坏哪些既有不变量？

### Step 6 · 实施修改

- 应用最小有效修改（规则 02.6）。
- 对每个连带项也同步修改。
- 修改时禁止规则 03 列出的反模式。

### Step 7 · 收敛验证（rule 06 强制）

> 这一步是 [`rules/06-verify-convergence.md`](rules/06-verify-convergence.md) 的执行入口。
> 完成下面所有子步骤前**禁止**声称完成；如有任意一步揭示问题未解决，**回到 Step 3 重新假设根源**。

**7.1 · 重触发原症状**：用 **Step 0 建立的同一个 feedback loop** 重跑（不是凭记忆复述命令）。粘贴新输出，明确"原报错消失"。Step 0 投入做的尖锐 / 确定性的 loop，在这一步直接付息——如果 loop 跑完仍命中原 signal，root cause 没修对，回 Step 3。

**7.2 · 边界 + 反向用例**：至少跑 1 个边界（空输入 / 错误路径 / 并发 / 跨平台 / Unicode）+ 1 个反向用例（应该 fail 的仍 fail）。

**7.3 · 连带不破坏**：跑相关测试套件 + lint + 类型检查；附输出。

**7.4 · 自答 4 题（必须显式回答）**：
1. **是不是真的解决了？** 证据是什么？如何排除"巧合 / 缓存 / 环境差异"？
2. **有没有更好的方案？** 与替代方案在简洁性 / 性能 / 可维护性 / 架构契合度上对比？
3. **改动是否经过验证？** 哪些没验？为什么不需要？
4. **验证是否合理？** 我跑的测试对应原问题的哪个机理？是否覆盖了 Step 5 中的根因因果链？

**7.5 · 量化（仅性能/竞态/兼容性修复）**：给数字 / 给重跑次数 / 给测试矩阵。

⚠️ 任意子步骤的答案是 "不知道 / 应该可以 / 差不多" → **未收敛，回 Step 3**。

## 禁止行为

直接跳到 Step 6 是本 skill 最常见的违规模式。具体禁止：

- ❌ 看到 stack trace 第一行就在那一行上加 try/except → 这是规则 03 反模式
- ❌ 测试失败就让测试通过（不问为什么之前失败）
- ❌ "我猜可能是 X" → 改 X → "应该好了" → 通通是反应式
- ❌ 跳过 Step 4（验证假设）直接进 Step 5
- ❌ **跳过 Step 0**（没建 feedback loop 直接进 Step 3 假设根源） — 这是新增的高频违规；没 loop 等于在 Step 4 没法证伪假设，整个流程退化成"猜 + 改 + 期待"
- ❌ "我跑过一次 stack trace 看到了，就当 loop 已经建立" → 错；Step 0 要求**可重复的 agent 可跑信号**，一次性人眼看到不算
- ❌ "loop 跑得太慢，先用印象判断" → 错；让 loop 变快是 Step 0.2 的任务，不是绕开 Step 0 的借口

## 输出契约

完成上述流程后，最终回复给用户的内容**必须包含**：

1. **Feedback loop 描述**（Step 0 的产物：用了哪种 loop 形态、跑一次多少秒、命中率）
2. **根源说明**（一段话讲清楚机理）
3. **修改清单**（含 `file:line`）
4. **连带项处理**（"我同时改了 X / 检查了 Y / 未改 Z 因为…"）
5. **收敛验证证据**（rule 06 的 Step 7 全部 5 个子步骤的产物：用 Step 0 同一个 loop 重触发的输出、边界用例结果、连带测试结果、4 题自答、量化对比）

如果中途发现问题超出预期复杂度（例如根源在另一个模块），**先回到用户**说明情况，不要单方面扩大修改范围。

> 关联规则：[`rules/02-systematic-not-reactive.md`](rules/02-systematic-not-reactive.md)、[`rules/03-root-cause.md`](rules/03-root-cause.md)、[`rules/04-full-context.md`](rules/04-full-context.md)、[`rules/06-verify-convergence.md`](rules/06-verify-convergence.md)。
