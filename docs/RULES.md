# Rule Catalog

> 索引版本。每条规则的**完整正文**位于 [`../rules/`](../rules/) 目录下；
> 本文档仅做摘要、severity、关联组件指引。
>
> 修改任意一条规则时，请按 [`../docs/ARCHITECTURE.md`](./ARCHITECTURE.md) §8
> 表格同步检查所有连带文件。

## 语言

- **English（骨架 / source of truth）** — [`../rules/01-*.md` ~ `../rules/12-*.md`](../rules/)（root 层）。英文是**骨架语言**：钩子注入默认英文（`prompts/` root），任意其它层的规则语义都以英文骨架为准。命令 / skill 的**正文**用中文书写（作者语言，可以是任意语言），但它们引用的规则**定义**以英文骨架为准。
- **中文翻译** — [`../rules/zh/`](../rules/zh/)。逐节跟随英文骨架、与英文 1-1 对应；**如出现 drift，以英文骨架为准**（CI 硬门 [`../hooks/scripts/i18n_check.py`](../hooks/scripts/i18n_check.py) 会拦，见 [`I18N.md`](./I18N.md)）。运行时用 `CC_ENFORCER_LANG=zh` 切换注入语言；任意新语言放 `rules/<code>/` + `prompts/<code>/`，缺失文件自动回退英文骨架。

---

## 规则编号约定

- 编号格式：`<两位数>-<kebab-case-名>.md`
- 编号一旦发布**不再回收**（即使规则被废弃，也不复用编号）。
- 当前编号区间：`01–12`。

---

## 规则一览

| ID  | 标题 | Severity | 完整文件 | 主要适用场景 |
|----:|------|---------|----------|--------------|
| 01 | 验证而非猜测 | **must** | [`../rules/01-verify-dont-guess.md`](../rules/01-verify-dont-guess.md) | 任何关于文件、API、版本、文献、报错信息的断言 |
| 02 | 系统式而非反应式 | **must** | [`../rules/02-systematic-not-reactive.md`](../rules/02-systematic-not-reactive.md) | 修 bug、改架构、重构、添加功能 |
| 03 | 修根因，不修症状 | **must** | [`../rules/03-root-cause.md`](../rules/03-root-cause.md) | 异常处理、测试失败、CI 失败、竞态、钩子失败；v0.28 起含上游溯源阶梯（症状位 → 传播路径 → 起源）与确诊先行 |
| 04 | 完整阅读，拒绝关键词依赖 | **must** | [`../rules/04-full-context.md`](../rules/04-full-context.md) | 编辑文件前、跨文件影响分析 |
| 05 | 引用必须可追溯 | **must** | [`../rules/05-cite-sources.md`](../rules/05-cite-sources.md) | 任何对外陈述（PR 描述、回复用户、报告） |
| 06 | 验证收敛 | **must** | [`../rules/06-verify-convergence.md`](../rules/06-verify-convergence.md) | 任何修复 / 更新 / 补丁完成后的强制收敛验证 |
| 07 | 任务忠实 | **must** | [`../rules/07-task-fidelity.md`](../rules/07-task-fidelity.md) | 任何任务声称完成前的请求覆盖、无降级、无遗漏二次确认 |
| 08 | 改前必读，写前必想 | **must** | [`../rules/08-read-before-edit-think-before-write.md`](../rules/08-read-before-edit-think-before-write.md) | 任何 `Edit` / `Write` 前的前置硬纪律（v0.11 物理强制）|
| 09 | 系统式修改，禁止打补丁 | **must** | [`../rules/09-systematic-modification.md`](../rules/09-systematic-modification.md) | 修改过程中的反补丁内容拦截（v0.11 物理强制）；v0.28 起含"一个根因，一次统一修复"（同类清扫，禁点对点补丁）|
| 10 | 禁止非必须硬编码 | **must** | [`../rules/10-no-hardcoding.md`](../rules/10-no-hardcoding.md) | 修改过程中把本应是配置/环境的密钥/凭证内联成代码字面量的内容拦截（v0.22 物理强制）|
| 11 | 禁止非必须路径依赖 | **must** | [`../rules/11-no-path-dependency.md`](../rules/11-no-path-dependency.md) | 修改过程中把机器特定的 user-home 绝对路径硬编码进代码的内容拦截（v0.22 物理强制）|
| 12 | 全库同步 —— 连带更新每一处引用 | **must** | [`../rules/12-repo-wide-sync.md`](../rules/12-repo-wide-sync.md) | 修改收尾的全库引用清扫（被动：sync-gate + Stop layer (i)，v0.23 物理强制）+ 按需全库陈旧/过时/冗余/错误/漂移扫描（主动：`repo-refresh` skill）|

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
       ╔══════════════════════════════════════╗
       ║ 10 无硬编码 / 11 无路径依赖（内容值约束 · 物理强制）║
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
       └─────────────────┬────────────────────┘
                         │
                         ▼
       ╔══════════════════════════════════════╗
       ║ 12 全库同步（仓库引用图轴 · sync-gate 物理强制）║
       ╚══════════════════════════════════════╝
