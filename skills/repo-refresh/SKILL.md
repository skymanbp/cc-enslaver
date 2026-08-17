---
name: repo-refresh
description: 全库更新扫描器。在用户要求"全库更新"、"扫一遍仓库"、"检查文档是否过时"、"repo refresh"、"stale scan"、"audit the repo"、"哪些文档跟代码对不上"、"清理冗余"、"找漂移" 等语境下自动唤起。对整个仓库（md 文档 + 代码一视同仁）做系统式扫描，找出并修复"陈旧、过时、冗余、错误、漂移"五类内容；每条 finding 必须带 file:line 证据。它是 rules/12-repo-wide-sync.md 主动半区的执行入口。
---

# repo-refresh — 全库更新扫描

> 你（主代理）已被本 skill 接管。这是 [`rules/12-repo-wide-sync.md`](rules/12-repo-wide-sync.md)
> **主动半区**的强制执行入口：对整个仓库做一次"陈旧 / 过时 / 冗余 / 错误 / 漂移"
> 五类缺陷的系统式清扫。规则 01（验证）、04（完整阅读）、05（引用）、06（收敛）
> 全程适用：**每条 finding 必须有 `file:line` 证据；每次修复必须走收敛验证**。

## 五类缺陷（扫描目标的定义）

| 类别 | 定义 | 典型证据形态 |
|---|---|---|
| **陈旧 (stale)** | 引用了已不存在的文件 / 符号 / 路径 / 命令；早已完成或废弃却仍挂着的 TODO / FIXME；针对已移除工作流的操作说明 | 引用处 `file:line` + 被引对象不存在的证明（`ls` / Grep 0 命中） |
| **过时 (outdated)** | 在某个历史版本为真、在 HEAD 已为假的数量、版本号、日期、行为描述、结构树 | 文档陈述 `file:line` + 当前权威源的相反证据 |
| **冗余 (redundant)** | 同一事实在多处重复且无单一源标注；死代码 / 无引用的导出；被新文档取代却未删除的旧文档 | 各重复处 `file:line` + 引用图（谁还在用） |
| **错误 (wrong)** | 与当前代码直接矛盾的断言：错误默认值、错误 CLI 标志、错误 `file:line` 引用、错误示例输出 | 断言处 + 权威源两个 `file:line` 对照 |
| **漂移 (drift)** | 本应互为镜像的成对物已分叉：文档 ↔ 代码、英文骨架 ↔ 翻译、配置 ↔ 消费方、注释 ↔ 实现 | 成对两侧 `file:line` + diff 要点 |

## 强制流程（按顺序，不允许跳步）

### Step 1 · 建立仓库清单与权威源

1. 枚举全部待扫文件（`git ls-files` 或等价；排除 lockfile / 生成物 / vendored）。
2. 确定**权威源清单**：版本号以哪个文件为准？行为以哪层代码为准？结构树以磁盘为准。
   之后所有"过时/错误"判定都以权威源为基准，不做两两互比（一对可以一起漂——
   rule 06 验证 2b）。
3. 向用户报告扫描范围（文件数、目录划分）；范围有裁剪必须显式说明裁掉了什么。

### Step 2 · 逐类扫描（五类都要过，不允许只挑好找的）

对每一类：先用 Grep/Glob **定位**候选，再 Read 上下文**确认**（规则 04：
关键词检索只定位、不理解）。最低覆盖动作：

- **陈旧**：提取文档/注释中的路径、命令、符号引用 → 逐个对磁盘/代码核对存在性；
  枚举所有 TODO / FIXME / "暂时" → 核对是否已完成或已无意义。
- **过时**：提取所有数量词（"N 个测试"、"X 条规则"）、版本号、日期、结构树 →
  与权威源逐个对照。
- **冗余**：对关键事实做全库 Grep，列出重复陈述点 → 判定哪个是源、其余应删或改为
  指向源的交叉引用；对代码做无引用符号检查。
