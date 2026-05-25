# Changelog

All notable changes to **cc-enslaver** are documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and
this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [Unreleased]

### Planned (roadmap)

- **Stop hook deep file-claim verification** — parse "I edited X" patterns
  in the agent's last message and check `git diff` / mtime against a
  session-start baseline. Catches the "claim edited but didn't" lying
  pattern.
- **Per-session ephemeral 圣旨** — `/cc-enslaver:edict add --session ...`
  for one-shot prompts (currently 圣旨 is project-persistent only).

---

## [0.15.0] — 2026-05-25

**English prompts mirror + `CC_ENSLAVER_LANG=en` injection switch.**

Closes the v0.6.2 / v0.11 follow-up: `rules/en/` has shipped all 9
rules in English since v0.6.2, but `prompts/` (the soft layer
injected at SessionStart / UserPromptSubmit) was Chinese-only. English
Claude Code users were getting English rule references but Chinese
discipline injections. v0.15 ships the matching `prompts/en/*.md` and
the language-switch plumbing.

### Added

- **`prompts/en/session-start.md`** — English mirror of the 9-rule
  table, the physical-enforcement table, the standard reply skeleton,
  the decision-time triggers, and the docs locations. Same density as
  the Chinese canonical (~95 lines).
- **`prompts/en/user-prompt.md`** — English mirror of the 13-row
  decision triggers table (~30 lines).
- **`hooks/scripts/inject_context.py`**:
  - `_resolved_lang()` reads `CC_ENSLAVER_LANG` env var
    (`zh` default; `en` switches; any other value falls back to `zh`
    fail-safe).
  - `load_prompt()` tries `prompts/en/<file>` when `lang == "en"`;
    falls back to `prompts/<file>` Chinese canonical with stderr
    warning if the English file is missing.

### Tests (+4)

`TestInjectContextEnglish`:
- `test_lang_en_uses_english_session_start` — keyword contract for
  English (Verify don't guess / Did this really solve the problem /
  rule 08 / layer (e), etc.) + asserts Chinese headers do NOT bleed
  through (proves the en/ file is actually being read).
- `test_lang_en_uses_english_user_prompt` — keyword contract for
  per-turn English injection.
- `test_unknown_lang_falls_back_to_chinese` — `CC_ENSLAVER_LANG=fr`
  must not drop the injection.
- `test_no_lang_env_var_uses_chinese` — defensive default-path test.

Existing 11 `TestInjectContextSessionStart` keyword-contract tests
still pass — Chinese remains the no-env-var default.

### Why default is `zh`, not the system locale

The user is a Chinese speaker (CLAUDE.md §5), the rules are written
in Chinese canonical, and most existing test contracts assert
Chinese phrases. Defaulting to system locale would silently flip
behavior on different developer machines (CI, Windows-vs-Linux,
LANG=C, etc.). Explicit opt-in via `CC_ENSLAVER_LANG=en` keeps
behavior deterministic.

### Tests: 154 → 158 (+4)

### Docs

- `CLAUDE.md` §3 repo tree: `prompts/en/` subdirectory + the v0.15
  switch note added.
- `CLAUDE.md` §5 metadata: `CC_ENSLAVER_LANG=en` env-var note.

---

## [0.14.0] — 2026-05-25

**Three more Bash bypass patterns + 圣旨 polish (global scope + CLI tests).**

A focused batch of v0.12/v0.13 roadmap items that share a theme: tighten
existing surfaces without introducing new architectural pieces.

### Added — three new Bash bypass patterns (rule 03)

`bash_guard.py` `STATIC_PATTERNS` now includes three additional regexes,
each with a positive deny case + at least one negative allow case in
`tests/test_bash_guard.py`:

| Pattern | Trigger | Rationale |
|---|---|---|
| `git rebase --skip` | `git rebase` followed anywhere by `--skip` | Skipping a conflict silently abandons the commit; conflicts are real semantic divergences (rule 03). Recovery: resolve, or `--abort`. |
| `--break-system-packages` | flag anywhere in the command | Bypasses PEP 668 protection; fix is venv / pipx / system package manager (rule 03). |
| `rm -rf` on root / `$HOME` / `~` | recursive force delete targeting `/`, system dirs (`/etc`, `/usr`, `/var`, etc.), `$HOME`, or `~/` | Catastrophic / irrecoverable; agents should surface to user, not act on their behalf (rule 03). Allows `rm -rf ./node_modules`, `rm -rf build/`, `rm -rf /tmp/foo`. |

Pattern-precedence-design note: `git reset --hard` was **not** added —
reliably detecting "with uncommitted changes" would require a
synchronous `git status` invocation inside the hook, which is too
invasive. False-positive rate would be high.

### Added — 圣旨 `--global` scope (v0.12 follow-up)

- **`hooks/scripts/manage_edicts.py`**:
  - `_global_path()` returns `~/.claude/cc-enslaver/edicts.toml`.
  - `add --global` writes to global file (was previously project-only).
  - `remove` falls back from project to global when not finding the
    edict in project; `remove --global` restricts to global file.
- **`commands/edict.md`**: documents `--global` for `add` and `remove`.
- **`docs/EDICTS.md`**: dedicated `--global` flag section + removed the
  "Limitations" entry that previously called this out as unsupported.

The loader's project-then-global resolution order is unchanged — project
edicts always take precedence when both files define the same id. The
add-CLI now matches that mental model on the write side too.

### Added — CLI subprocess test coverage (v0.12 follow-up)

`tests/test_edicts.py` gains two new test classes:

- **`TestManageCLI`** — 6 tests covering `path` on empty state, `add`
  writes + `list` reflection, add/remove round-trip, duplicate-id
  rejection, missing-id rejection, severity persistence.
- **`TestManageCLIGlobalFlag`** — 5 tests covering `--global` writes
  to HOME (not CLAUDE_PROJECT_DIR), loader fallback finds global file,
  project precedence over global in `list`, `remove` falls back to
  global, `remove --global` restricted to global only.