```

- **01 / 04 / 05** 是**输入端**约束：决定 agent 如何获取与陈述事实。
- **02** 是**思考过程**约束：决定 agent 如何把事实组织成方案。
- **08** 是**修改前置硬纪律**：把 04 + 02 折叠成 `Edit` / `Write` 之前的最低必答清单，并由 PreToolUse + Stop layer (e) 物理强制（v0.11）。
- **03** 是**输出端 (改什么)** 约束：决定 agent 修改代码时是否触达根因。v0.28 起 03 拥有**上游溯源阶梯**：症状位 / 传播路径 / 起源三级——修在前两级都算补丁；停在中途必须显式点名真正起源并说明理由；根因假设先经第一方证据**确诊**再动手。
- **09** 是**输出端 (怎么改)** 约束：把 03 的"反偷懒"升级为修改内容层的硬纪律，由 PreToolUse new_string 内容检测 + Stop layer (f) 物理强制（v0.11）。v0.28 起 09 增加**统一修复**要求：确诊的根因定义一个"类"，全库同类实例一次修完，点对点补丁被明令禁止。
- **06** 是**输出端 (改完之后 · 技术面)** 约束：决定 agent 是否真的把根因解决到收敛、是否经得起验证。
- **07** 是**输出端 (改完之后 · 契约面)** 约束：决定 agent 是否把用户**要求的全部**按**原标准**交付（无遗漏、无降级、无范围溢出）。06 与 07 互补：06 解决"症状-根因"轴，07 解决"请求-交付"轴。
- **08 与 09 互补**：08 是修改**前**的"准备充分了吗"，09 是修改**内容**的"姿势对了吗"。08 在 PreToolUse 的"已读检查"上 + Stop layer (e) 的"系统式自答"上落地；09 在 PreToolUse 的"new_string 内容检测"上 + Stop layer (f) 的"根因 + 影响 + 方案三件套"上落地。
- **10 / 11 是内容值约束**（v0.22）：09 拦"打补丁的姿势"，10 / 11 拦"塞进内容的值本身"——本应外化为配置/环境的密钥凭证（10）、本应运行时派生的机器特定路径（11）。三者共享 PreToolUse(Edit|Write) new_string 内容检测机制、共用 why-comment 逃生舱把"非必须"落地为可验证判定；与 09 不同的是 10 / 11 **无 Stop layer**（内容检测器一律 PreToolUse-only，避免对已被拦截的写入双重追责）。
- **检测器的"能被绕过 = 等于没有"（v0.25）**：三个内容检测器在 v0.25 各补了一处
  语法盲区，共同的教训是**逃生舱必须真的被读到，而不是靠改变字符串让检测器沉默**。
  rule 09 的 `try/except: pass` 此前要求 `pass` 完全裸露，于是行尾加任意注释即可
  放行——包括那条本该被审查的 why 注释，等于逃生舱对该标记从未生效；同时一个 `try`
  只看第一个 `except`，放过了"窄 handler + 兜底吞掉"这个最典型形态。rule 10 的密钥
  匹配要求分隔符紧跟关键字，于是 JSON / 带引号键 YAML（`"api_key": "…"`，最常见的
  凭证形态）全部漏过。判定这类缺口的方法是**形态矩阵**：对同一语义列出所有合法书写
  形式，逐个过检测器，而不是只测自己脑子里那一种写法。
- **"概念"要由模型回答，不是由更多正则回答（v0.26.0）**：v0.25.1 点名了下面那条
  根因，却只修了它的**实例**；第四轮审阅（审的是 v0.25.1 自己的修复 diff）证明机制
  一旦留着，同一根因立刻长出新一批——**包括一个倒退**：嵌套 `try/except` 从 v0.25.0
  的 DENY 变成 v0.25.1 的 allow，而那次重写的 docstring 正宣称"现在用栈处理嵌套"。
  修法是把四个反复被猜的结构性问题交给**共享模型**回答：
  [`lib/srclex.py`](../hooks/scripts/lib/srclex.py)（这个 `#` 是注释 / docstring /
  数据？这个字面量到哪结束？哪些物理行是一条逻辑行？——刻意选**词法器**而非
  `ast`/`tokenize`，因为 Edit 的 `new_string` 通常不是完整语法单元）、
  [`lib/mdctx.py`](../hooks/scripts/lib/mdctx.py)（这一行是 agent 自己的断言，还是
  被引用 / 被围栏包住的示例？——Stop layer (h) 的**两个半区现在共用它**，此前它们
  各持一份残缺副本且结论不一致）、[`lib/shellcmd.py`](../hooks/scripts/lib/shellcmd.py)
  （这条命令真正执行的是什么？git 子命令是哪个？python 的脚本操作数是哪个？），
  以及 state 的 **schema 归一**（不再只修"这次抛异常的那个字段"）。判定这类缺口的
  方法从"形态矩阵"升级为**"这个检测器在回答什么问题？它有资格回答吗？"**。
