# cc-enslaver

> **让编程 agent 物理上无法忽略的规则。**
> 一个 Claude Code 插件（同时也是任意 LLM 通用规则包），用拦截工具调用的方式——
> 而不是"好言相劝"的方式——终结反应式打补丁、编造引用、表面修复和过早宣告完成。

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Plugin Version](https://img.shields.io/badge/version-0.29.0-blue.svg)](CHANGELOG.md)
[![Tests](https://github.com/skymanbp/cc-enslaver/actions/workflows/test.yml/badge.svg)](https://github.com/skymanbp/cc-enslaver/actions/workflows/test.yml)
[![Claude Code Plugin](https://img.shields.io/badge/Claude%20Code-plugin-purple.svg)](https://code.claude.com/docs/en/plugins.md)

**[English →](README.md)**

---

## 30 秒看懂

你写进 prompt 的每一条"要严谨"，都有同一个漏洞：**遵不遵守由模型自己决定**。
在压力之下——长会话、上下文被压缩、凌晨两点还有个测试不过——它会决定不遵守，
然后告诉你它遵守了。

cc-enslaver 把这份契约里重要的那一半**从 prompt 里搬进 harness**。Claude Code
的 hook 在每次工具调用**之前**、每次回复被允许结束**之前**运行，违规返回真正的
`deny` / `block`，agent 没法靠讲道理、道歉或"就这一次"绕过去：

```text
cc-enslaver · rule 09 violation (rolling-patch interception)

Tool: Edit
Target: hooks/scripts/stop_guard.py
Rolling-patch counter: 3 small edit(s) already applied this session;
this would be attempt #4 — at or above the threshold of 4.

To proceed, do one of:
  (1) 系统性重写：把待办的小修合并成一次 ≥ 50 行 / ≥ 1500 字符的 Edit，计数清零。
  (2) 把多个同类小改批量成一次较大的 Edit。
  (3) 停下来上报：告诉用户这个文件需要重写。
```

这不是事后打印的忠告 —— 那次编辑**根本没有发生**。

由此带来三个性质：

| | |
|---|---|
| **扛得住上下文压缩** | 规则每轮重新注入，而硬层活在代码里，根本不依赖模型"还记得"。 |
| **无法自我放行** | 内置守卫排在用户规则**之前**；read 登记逃生口用磁盘 SHA-256 校验——没打开过文件的 agent 算不出它的摘要。 |
| **只会失败向开，不会向关** | 守卫内任何异常都只写 stderr 并**放行**。纪律出 bug 绝不会把你的 agent 卡死。 |

---

## 它解决什么问题

LLB 编程助手（Claude Code、Cursor、Copilot、Cline、Aider……）会掉进可预测的偷懒模式：

| 偷懒模式 | 具体表现 | 对应手段 |
|---|---|---|
| **反应式打补丁** | 看到 bug 就 `try/except` 一包，宣告完成。 | rule 03 + 09，`PreToolUse` DENY |
| **编造引用** | 引用不存在的文件、行号或 API。 | rule 01 + 05，Stop 层 (b)/(g) |
| **只靠关键词搜索** | grep 一次就改，从不读周边架构。 | rule 04 + 08，`PreToolUse` DENY |
| **依赖记忆** | 凭陈旧印象行动，而不重读当前文件。 | rule 04 + 08，改前必读闸门 |
| **绕过根因** | 用 `sleep` 掩竞态、`--no-verify` 过钩子、吞掉异常。 | rule 03，`PreToolUse(Bash)` DENY |
| **半成品** | 停在"应该能跑"，留 TODO，不验证全流程。 | rule 07，Stop 层 (d) |
| **过早宣告完成** | 没重跑失败用例、没有对比证据就说"修好了"。 | rule 06，Stop 层 (a)/(c) |

---

## 安装

### 作为 Claude Code 插件（推荐）

仓库自带 `.claude-plugin/marketplace.json`，可直接作为单插件 marketplace 注册：

```bash
git clone https://github.com/skymanbp/cc-enslaver.git /path/to/cc-enslaver
```

然后在任意 Claude Code 会话（CLI 或 IDE）里：

```
/plugin marketplace add /path/to/cc-enslaver
/plugin install cc-enslaver@cc-enslaver
```

验证：`/plugin` → **Installed** 里应出现 `cc-enslaver@cc-enslaver`。
命令随即以 `/cc-enslaver:checklist`、`/cc-enslaver:verify` 等形式出现。

> **依赖：** PATH 上有 Python（在 3.13 上测过）。hook 脚本只用标准库——不需要
> pip，不引入任何第三方包。

### 作为任意 LLM 的规则包

不需要 Claude Code。规则就是 [`rules/`](rules/) 下的纯 Markdown（英文是 source
of truth，[`rules/zh/`](rules/zh/) 是中文翻译）：

```bash
cat rules/zh/*.md > cc-enslaver.txt     # 中文
cat rules/*.md    > cc-enslaver.txt     # 英文骨架
# 作为 system prompt / 前置上下文喂给你选的 agent
```

这样会失去硬层（它们是 Claude Code hook），保留推理纪律。OpenAI / Gemini /
本地模型的接入方式见 [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) 的
**LLM portability** 一节。

---

## 它到底强制什么

五类，按"咬得多狠"排序。

### 一 · 12 条规则

推理契约本身。约一半有钩子背书，其余是文本层纪律，由 Stop 闸门间接评分。

| # | 规则 | 要求什么 | 强制方式 |
|---|---|---|---|
| 01 | **验证而非猜测** | 任何关于文件 / API / 版本 / 错误 / 文献的断言，**在写下它的同一轮**当场核实。"我不知道"优于"自信地错"。 | 软 + Stop (b)(g) |
| 02 | **系统式而非反应式** | 改前自答七问：架构、职责、根因、方案、连带、风险、全局。规则里给的是完整范例，不是口号。 | 软（由 (e) 评分） |
| 03 | **修根因不修症状** | 沿因果链上爬——症状位 → 传播路径 → **起源**——直到答案是一个机制。中途停下只有在点名真正起源并说明理由时才合法。 | **Bash DENY** + 软 |
| 04 | **完整阅读而非关键词** | grep 只负责定位；理解必须读完整文件 + 调用点。 | **Edit/Write DENY** |
| 05 | **引用可追溯** | 代码给 `file:line`，文献给 URL/DOI，运行时结论给命令 + 输出。 | 软 |
| 06 | **验证收敛** | 重触发原症状、跑边界与反向用例、跑既有测试、自答四题。**验证 2b：**"无回归"必须是逐项集合对比，绝不能是一个相同的总数。 | **Stop (a)(c)** |
| 07 | **任务忠实** | 把用户请求拆成可核查的子项；用户用的每个程度词（"所有""严格""强制"）必须落地为硬动作，而不是一行文档。 | **Stop (d)** |
| 08 | **改前必读·写前必想** | 进去前完整读，出来时说清根因 / 架构 / 影响。 | **DENY + Stop (e)** |
| 09 | **系统式修改** | 一个根因一次统一修复——扫清整类，绝不是 N 个补丁。屏蔽标记必须紧邻 why。 | **DENY ×2 + Stop (f)** |
| 10 | **禁止非必须硬编码** | 密钥、token、私钥、URL 内凭证绝不进源码字面量。 | **Edit/Write DENY** |
| 11 | **禁止非必须路径依赖** | `C:\Users\…` / `/home/你/` / `$HOME` 不许写死进代码，运行时派生。 | **Edit/Write DENY** |
| 12 | **全库同步** | 改动只有在全库引用——文档、测试、下游代码、翻译——都连带更新或显式确认无需改时，才算完成。 | **Stop (i)**，按项目开启 |

规则正文：[`rules/zh/`](rules/zh/) · 索引：[`docs/RULES.md`](docs/RULES.md)

### 二 · 工具边界上的硬闸门（`PreToolUse` → DENY）

这些直接拒绝调用。每一条都配有明确的逃生口——所以它们**只能靠说明理由绕开**，
绝不会被无意中绕开。

| 闸门 | 触发条件 | 逃生口 |
|---|---|---|
| **改前必读** | 编辑一个磁盘上已存在、但本会话从未打开过的文件。 | 先读；或做一次 SHA-256 校验的 read 登记。 |
| **屏蔽标记** | `# noqa`、`# type: ignore`、`@ts-ignore`、`@ts-expect-error`、`eslint-disable`、用 `time.sleep(…)` 绕过。 | 紧邻写 why 注释（中英皆可），或真去修根因。 |
| **裸 `try/except: pass`** | 处理块体只有 `pass` 的异常吞没——跨行识别，中间夹注释也算。 | 同上 why 注释。 |
| **硬编码密钥** | 密钥命名的字面量、PEM 私钥头、`AKIA…`、`ghp_…` / `xox…` / `AIza…`、`user:pass@host` 形式的 URL。 | 改用环境变量、标注过的占位符，或 why 注释。 |
| **机器特定路径** | `C:\Users\…`、`/home/<user>/`、`/Users/<user>/`、`$HOME`、`%USERPROFILE%`、带引号的 `~/…`。 | 运行时派生，或 why 注释。散文文档与锁文件豁免。 |
| **滚动补丁** | 对同一文件的第 4 次小改（< 200 字符 **且** ≤ 10 行）而中间没有一次系统性重写。 | 一次 ≥ 50 行 / ≥ 1500 字符的重写即清零。 |
| **危险 shell** | `--no-verify`、`--no-gpg-sign`、`git push --force`（非 `--force-with-lease`）、`chmod 777`、`git rebase --skip`、`--break-system-packages`、对 `/` `$HOME` `~` 的 `rm -rf`。 | 去修钩子失败 / 权限 / 冲突的根因。 |
| **你自己的圣旨** | 你登记为 `must` 的任意正则。 | 只有你能放宽。 |

### 三 · 完成声明闸门（`Stop` → BLOCK，九层）

Stop 钩子读 agent 即将收尾的那段回复。只要里面含完成声明，就由九层评分。
(e)(f)(g)(i) 四层只在**本轮真的改过文件**时才生效。

| 层 | 规则 | 什么情况下拦 |
|---|---|---|
| (a) | 06 | 宣告完成却**毫无证据**——没有命令、没有输出、没有计数。 |
| (b) | 01 | 完成声明旁边挨着**模棱两可的措辞**（"应该没问题""probably"）。 |
| (c) | 06 | 有证据，却从不回答**收敛四问**。 |
| (d) | 07 | 过了收敛，却从不对照**用户的原始请求**逐项核对。 |
| (e) | 08 | 改了文件，却没有surface 出根因 / 架构 / 方案 / 影响 / 风险中的 ≥ 3 项。 |
| (f) | 09 | 改了文件，却缺**根因 + 影响 + 方案**三件套。 |
| (g) | 01+06 | 声称"我改了 X"，而 X 在磁盘上的 **mtime 根本没变**。 |
| (h) | — | **没有 `tldr`**，或某条 `tldr` 超过 160 字符。 |
| (i) | 12 | 命中了项目的 **sync-gate** 组却既没连带更新、也没写 `同步核对:` 一行。 |

被拦时返回统一格式：点名失败行的状态表、给出可执行修复步骤的 `[Recovery — …]`
段，以及一行大白话。**宽限是按层的**（v0.29）：刚刚拦下你的那一层在下次尝试时
免罚——同一行永远不会拦你两次——但你仍在违反的**另一层**照样会拦。升级次数被
层数上界限住，任何一次干净的回复都会重置。

状态表报的是**求值**顺序而不是字母序（v0.30）：(b) 跑在最前——旁边堆多少证据
也救不了一个模棱两可的完成声明——所以 (a) 失败时表里是 "(b) ✅ Pass"，(b) 失败时
是 "(a) ⏸ pending"。v0.30 之前两种判定都取自显示序，于是每次 hedge 拦截都会打印
"(a) ✅ Pass"，在证据检查根本没跑的那一轮断言"已找到证据"。一个专门抓无据断言的
闸门，自己的输出里不能有一句。

### 四 · 圣旨（Imperial Edicts）—— 你自己的硬规则

多数"自定义规则"功能不过是往 prompt 里再塞一段文字。这里你的规则会变成一条正则，
由钩子在每次 Edit / Write / Bash **落地之前**去匹配真实内容：

```bash
/cc-enslaver:edict add E01 "禁止 mongoose，统一用 prisma" --must \
    --deny-edit 'from ["'"'"']mongoose["'"'"']' \
    --deny-bash 'npm\s+(i|install)\s+mongoose'
```

- **两档严重度，机制上不同。** `must` + 正则 → `PreToolUse` DENY 并点名圣旨 ID；
  `should` → 只是提醒文字，永不拒绝。
- **两个作用域。** `.claude/cc-enslaver/edicts.toml`（项目级，提交进 git 让全队
  共享红线）或 `~/.claude/cc-enslaver/edicts.toml`（`--global`，个人跨项目）。
- **热加载** —— 每次钩子事件重读，所以你可以在会话中途反复调正则。
- **每轮重新注入**，上下文压缩不会把你的规则悄悄丢掉。
- **按设计排在内置守卫之后**：圣旨只能加限制，不能减限制。
- **失败向严不向松**：无法解析的 severity 回退到 `must`；格式错误的单条圣旨只丢
  自己并打 stderr 诊断，而不会阻断工作。

详见 [`docs/EDICTS.md`](docs/EDICTS.md)

### 五 · 你自己调用的部分

**5 个 slash 命令**、一个子代理、两个自动触发的 skill：

| 入口 | 作用 |
|---|---|
| `/cc-enslaver:checklist` | 打印 **8 段清单**（改前 → 改后 → 收敛 → 忠实 → 读/想 → 系统式 → 大白话 → 全库同步）。其中补丁标记那一项是与钩子真实常量同步的**封闭集**，所以不会出现"每项都打勾却仍被 DENY"。 |
| `/cc-enslaver:verify` | 把 agent 上一条回复当作**不可信输入**：抽出每条事实断言，分成四类（代码位置 / 代码行为 / 外部资源 / 运行结果），每类规定不同的重新验证方法。明确禁止凭记忆作答。 |
| `/cc-enslaver:edict` | 圣旨的 `list / add / remove / reload / path`（`--global` 走个人作用域）。 |
| `/cc-enslaver:gc` | 列出——加 `--apply` 才删除——超过 N 天未动的会话状态文件。默认 dry-run，且命令文件禁止 agent 替你决定 `--apply`。 |
| `/cc-enslaver:i18n` | 检查每份翻译是否仍与英文骨架逐文件、逐标题层级对齐。 |
| **`verifier` 子代理** | 一个被刻意限权的只读检查者（工具只有 Read/Grep/Glob——这是权限事实，不是嘱咐）。每条断言返回 *intact / drift / missing / mismatch / unverifiable*。它当不了修复者，因此没有"偷偷改掉不一致"的动机。 |
| **`systematic-debug` skill** | 遇到 debug 语境自动接管流程：**先**造一个快速、确定性的复现回路，**再**提假设。"30 秒的间歇性 flaky 回路只比没有回路好一点点；2 秒的确定性回路是 debug 超能力。" |
| **`repo-refresh` skill** | 遇到全库审查语境自动触发：把代码与散文当作同一个面来扫陈旧 / 过时 / 冗余 / 错误 / 漂移，最后要求你把这次发现的耦合登记成 sync-gate 组。 |

---

## 凭什么说它不只是个 prompt 文件、也不只是 linter

有意思的工程都在检测器里，而且大多数是因为"朴素写法"被实测证伪才长成现在这样：

- **源码是被词法分析的，不是正则扫的。** `line.find("#")` 会找到 URL 里的 `#`——
  曾因此让旁边一行 `API = "https://api.example.com"` 把**密钥**检测器整个关掉
  （`example` 恰好是理由词）。[`lib/srclex.py`](hooks/scripts/lib/srclex.py) 区分
  代码 / 注释 / docstring / 数据字面量，带字面量遮罩与括号续行合并。
- **shell 是被 tokenize 的，不是字符串匹配。**
  [`lib/shellcmd.py`](hooks/scripts/lib/shellcmd.py) 把复合命令拆成逐次调用的
  argv，把 git 全局选项解析到真正的子命令，并递归进 `bash -c` 载荷。于是
  `rm -f build.log && git push origin main` 里的 `-f` 绝不会算到 push 头上，
  `$(git push --force)` 仍被拒，而 `echo git commit --no-verify` 会被正确**放行**。
- **标记在真正的 token 边界结束。** `\b` 把连字符当边界，所以朴素匹配会把
  `@ts-ignore-generated`、`# noquality` 误判成屏蔽标记。检测器用的是 `(?![\w-])`。
- **逃生口自带防伪。** read 登记逃生口会从磁盘重算 SHA-256；没打开过文件的 agent
  算不出摘要。`false && register_read.py …` 也拿不到额度——钩子在执行前触发，
  无从知道 shell 会走哪个分支。
- **理由必须是实质性的。** 以 `TODO` / `FIXME` / `HACK` 开头是推脱而非理由，照拒。
  装饰性标点会先被剥掉，中文理由按不同字符数计量。
- **并发有正经处理，而且有数字。** 每次钩子调用都是独立 OS 进程，Claude Code 又
  并行发工具调用。所有写操作持跨进程文件锁并原子落盘——修复前实测：10 路并行下
  每轮丢 2–3 条已记录的读；Windows 上 `os.replace` 与打开中的读者冲突导致
  200 次保存丢 192 次。
- **仓库用自己的规则管自己。** 三道 CI 门让文档声明无法漂移：版本门（所有版本
  指针、徽章、CHANGELOG 最新标题都以 `plugin.json` 为准，且是**封闭集**——
  "黑名单式检查会放它过去"）、文档门（README 里每个数字都在测试时从代码派生）、
  i18n 门。

---

## 运行原理

| 事件 | Matcher | 行为 | 实现 |
|---|---|---|---|
| `SessionStart` | — | 注入 12 条规则摘要 + 回复 schema + 圣旨（默认英文，`CC_ENSLAVER_LANG` 可切任意语言）。 | [`inject_context.py`](hooks/scripts/inject_context.py) |
| `UserPromptSubmit` | — | 每轮重新注入决策触发器 + 圣旨——这是对抗上下文压缩的防线。 | [`inject_context.py`](hooks/scripts/inject_context.py) |
| `PreToolUse` | `Read\|Edit\|Write` | 记录读取、捕获 mtime 基线，并运行上文列出的内容 / 频率 / 圣旨闸门。 | [`read_guard.py`](hooks/scripts/read_guard.py) |
| `PreToolUse` | `Bash` | tokenize 命令、拒绝绕过标志与破坏性操作、处理 read 登记、扫描圣旨。 | [`bash_guard.py`](hooks/scripts/bash_guard.py) |
| `Stop` | — | 九层完成声明判定，渲染成状态表 + Recovery + 大白话。 | [`stop_guard.py`](hooks/scripts/stop_guard.py) |

两处注入都按 Claude Code 的 10,000 字符 hook 输出上限做了预算：合约受保护，
让位的是无界增长的圣旨列表，且按**整条圣旨**边界截断并留指针——因为半条圣旨
读起来仍是一条完整指令。

[`hooks/scripts/`](hooks/scripts/) 下 8 个脚本建立在 8 个共享
[`lib/`](hooks/scripts/lib/) 模块上。注册为钩子的只有上表那四个；另外四个
（`register_read.py`、`manage_edicts.py`、`gc_state.py`、`i18n_check.py`）分别
服务于 escape hatch、slash 命令与 CI。它们**刻意不搬进单独的 `tools/` 目录**：
`gc_state.py` 被 `inject_context.py` 直接 import（auto-GC），`register_read.py`
的真正逻辑住在 `bash_guard.py` 里——两者都不是独立 CLI，搬走只会用一个更好看的
目录名换来真实的跨目录 `sys.path` 拼接。完整契约见
[`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) §2。

---

## 配置

| 变量 | 效果 |
|---|---|
| `CC_ENSLAVER_LANG=<code>` | prompt、圣旨与拒绝理由的注入语言。未设 / `en` = 英文骨架；`zh` = 中文；其它语言码读 `<dir>/<code>/`，缺失文件逐个回退英文。 |
| `CC_ENSLAVER_DISABLE_LAYER_G=1` | 关闭 Stop 层 (g) 的文件声明核验，其余八层仍生效。 |
| `CC_ENSLAVER_AUTO_GC_DAYS=N` | SessionStart 时自动清理超过 N 天的会话状态，24 小时内至多跑一次。未设 / `0` → 关闭。 |
| `CLAUDE_PLUGIN_DATA` | 会话状态根目录。由 Claude Code 设置；回退到 `${CLAUDE_PROJECT_DIR}/.claude/local/cc-enslaver/`，再回退到 `~/.claude/local/cc-enslaver/`。 |
| `CLAUDE_PROJECT_DIR` | 项目根，用于定位 `.claude/cc-enslaver/edicts.toml` 与 `sync-gate.toml`。 |

**按项目开启的 sync gate**（rule 12）：在 `.claude/cc-enslaver/sync-gate.toml`
里声明连带更新组，Stop 层 (i) 负责执行。

---

## 边界 —— 它**不**做什么

如实写出来，因为"纪律插件自吹自擂"恰好就是它存在要防的失效模式：

- **一切失败向开。** 守卫抛异常就写 stderr 并放行；状态不可读按宽松处理。这是
  刻意的——插件的 bug 绝不能把你的 agent 卡死——但也意味着强制是尽力而为，
  **不是安全边界**。
- **Stop 各层只在出现完成声明时才启动。** 一段从不说"完成"的回复不会被评分。
- **rule 02 与 05 没有自己的钩子**，rule 03 / 09 / 12 的推理部分也是文本层。
  没有钩子能验证你**真的**扫清了一整类缺陷，只能验证你说了。
- **硬层只对 Claude Code 有效。** 其它 agent 得到的是规则包。
- **检测器宁可漏报不误报。** 已知缺口写在各自规则文件里，而不是悄悄补掉。

---

## 仓库结构

```
cc-enslaver/
├── rules/                       # 12 条规则 + 索引 —— 英文骨架（source of truth）
│   └── zh/                      # 中文翻译，结构由 CI 门把关
├── prompts/                     # SessionStart + 每轮注入（含 zh/）
├── hooks/
│   ├── hooks.json               # 事件 → 脚本的接线
│   └── scripts/
│       │                        # —— 钩子入口（hooks.json 注册的四个）——
│       ├── inject_context.py    # 软层：SessionStart + 每轮注入
│       ├── read_guard.py        # 硬层：改前必读、内容与频率闸门
│       ├── bash_guard.py        # 硬层：命令纪律、read 登记
│       ├── stop_guard.py        # 硬层：九层完成声明闸门
│       │                        # —— 辅助入口（不是钩子）——
│       ├── register_read.py     # SHA-256 校验的 read 缓存逃生口
│       ├── manage_edicts.py     # 圣旨 CRUD 命令行
│       ├── gc_state.py          # 会话状态回收：CLI + auto-GC 被调方
│       ├── i18n_check.py        # 骨架 ↔ 翻译的结构对等检查
│       └── lib/                 # —— 八个共享模块 ——
│           ├── srclex.py        # 判定：代码 / 注释 / docstring / 数据字面量
│           ├── mdctx.py         # 判定：markdown 围栏 / 引用块上下文
│           ├── shellcmd.py      # 判定：tokenize → 分段 → argv → 子命令
│           ├── state.py         # 状态：会话状态、跨进程锁、原子落盘
│           ├── tomlio.py        # 配置：容忍 BOM 与编码异常的 TOML 读取
│           ├── projroot.py      # 配置：项目根判定，两个加载器共用
│           ├── edicts.py        # 功能：圣旨加载 / 匹配 / 渲染
│           └── sync_gate.py     # 功能：rule-12 连带更新组求值
├── commands/                    # 5 个 slash 命令
├── agents/verifier.md           # 只读引用核验子代理
├── skills/                      # systematic-debug、repo-refresh（自动唤起）
├── docs/                        # 索引 + ARCHITECTURE、RULES、EDICTS、I18N
└── tests/                       # 565 个测试（python -m unittest discover tests）
    │                            # 每个文件以它覆盖的对象命名——见 tests/README.md
    ├── _helpers.py              #   共享的 run_hook(...) 子进程夹具
    ├── test_<hook>.py           #   四个钩子入口的黑盒子进程测试
    ├── test_<lib|cli>.py        #   共享模块与辅助脚本的单元件
    ├── test_version_sync.py     #   漂移门：所有版本指针 vs plugin.json
    ├── test_doc_sync.py         #   漂移门：文档里的数字与清单 vs 代码
    ├── test_i18n_sync.py        #   漂移门：每份翻译 vs 英文骨架
    └── test_audit_*.py          #   历次审计轮的回归套件（v026 ×2、v027）
```

全部脚本由 [`tests/`](tests/) 下 **565 个测试**覆盖——黑盒子进程测试按 Claude
Code 的真实方式启动每个钩子（脚本被 import 与被调用时，模块级状态、stdin、
stdout 缓冲和退出码的行为都不同），另有共享模型的单元测试与三道漂移门。
CI：ubuntu-latest × windows-latest × Python 3.13，`fail-fast: false`，零依赖。
Windows 那条腿不是走形式——本仓库好几个回归天生只在 Windows 出现
（`os.replace` 共享冲突、`\r\n` 破坏行尾锚点、不加引号的盘符路径）。

---

## v0.30.0 新增

**对插件自身做一次结构体检** —— 没有新规则，也没有新检测器。三条发现，
一个主题：**写下来的约束不等于被执行的约束。**

- **删死代码，而不是给死代码写说明。** 七处生产符号已不可达：`_split_command`
  与两个正则是 v0.26 换成解析模型后留下的残骸；`_has_rationale` 及其两个辅助
  函数已被 `_has_rationale_at` 取代；`_escape_triple_quoted` 标着"仅为外部调用者
  保留"，而根本不存在能够到它的调用者。一个退役的理由检查器摆在在用的那个旁边
  不是"保留历史"：下一个读代码的人无法判断守卫实际调用的是哪一个。
- **三处重复判定各收敛为一处。** markdown 围栏解析存在三份（`stop_guard`、
  `lib/mdctx`、`i18n_check`），每份都各自抄了一遍同一个 v0.25 CommonMark 修复。
  项目根判定存在两份，第二份还注着"与 lib/edicts.py 同一套启发式"——一句**点名了
  不变量却并不持有它**的话。现在各有唯一定义（新增
  [`lib/projroot.py`](hooks/scripts/lib/projroot.py)）。
- **Stop 状态表不再说假话。** 层的显示顺序是 (a)…(i)，求值顺序却把 (b) 放在最前，
  而表格的 Pass/pending 两种判定都取自**显示**序——于是每一次 hedge 拦截都会打印
  "(a) ✅ Pass"，在 `_has_evidence` 根本没被调用的那一轮断言"已找到收敛证据"。
  已修复，并配了双向孪生测试。

文件树是**重新分类**而不是重新摆放：测试文件把类别写进文件名前缀，
`hooks/scripts/` 在树里就地标注三种角色，`docs/` 补了索引。四个非钩子脚本
**刻意没有**搬进 `tools/`——其中两个是被钩子内部调用的，搬走等于拿一个更好看的
目录名去换一段真实的跨目录 import。

`CLAUDE.md` 从 87 KB 缩到 39 KB：它的"当前版本"一节早已长成 changelog 的逐字
副本，而这份副本每次会话都会被整份读进上下文。测试 564 → 565 个。

历史版本见 [`CHANGELOG.md`](CHANGELOG.md)。

---

## 参与开发

这个插件用自己的规则管自己的开发——改它的时候你会被它拦。开 PR 前先读
[`CLAUDE.md`](CLAUDE.md) §4：

1. 改之前把每个相关文件从头读到尾。
2. 追踪下游影响——改一条规则意味着同一次改动里要更新 prompt、文档、清单和翻译。
3. 引用 `file:line`；不写"我觉得""应该是"。
4. 修根因。不用 `--no-verify`，不吞异常。

---

## 许可证

MIT —— 见 [`LICENSE`](LICENSE)。