Both classes sandbox both `CLAUDE_PROJECT_DIR` and `HOME` so writes
land inside tmp dirs (no contamination of the real user's `~/.claude`).

### Tests: 143 → 154 (+11)

| Class | New tests |
|---|---|
| `TestBashGuardMatrix` (extended) | +14 matrix rows |
| `TestManageCLI` | +6 |
| `TestManageCLIGlobalFlag` | +5 |

### Changed — docs

- `commands/edict.md`: argument-hint includes `[--global]` for `add`
  and `remove`; subcommand table notes fallback behavior; one global-
  scoped example added.
- `docs/EDICTS.md`: new `#### --global flag (v0.14)` subsection;
  Limitations entry about hand-editing for global edicts removed.

---

## [0.13.0] — 2026-05-25

**Rule-09 rolling-patch frequency layer (hard interception).**

Closes the largest remaining v0.11 escape route: rolling patches were
soft-layer-only — Stop layer (f) checked for "root cause + impact +
solution" closing markers but could not see the per-file edit
*pattern*. An agent could pile up 6 small Edits to the same file,
surface the right tokens at Stop, and pass — even though the
aggregate behavior was the exact rule-09 anti-pattern. v0.13 moves
that check from soft Stop-layer fallback to a hard `PreToolUse(Edit|
Write)` deny at the moment of intent.

### Added — rolling-patch counter (rule 09 hard layer)

- **`hooks/scripts/lib/state.py`**:
  - `get_edit_count(session_id, file_path) -> int`
  - `record_small_edit(session_id, file_path) -> int` (increments,
    returns new count)
  - `reset_edit_count(session_id, file_path)` (clears on systematic
    rewrite)
  - New JSON field: `edits_per_file: {normalized_path: count}`.
- **`hooks/scripts/read_guard.py`**:
  - `_classify_change(old, new) -> "small" | "systematic" | "medium"`.
  - `_check_rolling_patch(old, new)` wired into both Edit and Write
    branches.
  - Constants at module top: `SMALL_EDIT_MAX_CHARS = 200`,
    `SMALL_EDIT_MAX_LINES = 10`, `SYSTEMATIC_MIN_CHARS = 1500`,
    `SYSTEMATIC_MIN_LINES = 50`, `ROLLING_PATCH_THRESHOLD = 4`.
  - New deny template `ROLLING_PATCH_DENY_TEMPLATE` explaining the
    counter state and three recovery paths (combine into systematic
    Edit / Write whole file / surface to user).
- **+8 tests** in `tests/test_read_guard.py::TestRollingPatchInterception`
  covering: 3-allowed-4th-denied, denied-attempt-doesn't-increment,
  systematic-Edit-resets, two-files-independent-counters, medium-edit-
  no-op, systematic-Write-resets, new-file-write-no-count, JSON-field-
  contract.

### Classification thresholds (rule 09 §"Edit/Write 频率层")

| Class | Bounds | Counter action |
|---|---|---|
| **small** | max(\|old\|, \|new\|) < 200 chars AND max line count ≤ 10 | +1 (if predicted reach of 4 → DENY, **no increment**) |
| **systematic** | max chars ≥ 1500 OR max line count ≥ 50 | reset to 0 |
| **medium** | between the two | no change |

Why threshold = 4: matches the rule-09 doc's existing禁令 wording
"同一文件本会话 ≥ 4 次小幅 Edit". Why deny-without-increment:
incrementing on DENY would silently disable the threshold (next
attempt would be at 5, then 6 — the wall keeps moving). The pinned
counter forces a systematic edit to recover, which is the rule-09
intended behavior.

### Why this is rule 09 hard layer #2 (not a separate rule)

Rule 09 already covers both "content shape" (no patch markers) and
"aggregate pattern" (no rolling patches). v0.11 shipped only the
content shape as hard layer because the aggregate-pattern detector
needed per-file state plumbing (state.edits_per_file) which v0.11
deferred. v0.13 ships that state field and the matching detector.
Both are rule 09; the doc table now lists two separate "Edit/Write"
rows (content + frequency) under the same rule.

### Changed — documentation

- **`rules/09-systematic-modification.md`**: 物理拦截 table now lists
  the new frequency-layer row + a dedicated "Edit/Write 频率层 —
  rolling-patch 计数器 (v0.13)" subsection with classification table
  + recovery paths.
- **`rules/en/09-systematic-modification.md`**: same structural update.
- **`CLAUDE.md`** §2.11: physical-enforcement bullets now include the
  frequency layer.
- **`prompts/session-start.md`**: 物理强制 table gains a 5th row for
  the rolling-patch DENY trigger.

### Tests

- 135 → 143 (+8).

---

## [0.12.0] — 2026-05-25

**Stop-hook 输出表格化 + prompts 瘦身 54% + 圣旨（用户自定义硬规则）。**

Responds to three concrete usability problems uncovered during real
session use of v0.11:

1. *"软提醒强度不够 — context 一挤就被忽视。"*
2. *"Stop 收尾杂乱，6 个 layer 各说一大段；希望一眼看到 Pass/FAIL 表。"*
3. *"想要一个'圣旨'功能 — 用户能为本项目自定义硬规则，从启动起强制。"*

Each lands as a verifiable hard action, not a soft documentation
gesture: (1) prompts reduced from 260 → 120 lines of dense
keyword-driven tables, (2) every Stop block reason now renders a
uniform 6-row status table with FAIL row highlighted, (3) the 圣旨
TOML file + 3 hook integrations + slash command + CRUD CLI is shipped
behind 23 new tests.

### Added — 圣旨 (Imperial Edicts) system

- **`hooks/scripts/lib/edicts.py`** — TOML loader + soft-layer renderer
  + hard-layer matchers. Stdlib-only (`tomllib` since Python 3.11).
- **File location**: `${CLAUDE_PROJECT_DIR}/.claude/cc-enslaver/edicts.toml`
  (project-level, team-shareable). Falls back to `~/.claude/cc-enslaver/
  edicts.toml` for personal global. Both empty/missing → empty edict
  list, no behavior change (failing-open).
- **Schema** (array of tables, `[[edicts]]`):
  - `id` (required, string) — unique short id.
  - `text` (required, string) — imperative one-liner shown to the agent.
  - `severity` — `"must"` (default, physical DENY on match) | `"should"`
    (soft reminder only).
  - `deny_edit` — list of regexes matched against `Edit`/`Write`
    `new_string`/`content`.
  - `deny_bash` — list of regexes matched against `Bash` `command`.
  - `note` — optional rationale shown in the deny reason.
- **Injection** — `inject_context.py` appends the rendered edict table
  to both `SessionStart` and `UserPromptSubmit` injections. Survives
  context compaction via per-turn re-injection.
- **PreToolUse(Edit|Write) integration** — `read_guard.py` calls
  `edicts_lib.find_edit_violation` after the rule-09 patch-style check.
  First matching `must` edict → DENY with `cc-enslaver · 圣旨 <id>
  violation` reason naming the edict + matched pattern + snippet.
- **PreToolUse(Bash) integration** — `bash_guard.py` calls
  `edicts_lib.find_bash_violation` after the built-in static patterns
  (`--no-verify` / `--no-gpg-sign` / force-push / `chmod 777`) so 圣旨
  cannot accidentally whitelist a built-in bypass.
- **`hooks/scripts/manage_edicts.py`** — CRUD helper:
  `list / add / remove / reload / path`. Used by the slash command and
  directly from the shell.
- **`commands/edict.md`** — `/cc-enslaver:edict` slash command wrapping
  the manage script.
- **`docs/EDICTS.md`** — user guide with format, enforcement contract,
  3 worked examples, limitations.

#### Why TOML and not YAML

Python's stdlib has `tomllib` (3.11+) but no YAML parser. cc-enslaver's
no-third-party-deps contract holds since v0.1. Rolling a YAML subset
adds parser-bug risk; TOML's array-of-tables shape is verbose but
unambiguous, which suits a hand-edited config.

#### Order in the hook pipeline (security-relevant)

```
PreToolUse(Edit|Write):
  1. read-before-edit guard (rule 04 + 08)
  2. patch-style marker guard (rule 09)
  3. 圣旨 scan ← new in v0.12

PreToolUse(Bash):
  1. --no-verify / --no-gpg-sign / force-push / chmod 777 (rule 03 + 09)
  2. register_read.py escape hatch (v0.4.0)
  3. 圣旨 scan ← new in v0.12
```

Built-in disciplines always run first. An edict cannot whitelist
`--no-verify`; the built-in hook denies before reaching the edict
layer. A test (`test_builtin_no_verify_still_denies_when_edicts_loaded`)
encodes this contract.

### Changed — Stop hook block reason format (v0.12)

- **Uniform 4-part shape** for every block reason (layers a → f):
  ```
  cc-enslaver · Stop check FAILED at Layer (X) [rule NN — short label]

  | Layer | Rule | Status      | Note                              |
  |-------|------|-------------|-----------------------------------|
  | (a)   | 06   | ✅ Pass      |                                   |
  | (b)   | 01   | ✅ Pass      |                                   |
  | (c)   | 06   | ❌ FAIL     | self-quiz / marker absent         |
  | (d)   | 07   | ⏸  pending  | (gated by earlier fail)           |
  | (e)   | 08   | —  n/a      | (non-edit turn)                   |
  | (f)   | 09   | —  n/a      | (non-edit turn)                   |

  Done-claim matched: '...'

  [Recovery — rule 06 self-quiz]
  <short, 5-10 line actionable instructions>

  (One-shot guard: ...)
  ```
- **`stop_guard.py`**: 6 former monolithic ~50-line REASON templates
  replaced by `LAYER_META` + `_render_status_table(fail_layer_id,
  edit_turn)` + `_build_block_reason(...)` + 6 short `_RECOVERY_*`
  blurbs. ~120 lines removed, format made uniform.
- **`tests/test_stop_guard.py`**: 8 new tests in
  `TestV012StatusTableFormat` lock in the table format (header rows,
  earlier-layers-pass, edit-vs-non-edit n/a marking, recovery section,
  one-shot footer). Existing 43 layer-logic tests pass unchanged.

#### Why the table format

v0.11's prose-style block reasons were each 30-50 lines. When multiple
layers could plausibly fail in a row, the agent saw 200+ lines of
discipline text without a quick way to locate "what specifically went
wrong this time". The status table renders the verdict at a glance:
which gates passed (✅), which failed (❌), which never evaluated (⏸),
which were not applicable (—). Recovery instructions appear only for
the actual failing layer.

### Changed — prompts 瘦身 (260 → 120 lines, 54% reduction)

- **`prompts/session-start.md`**: 219 → 89 lines. 9 rules rendered as
  a compact one-line-per-rule table; physical-enforcement triggers as
  a 4-row trigger table; standard response skeleton as a 5-row stage
  table; decision-time self-check triggers as a flat list. All
  test-contract keywords preserved (验证收敛 / 重触发原症状 / 是不是真的
  解决了问题 / 任务忠实 / 改前必读 / 写前必想 / rule 08 / layer (e) /
  系统式修改 / 禁止打补丁 / rule 09 / layer (f), etc.).
- **`prompts/user-prompt.md`**: 41 → 31 lines. Refactored to a single
  13-row "决策触发器 → 触发规则 → 物理后果" table.
- **Why**: SessionStart injection lives at the top of the context
  window and is among the first content to be compressed by auto-compact
  in long sessions. Higher information density per line increases the
  odds that critical signal survives compression.

### Changed — `read_guard.py` / `bash_guard.py` plumbing

- New `_emit_raw_deny(reason)` helper exposed so圣旨 (and any future
  per-rule plugin) can emit a deny with a pre-built reason text without
  going through the legacy template-string interface.
- Each guard now loads edicts once per invocation (cheap disk read of a
  small TOML file). Live-editing the edicts file takes effect on the
  next tool call.

### Tests

- **+23 new tests** in `tests/test_edicts.py` covering: loader (no file,
  empty file, malformed TOML, missing fields, bad regex, duplicate id,
  unknown severity), soft injection rendering (presence on session-start
  + user-prompt, id labels, severity badges), hard layer Bash deny,
  hard layer Edit/Write deny on existing + new files, severity gating
  (`should` does not DENY), built-in patterns precedence (no edict
  whitelist of `--no-verify`), multi-edict first-match-wins.
- **+8 new tests** in `tests/test_stop_guard.py::TestV012StatusTableFormat`
  covering the new block-reason shape.
- **Suite total**: 104 → 135 (+31 net).

---

## [0.11.0] — 2026-05-19

- **Additional bypass patterns**
  - Evaluate adding `git reset --hard` (if uncommitted changes), `git rebase
    --skip`, `pip install --break-system-packages`, etc. — currently held back
    on false-positive concerns.
- **Stop hook deep file-claim verification** — parse "I edited X" patterns
  in the agent's last message and check `git diff` / mtime against the
  session-start baseline. v0.7.0 layered (b)+(c) on rule 06; v0.8.0 layered
  (d) on rule 07; v0.11.0 layered (e)+(f) on rule 08+09 — the file-claim
  version is still a future-version candidate.
- **Rolling-patch PreToolUse interception (rule 09 hardening)** — count
  `edits_per_file` in session state; DENY when same file > 5 small Edits
  in one session without a single ≥ 50-line systematic rewrite. v0.11
  punts this to soft layer (Stop layer (f) + rule 09 doc) on false-
  positive concerns; hard interception would require a "small Edit"
  heuristic that doesn't trip on legitimate small typo fixes.
- **English prompts** — `rules/en/` is complete through rule 09 (v0.11),
  but `prompts/session-start.md` and `prompts/user-prompt.md` are still
  Chinese-only. Hook injection therefore only benefits CJK Claude Code
  users in their native flow; the English mirror today is primarily for
  copy-pasting into other LLM system prompts.

---

## [0.11.0] — 2026-05-19

**全面规范化 + 新增 rule 08 (改前必读 / 写前必想) + rule 09 (系统式修改 / 禁止打补丁) + 两条新 Stop hook layer + PreToolUse(Edit|Write) 内容层物理拦截。**

This release responds directly to four concrete demands from the user:
"全面规范化"、"加入改前必读、写前必想且强制"、"物理上强制 Claude Code
遵守本插件规则"、"强化系统式修改严禁打补丁"。Each one lands as a
verifiable hard action (hook deny / Stop block / regex match), not as
soft documentation.

### Why rule 06 + 07 weren't enough

Rule 06 covers "did the part you edited actually converge?" (technical
axis). Rule 07 covers "did you do everything the user asked for at the
standard requested?" (contractual axis). But two adjacent failure modes
weren't being caught:

1. **Pre-action laziness** — an agent could Edit without ever Reading
   the call sites, or without recording *why* they were making the
   change. The PreToolUse read-before-edit gate (v0.3.2) only checked
   the *target* file was Read; downstream / connected files could be
   skipped silently, and the "think before write" half had no
   enforcement at all.
2. **Patch-style content** — even when rule 06 + 07 + read_guard all
   passed, the agent could land a `new_string` containing `try /
   except: pass`, `# noqa`, `@ts-ignore`, `time.sleep(0.5) # race`,
   etc., as the actual fix. These are rule 03 violations in spirit but
   rule 03 was a text rule; nothing physically intercepted them at the
   PreToolUse boundary.

Rule 08 closes axis (1); rule 09 closes axis (2). Both axes get
physical enforcement, not just text reminders, because the user's
literal demand was "物理上强制 Claude Code 遵守本插件规则" — system-
prompt-only enforcement was insufficient.

### Added — rule 08 (read-before-edit / think-before-write)

- **`rules/08-read-before-edit-think-before-write.md`** (Chinese
  canonical) + **`rules/en/08-*.md`** (English mirror). Defines:
  - **Read-half** — full Read of target + call sites + connected files
    is mandatory before any Edit.
  - **Think-half** — at least 3 of six rule-02 keywords (architecture
    / responsibility / root cause / solution / impact / risk + a
    "alternatives compared" item) must be surfaced in chain-of-thought
    or final reply before Edit / Write submission.
- **Stop hook layer (e)** — fires when `last_edit_turn == turn_count`
  (i.e., this turn actually edited a file) and the message lacks both
  an explicit rule-08 marker AND fewer than 3 of the six rule-02
  keywords. Read-only / analysis turns are never blocked by (e).

### Added — rule 09 (systematic modification, no patch-style)

- **`rules/09-systematic-modification.md`** (Chinese canonical) +
  **`rules/en/09-*.md`** (English mirror). 8 banned patch-style
  patterns + 6 patch-marker regex categories + 13 rationale tokens.
- **`hooks/scripts/read_guard.py` patch-style detector** — at
  PreToolUse, scans `new_string` (Edit) / `content` (Write) for:

  | Pattern | Reason |
  |---|---|
  | `try:\n …\nexcept …:\npass` (bare multi-line) | Silent exception swallow |
  | `# noqa` without rationale | Lint suppression |
  | `# type: ignore` without rationale | Type-checker suppression |
  | `// @ts-ignore` / `// @ts-expect-error` without rationale | TS suppression |
  | `// eslint-disable[-next-line\|-line]` without rationale | Lint suppression |
  | `time.sleep(...) # race/wait/workaround` | Sleep masking a race |

  Each is allowed when accompanied by an immediately-adjacent
  rationale comment containing one of: `because`, `原因`, `why`,
  `正当`, `rationale`, `see issue/pr/comment/ticket`,
  `intentional[ly]`, `deliberate[ly]`, `third-party`, `per
  spec/rfc/standard`. A bare suppression = laziness = DENY with a
  precise diagnostic citing rule 09.

- **Stop hook layer (f)** — fires on edit turns when the message
  lacks both an explicit rule-09 marker AND any of the three triplet
  axes (root cause / impact / solution). All three must be present
  for the keyword fallback to count.

### Added — physical enforcement infrastructure

- **`hooks/scripts/lib/state.py`**:
  - `record_edit_turn(session_id, turn_count)` — stamps
    `state["last_edit_turn"] = turn_count` after every accepted
    Edit/Write.
  - `did_edit_this_turn(session_id, turn_count)` — boolean used by
    stop_guard to scope layers (e)+(f) to edit turns. Returns False
    when `turn_count is None` (preferring false negatives over
    spurious blocks on missing payload).
- **`hooks/scripts/read_guard.py`** — refactored to:
  - Branch on tool (Read / Write / Edit) with patch-style check
    inserted between "read-before-edit" gate and "allow + record"
    path.
  - New `_find_unjustified_patch_marker(new_string)` helper with
    `_line_window(±1 line)` rationale-lookup window.
  - New `PATCH_DENY_TEMPLATE` with rule-09 diagnostic + acceptable-
    form examples in the deny reason.
  - Calls `state_lib.record_edit_turn(session_id, turn_count)` on
    every accepted Edit/Write.
- **`hooks/scripts/stop_guard.py`** — adds layers (e) and (f):
  - `RULE_08_MARKERS` (6 patterns) + `RULE_02_KEYWORDS` (6
    bilingual regex) + `_has_rule08_marker_or_keywords(text)`.
  - `RULE_09_MARKERS` (7 patterns) + `RULE_09_TRIPLET` (3 axes,
    bilingual) + `_has_rule09_marker_or_triplet(text)`.
  - Layered into `main()` after (d) and gated by
    `state_lib.did_edit_this_turn(...)`.
  - Two new block reason templates: `MISSING_RULE08_REASON`,
    `MISSING_RULE09_REASON`, each citing exactly which discipline
    failed and how to surface the missing markers.

### Added — full prompts / commands regularization (诉求 1)

- **`prompts/session-start.md`** — full rewrite:
  - Opens with a "🚨 物理强制层" advisory making the hook-deny /
    Stop-block surface explicit.
  - 9-rule summary section (was 7) with hook-enforcement annotations
    on every rule.
  - **Workflow constraints split into three time-ordered stages**:
    🔍 改前 / ✏️ 改中 / ✅ 改后, each tying back to specific rules.
  - **Standard response skeleton (§3)** — 5-stage template (改前 /
    改中 / 改后 rule 06 / 改后 rule 07 / rule 08+09 收尾) that
    modification-class tasks must follow. Explicit field list with
    sample contents.
  - Self-check trigger list extended with hook-enforcement callouts
    (e.g., "即将写 `# noqa` 无 why 注释 → 会被 PreToolUse 物理 DENY").
- **`prompts/user-prompt.md`** — full rewrite from a 7-item bullet
  list to a structured 9-item self-check broken into 改前 / 改中 /
  改后 stages, ended with a "物理强制提示" table mapping each
  laziness attempt to the specific hook that will catch it.
- **`commands/checklist.md`** — adds **section E** (rule 08, 5
  items E1–E5) + **section F** (rule 09, 8 items F1–F8). Default
  invocation now prints A/B/C/D/E/F. Argument-hint extended with
  `pre-edit` and `systematic`. Output-requirements section gains a
  unified icon legend (✅ / ⚠️ / ❌ / 🔍 / ✏️ / 🚨).
- **`agents/verifier.md`** — meta-rules section adds rule 08 as a
  constraint the verifier itself must respect (full Read before
  verdict, never grep-only).

### Changed

- **`docs/RULES.md`** — rule count 7 → 9; numbering range `01–07`
  → `01–09`; relationship diagram extends with rule 08 + rule 09
  boxes; component-table extended with hook scripts; "addition
  flow" updated for `10-xxx.md`.
- **`rules/00-index.md`** + **`rules/en/00-index.md`** — new rows
  for 08 and 09; range updated; English relationship paragraph
  extended.
- **`docs/ARCHITECTURE.md`** — Layer 1 hook table now mentions all
  three responsibilities (read-before-edit / patch-style / edit-
  turn stamping); Stop decision tree extended from 6 steps to 8
  steps; new "Edit / Write patch-style content blocking (v0.11)"
  subsection with regex catalog and rationale-token list; new
  rule-08 keyword table and rule-09 triplet table; connected-files
  matrix updated for all three changed scripts.
- **`CLAUDE.md`** — new §2.10 (rule 08) + §2.11 (rule 09);
  repository structure tree adds rules 08 / 09; §6 当前版本 fully
  rewritten with v0.11 detail block.
- **`.claude-plugin/plugin.json`** + **`marketplace.json`** —
  version bumped 0.10.0 → 0.11.0; descriptions rewritten to
  surface the v0.11 rule additions and physical-enforcement
  changes.

### Removed (from Unreleased roadmap)

- "Stop hook deep enforcement on more rules" — rule 08 and rule 09
  layers (e)+(f) cover the next two axes; remaining file-claim
  verification axis stays roadmap.

### Verified

```
# rule 06 convergence: see "Phase F" section in the v0.11 commit
# message for the full self-quiz (真解决 / 更好方案 / 哪些没验 /
# 验证合理).
```

Self-applied rule 06 + rule 07 + rule 08 + rule 09 before claiming
completion. Hook-layer dogfood confirmed in this very session: when
the agent tried to Edit `CLAUDE.md` without first having Read it via
the Read tool (the file was only available as injected `claudeMd`
context), `read_guard.py` correctly DENY-ed the Edit with the rule-
04/08 reason. The agent then Read the file and retried — exactly the
intended physical-enforcement loop.

---

## [0.10.0] — 2026-05-13

### Added — `systematic-debug` Step 0 = build feedback loop

The `systematic-debug` skill previously went straight from Step 1 (restate the
problem) into Step 3 (hypothesise root causes). In practice this collapsed
under hard bugs because **without a reproducible signal, Step 4 (verify
hypotheses) has nothing to act on** — the agent ends up writing plausible
explanations that cannot be falsified. The output looked disciplined but the
discipline never bound.

This release adds **Step 0 — Construct a Reproducible Signal (Feedback Loop)**
as a mandatory prerequisite to Step 1. It borrows the Phase-1 framing of
`mattpocock-skills:diagnose` ("If you have a fast, deterministic,
agent-runnable pass/fail signal for the bug, you will find the cause") and
adapts it to the cc-enslaver verification discipline.

Step 0 contents (all enforced, not advisory):

- **0.1 — Pick a loop form, in priority order**, from 10 concrete patterns:
  failing test → curl/HTTP script → CLI snapshot diff → headless browser →
  replay captured trace → throwaway harness → property/fuzz loop → bisection
  harness → differential loop → HITL bash script.
- **0.2 — Iterate on the loop itself**: faster, sharper signal, more
  deterministic. A 30-second flaky loop barely beats no loop; a 2-second
  deterministic loop is a debugging superpower.
- **0.3 — Non-deterministic bugs**: target a higher reproduction rate (50%
  flake is debuggable; 1% isn't). Loop the trigger 100×, parallelise, narrow
  timing windows.
- **0.4 — Cannot build a loop**: list the attempts, ask the user for
  environment access / captured artifact / instrumentation permission —
  **forbidden** to drop into Step 3 hypothesis-generation without a loop.
- **0.5 — Mandatory checkpoint before Step 1**: must answer four concrete
  questions — what is the loop, how fast does it run, how often does it hit
  the bug, what does the signal look like.

The verify-convergence step (Step 7.1) now reuses the same loop from Step 0
rather than asking the agent to recall the original repro command.

Three new entries in the forbidden-behaviours list:

- Skipping Step 0 and going straight to Step 3
- Treating a one-off stack-trace observation as "the loop is already built"
- Using "the loop is slow" as an excuse to fall back on impression-based debug

### Why this and why now

`mattpocock-skills` was installed on 2026-05-13 as a Claude Code marketplace.
The `diagnose` skill in that pack codifies what "build a feedback loop first"
actually looks like as a 10-pattern menu, which is exactly the gap
cc-enslaver's systematic-debug skill had. Importing those patterns (with
attribution; the upstream is MIT-licensed) closes the gap without inventing
a parallel taxonomy.

### Compatibility

No breaking changes — Step 0 is additive. Existing Step 1–Step 7 behaviour is
preserved; Step 7.1 now reads "rerun the Step 0 loop" instead of "rerun the
original command" (semantically equivalent for users who do build a loop, and
strictly stricter for users who don't).

---

## [0.9.1] — 2026-05-06

**Critical bugfix: the Stop hook was a silent no-op for v0.6.0 through
v0.9.0.** All four Stop-hook discipline layers (no-evidence, hedge,
rule-06 self-quiz, rule-07 fidelity) were never actually firing on
Claude Code 2.x. The prompt-injection layers (SessionStart /
UserPromptSubmit) worked the whole time, so the failure was invisible
unless you specifically inspected `${CLAUDE_PLUGIN_DATA}/sessions/<sid>.json`
for a `last_blocked_turn` field that never appeared.

### Root cause

`stop_guard.py:_last_assistant_message_from_transcript` had two
silent-failure bugs that compounded:

1. **Wrong JSONL field path.** The parser read `entry.get("content")`
   (top-level), but Claude Code 2.x writes assistant entries as
   `{"type": "assistant", "message": {"content": [...]}}` — content is
   *nested under `message`*. The top-level `content` was always `None`,
   so `last_assistant` was always `""`, and `if not message: return 0`
   short-circuited every Stop event.
2. **Trailing-tool_use overwrite.** Even if bug 1 had been absent, the
   parser overwrote `last_assistant` on *every* assistant entry,
   including the trailing tool_use entries that contain no text blocks.
   A turn that ended with a tool_use after the text reply (the common
   case in Claude Code 2.x) would still wipe the prior text out to `""`.

The original test (`TestTranscriptFallback`) used a synthetic schema
that matched the broken parser (`{"role":"assistant", "content":[...]}`),
so it passed without ever exercising the real Claude Code schema. The
bug was discoverable only by inspecting an actual transcript or by
noticing that `last_blocked_turn` was never being written to disk.

### Fix

`hooks/scripts/stop_guard.py` — `_last_assistant_message_from_transcript`:

- Read `entry.get("message", {}).get("content")` first (Claude Code 2.x
  schema), fall back to top-level `entry.get("content")` for backwards
  compatibility with the older / generic schema.
- Skip entries whose extracted text is empty so the most recent
  text-bearing reply wins, instead of being clobbered by a trailing
  tool_use entry.

### Added

- `tests/test_stop_guard.py::TestTranscriptFallback`:
  - `test_falls_back_to_transcript_claude_code_2x_schema` — real
    `{"type":"assistant","message":{"content":[...]}}` schema (the
    case that exposes bug 1).
  - `test_falls_back_to_transcript_legacy_top_level_schema` —
    backwards-compat for `{"role":"assistant","content":[...]}`.
  - `test_falls_back_to_transcript_string_content` — bare-string
    `content` form.
  - `test_text_reply_wins_over_later_tool_use_entry` — exposes bug 2;
    text reply followed by a trailing tool_use entry must still BLOCK.
- Test count 76 → **79 pass**.

### Verified

```
$ python -m unittest discover tests
...............................................................................
Ran 79 tests in <X>s
OK
```

Smoke against the actual session transcript at
`~/.claude/projects/d--Projects-anti-laziness/<sid>.jsonl`:

- Parser now extracts the most recent text-bearing assistant entry
  (66 chars on this session at fix time) instead of the empty string.
- End-to-end Stop hook with a fake done-claim appended to the real
  transcript now BLOCKs at Layer (a) (rule 06 base) when no evidence
  is supplied, and at Layer (d) (rule 07) when evidence + rule-06
  marker are present but no rule-07 fidelity marker.

### Impact on user experience

After upgrading and restarting Claude Code, all four Stop-hook layers
will fire for the first time. Replies that say "done" / "fixed" /
"已解决" / etc. will be blocked unless they include the rule-06 and
rule-07 evidence required by the discipline contract. This is the
behaviour the documentation has promised since v0.6.0; v0.9.1 is the
first release where the promise is actually kept.

The one-shot guard (3-turn grace window after each block) still
prevents infinite re-block loops — the agent gets exactly one
corrective turn, then up to two more "free" Stop attempts before the
hook fires again.

---

## [0.9.0] — 2026-05-04

**Project rename: `anti-laziness` → `cc-enslaver` (and marketplace
`agent-rigor` → `cc-enslaver`).** All five name layers (plugin name,
marketplace name, GitHub repo, slash-command prefix, on-disk state
directory basename) are now unified under a single identifier. No
behavioural change to any rule, hook, or test — only string
substitution + version bump.

### Why

Pre-0.9.0 the repo had two parallel names by accident of history:
the plugin internal `name` field said `anti-laziness`, while the
marketplace + GitHub repo used `agent-rigor`. New users saw
`/plugin install anti-laziness@agent-rigor` and asked which is "the"
name. v0.9.0 collapses everything to **`cc-enslaver`** so the
marketplace/install/slash-command/import-path all match.

### Breaking changes (rename consequences)

- **Slash commands** prefixes change:
  `/anti-laziness:checklist` → `/cc-enslaver:checklist`,
  `/anti-laziness:verify`    → `/cc-enslaver:verify`,
  `/anti-laziness:gc`        → `/cc-enslaver:gc`.
- **Install command** is now `/plugin install cc-enslaver@cc-enslaver`
  (still works against the same local marketplace path).
- **State directory basename** changes from `anti-laziness` to
  `cc-enslaver` in the fallback paths
  (`~/.claude/local/cc-enslaver/sessions/` and
  `${CLAUDE_PROJECT_DIR}/.claude/local/cc-enslaver/sessions/`).
  The `${CLAUDE_PLUGIN_DATA}` path supplied by Claude Code is keyed
  on the plugin's `name`, so it also moves automatically. **Old
  per-session state files (`last_blocked_turn`, `read_files`) will
  not migrate** — they are effectively orphaned. Acceptable because
  state is short-lived (one Claude Code session) and the orphans are
  harmless KB-sized JSON. Run `/cc-enslaver:gc --apply` against the
  *old* state dir if you want to reclaim space.
- **GitHub repository name** changes from `skymanbp/agent-rigor` to
  `skymanbp/cc-enslaver`. GitHub installs an automatic redirect from
  the old name, so existing clones / CI badges keep working. The
  CHANGELOG `compare` links and `plugin.json` `homepage` /
  `repository` fields now point at the new URL directly.
- **Already-installed copies** of the plugin will continue to work
  on the old name until the user re-installs from the renamed
  marketplace. `/plugin marketplace remove agent-rigor` then
  `/plugin marketplace add /path/to/cc-enslaver`, then
  `/plugin install cc-enslaver@cc-enslaver`.

### Out of scope (rename did NOT touch)

- **Local clone directory** `D:\Projects\anti-laziness\` — the user
  should `Rename-Item` (or fresh `git clone` after pushing the new
  name) on their own machine. The plugin code does not depend on
  this directory's basename; only `${CLAUDE_PLUGIN_ROOT}` matters,
  which Claude Code resolves at install time.
- **Rule pack content** (`rules/01..07-*.md`) — the seven discipline
  rules are unchanged. The plugin's new name is the *enforcer*; the
  *rules* it enforces still describe lazy patterns and discipline.

### Changed (mechanical text replacements)

- `anti-laziness` → `cc-enslaver` (117 occurrences across 22 files):
  plugin.json, marketplace.json, CLAUDE.md, CHANGELOG.md, README.md,
  agents/verifier.md, commands/{checklist,gc,verify}.md,
  docs/ARCHITECTURE.md, prompts/{session-start,user-prompt}.md,
  rules/{,en/}00-index.md, hooks/scripts/{bash_guard,gc_state,
  inject_context,read_guard,register_read,stop_guard}.py,
  hooks/scripts/lib/state.py, tests/_helpers.py.
- `agent-rigor` → `cc-enslaver` (homepage/repository URL +
  marketplace `name` field + CHANGELOG compare links + README
  install instructions): plugin.json, marketplace.json, CHANGELOG.md,
  README.md.
- `alaz-` → `ccens-` (test tempdir prefix in 5 test files):
  tests/test_{gc_state,bash_guard,register_read,read_guard,
  stop_guard}.py.
- README.md version badge `0.7.0` → `0.9.0` (caught the stale badge
  while at it; v0.8.0 had bumped plugin.json but missed the badge).

### Added

- This CHANGELOG entry. No new code.

### Verified

```
$ python -m unittest discover tests
............................................................................
Ran 76 tests in <X>s
OK
```

All 76 tests pass against the renamed identifiers. Smoke test:
`stop_guard.py` rule-06/07 block reasons now read
`cc-enslaver · rule 0X enforcement (...)` and the injected context
mentions `cc-enslaver` in place of `anti-laziness`.

Self-applied rule 06 + rule 07 — including verifying every modifier
the user used ("全部统一" / "保证更新" / "正常工作") landed as actual
zero-residual replacements + green test suite, not as soft promises.

---

## [0.8.0] — 2026-05-04

> **Note:** v0.8.0 was rolled into the v0.9.0 commit (the project rename
> happened immediately after rule 07 was finished, before either had been
> tagged). There is therefore **no separate `v0.8.0` git tag or GitHub
> release**; the rule-07 work below is included in `v0.9.0`. This entry
> is preserved for changelog continuity.

**New core rule 07 — task fidelity (request coverage / no-degrade).** The
first seven rules covered specific lazy patterns. Rule 06 (v0.5.0) closed
the *technical* convergence axis ("did the part I edited actually fix the
root cause?"). Rule 07 closes a different axis the previous six could not
catch: **silent omission, silent degrade, concept-swap, scope creep, and
buried TODOs**.

### Why rule 06 wasn't enough

Real failure mode: user says "add rule 07 — strictly enforced; second-pass
confirmation that nothing was omitted or degraded". An agent could:

- write the rule doc + update the index (rule 06 says "I converged on the
  doc"), and
- *silently skip* the prompt injection, the checklist, the stop_guard hook,
  the tests, and the version bump,
- then declare "done" with `$ pytest passed` as evidence.

Rule 06's self-quiz (真解决 / 更好方案 / 哪些没验 / 验证合理) does not
naturally surface "did I do *every sub-task the user asked for at the
standard requested*?". Tests cannot answer it either — tests cover code
that exists, not code you forgot to write. Rule 07 makes this axis
first-class.

### What rule 07 demands

After the rule-06 convergence pass, the agent must additionally answer:

1. **Coverage** — Decompose the user's *original* message. How many
   sub-items? Which did you do? Which did you not do, and why?
2. **Standard** — Which modifier words did the user use ("强制 / 必须 /
   完整 / 严格 / 所有 / 立即 / 全面", "mandatory / strict /
   comprehensive / all / every / immediate")? Did each one land as a
   verifiable hard action (hook / assertion / test) or did some end up
   as soft documentation only?
3. **Fidelity** — Did you concept-swap (subset / approximation /
   something-related-but-not-A)? Did you do refactors / abstractions
   the user didn't ask for? Did you bury any TODO / FIXME /
   commented-out test while saying "done"?

Termination: all three must have traceable answers + every modifier word
has hard-evidence anchor + half-finished pieces are surfaced.

### Stop-hook Layer (d)

`stop_guard.py` gains a fourth layer that fires *after* (a)(b)(c) pass:

```
1. one-shot guard window?      → ALLOW (existing)
2. no done-claim?              → ALLOW (existing)
3. hedge near done?            → BLOCK (rule 01, v0.7.0)
4. no evidence?                → BLOCK (rule 06 base, v0.6.0)
5. no rule-06 quiz/marker?     → BLOCK (rule 06 deep, v0.7.0)
6. no rule-07 marker/quiz?     → BLOCK (rule 07, NEW)
7. otherwise                   → ALLOW
```

Pass condition for (d) mirrors (c): any single fidelity marker (`rule 07`,
`任务忠实`, `请求覆盖`, `原始请求`, `无降级`, `无遗漏`, `task fidelity`,
`request coverage`, `no degradation`, `no omission`, `no scope creep`,
`covered all`, `all requested`, or any `✅ 完成 / ✅ done` checklist row)
**OR** at least 2 of 3 fidelity self-questions matched.

### Added

- **`rules/07-task-fidelity.md`** — Chinese canonical rule:
  1. Check 1 — decompose the original request.
  2. Check 2 — mark every sub-item ✅ / ⚠️ / ❌ with evidence.
  3. Check 3 — every modifier word has a hard-evidence anchor.
  4. Check 4 — no scope creep.
  5. Check 5 — surface every half-finish.
  6. Three-question self-quiz (coverage / standard / fidelity).
- **`rules/en/07-task-fidelity.md`** — English mirror.
- **`hooks/scripts/stop_guard.py`**:
  - `FIDELITY_MARKERS` (18 patterns: `rule 07`, `任务忠实`, `请求覆盖`,
    `原始请求`, `无降级`, `无遗漏`, `无超范围`, `task fidelity`,
    `request coverage`, `no degrad`, `no omission`, `no scope creep`,
    `covered all`, `all requested`, plus the `✅/⚠️/❌ + 完成/done`
    checklist-row regex).
  - `FIDELITY_QUIZ_PATTERNS` (3 regexes for coverage / standard /
    fidelity questions, Chinese + English).
  - `_has_fidelity_marker_or_quiz()` helper.
  - `MISSING_FIDELITY_REASON` block-reason template.
  - Layer (d) wired into `main()` after the layer (c) gate.
- **`tests/test_stop_guard.py::TestFidelityLayer`** — 7 cases:
  - Layer (d) blocks when (a)(b)(c) pass but no fidelity signal.
  - Single `rule 07` marker passes.
  - `任务忠实` Chinese marker passes.
  - `no degradation` English marker passes.
  - 2 of 3 fidelity quiz questions pass.
  - Even a thorough rule-06 self-quiz alone is blocked at Layer (d).
  - `✅ 完成` checklist-emoji form passes.
- **`tests/test_inject_context.py`** — 2 new cases:
  - `test_content_references_rule_07_fidelity` — session-start prompt
    surfaces 任务忠实 / 覆盖性 / 标准性 / 忠实性 / 原始请求.
  - `test_user_prompt_includes_fidelity_check` — per-turn reminder
    contains 忠实.
- Test count 67 → **76 pass**.

### Changed

- **`prompts/session-start.md`** — adds the rule 07 summary block;
  workflow constraint extends from "rule 06 verifications + file:line"
  to "rule 06 + rule 07 fidelity quiz". Self-check triggers append the
  4 rule-07 triggers (no original-message check, modifier-word degrade,
  buried TODO, scope creep).
- **`prompts/user-prompt.md`** — adds a 7th per-turn self-check item
  for fidelity (coverage / standard / fidelity).
- **`commands/checklist.md`** — gains a brand-new section **D** with
  D1–D6 (D6.1–D6.3 for the 3-question fidelity quiz). Default
  invocation now prints A/B/C/D; argument-hint extended with `fidelity`.
- **`docs/RULES.md`** — rule count 6 → 7; numbering range `01–06` →
  `01–07`; relationship diagram extended; "addition flow" updated for
  `08-xxx.md`.
- **`rules/00-index.md` / `rules/en/00-index.md`** — new row + English
  relationship paragraph for rule 07.
- **`CLAUDE.md`** — new section §2.9 "声称完成前必须做忠实自答"; rules
  tree now lists 07; §6 "当前版本" reflects v0.8.0.
- **`agents/verifier.md`** — meta-rules section adds rule 07 as one of
  the constraints the verifier itself must respect.
- **`.claude-plugin/plugin.json` + `marketplace.json`** — version
  bumped 0.7.0 → 0.8.0.

### Verified

```
$ python -m unittest discover tests
............................................................................
Ran 76 tests in <X>s
OK
```

Self-applied rule 06 + rule 07 — including the new layer (d) — before
shipping.

---

## [0.7.0] — 2026-04-29

**Stop hook deep rule-06 enforcement.** v0.6.0's done-claim heuristic
("done + any evidence → allow") was gameable — an agent could fake `$ ls`
output and pass. v0.7.0 layers two stricter checks on top:

- **Hedged-completion detection** (rule 01 cross-enforcement): if a
  done-claim appears within ~50 chars of a first-person uncertainty
  marker (`我觉得` / `我相信` / `应该是` / `I think` / `probably` /
  `maybe`), block. Confident verification cannot coexist with hedged
  language.
- **Missing self-quiz detection** (rule 06 deep): even with evidence,
  if the message lacks both an explicit convergence marker (`rule 06`
  / `自答` / `收敛` / `重触发` / `边界用例` / `convergence`) AND fewer
  than 2 of the 4 self-questions are detected (真解决 / 更好方案 /
  哪些没验 / 验证合理), block.

Decision tree:

```
1. one-shot guard window? → ALLOW (existing v0.6.0)
2. no done-claim?         → ALLOW (existing v0.6.0)
3. hedge near done?       → BLOCK (NEW: rule 01 reason)
4. no evidence?           → BLOCK (existing v0.6.0 reason)
5. no quiz/marker?        → BLOCK (NEW: rule 06 deep reason)
6. otherwise              → ALLOW
```

Each block has a distinct reason text so the agent sees exactly which
discipline gate failed.

### Why "≥ 2 of 4 questions OR any single marker" (not stricter)

If we required all 4 questions verbatim, false-positive rate would
explode — agents using their own phrasing would be blocked despite
genuine convergence work. Accepting a single rule-06 marker (`收敛` /
`rule 06` / `重触发`) lets careful agents pass with their natural
language; demanding ≥ 2 questions when no marker is present keeps the
bar above "throw any one keyword". One-shot guard caps false-positive
cost at 1 turn regardless.

### Added

- `hooks/scripts/stop_guard.py`:
  - `HEDGE_NEAR_DONE_PATTERNS` — bidirectional regex (hedge-then-done
    OR done-then-hedge, within 50 chars).
  - `CONVERGENCE_MARKERS` — `rule 06`, `自答`, `收敛`, `convergence`,
    `self-quiz`, plus rule-06 specific check names (`重触发`,
    `边界用例`, `反向用例`).
  - `SELF_QUIZ_PATTERNS` — 4 regexes for the 4 self-questions
    (Chinese + English).
  - `_has_hedge_near_done()`, `_has_self_quiz_or_marker()` helpers.
  - 3 distinct block-reason templates (`NO_EVIDENCE_REASON`,
    `HEDGED_DONE_REASON`, `MISSING_QUIZ_REASON`).
  - Layered decision logic in `main()`.
- `tests/test_stop_guard.py` — 7 new cases:
  - `TestDoneClaimWithEvidenceAndQuiz` (5 cases): explicit-marker
    pass, `重触发`-keyword pass, evidence-only-blocks-under-v07,
    2-self-questions pass, explicit-`rule 06`-mention pass.
  - `TestHedgedCompletion` (5 cases): Chinese 我觉得+done blocked,
    English `I think fixed` blocked, `probably done`+evidence blocked,
    done-then-hedge blocked, far-away hedge allowed.
- Test count 60 → **67 pass**.

### Changed

- `.claude-plugin/plugin.json` + `marketplace.json` — version bumped
  0.6.2 → 0.7.0.
- The previous test `test_done_with_test_count_allows` ("fixed. 22
  passed, 0 failed.") was renamed to
  `test_evidence_only_without_quiz_or_marker_is_blocked_v07` and
  flipped to expect a block. This is the codified v0.7 tightening:
  evidence alone is no longer sufficient.

### Removed (Unreleased roadmap)

- Implicit "deep rule-06 enforcement" / "Stop-hook claim verification"
  for the *self-quiz* aspect. The deeper "verify edited file via
  git/mtime" version remains an Unreleased v0.8+ candidate.

### Verified

```
$ python -m unittest discover tests
...................................................................
Ran 67 tests in <X>s
OK
```

Self-applied rule 06 — including the new v0.7 deep layer — before
shipping. CI matrix re-verifies on push.

---

## [0.6.2] — 2026-04-29

English mirror of `rules/`. Adds `rules/en/00-index.md` plus
`01-verify-dont-guess.md` through `06-verify-convergence.md`. The
Chinese sources remain canonical; the English mirror is best-effort
and intended for two use cases:

1. Non-CJK readers who want to read the discipline pack.
2. Using cc-enslaver as an LLM-agnostic system-prompt fragment with
   non-Claude agents (OpenAI / Gemini / local models). Concatenate
   `rules/en/*.md` and prepend to your agent's system prompt.

### Added

- `rules/en/00-index.md` — index parallel to `rules/00-index.md`.
- `rules/en/01-verify-dont-guess.md`
- `rules/en/02-systematic-not-reactive.md`
- `rules/en/03-root-cause.md`
- `rules/en/04-full-context.md`
- `rules/en/05-cite-sources.md`
- `rules/en/06-verify-convergence.md`

### Changed

- `.claude-plugin/plugin.json` + `marketplace.json` — version bumped
  0.6.1 → 0.6.2 (patch: documentation only, no behavioural change).
- `CLAUDE.md` §6 — flips English mirror from roadmap to implemented.
- `README.md` — install section's "as a rule pack for any other LLM"
  now points at `rules/en/`.
- `docs/ARCHITECTURE.md` — Layer 5 description mentions both the
  Chinese sources and the English mirror.
- `docs/RULES.md` — adds a "Languages" pointer to `rules/en/`.

### Removed (Unreleased roadmap)

- "English mirror of `rules/`" — implemented here.

### Verified

- 60/60 unit tests pass (no executable code added; rules are static
  Markdown). CI matrix re-verifies on push.
- All 7 English files have valid YAML frontmatter and parallel
  structure to their Chinese counterparts.

---

## [0.6.1] — 2026-04-29

Session state GC. Manual-only (no auto-trigger) — invokable from a
Bash tool call or via the new `/cc-enslaver:gc` slash command.

### Why

Each session writes one JSON file to `${CLAUDE_PLUGIN_DATA}/sessions/<sid>.json`.
Files are KB-sized but sessions accumulate without bound across
months of use. v0.6.1 adds the manual cleanup path. Auto-on-
SessionStart was deferred to keep the hot SessionStart hook lean
and to avoid a code path running on every cold start.

### Added

- **`hooks/scripts/gc_state.py`** — standalone CLI:
  - Required: exactly one of `--dry-run` / `--apply` (refuses to
    proceed if both or neither are given — prevents accidental
    deletion).
  - `--older-than DAYS` (default 30) — files newer than the threshold
    are never touched.
  - Prints `state_dir`, `scanned`, `threshold`, `eligible` count,
    per-file age and size, and either `[dry-run] would delete` or
    `deleted: N / bytes_freed: B` summary.
  - Only globs `<state_dir>/*.json`; refuses to touch anything outside.
- **`commands/gc.md`** — `/cc-enslaver:gc` slash command. Defaults
  to `--dry-run`; invokes the script with whatever argument shape
  the user requested. Documents safe-default semantics.
- **`tests/test_gc_state.py`** (9 cases):
  - Arg validation (no flags, both flags, negative threshold)
  - Dry-run lists without deleting; "nothing to do" path
  - Apply deletes + prints summary; no-eligible is no-op
  - Threshold boundary tests (higher threshold keeps more files)

### Changed

- `.claude-plugin/plugin.json` + `marketplace.json` — version bumped
  0.6.0 → 0.6.1 (patch: new tooling, no behavioural change to the
  hook layer).
- Test count 51 → **60 pass** (+9 gc cases).

### Removed (Unreleased roadmap)

- "Session state GC" — implemented here (manual flavour). Auto-GC
  on SessionStart is now a v0.7+ candidate.

### Verified

```
$ python -m unittest discover tests
............................................................
Ran 60 tests in <X>s
OK
```

Self-applied rule 06 convergence check; full report in commit / release notes.

---

## [0.6.0] — 2026-04-29

**Stop hook lands.** Rule 06 (`验证收敛`) was a soft rule until now —
v0.5.0 surfaced it via prompt injection, checklist, and skill, but
nothing prevented an agent from typing `已解决` and walking away. v0.6.0
adds a `Stop` hook that catches done-claim-without-evidence at turn
boundary and forces one corrective turn.

### How it works

Every Stop event, `stop_guard.py` inspects the agent's last message:

- **Done-claim detected** (`已解决` / `修好了` / `改好了` / `fixed` /
  `done` / etc.) and **no evidence** (no `$ ` shell prompt, no test
  output, no `重触发`, no `pytest`/`unittest`/`Ran N tests`, no fenced
  code block of output) → return
  `{"decision": "block", "reason": <rule-06 reminder>}`. Claude Code
  forces the agent to take another turn.
- **No done-claim** OR **claim plus evidence** → silent allow.

### One-shot guard

A Stop hook that always blocks would loop forever. We persist
`last_blocked_turn` in the per-session state file alongside
`read_files`. If the current `turn_count` is within 3 turns of the
last block, we skip the heuristic. The agent gets the corrective
turn (and a small grace window in case the recovery itself spans
multiple messages); after the grace expires, fresh blocks resume.

### Why heuristic, not file-claim verification

Originally roadmap-described as "verify mtime / git status of files
the agent claims to have edited". We deliberately scope down to the
done-claim heuristic for v0.6.0 because:

- Natural-language extraction of file paths from arbitrary phrasings
  is fragile and produces high false positives.
- The done-without-evidence heuristic is robust: a careful agent
  always cites evidence per rule 05, so this only fires on actual
  laziness.
- The one-shot guard caps the false-positive cost at exactly one
  extra turn per session.

Deep file-claim verification is a v0.7+ candidate — would parse
"I edited X" patterns and check `git diff` / mtime against
session-start baseline.

### Added

- **`hooks/scripts/stop_guard.py`** — Stop event handler. Done-claim +
  evidence patterns documented inline; transcript fallback if
  `assistant_message` is missing from the payload (parses
  `transcript_path` JSONL). Failing-open on exception.
- **`hooks/scripts/lib/state.py`** — `record_stop_block(session_id,
  turn_count)` and `was_just_blocked(session_id, turn_count)` helpers.
  `was_just_blocked` returns True when current turn is within
  `[last + 1, last + 3]` (grace window).
- **`tests/test_stop_guard.py`** — 16 cases:
  - Done-claim Chinese (incl. `改好了` idiom regression case)
  - Done-claim English
  - Block records `last_blocked_turn`
  - Done + evidence (command output / test count / `重触发` keyword)
  - No done-claim allows
  - One-shot guard (turn N+1, turn N+3, turn N+4)
  - Event gating (SubagentStop / PreToolUse → no-op)
  - Empty payload allows
  - Transcript fallback
  - Malformed stdin → fail-open
- **`hooks/hooks.json`** — registers `Stop` event (no `matcher` since
  Stop fires unconditionally per Claude Code spec).

### Changed

- `.claude-plugin/plugin.json` + `marketplace.json` — version bumped
  0.5.1 → 0.6.0.
- Test count 35 → **51 pass** (+16 stop_guard cases).

### Removed (Unreleased roadmap)

- "Stateful `Stop` hook" — implemented here (heuristic flavour). The
  deeper "verify file claims via mtime/git" version is now an
  Unreleased v0.7 candidate.

### Verified

```
$ python -m unittest discover tests
...................................................
----------------------------------------------------------------------
Ran 51 tests in <X>s

OK
```

Self-applied rule 06 convergence check before commit; full report in
the commit message + GitHub release notes.

---

## [0.5.1] — 2026-04-28

CI infrastructure. No plugin behavioural change — adds GitHub Actions
to run the existing test suite on every push and PR. The 35 unit tests
that v0.5.0 ships were previously only verified on the maintainer's
machine; from this release onward, every commit to `main` and every
pull request is gated by a green run on Linux + Windows.

### Added

- **`.github/workflows/test.yml`** — `tests` workflow:
  - Triggers: `push` to `main`, `pull_request` to `main`,
    `workflow_dispatch` (manual re-run from the Actions tab).
  - Matrix: `ubuntu-latest` + `windows-latest`, Python `3.13`. The
    Windows runner exists because `state.py` and the path-normalization
    paths in `read_guard.py` specifically handle Windows quirks; testing
    on POSIX alone would miss regressions there.
  - Steps: checkout → setup-python@v5 → `python -m unittest discover
    tests -v`.
  - `concurrency` cancels stale runs when new commits land on the same
    ref, so a rapid chain of pushes doesn't burn matrix minutes.
  - `permissions: contents: read` keeps the runner principle-of-least.
- **README.md** — `tests` status badge added to the badge row.

### Changed

- `.claude-plugin/plugin.json` + `marketplace.json` — version bumped
  0.5.0 → 0.5.1 (patch: no behavioural change to plugin users).
- `CLAUDE.md` §6 — `v0.5.0 → v0.5.1` and the line about CI flips from
  unimplemented to implemented.

### Removed (from Unreleased roadmap)

- "CI" — implemented here.

### Verified (rule 06 self-applied)

- **C1 重触发原症状**: "no CI" was the failure mode → workflow file now
  exists at `.github/workflows/test.yml` and parses as valid YAML.
- **C2 边界 + 反向**: YAML triggers cover push/PR/manual; matrix covers
  Linux + Windows; python `3.13` matches the reference environment;
  cancellation policy covers rapid-push edge case. First actual CI run
  on push will be the live integration test.
- **C3 连带不破坏**: `python -m unittest discover tests` locally
  produces `Ran 35 tests in 4.312s — OK` with no regressions.
- **C4 自答**:
  1. *真解决?* — Yes for the project-internal failure mode (silent
     test regressions). Caveat: CI green only proves the suite passes;
     it doesn't prove tests cover the right behaviour.
  2. *更好方案?* — Could matrix wider Python (3.11/3.12), could add
     pre-commit hooks locally too, could enable required-status-check
     branch protection. All deferred — minimum effective change is one
     workflow file, single Python version, observe one run, expand if
     needed.
  3. *改动经过验证?* — YAML syntax validated locally via `yaml.safe_load`;
     test suite confirmed green locally. Live workflow run on push is
     the final verification gate (visible from the Actions tab and the
     README badge).
  4. *验证合理?* — The check chain is "YAML parses → workflow runs →
     unittest passes on two OSes". This matches the failure-mode causal
     chain (broken test → silent regression in main).
- **C5 量化**: test count unchanged at 35 (CI doesn't add tests, just
  enforces them); matrix expansion = 1 OS → 2 OSes.

---

## [0.5.0] — 2026-04-28

New core rule 06 — **验证收敛 / verify-convergence**. Promotes the
"after-fix verification" discipline from an implicit habit into a
first-class rule with mandatory checks at every layer.

### Motivation

The first 5 rules covered specific lazy patterns: guessing (01),
reactive thinking (02), root-cause bypass (03), keyword-only edits (04),
unverifiable citations (05). They did not cover **premature
declaration of done** — the meta-failure where an agent claims "fixed"
without verifying the fix actually root-cured the problem and didn't
introduce regressions. Real incidents in this project (the
`fixture.bin` smoke test that revealed v0.3.1's PostToolUse scope bug;
the cache short-circuit only surfacing in production) all share that
shape: a fix shipped, then a test run later showed the original
failure still latent. Rule 06 makes that explicit.

### Added

- **`rules/06-verify-convergence.md`** — defines the convergence
  contract:
  1. **重触发原症状** — re-run the exact failing command/input
  2. **边界 + 反向用例** — at least 1 edge case + 1 negative case
  3. **连带不破坏** — full test/lint/typecheck pass
  4. **强制自答 4 题** —
     - 是不是真的解决了？（具体证据）
     - 有没有更好的解决方法？（与替代方案对比）
     - 改动是否经过验证？（哪些没验？为什么不需要？）
     - 验证是否合理？（是否覆盖了 rule 03 的根因因果链？）
  5. **量化优于定性** — for performance/race/compat: numbers, repeat
     counts, test matrices.
  Convergence terminates *only* when 1–5 are all backed by traceable
  evidence; otherwise → loop back to rule 02.
- Cross-references documented: 06 vs 02 (pre- vs post-action global
  check), 06 vs 03 (what to fix vs whether the fix actually rooted),
  06 vs 01 (input-side vs output-side anti-guessing), 06 vs 05
  (evidence form).
- **`prompts/session-start.md`** — adds the rule 06 summary block
  and converts the workflow constraint from "report with file:line" to
  "execute rule 06 verifications 1-5 + report with file:line +
  evidence".
- **`prompts/user-prompt.md`** — adds a 6th per-turn self-check item:
  "如果即将声称'完成'：是否重触发原症状？是否跑了边界+反向？是否自答了 4 题？"
- **`commands/checklist.md`** — gains a brand-new section **C** with
  C1-C5 (and C4.1-C4.4 for the 4-question self-quiz). Default invocation
  now prints A/B/C; argument-hint extended with `converge`.
- **`skills/systematic-debug/SKILL.md`** — Step 7 rewritten as the
  rule-06 entry point with all 5 sub-steps; output contract now demands
  "convergence verification evidence" not just "verification evidence".
- **`CLAUDE.md`** — new section §2.8 "改完必须收敛验证"; rules tree
  now lists 06; §6 "当前版本" reflects v0.5.0.

### Changed

- `rules/00-index.md` and `docs/RULES.md` — rule count 5 → 6;
  numbering range `01–05` → `01–06`; relationship diagram extended;
  "addition flow" updated for `07-xxx.md`.
- `.claude-plugin/plugin.json` + `marketplace.json` — version bumped
  0.4.0 → 0.5.0.
- `tests/test_inject_context.py` — adds an assertion that
  session-start prompt mentions rule 06 and convergence vocabulary.

### Verified

```
$ python -m unittest discover tests
.................................
----------------------------------------------------------------------
Ran 33 tests in <X>s

OK
```

(Test count unchanged: rules are documentation, not executable code.
The convergence rule's enforcement happens via prompt injection +
human/agent discipline, not via a hook script. Future hardening
options — a Stop-hook claim verifier — are documented in Unreleased
roadmap.)

---

## [0.4.0] — 2026-04-28

Read-cache escape hatch — `register_read.py` + `bash_guard.py` extension.

### Problem

After v0.3.2 fixed the out-of-project scope bug, a second failure mode
surfaced 2026-04-28 in another project (paper-review): `read_guard`
denied `Edit` on `SKILL.md` despite multiple `Read` calls. State file
inspection showed the path **was never recorded**. Root cause:
**Claude Code's harness has a Read result cache. Repeated `Read` of
the same file may be served from cache without invoking the `Read`
tool at all** — so neither `PreToolUse(Read)` (v0.3.2) nor
`PostToolUse(Read)` (earlier) ever fires. The file never enters
session state, and subsequent `Edit` is denied even though the agent
legitimately read the file. This is a Claude Code harness behavior,
not something the plugin can intercept.

### Fix

Provide an explicit "register-as-read" entry that an agent can invoke
when it knows it has read a file but the hook never fired. To prevent
this from itself becoming a laziness vector (agent registers without
actually reading), the entry **requires a SHA-256 of the file's current
on-disk content** — `bash_guard.py` recomputes the hash from disk and
only registers if the agent's claim matches.

### Added

- **`hooks/scripts/register_read.py`** — user-facing CLI stub. Takes
  `--file ABS_PATH --hash SHA256`. Verifies its own hash check (so the
  command line surface is sane) and exits 0/1/2/3 per documented exit
  codes. The actual session-state mutation happens in `bash_guard.py`.
- **`hooks/scripts/bash_guard.py` extension** — when the Bash command
  matches a `register_read.py` invocation, parse `--file` / `--hash`,
  recompute SHA-256 from disk, and:
  - if match: `state_lib.add_read(session_id, file_path)` + ALLOW
  - if mismatch / file missing / bad path / bad hash format: DENY
    with a precise diagnostic
  This is the only place where `session_id` is available, hence the
  registration must happen here (not in the stub script).
- **`hooks/scripts/read_guard.py` deny message** — now points the
  agent at the escape hatch with an inline shell example (SHA-256
  one-liner + register invocation).
- **Tests**:
  - `tests/test_register_read.py` (5 cases): correct hash, mismatch,
    missing file, relative path, uppercase hash normalization.
  - `tests/test_bash_guard.py::TestBashGuardRegisterFlow` (6 cases):
    correct hash allows + records, wrong hash denies + does not record,
    missing file denies, relative path denies, bad hash format denies,
    non-register command falls through to bypass-pattern checks.
  - **Total tests: 22 → 33** (all pass).

### Changed

- `.claude-plugin/plugin.json` + `marketplace.json` — version bumped
  0.3.2 → 0.4.0.
- `CLAUDE.md` §6 — adds the escape hatch to the implemented list.
- `docs/ARCHITECTURE.md` — Layer 1 §2 gains a new "Read-cache escape
  hatch" subsection; connected-files matrix gets `register_read.py`.
- `README.md` — version badge and feature list updated.

### Removed (from Unreleased roadmap)

- "Read-cache escape hatch" — implemented here.

### Verified

```
$ python -m unittest discover tests
.................................
----------------------------------------------------------------------
Ran 33 tests in 6.410s

OK
```

---

## [0.3.2] — 2026-04-27

Hotfix for a hook-scope bug discovered during live use of v0.3.1.

### Problem

`read_guard.py` recorded files in `PostToolUse(Read|Write)` and gated
edits in `PreToolUse(Edit|Write)`. Empirically (Claude Code v2.1.x),
**`PostToolUse` does not fire for tool calls whose target file is
outside the current project working directory, but `PreToolUse` does
fire for those calls**. The two hook events had different scopes.

Concrete failure case observed: agent calls `Read X` where X lives at
`C:\Users\<user>\.claude\projects\<project>\memory\file.md` (outside
the project's `cwd`). Read returns content; PostToolUse never fires;
state file unchanged. Agent then calls `Edit X`. PreToolUse fires,
checks state, file not present → DENY, even though the agent literally
just read the file.

### Fix

Move all recording into `PreToolUse`. The Pre handler now covers
`Read | Edit | Write`:

| Tool  | Behavior |
|-------|----------|
| Read  | record `file_path`; allow |
| Write | if file exists and is unrecorded → DENY; else record + allow |
| Edit  | if file exists and is unrecorded → DENY; else allow |

Because both record and gate live in the same hook event, they share
a scope by construction.

### Changed

- **`hooks/scripts/read_guard.py`** — `_handle_post_tool_use` removed.
  `_handle_pre_tool_use` now branches on `Read` / `Write` / `Edit` per
  the table above. Recording on Read is speculative (happens before the
  Read result is known); a Read of a non-existent path leaves a phantom
  record but is harmless because Edit's `os.path.exists` short-circuit
  covers it.
- **`hooks/hooks.json`** — `PostToolUse` block removed entirely.
  `PreToolUse` first matcher widened from `Edit|Write` to
  `Read|Edit|Write`.
- **`tests/test_read_guard.py`** — restructured around the new
  PreToolUse-only contract. New test classes: `TestPreReadRecords`,
  `TestPreWrite` (3 cases), `TestPreEdit` (4 cases incl.
  Write-then-Edit flow), `TestEventGating` (verifies stray PostToolUse
  is a no-op so future regressions can't sneak recording back in).
  Total: **22 tests pass** (up from 18 in v0.3.1).
- **`.claude-plugin/plugin.json`** + **`marketplace.json`** — version
  bumped 0.3.1 → 0.3.2.

### Verified

```
$ python -m unittest discover tests
......................
----------------------------------------------------------------------
Ran 22 tests in 3.047s

OK
```

---

## [0.3.1] — 2026-04-27

Install-time fix. v0.3.0 could not actually be installed via
`claude plugin install` because of two manifest issues that were not
caught by `claude plugin validate`:

1. The `plugin.json` listed `commands`, `skills`, `agents`, and `hooks`
   pointers to standard locations (e.g. `"hooks": "./hooks/hooks.json"`).
   At install time Claude Code rejects this with either
   `agents: Invalid input` or `Hook load failed: Duplicate hooks file
   detected` — the standard locations under `commands/`, `skills/`,
   `agents/`, and `hooks/hooks.json` are **auto-discovered**, and
   listing them in the manifest causes a duplicate-load conflict.
2. The `agents/verifier.md` frontmatter declared `tools: Read, Grep,
   Glob` (CSV string). The install validator expects a YAML list.

### Changed

- **`.claude-plugin/plugin.json`** — removed `commands`, `skills`,
  `hooks` path fields. The `agents` field had already been removed in a
  pre-release attempt. Standard layouts are now fully auto-discovered.
  Manifest `commands`/`skills`/`agents`/`hooks` are reserved for **non-
  standard** layouts (overrides only).
- **`agents/verifier.md`** — `tools` frontmatter converted from CSV
  string to YAML list:
  ```yaml
  tools:
    - Read
    - Grep
    - Glob
  ```
- **`.claude-plugin/plugin.json`** + **`marketplace.json`** — version
  bumped 0.3.0 → 0.3.1.

### Verified

```
$ claude plugin install cc-enslaver@cc-enslaver
✔ Successfully installed plugin: cc-enslaver@cc-enslaver (scope: user)
$ claude plugin list
  ❯ cc-enslaver@cc-enslaver
    Version: 0.3.1
    Scope: user
    Status: ✔ enabled
```

---

## [0.3.0] — 2026-04-27

Bash bypass-pattern guard + a persistent test suite. The hard layer now
extends from "read-before-edit" to "no shortcut bypasses" at the tool boundary,
and every hook script has black-box subprocess tests that reproduce
production-realistic stdin payloads.

### Added

- **`hooks/scripts/bash_guard.py`** — `PreToolUse` matcher `Bash`. Detects:
  - `--no-verify` (skipping commit hooks)
  - `--no-gpg-sign` (skipping commit signature)
  - `git push --force` / `-f` *without* `--force-with-lease`
  - `chmod 777` (and `chmod -R 777`, `chmod 0777`, `chmod -R 0777`)
  Each match emits a structured deny with a recovery instruction citing rule 03
  (rules/03-root-cause.md). Failing-open on exception. Word-boundary aware —
  `--no-verify-extra` and `--force-with-lease` do not false-match.
- **`tests/`** — black-box unittest suite invoking each hook script as a real
  subprocess with synthetic JSON stdin (mirroring Claude Code's runtime). Zero
  third-party deps. Run with `python -m unittest discover tests`. 18 tests:
  - `test_inject_context.py` — soft layer + UTF-8/CJK survival.
  - `test_read_guard.py` — record/allow/deny matrix, fail-open, path
    normalization (forward/backward slash equivalence on Windows).
  - `test_bash_guard.py` — full bypass-pattern matrix, event gating
    (PostToolUse and non-Bash payloads ignored), fail-open.
- **`tests/README.md`** — runner and "how to add a new test case" guide.

### Changed

- `hooks/hooks.json` — `PreToolUse` now has two matcher entries: `Edit|Write`
  routes to `read_guard.py`, `Bash` routes to `bash_guard.py`.
- `.claude-plugin/plugin.json` — version bumped `0.2.0 → 0.3.0`.
- `.claude-plugin/marketplace.json` — version bumped `0.2.0 → 0.3.0`.
- `CLAUDE.md` §6 — reflects v0.3.0 + the new test suite.
- `docs/ARCHITECTURE.md` — Layer 1 table now lists 5 events; data-flow
  diagram updated; connected-files matrix gains entries for `bash_guard.py`
  and `tests/`.
- `README.md` — defense-layer list now includes Bash bypass guard; hook table
  lists 5 events.

### Removed (from Unreleased roadmap)

- "Bash bypass-pattern guard" — implemented here.

---

## [0.2.0] — 2026-04-27

The hard layer goes live. Soft prompt-injection (v0.1.0) is now backed by an
actual gate: the agent cannot Edit a file it has not first Read, and any tool
call against a file is recorded as "known content" for the rest of the session.

### Added

- **`hooks/scripts/lib/state.py`** — per-session JSON state at
  `${CLAUDE_PLUGIN_DATA}/sessions/<session_id>.json` (with documented fallbacks
  to `${CLAUDE_PROJECT_DIR}/.claude/local/cc-enslaver/sessions/` and
  `~/.claude/local/cc-enslaver/sessions/`). Path normalisation via
  `os.path.realpath` + `os.path.normcase` for case-insensitive Windows
  comparison.
- **`hooks/scripts/read_guard.py`** — single script with two roles:
  - `PostToolUse` matcher `Read|Write`: append touched file to session state.
  - `PreToolUse` matcher `Edit|Write`: emit
    `{"hookSpecificOutput": {"permissionDecision": "deny", ...}}` when the
    target already exists on disk but has not been recorded for this session.
    Allows new-file creation (`os.path.exists` check). Failing-open: any
    exception logs to stderr but lets the tool call proceed.
- **`.claude-plugin/marketplace.json`** — the plugin can now be installed
  locally via `/plugin marketplace add <path-to-repo>` and then
  `/plugin install cc-enslaver@<marketplace-name>`.

### Changed

- **`hooks/hooks.json`** — registers four events now: `SessionStart`,
  `UserPromptSubmit`, `PostToolUse` (matcher `Read|Write`), `PreToolUse`
  (matcher `Edit|Write`).
- **`.claude-plugin/plugin.json`** — version bumped `0.1.0 → 0.2.0`.
- **`docs/ARCHITECTURE.md`** — Layer 1 description, data-flow diagram, and the
  connected-files matrix updated to cover `read_guard.py` + `lib/state.py`.
- **`README.md`** — hook table now lists all four events; install section
  documents the `/plugin marketplace add` flow.
- **`CLAUDE.md`** — §6 "当前版本" reflects v0.2.0.

### Removed (from Unreleased roadmap)

- "Hard-layer `PreToolUse` blocks" (read-before-edit half) — implemented here.
- "Marketplace manifest" — implemented here.
- "Verification trace persistence" — replaced by per-session state. Cross-session
  persistence is intentionally out of scope (session boundaries are meaningful).

---

## [0.1.0] — 2026-04-27

Initial skeleton release. Establishes the full layered defense scaffold; only the
soft layer is wired live.

### Added

- **Plugin manifest** — `.claude-plugin/plugin.json` with name, version, author,
  license, and pointers to `commands/`, `agents/`, `skills/`, and
  `hooks/hooks.json`.
- **Project instructions** — formalized `CLAUDE.md` (replaces the original
  free-form `claude.md`), now structured into goals, principles, repo layout,
  contribution flow, metadata, and version status.
- **Rule pack** (`rules/`) — five LLM-agnostic Markdown rule files plus an index:
  - `01-verify-dont-guess.md`
  - `02-systematic-not-reactive.md`
  - `03-root-cause.md`
  - `04-full-context.md`
  - `05-cite-sources.md`
- **Prompt-injection content** (`prompts/`) — `session-start.md` and
  `user-prompt.md`, distilled from the rule pack for in-context use.
- **Hook layer** (`hooks/`) — `hooks.json` registers two events
  (`SessionStart`, `UserPromptSubmit`); `scripts/inject_context.py` emits the
  appropriate `additionalContext` JSON for each event.
- **Slash commands** (`commands/`) — `/cc-enslaver:checklist` prints the
  systematic-thinking checklist; `/cc-enslaver:verify` prompts a
  re-verification pass.
- **Verifier subagent** (`agents/verifier.md`) — independent `file:line` citation
  re-reader, returns drift/missing/intact verdict.
- **Skill** (`skills/systematic-debug/`) — auto-invokes on debugging language and
  forces a root-cause walk-through before any fix is proposed.
- **Repo-standard files** — `README.md` (bilingual), `LICENSE` (MIT),
  `.gitignore`, this `CHANGELOG.md`, `docs/ARCHITECTURE.md`, `docs/RULES.md`.

### Removed

- Original free-form `claude.md` (replaced by the structured `CLAUDE.md`).

[Unreleased]: https://github.com/skymanbp/cc-enslaver/compare/v0.11.0...HEAD
[0.11.0]: https://github.com/skymanbp/cc-enslaver/compare/v0.10.0...v0.11.0
[0.10.0]: https://github.com/skymanbp/cc-enslaver/compare/v0.9.1...v0.10.0
[0.9.1]: https://github.com/skymanbp/cc-enslaver/compare/v0.9.0...v0.9.1
[0.9.0]: https://github.com/skymanbp/cc-enslaver/compare/v0.7.0...v0.9.0
[0.8.0]: https://github.com/skymanbp/cc-enslaver/compare/v0.7.0...v0.9.0
[0.7.0]: https://github.com/skymanbp/cc-enslaver/compare/v0.6.2...v0.7.0
[0.6.2]: https://github.com/skymanbp/cc-enslaver/compare/v0.6.1...v0.6.2
[0.6.1]: https://github.com/skymanbp/cc-enslaver/compare/v0.6.0...v0.6.1
[0.6.0]: https://github.com/skymanbp/cc-enslaver/compare/v0.5.1...v0.6.0
[0.5.1]: https://github.com/skymanbp/cc-enslaver/compare/v0.5.0...v0.5.1
[0.5.0]: https://github.com/skymanbp/cc-enslaver/compare/v0.4.0...v0.5.0
[0.4.0]: https://github.com/skymanbp/cc-enslaver/compare/v0.3.2...v0.4.0
[0.3.2]: https://github.com/skymanbp/cc-enslaver/compare/v0.3.1...v0.3.2
[0.3.1]: https://github.com/skymanbp/cc-enslaver/compare/v0.3.0...v0.3.1
[0.3.0]: https://github.com/skymanbp/cc-enslaver/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/skymanbp/cc-enslaver/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/skymanbp/cc-enslaver/releases/tag/v0.1.0
