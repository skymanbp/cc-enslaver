# 圣旨 — User-Defined Imperial Edicts

> Project-specific hard rules that ride on top of cc-enslaver's built-in
> 9 rules. v0.12 introduces this as a layer-0 customisation mechanism.

---

## 1. Why 圣旨

The built-in 9 rules cover general AI laziness patterns (verify don't
guess, root cause not symptom, etc.). But every project has its own red
lines that no general rule can cover:

- "禁止使用 mongoose，统一用 prisma"
- "所有 API 必须经过 `src/api/client.ts`"
- "禁止在 React 组件里直接调用 fetch"
- "不允许在 .map 里 await"
- "数据库迁移文件必须配对一份 rollback"

These are **per-project**, **user-defined**, and ideally **physically
enforced** (not just soft reminders that get ignored). 圣旨 is that.

The metaphor: built-in rules are constitutional law; 圣旨 is project
royal decree — more specific, top priority, can override default
suggestions, but cannot override constitutional safeguards (the built-in
hooks still run first).

---

## 2. File format

Location: `${CLAUDE_PROJECT_DIR}/.claude/cc-enslaver/edicts.toml`.
Fallback: `~/.claude/cc-enslaver/edicts.toml` (personal global).

Format: TOML, array of tables.

```toml
[[edicts]]
id = "E01"                                  # required: unique short id
text = "禁止使用 mongoose，统一用 prisma"   # required: imperative text shown to the agent
severity = "must"                           # "must" (default) | "should"
deny_edit = ['''from ["']mongoose["']''']   # optional: regex list, matched against Edit/Write content
deny_bash = ['''npm (i|install) mongoose''']  # optional: regex list, matched against Bash commands
note = "已统一到 prisma；mongoose 在 PR #142 移除"  # optional: rationale shown in deny reason

[[edicts]]
id = "E02"
text = "所有 API 必须经过 src/api/client.ts"
severity = "should"                         # soft layer only: injected as reminder, NOT physically enforced
```

### Fields

| Field | Required | Type | Description |
|---|---|---|---|
| `id` | yes | string | Unique short id (any string). Appears in deny reasons. |
| `text` | yes | string | Imperative one-liner the agent sees in the injection. |
| `severity` | no (default `must`) | `"must"` \| `"should"` | `must` = physically DENY on regex match. `should` = soft reminder only. |
| `deny_edit` | no | list[string] | Regexes matched against Edit/Write `new_string` / `content`. |
| `deny_bash` | no | list[string] | Regexes matched against Bash `command`. |
| `note` | no | string | Optional context shown in the deny reason (e.g. PR link, ticket id). |

### Regex tips

- **Use triple-quoted strings** (`'''...'''`) — TOML's single-quoted
  literal strings need no escaping inside, so your regex stays readable.
- Regexes use Python's `re` syntax. Test interactively with
  `python -c "import re; print(re.search(r'PATTERN', 'TEST_STRING'))"`.
- Each edict can have multiple `deny_edit` / `deny_bash` patterns; any
  match triggers the deny.
- A broken regex is **skipped with a stderr warning**; the other
  patterns in the same edict still apply.

---

## 3. Enforcement contract

| Layer | When | Behavior |
|---|---|---|
| Soft (SessionStart) | At session boot | All edicts (must + should) injected as a markdown table. Survives the entire session. |
| Soft (UserPromptSubmit) | Every user turn | Re-injected to survive context compaction. |
| Hard (`PreToolUse(Edit\|Write)`) | When agent calls Edit / Write | For each `must` edict with `deny_edit`: scan `new_string` / `content`. First match → DENY with reason naming the edict id. |
| Hard (`PreToolUse(Bash)`) | When agent calls Bash | For each `must` edict with `deny_bash`: scan `command`. First match → DENY. |

**Built-in rules always run first.** The order in `read_guard.py` is:

1. read-before-edit guard (rule 04 + 08)
2. patch-style marker guard (rule 09)
3. **圣旨 scan**

Order in `bash_guard.py`:

1. `--no-verify` / `--no-gpg-sign` / force-push / `chmod 777` (rule 03 + 09)
2. `register_read.py` escape hatch (v0.4.0)
3. **圣旨 scan**

You cannot define an edict that whitelists `--no-verify` — the built-in
hook fires before reaching the edict layer.

---

## 4. Managing edicts

### Slash command (`/cc-enslaver:edict`)

```
/cc-enslaver:edict list
/cc-enslaver:edict add E01 "禁止 mongoose" --must --deny-edit 'mongoose' --deny-bash 'npm i mongoose'
/cc-enslaver:edict remove E01
/cc-enslaver:edict path
```

### Direct CLI

```bash
python "${CLAUDE_PLUGIN_ROOT}/hooks/scripts/manage_edicts.py" list
python "${CLAUDE_PLUGIN_ROOT}/hooks/scripts/manage_edicts.py" add ID "TEXT" [--must|--should] \
    [--deny-edit REGEX]* [--deny-bash REGEX]* [--note NOTE]
python "${CLAUDE_PLUGIN_ROOT}/hooks/scripts/manage_edicts.py" remove ID
```

### Hand-edit

The file is small enough to edit directly. Changes take effect on the
next hook event — no reload needed (the loader reads disk on every
invocation).

---

## 5. Examples

### Block a specific library

```toml
[[edicts]]
id = "E01"
text = "禁止使用 mongoose，统一用 prisma（PR #142 已迁移）"
severity = "must"
deny_edit = [
    '''from ["']mongoose["']''',
    '''require\(["']mongoose["']\)''',
    '''import .* from ["']mongoose["']''',
]
deny_bash = [
    '''npm\s+(i|install)\s+.*\bmongoose\b''',
    '''yarn\s+add\s+.*\bmongoose\b''',
]
note = "see PR #142 / RFC 0007"
```

### Enforce architecture boundary (soft)

```toml
[[edicts]]
id = "E02"
text = "所有 HTTP 调用必须通过 src/api/client.ts；不要直接用 fetch / axios"
severity = "should"  # soft -- complex to regex perfectly, prefer reminder
```

### Block a known footgun

```toml
[[edicts]]
id = "E03"
text = "禁止在 .map / .forEach 内 await（用 Promise.all + map）"
severity = "must"
deny_edit = [
    '''\.(map|forEach)\s*\(\s*(?:async\b[^)]*=>|\([^)]*\)\s*=>\s*\{[^}]*\bawait\b)''',
]
note = "并发会被串行化；用 Promise.all(arr.map(async ...))"
```

---

## 6. Limitations & future work

- **Per-session ephemeral edicts** (e.g. `/cc-enslaver:edict add --session ...`)
  not yet supported. Add an edict to the file or pass `--should` for a
  light-touch reminder instead.
- **Global ~/.claude fallback** is loaded but the `add` CLI only writes
  to `${CLAUDE_PROJECT_DIR}`. Hand-edit `~/.claude/cc-enslaver/edicts.toml`
  for personal-global edicts.
- **No exception mechanism** — an edict either matches or it doesn't.
  If you want a per-file exemption, write a more specific regex or
  remove the edict.
- **Regex is the only matcher.** AST-based / semantic matching is out of
  scope; if you need it, write a custom hook in `hooks/hooks.json`.

See [`CHANGELOG.md`](../CHANGELOG.md) §0.12 for the full enforcement
contract changelog.