- **检测器描述的必须是"概念"而不是"字符串"（v0.25.1）**：上一条只补了单个盲区，
  v0.25.1 的第三轮审阅发现同一根因还有**九种拼写**在外面——CRLF 让五个单行标记
  全部失效（本插件主平台就是 Windows）；任意尾随文本让标记**根本不匹配**，于是
  `@ts-ignore` 后跟一个光秃秃的延期词反而放行、而理由检查从未运行；把理由写在
  `pass` **上面独立一行**（最自然的写法）会把吞错行挪出扫描器视野，逃生舱依旧
  不可达——v0.25 只修了同行写法，还配了一条因错误原因而通过的回归测试；
  `except X: pass` 单行形、`time.sleep(max(0, d))` 嵌套括号、
  源码里**成对**反斜杠的 `"C:\\Users\\bob"`、`git -C repo push --force`、
  引号形 `"--force"`、`+refspec`、`--mirror` 同样全在外面。
  推论一：**理由必须真的是注释**。逃生舱此前搜整个原始窗口，于是
  `reason = compute()` 这种普通代码里的 token 就能让标记沉默。
  推论二：**每条"带理由应放行"的测试必须配一条"去掉理由必须拦"的孪生断言**，
  否则测试可能只是因为检测器从未触发而通过——这正是本仓库连续两个版本踩中的形态。
- **配置读进来的值必须先验类型（v0.25.1）**：`severity = ["must"]` 与
  `mode = []` 都是合法 TOML，而 `值 not in 集合` 抛 `TypeError: unhashable type`，
  逃出两个 docstring 自称"never raises"的 loader，落进最外层 failing-open——
  rule 04 + 08 整场失效，Stop layer (i) 连同回合边界的 `clear_edit_flag` 一起没了。
  与 v0.25 那条编码缺陷是同一个洞的两扇门：那次加固的是**文件怎么读**，
  这次加固的是**读出来的值能是什么**。
- **点对点补丁升级为"溯源 → 确诊 → 统一修复"硬纪律（v0.28.0）**：问题出现时禁止
  逐处修补。rule 03 新增上游溯源阶梯（沿因果链上爬到机制 / 设计决策 / 缺失不变量
  为止，停在中途必须显式说明），rule 09 新增"一个根因，一次统一修复"（确诊先于
  动手；确诊的根因定义一个类，全库同类实例枚举后一次修完；验证还要重触发类里
  另一个实例以证明类已闭合，类只有一个成员时显式说明即可）。动机是本仓库自己的实测史：v0.25.1 点名了根因却只修
  实例，机制存活并在 v0.26 再生出同一类新缺陷（含一个倒退）；v0.26 换机制（33 条
  finding → 三个根因 → 四个统一件）才收口——v0.28 把那次的做法固化为每次修复的
  强制形态。与 v0.22.1 同一先例，**零新检测器**：这是推理形态而非钩子可匹配的语法
  形态，落在规则文本 + 注入表；既有硬层（补丁标记内容层、rolling-patch 频率层、
  Stop layer (f) 三件套）仍是物理地板。