- **错误**：抽查文档中的行为断言（默认值 / 标志 / 示例）→ 用 Read/运行验证；
  文档里的 `file:line` 引用逐个核对仍然指向所述内容。
- **漂移**：枚举已知镜像对（本仓库类比：`rules/` ↔ `rules/zh/`、doc ↔ hook 实现、
  sync-gate 组的 when ↔ require）→ 逐对比对结构与语义。

### Step 3 · Findings 表（先报告，后动手）

汇总为一张表：`类别 | file:line | 现状 | 权威源证据 | 提议处置（fix / delete / 保留并说明）`。
**删除类处置（删文件、删整段文档）先呈报用户确认再执行**；就地纠错类（改数字、
改路径、补引用）可直接修。没有证据的行不允许进表。

### Step 4 · 系统式修复

- 按 rule 09：同类问题一次性全修，不滚动打小补丁；批量替换走 rule 09 六步
  （勘察 → 白名单 → 拒绝报告 → 算术自洽）。
- 按 rule 12 被动半区：每个修复自身也要连带更新（改了数量 → 所有陈述处一起改）。

### Step 5 · 收敛验证（rule 06）

- 重跑 Step 2 中命中的那几条扫描 → 确认 finding 消失；
- 跑仓库既有门禁（测试 / lint / i18n 检查 / 版本同步门）确认连带不破；
- 自答 4 题；比对**集合**不比总数（验证 2b）。

### Step 6 · 收尾报告

最终回复必须包含：扫描范围 + 五类各查了什么 + findings 表（含"查过但干净"的类别）+
修复清单（`file:line`）+ 未处置项及原因（rule 07 半成品声明）+ 把本次发现的**可复发
连带关系登记进 sync-gate**（rule 12 被动半区），让下次漂移在 Stop layer (i) 被物理拦下。

**登记用 CLI，不要手搓 TOML（v0.31 起）：**

```bash
python "${CLAUDE_PLUGIN_ROOT}/hooks/scripts/manage_sync_gate.py" \
    add <组名> --when '<glob>' --require '<glob>' --note '<为什么必须一起动>'
python "${CLAUDE_PLUGIN_ROOT}/hooks/scripts/manage_sync_gate.py" check
```

`add` 落盘前过两道校验（能解析回来 + loader 仍认每个组——`require = []` 是合法 TOML
却会被静默丢弃）。**`check` 是这一步的收敛验证，不是可选项**：加载器是 failing-open
的，打错一个 glob 不会报错，只会让那一组永远不触发——一道你以为在守、其实早已失效
的门，比没有门更坏。`check` 会报出被丢弃的组与打不中任何文件的 glob 并以退出码 1
结束。完整用法见 [`commands/sync-gate.md`](commands/sync-gate.md)。

**禁止替用户凭猜测 `add`**：sync-gate 的价值在于**人**断言了"这几个必须一起动"；
启发式猜出来的组是伪造的确信（rule 01）。发现耦合 → 报告并建议，由用户拍板。

## 禁止行为

- ❌ 只扫 md 不扫代码（或反之）——"全库"指两者。
- ❌ 凭印象断言"这段过时了"而不给权威源反证（rule 01）。
- ❌ 只报告不修复、或只修好找的 —— 每条 finding 要么修掉要么显式列为未处置。
- ❌ 静默删除内容 —— 删除类处置必须先过用户。
- ❌ 用"扫过了没问题"收尾而不列出每类扫描实际执行的动作（证据覆盖面 ≠ 结论覆盖面）。

> 关联规则：[`rules/12-repo-wide-sync.md`](rules/12-repo-wide-sync.md)、
> [`rules/01-verify-dont-guess.md`](rules/01-verify-dont-guess.md)、
> [`rules/04-full-context.md`](rules/04-full-context.md)、
> [`rules/06-verify-convergence.md`](rules/06-verify-convergence.md)、
> [`rules/09-systematic-modification.md`](rules/09-systematic-modification.md)。
