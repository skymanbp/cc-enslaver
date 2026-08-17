---
description: 管理本项目的 rule 12 同步门禁（sync-gate.toml）—— init / list / check / add / remove / path。check 会报出「被 loader 丢弃的组」与「打不中任何文件的 glob」。
argument-hint: "check | list | init | add NAME --when GLOB --require GLOB [--all] [--note ...] | remove NAME | path"
---

# /cc-enslaver:sync-gate

> rule 12 的**被动半区**由 `.claude/cc-enslaver/sync-gate.toml` 驱动：某组的
> `when` glob 命中了本会话编辑过的文件，而 `require` 侧一个都没动 → Stop
> layer (i) 拦下完成声明（除非回复里有 `同步核对:` / `sync-check:` 标记）。
> 本命令调用 [`hooks/scripts/manage_sync_gate.py`](hooks/scripts/manage_sync_gate.py)。
> 机制说明见 [`rules/12-repo-wide-sync.md`](rules/12-repo-wide-sync.md)。

## 为什么必须有 `check`

`sync_gate.load()` 是**故意 failing-open** 的：配置解析失败、某个组缺
`when`/`require`、某个 glob 打不中任何文件 —— 这些情况下它都**不报错**，只是
静默地不再守护，外加一行没人看的 stderr。

后果是：**一道你以为在守着、其实早就失效的门，比没有门更坏**，因为你不会再去
看它。`check` 就是唯一能戳破这层的东西。

## 子命令

| 子命令 | 作用 |
|---|---|
| `check` | 打印 loader 实际解析出的组 + **被丢弃的组**（写在文件里但 loader 不认）+ **打不中任何文件的 glob**。有任何问题 → 退出码 1，因此可以直接进 CI。 |
| `list` | 只打印实际加载的组（`check` 的安静版）。 |
| `init` | 生成带注释的模板（0 个组）。**已存在则拒绝覆盖。** |
| `add` | 追加一组，写前双重校验（见下）。 |
| `remove` | 按名字删一组。 |
| `path` | 打印解析到的配置路径。 |

## 你（receiving agent）要做的

```bash
python "${CLAUDE_PLUGIN_ROOT}/hooks/scripts/manage_sync_gate.py" check
python "${CLAUDE_PLUGIN_ROOT}/hooks/scripts/manage_sync_gate.py" init
python "${CLAUDE_PLUGIN_ROOT}/hooks/scripts/manage_sync_gate.py" \
    add rules-fanout --when 'rules/*.md' --require 'docs/RULES.md' \
    --note '改规则要同步索引'
python "${CLAUDE_PLUGIN_ROOT}/hooks/scripts/manage_sync_gate.py" remove rules-fanout
```

参数：
- `--when GLOB` / `--require GLOB`：可重复。对**项目相对路径**做 fnmatch，
  `*` **跨路径分隔符**（所以 `rules/*.md` 也覆盖 `rules/zh/`）。
- `--all`：`mode = "all"`，**每一个** require glob 都必须有编辑命中。用于
  锁步不变量（例：`plugin.json` 改了，`marketplace.json` 与 `CHANGELOG.md`
  必须双双跟上——只跟一个正是 v0.22.1 的翻车形态）。不加则是 any-of。
- `--note`：为什么这几个文件必须一起动。会出现在 layer (i) 的拦截理由里，
  所以写给"三个月后的自己"看。

## 写入契约

`add` / `remove` 会**重写整个文件**，落盘前过两道：

1. **能不能解析回来**（`tomlio.dumps_check`）—— 序列化 bug 不许把配置写坏。
2. **loader 认不认**（用真正的 `sync_gate.load_file` 回读）—— 一个 `require = []`
   的组是**合法 TOML**，但会被 loader 静默丢弃。只做第 1 道的话，CLI 会报告
   "已添加"，而那一组什么也不守。任何一组回读不到 → 拒写并原样还原文件。

写入目标由 `CLAUDE_PROJECT_DIR` → 带 `.git`/`.claude` 标记的 cwd **确定性**解析，
**不会**去搜索"哪里已经有一个配置文件"。没有 `--global`：glob 是仓库相对的，
一个组离开它的仓库就没有意义。

## 禁止

- ❌ **不要**替用户凭猜测 `add` 分组。sync-gate 的价值在于**人**断言了"这几个
  必须一起动"；启发式猜出来的组是伪造的确信（rule 01）。发现耦合 → 报告给用户，
  由用户决定是否登记。
- ❌ **不要**用 `remove` 来让一次 layer (i) 拦截消失。那是把温度计砸了。要么真去
  同步 require 侧，要么写一行 `同步核对: <为什么不用改>`。
- ❌ 不要手改完 TOML 就宣称配好了 —— 跑 `check`，否则你不知道 loader 认了几组。

## 与 `repo-refresh` 的关系

[`skills/repo-refresh/SKILL.md`](skills/repo-refresh/SKILL.md) 的收尾步骤要求把
本次扫描发现的可复发连带关系登记进 sync-gate。在此之前它只能让 agent 手搓 TOML；
现在它应当调用本命令的 `add`，并以 `check` 收尾。