- **12 是输出端（仓库引用图轴）约束**（v0.23）：06 收敛"被改的部分"，07 覆盖"用户要的部分"，12 补上"仓库其余部分跟着走"——所改内容的全库引用（文档 / 下游 / 测试 / 镜像翻译）必须连带更新或显式核对。被动半区由项目级 `.claude/cc-enforcer/sync-gate.toml` + Stop layer (i) 物理强制（组未满足且无 `同步核对` / `sync-check` 标记 → BLOCK；无配置的项目该层关闭）；主动半区是 `repo-refresh` skill 的全库五类缺陷扫描。

---

## 各组件如何引用这些规则

| 组件 | 引用方式 |
|------|---------|
| [`../prompts/session-start.md`](../prompts/session-start.md) | 全部 12 条规则的浓缩版（v0.11 加入 rule 08 / 09；v0.20 标准回答骨架改为 YAML 回复 schema + `tldr` 大白话收尾；v0.23 加 tldr 长度硬约定 + rule 12） |
| [`../prompts/user-prompt.md`](../prompts/user-prompt.md) | 12 条规则的结构化每轮自检清单（v0.11 重构；v0.20 收尾骨架改 YAML schema；v0.23 加 tldr 长度 + rule 12 触发行）|
| [`../commands/checklist.md`](../commands/checklist.md) | 把 12 条规则映射成可勾选的检查项（A 改前 / B 改后 / C 收敛验证 / D 任务忠实 / E 改前必读·写前必想 / F 系统式修改 / G 大白话 TL;DR 收尾 / H 全库同步） |
| [`../agents/verifier.md`](../agents/verifier.md) | 主要执行规则 05（引用可追溯）+ 规则 01 的事后验证；同时尊重规则 07 + 08 |
| [`../skills/systematic-debug/SKILL.md`](../skills/systematic-debug/SKILL.md) | 主要执行规则 02 + 03 + 06 + 08 + 09 |
| [`../skills/repo-refresh/SKILL.md`](../skills/repo-refresh/SKILL.md) | 规则 12 主动半区：全库陈旧 / 过时 / 冗余 / 错误 / 漂移扫描（v0.23）|
| [`../hooks/scripts/read_guard.py`](../hooks/scripts/read_guard.py) | 规则 04 + 08（read-before-edit）+ 规则 09（new_string 补丁标记物理拦截 + rolling-patch **频率**策略）+ 规则 10 + 11（硬编码 / user-home 路径依赖内容检测）+ 规则 12（edited_files 会话记录，v0.23）|
| [`../hooks/scripts/lib/editscale.py`](../hooks/scripts/lib/editscale.py) | 规则 09 的**规模判定**（v0.35）：small / systematic / medium 分类（含相对目标文件的 30% 覆盖率通道）+ 两个豁免（净减少、记账类）。频率策略留在 read_guard，这里只回答"这次改动相对它所改的东西有多大" |
| [`../hooks/scripts/bash_guard.py`](../hooks/scripts/bash_guard.py) | 规则 03 + 09（bypass 模式拦截）|
| [`../hooks/scripts/stop_guard.py`](../hooks/scripts/stop_guard.py) | 规则 06 layer (a)(c) + 规则 01 layer (b) + 规则 07 layer (d) + 规则 08 layer (e) + 规则 09 layer (f) + 规则 01+06 layer (g) + TL;DR 收尾约定 layer (h, v0.20；v0.23 加单条长度上限，v0.35 改按 160 **显示列**计) + 规则 12 sync-gate layer (i, v0.23) |
| [`../hooks/scripts/lib/sync_gate.py`](../hooks/scripts/lib/sync_gate.py) | 规则 12 被动半区：`.claude/cc-enforcer/sync-gate.toml` 加载 + 连带组求值（v0.23）；写目标解析（`default_project_path`，确定性）与 glob 匹配（`matches_any`，与门禁共用唯一定义）v0.31 |
| [`../hooks/scripts/manage_sync_gate.py`](../hooks/scripts/manage_sync_gate.py) + [`../commands/sync-gate.md`](../commands/sync-gate.md) | 规则 12 的**配置编写与体检**（v0.31）：`init / list / check / add / remove / path`。`check` 是关键——加载器 failing-open，被丢弃的组与打不中文件的 glob 都不会报错，只会静默停止守护；`check` 把两者点名并以退出码 1 结束，可进 CI（本仓库自 v0.32 起对自己的配置断言它） |

---

## 添加新规则的流程

1. 在 [`../rules/`](../rules/) 下创建 `13-xxx.md`（v0.23 起编号区间是 01–12，新规则从 13 开始）。
2. 文件必须包含 YAML frontmatter（参考现有任意规则的开头）：
   ```yaml
   ---
   id: "13"
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
