# Architecture

> Audience: developers extending or auditing the plugin.
> Doc index: [`./README.md`](./README.md). Companion docs:
> [`../CLAUDE.md`](../CLAUDE.md) (project-level rules),
> [`./RULES.md`](./RULES.md) (catalog of every rule),
> [`../tests/README.md`](../tests/README.md) (the suite, file by file).

---

## 1. Why a layered design

A single mechanism can never enforce discipline reliably. Prompt injection can be
ignored by a confident-and-wrong agent; a hard tool block can be bypassed by
re-phrasing; a subagent verifier only fires when invoked. We therefore stack
**five independent layers**, each catching a different failure mode:

```
┌─────────────────────────────────────────────────────────────┐
│  Layer 5 — LLM-agnostic core (rules/ — plain Markdown)      │  source of truth
├─────────────────────────────────────────────────────────────┤
│  Layer 4 — Skill (auto-invoked on debugging language)       │  contextual nudge
├─────────────────────────────────────────────────────────────┤
│  Layer 3 — Verifier subagent (independent re-reader)        │  citation audit
├─────────────────────────────────────────────────────────────┤
│  Layer 2 — Slash commands (user/agent-triggered)            │  on-demand
├─────────────────────────────────────────────────────────────┤
│  Layer 1 — Hooks (always-on prompt injection)               │  always-on
└─────────────────────────────────────────────────────────────┘
```

Failure of any one layer does not collapse the system; the next layer still
catches the lazy behaviour, often via a different signal.

---

## 2. Layer 1 — Hooks (always-on)

**Wired in:** [`../hooks/hooks.json`](../hooks/hooks.json).
**Implementations:**
- Soft injection: [`../hooks/scripts/inject_context.py`](../hooks/scripts/inject_context.py)
- Read-before-edit guard: [`../hooks/scripts/read_guard.py`](../hooks/scripts/read_guard.py) + [`../hooks/scripts/lib/state.py`](../hooks/scripts/lib/state.py)
- Bash guard (bypass patterns + register-as-read): [`../hooks/scripts/bash_guard.py`](../hooks/scripts/bash_guard.py)
- Register stub (v0.4.0): [`../hooks/scripts/register_read.py`](../hooks/scripts/register_read.py)
- Stop guard (v0.6.0 → … → v0.23.0, rule 01 + 06 + 07 + 08 + 09 + 12 + TL;DR enforcement): [`../hooks/scripts/stop_guard.py`](../hooks/scripts/stop_guard.py) + [`../hooks/scripts/lib/sync_gate.py`](../hooks/scripts/lib/sync_gate.py)
- **Shared judgement models (v0.26.0)** — three modules that exist because
  every guard had been answering a *structural* question with a *textual*
  test, and each audit round regenerated the same defect class:
  - [`../hooks/scripts/lib/srclex.py`](../hooks/scripts/lib/srclex.py) —
    tolerant source lexer. Answers "is this `#` a comment, a docstring, or
    data?", "where does this literal end?", and "which physical lines form
    one logical line?". Deliberately a **lexer, not a parser**: an Edit's
    `new_string` is usually not a syntactically complete unit, so `ast` /
    `tokenize` would raise on ordinary input and force a fallback that
    recreates the original bug. Consumed by `read_guard`'s rule 09/10/11
    detectors. It is what makes the rationale hatch mean "a why-**comment**"
    (previously `line.find("#")` found the `#` inside a URL, so one
    neighbouring `https://api.example.com` line disabled the secret detector).
  - [`../hooks/scripts/lib/mdctx.py`](../hooks/scripts/lib/mdctx.py) —
    markdown line context (fence state + info string, blockquote including
    nesting under list items and CommonMark lazy continuation). Consumed by
    **both** halves of Stop layer (h); they previously carried partial
    private copies of this judgement and disagreed about which fences count.
    **v0.27** splits the verdict in two, because one flag could not serve
    both halves: `attributable` (generous — "could a reader read this as
    the agent's own words?", used for PRESENCE, since a false negative
    blocks a reply for a tldr that is visibly present) and `countable`
    (conservative — "is this definitely the agent's own words?", used for
    MEASUREMENT against the tldr cap — 160 **display columns** since
    v0.35). They differ only on lazy continuation, which is exactly why
    v0.26 could not implement it.
  - [`../hooks/scripts/lib/shellcmd.py`](../hooks/scripts/lib/shellcmd.py) —
    shell command model: tokenise → segments → argv, plus `git_subcommand`
    (skipping value-taking global options) and `python_script_arg` (knowing
    that `-c` / `-m` take code/module operands, not scripts). Consumed by
    `bash_guard`'s force-push detector *and* its register parser, which were
    two independent text heuristics that had already drifted apart.
  - [`../hooks/scripts/lib/editscale.py`](../hooks/scripts/lib/editscale.py)
    (**v0.35**) — change-scale model: `classify_change(old, new, scale)`
    answers "how big is this edit *relative to the file it edits*", plus
    the two shapes that are never rolling patches (`is_net_reduction`,
    `is_bookkeeping_edit`). Consumed by `read_guard`'s rule-09 frequency
    layer, which keeps only the *frequency* policy (how many small edits
    per file before DENY). Same reason as the three above: the
    classification had only ever been reachable through a hook payload,
    so its worst case — a file below both absolute floors, where NO edit
    can qualify as systematic and the counter can never be reset —
    survived twenty-two releases because every test fixture happened to
    be one line long. A model with a signature can be asked directly.
- **Project-root detection shared by both config loaders (v0.30)**: [`../hooks/scripts/lib/projroot.py`](../hooks/scripts/lib/projroot.py). Both hand-edited configs (`edicts.toml`, `sync-gate.toml`) fall back to the process cwd when `CLAUDE_PROJECT_DIR` is missing — which Claude Code's Bash tool does not reliably propagate on Windows (the v0.18.1 finding) — but only when that cwd carries a `.git` / `.claude` marker, so a session started in `~/Downloads` cannot load a stranger's hard rules. The predicate lived in both loaders until v0.30, the second copy annotated *"Same project-root heuristic as lib/edicts.py"*: a comment that names an invariant without holding it, so widening one copy leaves the other silently behind. Same answer `tomlio` gave one layer down.
- Hardened TOML reader shared by both config loaders (v0.25): [`../hooks/scripts/lib/tomlio.py`](../hooks/scripts/lib/tomlio.py) — strips a UTF-8 BOM and turns a non-UTF-8 config into a stderr diagnostic instead of an uncaught `UnicodeDecodeError`. Both configs drive hard guards, and in both the failure was *silent disablement* of enforcement: a GBK-saved `edicts.toml` escaped `edicts.load()` and unwound past every downstream check in `read_guard`, switching off read-before-edit for the whole session. **v0.25.1 extends this to the parsed values, not just the bytes**: `severity = ["must"]` / `mode = []` are valid TOML, and `value not in SET` raises `TypeError: unhashable type` — which escaped the same two loaders through a different door. Both now type-check before the membership test, and `manage_edicts.py` was finally routed through this module too (v0.25 wired the two hook-side loaders and never swept the tree, so `edict list / add / remove` still crashed on a file the hooks read fine — the repo-wide-sync omission rule 12 exists to catch).

Five hook entries across four events:

| Event | Matcher | Script | Purpose |
|---|---|---|---|
| `SessionStart` | — | `inject_context.py` | Inject full discipline summary at session boot; then run the two maintenance passes (opt-in auto-GC of old session state, `CLAUDE_ENV_FILE` dedupe) |
| `UserPromptSubmit` | — | `inject_context.py` | Inject compact per-turn reminder |
| `PreToolUse` | `Read\|Edit\|Write` | `read_guard.py` | Record on Read/Write; deny Edit/Write of unread existing file (rule 04 + 08); deny Edit/Write with unjustified patch-style new_string (rule 09), hardcoded secret (rule 10), or user-home path dependency (rule 11) in code targets; record the edit-turn signal for Stop layers (e)/(f)/(g)/(i) — `edited_since_last_stop` flag always, plus `last_edit_turn` when the payload supplies a turn_count (v0.23: production payloads do NOT); record accepted edits into `edited_files` for Stop layer (i) (rule 12, v0.23) |
| `PreToolUse` | `Bash` | `bash_guard.py` | Deny on bypass patterns (rule 03 + 09); also register file-as-read on `register_read.py` invocation |
| `Stop` | — | `stop_guard.py` | Nine-layer block: (a) no-evidence / (b) hedged-completion / (c) missing rule-06 quiz / (d) missing rule-07 fidelity / (e) missing rule-08 system-thinking (edit turns only) / (f) missing rule-09 triplet (edit turns only) / (g) file-claim contradicted (edit turns only) / (h) missing or overlong TL;DR / (i) rule-12 sync-gate group unmet (edit turns only, opt-in per project) |

#### Why everything in `PreToolUse` (and not split with `PostToolUse`)

v0.3.1 split recording (PostToolUse) and gating (PreToolUse). v0.3.2 unified
both into PreToolUse because **`PostToolUse` does not fire for tool calls
whose `tool_input.file_path` lies outside the current project working
directory, while `PreToolUse` does**. The mismatch caused false-positive
denies on out-of-project files (e.g., per-project memory files in
`~/.claude/projects/<project>/memory/`): the agent would Read X, no record,
then Edit X → DENY. v0.3.2 records on PreToolUse(Read) and gates on
PreToolUse(Edit/Write); both share a scope by construction.

The trade-off: recording in Pre is speculative (happens before the tool
result is known). **Only targets that already exist are recorded (v0.25).**
The earlier reasoning here — that a phantom record for a not-yet-existing
path was harmless because Edit's `os.path.exists` short-circuit covers it —
was wrong, and the code now says so explicitly. That short-circuit only
holds while the file is *still* missing: Read a build artifact before it
exists (an ordinary workflow), let the build create it, and the stale
record satisfies `has_read`, so an Edit — or a whole-file Write — lands on
content the session has never seen, with rule 04 disabled for that path for
the rest of the session. A missing target still records an mtime baseline,
which is exactly what Stop layer (g) needs to adjudicate "I created X".

#### Why four scripts (not one)

Four scripts are registered as hooks (`inject_context.py`, `read_guard.py`,
`bash_guard.py`, `stop_guard.py` — the last since v0.6.0). Each has a
different responsibility and a different failure mode:
- `inject_context.py` never blocks: always exit 0, and stdout carries
  nothing but `additionalContext`. It is *not* disk-read-only, though —
  on `SessionStart` it also runs two maintenance passes: opt-in auto-GC
  (deletes expired session files, rewrites the `_auto_gc.json` marker)
  and `envfile.maybe_dedupe()` (rewrites the harness-owned
  `CLAUDE_ENV_FILE`, v0.34). Both run after the payload is assembled and
  both fail open, so their failure mode is a skipped maintenance pass,
  never a lost injection.
- `read_guard.py` owns per-session disk state, with both recording and
  gating in PreToolUse (Read/Write/Edit). Its failure mode is state-file
  corruption.
- `bash_guard.py` inspects commands and also mutates session state (the
  `register_read` escape hatch) and reads `edicts.toml` off disk. Since
  v0.26 its two structural decisions — force-push detection and
  register-command parsing — go through the `lib/shellcmd` parse model
  rather than regexes over the raw command string, so its failure mode is
  a mis-parse, not just a regex bug.
- `stop_guard.py` is read-only with respect to the turn's work but owns the
  Stop decision tree and the one-shot block state.

Collapsing them into one script would chain independent failure modes
behind a single try/except — a bug in any one would mask the others. Keeping
them separate also lets each script load only the imports it actually needs.

#### Soft-layer output contract (`inject_context.py`)

Always exit 0. Emits:

```json
{
  "hookSpecificOutput": {
    "hookEventName": "SessionStart",
    "additionalContext": "<contents of prompts/session-start.md>"
  }
}
```

Never blocks, and nothing but that envelope reaches stdout. It is not
inject-only on disk, however: `SessionStart` additionally runs the opt-in
auto-GC (prunes session state, rewrites `_auto_gc.json` — see
[`gc_state.py`](../hooks/scripts/gc_state.py)) and
[`lib/envfile.py`](../hooks/scripts/lib/envfile.py)'s `maybe_dedupe()`,
which collapses duplicate `export` lines in the harness's
`CLAUDE_ENV_FILE` (v0.34). Both are side-channel maintenance — invoked
after the context is built, failing-open, diagnostics on stderr only —
so neither can alter or suppress the injected payload.

#### Hard-layer output contract (`read_guard.py`)

`PreToolUse` (record): on Read/Write, `state_lib.add_read` is called and the
script exits 0 silently with state written to disk.

`PreToolUse` (allow): exit 0 silently. (Allow is the default with no output.)

`PreToolUse` (deny): exit 0, emits

```json
{
  "hookSpecificOutput": {
    "hookEventName": "PreToolUse",
    "permissionDecision": "deny",
    "permissionDecisionReason": "cc-enforcer · rule 04 violation ..."
  }
}
```

The reason text tells the agent precisely how to recover (Read first, then retry).

#### Per-session state storage

The guard uses **session_id** from the hook payload as the state key. Storage
location resolves in this order:

1. `${CLAUDE_PLUGIN_DATA}/sessions/<sid>.json` — preferred, set by Claude Code
   for plugin hooks.
2. `${CLAUDE_PROJECT_DIR}/.claude/local/cc-enforcer/sessions/<sid>.json` —
   per-project fallback.
3. `~/.claude/local/cc-enforcer/sessions/<sid>.json` — final fallback.

State files are git-ignored (`.gitignore:27` — `.claude/local/`, which
covers fallback 2; fallbacks 1 and 3 live outside the repo). Paths within state are
canonicalised via `os.path.realpath` + `os.path.normcase` so case-insensitive
filesystems (Windows) compare correctly.

**Concurrency (v0.23, completed v0.24)**: every hook invocation is a separate
OS process, and Claude Code fires parallel tool calls as concurrent hook
subprocesses sharing one session file. Every state *mutation* holds a
per-session cross-process advisory lock (`_session_lock`: `msvcrt.locking` on
Windows / `fcntl.flock` on POSIX, on a sibling `<sid>.json.lock` file) across
its load→mutate→save cycle, and `save()` is atomic (unique temp file +
`os.replace`) so readers can never observe a torn JSON. Measured before the
v0.23 fix: 10 parallel `PreToolUse(Read)` hooks lost 2-3 of 10 recorded paths
per round — the visible symptom was a false rule-04 DENY immediately after the
file WAS read. **v0.24 closed the other half**: the v0.23 read accessors were
lock-free, and on Windows a writer's `os.replace` fails with `PermissionError`
while ANY process holds the target open (CPython's `open()` does not request
`FILE_SHARE_DELETE`) — the hooks' own readers collided with their own writers
(measured 300/300 lost saves under tight-loop readers; live state dirs carried
orphan `<sid>.json.<pid>.tmp` debris). Read accessors now route through the
same lock (`_load_shared`), `save()` retries the replace with a short backoff
against non-cooperating external readers (antivirus / indexers) and unlinks
its temp file if it ever gives up, and `load()` retries once on a transient
`OSError` (a bare degrade returns an empty record, which a locked mutator
would save back — full session amnesia). Lock acquisition failure still
degrades to unlocked behavior with a stderr diagnostic (failing-open, never a
bricked agent). `gc_state.py` prunes `*.json` session files and (v0.24)
sweeps day-old orphan `*.tmp` files; lock files are never deleted out from
under a holder.

#### Failing-open

Any unhandled exception in `read_guard.py` is caught, logged to stderr, and
the script exits 0 (allow). A bug in the guard cannot be permitted to brick
the agent — discipline enforcement must never become an obstacle to actual work.

#### `Stop` guard (rule 01 + 06 + 07 + 08 + 09 + 12 + TL;DR enforcement, v0.6.0 → v0.7.0 → v0.8.0 → v0.11.0 → v0.16.0 → v0.20.0 → v0.23.0)

`stop_guard.py` (event `Stop`, no matcher — Stop fires unconditionally per
Claude Code spec) inspects `payload.assistant_message` (or falls back to
the last assistant entry in `payload.transcript_path`).

**Decision tree (v0.11.0):**

| Step | Condition | Action |
|------|-----------|--------|
| 0 | One-shot guard window (`turn_count` ∈ `[last_blocked + 1, last_blocked + 3]`; **v0.23**: production Stop payloads carry no turn_count — verified live — so a monotonic turn number is synthesized from the per-session `stop_counter`, which restores the grace arithmetic in production). **v0.24**: the message is now extracted *before* this guard, and a grace-window reply carrying a sync marker records its layer-(i) group acknowledgement — but only when the block being recovered from was itself at layer (i) (`last_blocked_layer`), so a reply merely quoting "sync-check" while recovering from an unrelated layer cannot ack anything. The block→recover-with-`同步核对` flow used to lose the ack entirely, so the answered group re-blocked after the grace expired | Allow |
| 1 | No done-claim regex matched | Allow |
| 2 | Hedge regex within 50 chars of done-claim (rule 01) | **Block** (layer (b), `_RECOVERY_B`) |
| 3 | No evidence regex matched (v0.6.0 base) | **Block** (layer (a), `_RECOVERY_A`) |
| 4 | No convergence marker AND fewer than 2 self-quiz questions (rule 06 deep) | **Block** (layer (c), `_RECOVERY_C`) |
| 5 | No fidelity marker AND fewer than 2 of 3 fidelity questions (rule 07) | **Block** (layer (d), `_RECOVERY_D`) |
| 6 | edit turn (`edited_since_last_stop` flag, or `last_edit_turn == turn_count` when supplied) AND no rule-08 marker AND fewer than 3 of 6 rule-02 keywords (rule 08, **v0.11**; edit signal fixed for production in **v0.23**) | **Block** (layer (e)) |
| 7 | edit turn AND no rule-09 marker AND triplet (root-cause + impact + solution) incomplete (rule 09, **v0.11**) | **Block** (layer (f)) |
| 8 | edit turn AND a file-edit/create claim is **definitively contradicted** by the on-disk mtime baseline (rule 01 + 06, **v0.16**; `CC_ENFORCER_DISABLE_LAYER_G=1` to skip) | **Block** (layer (g)) |
| 9 | No TL;DR marker (`tldr:` / `大白话` / `一句话总结` / `TL;DR`) — fires on **every** done-claim turn, not just edit turns (**v0.20**) | **Block** (layer (h)) |
| 10 | A tldr item wider than `TLDR_MAX_ITEM_COLUMNS` (160 **display columns**, **v0.35** — a CJK character costs 2, so ≈ 80 汉字; ASCII is unchanged at 160) — one sentence per item, cause + action + outcome; several things → one short line each (**v0.23**) | **Block** (layer (h), "overlong" note + dedicated recovery) |
| 11 | edit turn AND a sync-gate group's `when` glob matched an edited file with its `require` side unsatisfied (per the group's `mode`: any-of by default, all-of for lock-step invariants) AND the group is not in the session's `sync_acked_groups` AND no sync marker (`同步核对` / `sync-check` / `rule 12` / `全库同步` / `连带核对` / `repo-wide sync` — deliberately NOT `sync-gate`, which is the config file's name, not a claim) in the reply (rule 12, **v0.23**; per-project opt-in via `.claude/cc-enforcer/sync-gate.toml` — no config, never fires). A marker escape records the acknowledged groups for the session, so one explicit answer per group suffices. **v0.27**: the marker settles only groups the session has actually been SHOWN (`last_blocked_groups`) — the primary path used to ack every pending group while the grace path acked only the presented set, and that inconsistency was itself the bypass (outlast the grace window, reach the looser path). A group is therefore named by one block, then settled by the next reply's marker: one *informed* answer per group. | **Block** (layer (i)) |
| 12 | All gates passed | Allow |

**Done-claim patterns**: `已解决` / `已修复` / `已完成` / `完成了` / `完工` /
`搞定` / `[修改弄搞]好了` / `\bfixed\b` / `\bdone\b` / `\bcompleted\b` /
`\bresolved\b` / `\bimplemented\b` / `\bfinished\b` (v0.25.1) /
`(is|are|was|were) complete` / `<noun> complete` / `ready to ship`
(v0.26) / `all set` / `should work now` / `that should do it`. The list
is exhaustive on purpose: `_has_done_claim` gates **all nine layers**, so
a completion phrased outside it skips the entire stack — which is why
v0.25.1 and v0.26 each had to widen it after finding a live phrasing that
matched nothing. Note that `should work now` and `that should do it` are
**done**-claims, not hedges; bare `should` is excluded from the hedge set
just below, and the two lists do not overlap.

**Evidence patterns**: shell-prompt lines (`$ ` / `> `), `Ran N tests`,
`N passed/failed`, `pytest` / `unittest`, `重触发` / `边界用例` / `反向用例`
/ `收敛`, `verified` / `re-?ran` / `validated`, fenced code block
of ≥20 chars output.

**v0.7.0 hedge patterns** (must be within 50 chars of a done-claim, in
either order, to fire): `我[记觉]得` / `我相信` / `可能就` / `应该是` /
`大概(是)?` / `I think` / `I believe` / `I guess` / `maybe` / `probably`
/ `kinda` / `sort of`. Generic non-first-person hedges like `通常` or
`should` are intentionally **excluded** — they appear too often in
legitimate technical writing far from the completion claim.

**v0.7.0 convergence markers** (single match suffices to pass the
self-quiz gate): `rule 06` / `自答` / `收敛` / `convergence` /
`self-quiz`, plus the rule-06-specific check names `重触发` / `边界用例`
/ `反向用例`.

**v0.7.0 self-quiz patterns** (≥ 2 of 4 must match, in either Chinese
or English):

| # | Question | Patterns |
|---|----------|----------|
| 1 | Really solved? | `真.*?解决` / `really.*?(?:solv\|fix)` |
| 2 | Better solution? | `更好.*?(?:方案\|方法\|做法)` / `better.*?(?:solut\|approach\|way)` |
| 3 | Unverified parts? | `(?:哪些\|哪里).*?(?:没验\|未验)` / `unverif` |
| 4 | Meaningful verification? | `验证.*?(?:合理\|是否充分)` / `verification.*?(?:meaning\|reasonab)` |

**v0.8.0 fidelity markers** (rule 07; single match suffices to pass
the fidelity gate): `rule 07` / `任务忠实` / `请求覆盖` / `原始请求` /
`无遗漏` / `无降级` / `未降级` / `未遗漏` / `无超范围` / `未超范围` /
`task fidelity` / `request coverage` / `request fidelity` /
`no degradation` / `no omission` / `no scope creep` / `covered all` /
`all requested`, plus the `[✅⚠️❌] … (完成|done|完工)` checklist-row
pattern (the agent enumerated original-request items with check
marks).

**v0.8.0 fidelity self-quiz patterns** (rule 07; ≥ 2 of 3 must match,
in either Chinese or English):

| # | Question | Patterns |
|---|----------|----------|
| 1 | Coverage — did I do every sub-item? | `(?:用户\|原始).*?(?:请求\|要求).*?(?:拆\|列\|包含\|分成\|项\|子项)` / `decompos.*?request` / `sub-?item` / `coverage.*?(?:check\|complete)` |
| 2 | Standard — did each modifier word land as hard action? | `(?:强制\|必须\|完整\|严格\|全面\|所有).*?(?:落实\|硬动作\|硬证据\|拦截\|断言\|实现\|生效)` / `(?:mandator\|strict\|comprehensive\|all\|every\|hard).*?(?:enforced\|verifi\|hook\|assert\|land)` |
| 3 | Fidelity — concept-swap / scope creep / buried TODO? | `偷换\|降级\|超范围\|额外的?(?:改\|修)\|遗漏\|裁剪` / `concept.?swap\|degrad\|scope.?creep\|omission\|trim\|drive-?by` |

Layer (d) fires only when (a)(b)(c) all pass, so the agent has
already shown it both has evidence and engaged with the rule-06
self-quiz; the fidelity layer adds the orthogonal "did you deliver
everything the user asked for?" check before allowing the Stop.

**v0.11.0 rule-08 closing markers** (layer (e); single match
suffices to pass the gate): `rule 08` / `改前必读` / `写前必想` /
`read-before-edit` / `think-before-write` / `系统式自答`.

**v0.11.0 rule-02 systematic-thinking keywords** (layer (e)
fallback; ≥ 3 of 6 must match):

| # | Keyword (CN / EN) |
|---|-------------------|
| 1 | 架构 / architecture / architectural |
| 2 | 职责 / responsibility |
| 3 | 根源 / 根因 / root-cause |
| 4 | 方案 / solution / approach |
| 5 | 连带 / 下游 / 影响范围 / downstream / impact / connected |
| 6 | 风险 / 不变量 / invariant / risk |

**v0.11.0 rule-09 closing markers** (layer (f); single match
suffices to pass the gate): `rule 09` / `系统式修改` / `打补丁` /
`systematic modification` / `patch-style` / `non-patch` / `反补丁`.

**v0.11.0 rule-09 triplet keywords** (layer (f) fallback; **all
three** must match):

| # | Triplet axis (CN / EN) |
|---|-------------------------|
| 1 | 根源 / 根因 / root-cause |
| 2 | 连带 / 影响范围 / impact / blast-radius / downstream |
| 3 | 方案 / solution / approach / alternative |

**v0.20.0 TL;DR markers** (layer (h); single match suffices to pass
the gate): `tldr:` (the canonical YAML schema field) / `大白话` /
`一句话总结` / `一句总结` / `TL;DR`. Unlike (e)/(f)/(g), layer (h)
fires on **every** done-claim turn — a status report or an answer
benefits from a one-line takeaway just as much as a code edit. It is the
final gate (reached only after all discipline checks pass) and is
enforced as a closing readability convention, deliberately **not**
promoted to a tenth numbered rule (which would require the full
`rules/*.md` + `rules/zh/` + `00-index` + docs fan-out). The v0.20
canonical reply schema is a YAML block whose field names (`改前 / 改中 /
收敛 / 忠实 / 收尾 / 同步核对 / tldr`, English: `before / edits /
convergence / fidelity / closing / sync-check / tldr`) ARE the layer
markers above — so a
schema-conformant reply passes (a)-(h) with no detector changes.

**v0.31.1 — `sync-check` / `同步核对` joins the schema.** Rule 12 shipped in
v0.23, three releases after the v0.20 schema was fixed, and its
acknowledgement was the one closing obligation with no field to write it in:
free prose the agent had to remember. It is now a field like the rest, and —
per the v0.20 design — the field name IS the `SYNC_MARKERS` pattern, so no
detector changed. **It does not weaken layer (i)**, verified by probe rather
than by reading: since v0.27 a marker settles only groups a previous block
actually NAMED, so a first violation still blocks and names its group, and the
schema field is where the answer to *that* group goes on the next turn. A
mandatory field does invite a boilerplate answer, though, and that half stayed
open until v0.32: a placeholder value now counts as absent, and a marker the
agent merely quoted is not the agent's claim.
**v0.32 closes the gap v0.31.1 recorded.** `_has_sync_marker` was
`any(pattern.search(text))` — presence only — so `sync-check: n/a`, and a
marker the agent merely *quoted*, both settled a named group. It now applies
the two tests layer (h) already applies to `tldr`, through the same `lib/mdctx`
model: **attribution** (a marker inside a non-canonical fence or a blockquote
is illustrative, not a claim) and **substance** (the value must carry content,
on its own line or the next non-blank one; `_SYNC_NON_ANSWERS` treats a bare
placeholder as absent, and a non-answer cannot borrow the following line).
Deliberate strictness increase, decided by the user on 2026-08-17. **The limit
is pinned by its own test**: vacuous *prose* (`sync-check: checked it`) is not
detected and is not claimed to be — over-reaching would refuse honest reports,
which is the worse error.

**v0.20.0 block-reason 大白话 line**: every block reason now appends a
one-line plain-language takeaway (`大白话: ...`) before the one-shot
footer, so cc-enforcer's own output is symmetric with the layer-(h)
requirement it imposes on the agent.

**v0.23.0 layer (h) length cap** (**v0.35** — now measured in display
columns): beyond mere presence, each tldr item must stay within
`TLDR_MAX_ITEM_COLUMNS` (160) display columns, where an East-Asian
wide character costs 2 and a combining mark 0. The constant was
`TLDR_MAX_ITEM_CHARS` and counted code points until v0.35, which made
one number mean two things across a bilingual contract — the comment
above it conceded as much ("a full English sentence fits; a Chinese
sentence is far shorter"), i.e. the zh side enforced a bound about
twice as loose while the whole point of the layer is that a TL;DR is
one sentence. ASCII behaviour is unchanged. Extraction is
line-based and conservative (only lines attributable to a tldr marker —
the marker line's value plus more-indented continuation / `- ` list
lines — are measured; anything ambiguous is not measured, failing open).
The block reuses layer (h) with an "overlong" table note and its own
recovery text (`_RECOVERY_H_LONG`).

**v0.25.1 layer (h) presence must mean content**: a bare `tldr:`, a
`tldr: ""`, or a blockquoted `> tldr: …` (quoting someone else) used to
satisfy the presence half outright, while the length half then measured
nothing — so the emptiest possible summary passed both. `_has_tldr` now
requires the marker to introduce actual text, on its own line or on the
next non-blank one, and ignores blockquoted markers.

**v0.25.1 `_has_done_claim` is the gate on all nine layers.** Every layer
is downstream of it, so a completion phrased outside `DONE_PATTERNS` did
not skip one check — stop_guard returned immediately and cleared the edit
flag on the way out. `已完成` / `Implemented` / `Finished` /
`is/are complete` were all silently exempt and are now covered. The
converse was also true: a bare keyword search read `Not done; tests
failed.` and `This is not fixed` as completions (and unbounded `all set`
matched inside "Not all settings"), so an honest report of failure could
be blocked. Matches preceded by a negator are now skipped and the scan
continues, so a later unnegated claim still counts. Evidence detection
(layer (a)) also learned the Windows prompt shapes `PS C:\repo>` and
`C:\repo>`, which matched none of the POSIX-only patterns — a Windows
user pasting a genuine transcript was told they had produced none.

**v0.23.0 layer (i) — rule 12 repo-wide sync gate**: `read_guard.py`
records every ACCEPTED Edit / Write path into the session's
`edited_files` set; at Stop, `lib/sync_gate.py` loads the project's
`.claude/cc-enforcer/sync-gate.toml` (resolution: payload cwd →
`CLAUDE_PROJECT_DIR` → process cwd with a project-root marker; no
home-level fallback — groups are inherently per-repo) and evaluates each
`[[groups]]` entry: `when` globs matched by an edited project-relative
path with the `require` side unsatisfied (any-of by default;
`mode = "all"` demands every require glob be matched) → violation. The
reply passes anyway if it carries a sync marker (SYNC_MARKERS), making
"checked, no change needed" an explicit, legitimate outcome — and the
escaped groups are persisted as `sync_acked_groups`, so the cumulative
edited-file set cannot re-block an already-answered group on later
unrelated edits. fnmatch semantics: `*` crosses path separators;
matching is normcased. No config → the layer never fires (per-project
opt-in). Loader and evaluator are failing-open.

**v0.25.1 — the grace-window ack is scoped to the groups the block
presented.** A recovery turn is still an editing turn: if it touched
files violating a *different* group, that group became pending only
after the block, was never shown to the agent, and was never answered —
yet `_ack_pending_sync_groups` re-derived "everything pending now" and
silenced it for the rest of the session. The layer-(i) block now records
its presented group names (`last_blocked_groups`), and the ack
intersects with that set (falling back to the pending set when no list
was recorded, i.e. a block from before this field existed). The related
question of whether the ack should also honour recoveries from layers
other than (i) is a **contract** question about enforcement strictness,
reaffirmed as "stay strict" by the user on 2026-08-10.

**Why layers (e)+(f) are scoped to edit turns**: a pure analysis /
answer turn should not be forced to surface think-before-write or
root-cause/impact/solution markers — there was nothing modified for
those to apply to. **Edit-turn signal (reworked in v0.23)**: the
original v0.11 design stamped `last_edit_turn = turn_count` and
compared it at Stop — but a live-state E2E audit found production hook
payloads carry NO `turn_count` (a real session with 27 recorded edits
had no `last_edit_turn` key at all), so layers (e)/(f)/(g)/(i) had
never fired outside the test suite. `read_guard.py` now always sets an
`edited_since_last_stop` flag on every accepted Edit / Write;
`did_edit_this_turn` honors the flag OR the exact turn match (test
harnesses / future payloads). stop_guard clears the flag on every
ALLOWED Stop (a turn boundary) and keeps it on blocks — the recovery
reply is the same logical turn. The one-shot guard still applies, via
the synthesized `stop_counter` turn number when the payload has none.

**Why detection is heuristic and lightweight**: same rationale as
layers (c)(d). A careful agent who genuinely did the rule-08/09
work will naturally use these keywords in their own phrasing;
demanding a verbatim formula would false-positive on legitimate
prose. The single-marker escape (`rule 08` / `rule 09`) lets an
agent who used non-keyword phrasing still flag they did the work.
The one-shot guard caps false-positive cost at exactly 1 corrective
turn per block.

**One-shot guard**: `state_lib.record_stop_block(session_id, turn_count)`
on every block; `state_lib.was_just_blocked(session_id, turn_count)`
returns True for `turn_count ∈ [last + 1, last + 3]` so the agent has a
multi-turn grace window to recover. After the grace expires, fresh
blocks resume.

**Block output is asymmetric**: Stop hook uses **top-level**
`{"decision": "block", "reason": ...}`, NOT the `hookSpecificOutput`
envelope used by `PreToolUse`. Verified against
https://code.claude.com/docs/en/hooks.md.

**Why heuristic first, file-claim verification later**: deep "I edited X"
→ `git diff` / mtime verification was the original roadmap idea. v0.6.0
deliberately shipped the lighter heuristic — natural-language file-path
extraction is fragile (high false positives), while done-claim-without-
evidence is robust (a careful agent always cites evidence per rule 05,
so this only fires on actual laziness). v0.7.0 deepened the rule-06
side (hedge + self-quiz); v0.8.0 added the rule-07 fidelity layer; the
file-claim verification itself landed as layer (g) in v0.16 with the
conservative mtime-baseline design described above.

#### `Edit` / `Write` patch-style content blocking (v0.11.0)

`read_guard.py` gains a second responsibility beyond read-before-edit:
the `new_string` (Edit) or `content` (Write) is scanned for **patch-
style markers** — `try / except: pass`, `# noqa`, `# type: ignore`,
`// @ts-ignore`, `// @ts-expect-error`, `// eslint-disable[-next-
line]`, `time.sleep(...) # race/wait/workaround` — and DENY-ed when
present **without an adjacent rationale comment** (the line itself or
±1 line must contain one of: `because`, `原因`, `why`, `正当`,
`rationale`, `see issue/pr/comment/ticket`, `intentional`,
`deliberate`, `third-party`, `per spec/rfc/standard`).

| Pattern | Why |
|---|---|
| `try:\n …\nexcept …:\npass` (multi-line, bare) | Silent exception swallow (rule 03 + 09) |
| `# noqa` without rationale | Lint suppression without justification (rule 03 + 09) |
| `# type: ignore` without rationale | Type-checker suppression (rule 03 + 09) |
| `// @ts-ignore` / `// @ts-expect-error` without rationale | TS suppression (rule 03 + 09) |
| `// eslint-disable[-next-line\|-line]` without rationale | Lint suppression (rule 03 + 09) |
| `time.sleep(...) # race/wait/workaround` | Sleep masking a race (rule 03 + 09) |

This is the **physical-enforcement** half of rule 09. The
soft-layer half (the `rules/09-systematic-modification.md`
discipline + Stop layer (f) closing check) covers the cases the
regex set cannot catch (rolling patches, loosened assertions, etc.).

#### `Edit` / `Write` hardcoding + path-dependency blocking (v0.22.0)

A third and fourth content responsibility of `read_guard.py`, added
alongside the rule-09 patch-style scan and sharing its mechanism
(`new_string` / `content` scan → DENY on first hit, with a why-comment
escape hatch). They physically enforce rule 10 (no non-essential
hardcoding) and rule 11 (no non-essential path dependency):

| Detector (function) | Flags (high-confidence only) | Rule |
|---|---|---|
| `_find_hardcoded_secret` | assignment to a secret-named identifier (`password` / `api_key` / `secret` / `private_key` / …) with a ≥ 8-char string literal, bare **or quoted** key; PEM `-----BEGIN … PRIVATE KEY-----`; AWS `AKIA…` access-key; provider-issued token literals (`ghp_…` / `xox…` / `AIza…`, v0.25.1); credentials embedded in a connection URL (`://user:pass@`) | 10 |
| `_find_path_dependency` | machine-specific **user-home** absolute paths (`C:\Users\…` / `/home/…` / `/Users/…`) with **raw or escaped** separators (v0.25.1), plus `$HOME` / `%USERPROFILE%` / quoted `~/…` inside a string literal | 11 |

Two scoping refinements keep false positives low, honouring the repo's
"宁可漏报不误报" detector philosophy:

- **Escape hatch = how "non-essential" is operationalized.** A flagged
  literal / path *with* an adjacent rationale comment (the extended
  `HARDCODE_RATIONALE_TOKENS`: the rule-09 tokens plus `essential` /
  `必须` / `必需` / `example` / `fixture` / `placeholder` / `占位` /
  `sample` / `test data`) is allowed; obvious placeholders (`example`,
  `changeme`, `xxxx`, `<…>`, `your-`, and `os.environ` / `getenv` /
  `process.env` reads) are skipped by construction. "Essential"
  hardcoding declares itself; lazy hardcoding does not.
  The rule-09 base set gained the Chinese "because"/"deliberately" forms
  in v0.26 (`因为` / `之所以` / `理由` / `故意` / `刻意` / `有意` / `特意`)
  alongside `reason` / `tracking` / `vendor` — only the noun `原因` had
  been listed, so the most natural Chinese spelling was rejected while
  English `because` passed, in a Chinese-primary repo. The token must sit
  in **comment text** (v0.25.1) and "comment" is decided by the
  [`lib/srclex`](../hooks/scripts/lib/srclex.py) lexer (v0.26), so a `#`
  inside a URL is not one while `/* … */` blocks and own-line docstrings
  are.
- **Prose-doc + lockfile targets are exempt** (`_is_scannable_target`
  returns False for `.md` / `.markdown` / `.rst` / `.txt` / `.adoc` /
  `.asciidoc` and `*.lock` / `package-lock.json` / `yarn.lock` /
  `poetry.lock` / `Cargo.lock`). The user framed this as "写完**代码**后"
  detection, and this repo's own docs are full of example paths and
  values — scanning them would self-trip. The rule-09 patch check keeps
  its all-files behaviour; only these two new detectors are gated.
  v0.24 refinements: `requirements*.txt` / `constraints*.txt` stay
  scannable despite `.txt` (dependency manifests are a real
  credential-leak vector); a pure-alpha CamelCase secret *value*
  (`password: "SecretStr"` — a Python forward-reference annotation) is
  skipped; and the POSIX `/home/…` pattern rejects matches glued to a
  hostname (`https://host/home/alice/…` is a route, not a path).

  **v0.25.1 corrections to the two clauses above.** The CamelCase relief
  is now scoped to the `:` spelling it was written for — it applied to
  `=` as well, so `password = "SuperSecret"` was silently allowed. The
  placeholder filter now also covers the standalone literal patterns, not
  only keyword assignments, so an obviously fake
  `postgres://user:redacted@host/db` stops being denied. And the rule-09
  patch check is **no longer literally all-files**: prose targets keep
  matching only the *bare* marker form, because v0.25.1 dropped the
  end-of-line anchors (see below) and this repo's own docs name those
  markers 54 times. Enforcement on code is unchanged-or-stricter; only
  the doc false-positive surface moved.

**Rule-09 marker matching (v0.25.1).** The five single-line patterns no
longer end in `[ \t]*(?:\n|$)`, and removing that anchor is the fix:

- `\r\n` could never match it, so on Windows — this plugin's primary
  platform — all five detectors were silently off for CRLF files.
- *Any* trailing text made a marker match nothing at all, so
  `// @ts-ignore` + a bare deferral keyword was ALLOWED while the bare
  form was denied, and the rationale check was never reached. Trailing
  text now goes to `_inline_reason_is_substantive`, which accepts an
  explanation and rejects a leading TODO / FIXME / HACK / WIP / later.

`_scan_bare_try_except_pass` returns **every** hit (a justified swallow no
longer hides an unjustified one), tracks nested `try` blocks with a stack,
recognises `except X: pass` one-liners, and **skips comment lines** when
locating the swallow — that last one is what finally makes rule 09's
why-comment hatch reachable for its most natural spelling (a rationale on
its own line above `pass` used to move the `pass` out of the scanner's
sight, so `_has_rationale` was never consulted). `_has_rationale` itself
now reads **comment text only** (`_comment_text`); it used to lowercase
the whole raw window, so any token in ordinary code — `reason =
compute()` — satisfied the hatch.

Unlike rule 09, rule 10 / 11 have **no Stop layer** — content detectors
are `PreToolUse`-only by precedent (the sibling `# noqa` / `@ts-ignore`
detectors have no Stop twin), and a Stop layer would double-jeopardy an
already-blocked write.

#### `Bash` bypass-pattern blocking

`bash_guard.py` (matcher `Bash`) inspects the `tool_input.command` and denies
**six static patterns plus a separately-implemented force-push detector**
(the force-push case parses the command rather than matching a regex, so it
does not live in `STATIC_PATTERNS`):

| Pattern | Why |
|---|---|
| `--no-verify` (whitespace-bounded) | Skipping commit/push hooks ships unchecked code. Rule 03. |
| `--no-gpg-sign` | Skipping commit signature verification. Rule 03. |
| `chmod 777` (regex `chmod (-R)? 0?777`) | World-writable permissions never solve the underlying access issue and create security risk. Rule 03. |
| `git rebase --skip` (v0.14) | Silently abandoning a conflicting commit discards work instead of resolving it. Rule 03. |
| `--break-system-packages` (v0.14) | Bypassing PEP 668 to write into a managed interpreter. Rule 03. |
| `rm -rf` on a root path / `$HOME` / `~` (v0.14) | Unrecoverable deletion of a whole tree. Rule 03. |
| `git push --force` / `-f` / `+refspec` / `--mirror`, *not* `--force-with-lease` — **detector, not a static pattern** | Force-push is irreversible and can overwrite teammates' work. Rule 03. The safer `--force-with-lease` variant is allowed. |

Each match emits the same deny shape as `read_guard.py`, with a reason that
explains the rule violation and how to address the real underlying problem.

Word-boundary care: `--no-verify-extra` (longer flag) does not match;
`echo --force >> notes.txt` (no `git push`) does not match;
`git push --force-with-lease` is stripped before the `--force` check, so it
also does not match.

**Sub-command scoping (v0.25, re-implemented as a parse model in v0.26).**
Force-push detection began as a split on a fixed separator list (`&&`, `||`,
`;`, `|`, newline) plus text matching inside the `git push` segments. That
fixed the original both-directions error — `rm -f build.log && git push
origin main` was denied as a force push (the `-f` belongs to `rm`; likewise
`make -f`, `docker build -f`), while `git push -fu origin main`, a real force
push since git accepts stacked short options, never matched a
whitespace-delimited `-f` token.

Since v0.26 the same decision is made through [`lib/shellcmd.py`](../hooks/scripts/lib/shellcmd.py):
tokenise → segments → argv → git sub-command. The separator set is larger
(it includes `$(…)`, backticks and subshell parentheses), it recurses into a
shell's `-c` operand, and it requires `argv[0]` to actually *be* git with the
sub-command resolved past global options. The text heuristic it replaced was
catching `$(git push --force)` only by accident, which is why the model had
to cover command substitution before it could ship: that command really does
execute. In the other direction `git config alias.deploy "push --mirror"`
(sub-command is `config`) and an `echo` of a force-push string are no longer
denied.

**Force-push spellings (v0.25.1).** Four more unconditional-overwrite forms
were passing. The segment filter matched `git push` adjacently, so a global
option between them (`git -C repo push --force`, `git --git-dir=… push`) hid
the whole segment; quote characters are now stripped before matching, since
`git push "--force"` is the same operation the whitespace-delimited pattern
could not see past; and two spellings that carry no `--force` flag at all are
now recognised — `git push origin +main:main` (git's own "force this ref"
syntax) and `git push --mirror` (force-updates every mirrored ref).

**Register-invocation command position (v0.25.1).** `_parse_register_invocation`
accepted *any* token ending in `register_read.py`, so
`echo /not/executed/register_read.py --file F --hash H` registered `F` as read
without the sanctioned script ever running (a differently-named neighbour such
as `unregister_read.py` matched the suffix too). The token must now be in
command position: the first word of its shell segment, or the argument of a
Python interpreter. Tokenisation also moved to `shlex.shlex(escape="")` on
Windows — `posix=True` mangles unquoted backslash paths (the v0.25 bug) while
`posix=False` fails to group a quoted `--file="C:\Dir With Space\x.py"` (the
v0.25 *fix's* bug); disabling escape handling gives quote grouping and literal
backslashes at once.

If the user has explicitly authorised a bypass, `bash_guard` will still deny.
The agent should surface the deny reason to the user and let the user run the
command manually — that is the intended discipline (no AI-mediated bypassing).

**Check order (v0.25).** All deny checks — static patterns, force-push,
圣旨 — run **before** the register-as-read handling below, and a file is
registered only once the whole command is known clean. Until v0.24 the
registration was processed first and returned immediately on success, on
the assumption that such a command simply *was* a registration. But a
command can *contain* a registration while doing other things, so
`python …/register_read.py --file F --hash H && git push --force` was
ALLOWED: the entire bypass catalog was skipped for the rest of the compound
command. Registration and bypass-scanning are orthogonal concerns and both
must run; putting the denies first also means a command destined for denial
never mutates session state — the same ordering principle as v0.24's
read_guard fix, where a DENIED Write must not grant read-before-edit
authorization.

#### Read-cache escape hatch (v0.4.0)

A second responsibility of `bash_guard.py`: detect invocations of
`register_read.py` and, only when valid, register the target file in
session state. Motivation:

- Claude Code's harness has a Read result cache. Repeated `Read` of the
  same file within a session may be served from cache *without invoking
  the Read tool*. When that happens, neither `PreToolUse(Read)` nor
  `PostToolUse(Read)` fires, the file never enters session state, and a
  later `Edit` is falsely denied.
- We can't fix the harness from a plugin. We can provide an explicit
  registration path: `register_read.py --file ABS_PATH --hash SHA256`.
- The hash is the laziness gate. `bash_guard.py` recomputes SHA-256 of
  the file on disk and only registers if it matches the agent's claim.
  An agent that has not actually opened the file can't produce the
  current on-disk hash, so the hatch can't be abused.
- **Argument parsing (v0.25, superseded by the v0.26 command model).**
  The original bug: `shlex.split(posix=True)` treats a backslash as an
  escape, so an unquoted `C:\Users\me\note.txt` came back as
  `C:Usersmenote.txt` and the hatch denied with "file does not exist on
  disk" — the recovery path for a false rule-04 DENY was itself broken on
  this plugin's primary platform. It went unnoticed for 21 releases because
  every test quoted the path, and quoting survives posix splitting.
  Parsing now lives in [`lib/shellcmd.py`](../hooks/scripts/lib/shellcmd.py)
  and runs in **plain posix mode** (plus `commenters=""`, so a `#` in a
  path no longer truncates the command). **v0.27 removed the host-OS
  branch entirely**: v0.25.1 had disabled backslash escaping on Windows,
  but Claude Code's Bash tool there runs Git Bash / MSYS, which is POSIX
  — measured, that shell eats an unquoted drive path's separators just as
  posix `shlex` does, so the branch never rescued anything, while it did
  hide a real force-push evasion (a backslash-split `--force` reaches git
  intact). The supported spelling for a drive path is a **quoted** one.
  Both `--file X` and `--file=X`
  are accepted, matching what `register_read.py`'s own argparse accepts;
  previously the `=` spelling made the hook classify the command as "not a
  registration", so nothing was registered while the stub script still
  printed `register_read: ok`. The script operand is now identified by
  argv position rather than by scanning backwards for dashes, so
  `python -c register_read.py …` no longer registers anything (the script
  never runs) while `python -X utf8 register_read.py …` and `python3.13`
  are recognised.

Flow:

```
agent computes SHA-256 of file --> agent runs `python register_read.py --file ABS --hash SHA`
                                              │
                                              ▼
                  PreToolUse(Bash) fires → bash_guard.py
                  ├─ recognises register_read.py invocation
                  ├─ recomputes SHA-256 from disk
                  ├─ if match: state_lib.add_read(session_id, path); ALLOW
                  └─ if mismatch / file missing / bad path / bad hash: DENY
                                              │
                  ALLOW lets register_read.py run as a no-op CLI that prints
                  confirmation and exits 0. The state mutation has already
                  happened in the hook.
```

The contract is asymmetric on purpose: the user-facing script
(`register_read.py`) verifies its own hash for command-line UX, but
the *authoritative* hash check + state mutation lives in the hook,
because only the hook payload exposes `session_id`.

---

## 3. Layer 2 — Slash commands (on-demand)

**Wired in:** [`../commands/`](../commands/).

Six user-invokable surfaces. (This section said "two" from v0.12, when
`/cc-enforcer:edict` shipped, until v0.30 — three commands existed and were
documented everywhere except the architecture doc that claims to enumerate the
layer.)

| Command | Source | Use case |
|---|---|---|
| `/cc-enforcer:checklist` | [`../commands/checklist.md`](../commands/checklist.md) | Print the eight-section pre-action / pre-finish discipline checklist. |
| `/cc-enforcer:verify`    | [`../commands/verify.md`](../commands/verify.md)    | Trigger a re-verification pass on the agent's recent claims. |
| `/cc-enforcer:edict`     | [`../commands/edict.md`](../commands/edict.md)      | `list / add / remove / reload / path` for Imperial Edicts (v0.12). Backed by [`../hooks/scripts/manage_edicts.py`](../hooks/scripts/manage_edicts.py). |
| `/cc-enforcer:gc`        | [`../commands/gc.md`](../commands/gc.md)            | List — or with `--apply`, delete — session-state files older than N days (v0.6.1). Backed by [`../hooks/scripts/gc_state.py`](../hooks/scripts/gc_state.py). |
| `/cc-enforcer:i18n`      | [`../commands/i18n.md`](../commands/i18n.md)        | Report structural drift between every translation and the English skeleton (v0.21). Backed by [`../hooks/scripts/i18n_check.py`](../hooks/scripts/i18n_check.py). |
| `/cc-enforcer:sync-gate` | [`../commands/sync-gate.md`](../commands/sync-gate.md) | `init / list / check / add / remove / path` for this project's rule-12 co-update groups (v0.31). Backed by [`../hooks/scripts/manage_sync_gate.py`](../hooks/scripts/manage_sync_gate.py). **`check` is the reason it exists**: `sync_gate.load()` is failing-open, so a dropped group or a glob matching no file stops guarding *silently*. `check` names both and exits 1. Writes are validated twice — parses back, **and** every group survives a real `load_file()` round-trip, because a `require = []` entry is legal TOML the loader then discards. |

Slash commands in Claude Code are flat Markdown files in `commands/`. Their YAML
frontmatter declares the command's behaviour; the body is the prompt the agent
receives when invoked.

**Why their links look repo-root-relative.** A command / skill / agent / prompt
file is a *prompt payload*, not a rendered page: the agent that reads it resolves
paths against the project root, not against the file's own directory. So
`[rules/03-root-cause.md](rules/03-root-cause.md)` inside `commands/checklist.md`
is correct as written, and `test_doc_sync.py` resolves links from either base for
exactly this reason. Documents meant for a human reader on GitHub —
`README*.md`, `docs/`, `rules/`, `CLAUDE.md` — use file-relative links instead.

---

## 4. Layer 3 — Verifier subagent

**Wired in:** [`../agents/verifier.md`](../agents/verifier.md).

A read-only subagent. Given a list of `file:line` citations the main agent
produced, the verifier independently:

1. Reads each cited file.
2. Confirms the line number exists and the cited content matches.
3. Reports one of five verdicts per citation — `intact` / `drift` /
   `missing` / `mismatch` / `unverifiable` (the full table, with the
   evidence each verdict owes, is in
   [`../agents/verifier.md`](../agents/verifier.md)).

It carries `Read`, `Grep`, `Glob` tools — explicitly **no** `Edit`, `Write`, or
`Bash`. It cannot mutate state; its only output is a verdict.

---

## 5. Layer 4 — Skill (contextually auto-invoked)

**Wired in:** [`../skills/systematic-debug/SKILL.md`](../skills/systematic-debug/SKILL.md)
+ [`../skills/repo-refresh/SKILL.md`](../skills/repo-refresh/SKILL.md) (v0.23).

Skills are auto-invoked by Claude Code based on the YAML `description` matching
the user's prompt. `systematic-debug` triggers on debugging language ("debug",
"why is this failing", "fix this bug", error/stack-trace patterns) and forces
the agent through the seven systematic-thinking questions from
[`../rules/02-systematic-not-reactive.md`](../rules/02-systematic-not-reactive.md)
**before** proposing any code change.

`repo-refresh` (v0.23) triggers on whole-repo audit language ("全库更新",
"repo refresh", "stale scan", "audit the repo") and executes rule 12's
active half: a systematic sweep of the entire repository — docs and code
— for stale / outdated / redundant / wrong / drifted content, every
finding carrying `file:line` evidence, deletions gated on user
confirmation, closing with a suggestion to register recurring co-update
pairs as sync-gate groups.

---

## 6. Layer 5 — LLM-agnostic core

**Source of truth:** [`../rules/`](../rules/) (English — the **skeleton** /
source of truth, at the root) + [`../rules/zh/`](../rules/zh/) (中文
translation). The skeleton↔translation contract is version-controlled — see
[`I18N.md`](./I18N.md).

Each rule is plain Markdown with a small YAML frontmatter (`id`, `title`,
`severity`). Every other layer in this plugin **derives from** the English
skeleton — the prompt injections in `prompts/` are distillations, the slash
commands and skill reference rule IDs, the verifier checks compliance with
rule 05. Translations live in `rules/<lang>/` (e.g. `rules/zh/`) and follow
the skeleton file-for-file; **if a translation ever drifts from the skeleton,
the English version wins** (and CI turns red — `i18n_check.py`, see `I18N.md`).

This separation is what makes the plugin **LLM-agnostic**: any agent runtime
that does not speak Claude Code's plugin protocol can still consume the rules
directly:

```bash
# OpenAI / generic — English skeleton (default):
cat rules/*.md > /tmp/cc-enforcer-system-prompt.txt

# OpenAI / generic — 中文 translation:
cat rules/zh/*.md > /tmp/cc-enforcer-system-prompt.txt

# Cursor / Cline / Aider — symlink rules/ or rules/zh/ into the project's
# rule directory or copy the index.
```

---

## 7. Data flow at a glance

```
Session starts
    │
    ▼
SessionStart hook fires → inject_context.py --event SessionStart
    │  reads prompts/session-start.md (distilled from rules/*.md)
    │  then, after the payload is assembled, two maintenance passes
    │  (both failing-open, neither touching the payload):
    │      auto-GC        → prune old session state + rewrite _auto_gc.json
    │                       (opt-in: CC_ENFORCER_AUTO_GC_DAYS)
    │      envfile        → dedupe `export` lines in CLAUDE_ENV_FILE (v0.34)
    ▼
Claude Code injects full discipline summary into context

User submits prompt
    │
    ▼
UserPromptSubmit hook fires → inject_context.py --event UserPromptSubmit
    │  reads prompts/user-prompt.md (compact reminder)
    ▼
Claude Code injects pre-turn reminder

Agent calls Read, Edit, or Write
    │
    ▼
PreToolUse hook fires (matcher Read|Edit|Write) → read_guard.py
    │
    ├─ tool=Read                                   → record path (only if it
    │                                                 exists) + mtime baseline,
    │                                                 ALLOW (silent)
    ├─ tool=Write, target exists but unrecorded    → DENY (rule 04)
    ├─ tool=Edit,  target exists but unrecorded    → DENY (rule 04)
    ├─ tool=Edit,  target does not exist on disk   → ALLOW (Claude Code rejects)
    └─ otherwise → CONTENT CHECKS run on new_string / content, in order:
           patch marker (rule 09)      → DENY
           hardcoded secret (rule 10)  → DENY
           path dependency (rule 11)   → DENY
           圣旨 deny_edit regex        → DENY
           rolling-patch counter       → DENY on the 4th small edit
         all clear → record read + edit-turn signal + edited_files, ALLOW

    (Every write branch runs the same content pipeline — the older diagram
     showed Write-new and recorded-Edit as bare ALLOWs, which read as "no
     content checks apply here". They do; a new file is denied for a
     hardcoded secret exactly like an existing one.)

State file: ${CLAUDE_PLUGIN_DATA}/sessions/<sid>.json (or fallback paths)

Agent calls Bash
    │
    ▼
PreToolUse hook fires (matcher Bash) → bash_guard.py
    │
    ├─ command matches --no-verify                       → DENY (rule 03)
    ├─ command matches --no-gpg-sign                     → DENY (rule 03)
    ├─ command matches chmod 0?777                       → DENY (rule 03)
    ├─ command matches git rebase --skip        (v0.14)  → DENY (rule 03)
    ├─ command matches --break-system-packages  (v0.14)  → DENY (rule 03)
    ├─ command matches rm -rf on root / $HOME / ~ (v0.14)→ DENY (rule 03)
    ├─ a git push segment force-updates (--force / -f cluster / +refspec /
    │        --mirror, but not --force-with-lease)       → DENY (rule 03)
    ├─ command matches a must 圣旨 deny_bash regex       → DENY (edict)
    │        (v0.25: every deny check above runs BEFORE the step below, so a
    │         registration can no longer shield the rest of a compound command)
    ├─ command is a register_read.py invocation          → verify SHA-256:
    │        match   → record file as read, ALLOW
    │        no match / missing file / bad args → DENY
    └─ no bypass pattern matched                         → ALLOW (silent exit 0)

   ─── if user/agent invokes /cc-enforcer:verify ───
                       │
                       ▼
            verifier subagent runs
                       │
                       ▼
            re-reads cited file:line → drift/missing/intact verdict

   ─── if user prompt matches "fix this bug" ───
                       │
                       ▼
            systematic-debug skill auto-invokes
                       │
                       ▼
            forces 7-question root-cause walk
```

---

## 8. Editing this plugin — connected-files map

When you change one component, these are the files that must be re-checked
in the same change. This is enforced by [`../CLAUDE.md`](../CLAUDE.md) §4.

| If you edit… | Also re-check… |
|---|---|
| `rules/<n>-*.md` (English skeleton) | `rules/zh/<n>-*.md` (中文 translation — keep header structure identical, then `python hooks/scripts/i18n_check.py`), `prompts/session-start.md`, `prompts/user-prompt.md`, `docs/RULES.md`, `commands/checklist.md`, `rules/00-index.md` + `rules/zh/00-index.md` (program-readable index), `tests/test_inject_context.py` (the prompt-content assertion list) |
| `prompts/*.md` (English skeleton) | `prompts/zh/*.md` (中文 translation — keep header structure identical, then `python hooks/scripts/i18n_check.py`), `hooks/scripts/inject_context.py` (filename mapping), `docs/I18N.md`, this doc |
| `hooks/scripts/inject_context.py` | `hooks/hooks.json` (registration), `.claude-plugin/plugin.json` (hooks pointer), `tests/test_inject_context.py` |
| `hooks/scripts/lib/envfile.py` (v0.34) | `hooks/scripts/inject_context.py` (the SessionStart call site beside auto-GC), `tests/test_envfile.py`. Changing what the line model ACCEPTS changes what can be rewritten in a harness-owned file every other plugin appends to — the refusal twins must be re-checked in both directions (still collapses the field shape, still refuses anything it cannot represent byte-identically). |
| `hooks/scripts/read_guard.py` | `hooks/hooks.json` (event registration + matcher), `hooks/scripts/lib/state.py` (state contract + `record_edit_turn`), this doc §2 (deny output contract + patch-style table + hardcoding/path-dependency table), `rules/10-no-hardcoding.md` + `rules/11-no-path-dependency.md` (the rules these detectors enforce), `tests/test_read_guard.py` (read-before-edit cases + patch-style + hardcoded-secret + path-dependency positive/negative/prose-doc-exempt cases + record_edit_turn cases) |
| `hooks/scripts/lib/state.py` | `hooks/scripts/read_guard.py` (consumer of `record_edit_turn` + `record_edited_file`), `hooks/scripts/stop_guard.py` (consumer of `did_edit_this_turn` + `get_edited_files`), `.gitignore` (state dir must stay ignored), this doc §2 (storage location), `tests/test_read_guard.py` + `tests/test_stop_guard.py` |
| `hooks/scripts/lib/sync_gate.py` | `hooks/scripts/stop_guard.py` (layer (i) consumer), `rules/12-repo-wide-sync.md` + `rules/zh/12-repo-wide-sync.md` (the rule it enforces), `.claude/cc-enforcer/sync-gate.toml` (this repo's own dogfood config), `hooks/scripts/lib/tomlio.py` (config reader), this doc §2 ("layer (i)" note), `tests/test_stop_guard.py` + `tests/test_sync_gate.py` (sync-gate cases) |
| `hooks/scripts/lib/srclex.py` (v0.26) | `hooks/scripts/read_guard.py` (every rule 09/10/11 content detector + the rationale hatch), this doc §2 (shared-models list), `tests/test_audit_v026_models.py` (`TestSrclex` + the rule-09/10/11 regression classes). Changing what counts as a comment / docstring / literal changes what the rationale hatch accepts, so the twin assertions in `TestRationaleHatchV026` must be re-checked in BOTH directions. |
| `hooks/scripts/lib/mdctx.py` (v0.26) | `hooks/scripts/stop_guard.py` — **both** halves of layer (h) (`_has_tldr` presence + `_tldr_items` length). They must stay on one model; the defect this replaced was exactly the two disagreeing. Also this doc §2, `tests/test_audit_v026_models.py` (`TestMdctx`, `TestTldrContextV026`) + `tests/test_stop_guard.py` (`TestTldrLayerH`, `TestTldrLengthLayerH`). |
| `hooks/scripts/lib/shellcmd.py` (v0.26) | `hooks/scripts/bash_guard.py` — **both** the force-push detector and `_parse_register_invocation`. It exists so those two stop being independent text heuristics that drift; a change here needs both directions re-checked (real bypasses still denied, innocent commands still allowed). Also this doc §2, `tests/test_audit_v026_models.py` (`TestShellcmd`, `TestForcePushCommandModelV026`, `TestRegisterCommandModelV026`) + `tests/test_bash_guard.py`. |
| `hooks/scripts/lib/editscale.py` (v0.35) | `hooks/scripts/read_guard.py` (the rule-09 frequency layer and its DENY template, which formats the LIVE constants — never a second hand-copied set), this doc §2 (shared-models list), `docs/RULES.md` (component table), `rules/09-systematic-modification.md` **and its zh mirror** (the classification table + the exemption table are the LLM-agnostic statement of this model — `rules/` is the product, so a stale bound there ships weaker discipline to every non-Claude-Code consumer), `prompts/*.md` ×4 (the DENY row agents actually act on), `tests/test_editscale.py` (unit) + `tests/test_read_guard.py::TestRollingPatchInterception` (wiring). Loosening ANY bound needs its refusal twin re-checked: the exemptions are the only place a small edit can pass at the threshold, so a test that only shows what now passes stays green when the whole gate is deleted. **Fixture warning:** these tests need a target file large enough that the ABSOLUTE bounds bind; the one-line fixture used from v0.13 to v0.34 is exactly why the small-file lock-in went unseen. |
| `hooks/scripts/lib/tomlio.py` (v0.25) | **Both** TOML config loaders — `hooks/scripts/lib/edicts.py` and `hooks/scripts/lib/sync_gate.py`. A change here changes how *every* hand-edited config degrades, so it needs both `tests/test_edicts.py` and `tests/test_sync_gate.py` re-checked. It exists precisely so the BOM / non-UTF-8 hardening is not hand-copied into two loaders that then drift apart. |
| `hooks/scripts/manage_sync_gate.py` (v0.31) | `commands/sync-gate.md` (the slash command), `hooks/scripts/lib/sync_gate.py` (**both** resolvers — `default_project_path` for writes, `config_path` for reads; conflating them is the defect this CLI shipped with), `hooks/scripts/lib/tomlio.py` (the shared encoder), `tests/test_manage_sync_gate.py`. A change to how a group is SERIALISED needs the round-trip assertions re-checked: the writer's contract is not "produces valid TOML" but "produces groups the loader still keeps". |
| `hooks/scripts/lib/tomlio.py` — writer half (v0.31) | **Both** config CLIs — `manage_edicts.py` and `manage_sync_gate.py` alias `basic_string`. Its escaping rules were each learned from a config that the CLI reported as written and tomllib then refused (a raw newline; DEL passing a `>= " "` guard), so a change here can silently unenforce every rule in a project's config. `tests/test_manage_sync_gate.py::TestSharedPrimitives` pins the sharing itself, not just the behaviour. |
| `hooks/scripts/lib/projroot.py` (v0.30) | **Both** config loaders again — `lib/edicts.py` and `lib/sync_gate.py` alias it. Widening what counts as a project root widens where *both* configs may be picked up, which is a security-shaped change, not a convenience one: a false positive makes another project's `must` edicts apply to this session. Re-check `tests/test_edicts.py` (`TestCwdFallback`, `TestManageCLICwdFallback`) and `tests/test_sync_gate.py` (`TestConfigPath`). |
| `hooks/scripts/lib/mdctx.py` — fence helper (v0.30) | `mdctx.fence_marker` now has THREE consumers: `stop_guard._is_fence`, `stop_guard`'s layer-(h) context model, and `i18n_check._fence_run`. It used to be copied into all three, each with its own comment claiming they "must agree". Changing fence geometry changes which headings `i18n_check` sees AND which tldr lines layer (h) measures — re-run `python hooks/scripts/i18n_check.py` as well as the stop-guard suite. |
| `.claude/cc-enforcer/sync-gate.toml` | `hooks/scripts/lib/sync_gate.py` (schema), `rules/12-repo-wide-sync.md` (documented example), CLAUDE.md §4 (the co-update map the groups encode) |
| `skills/repo-refresh/SKILL.md` | `rules/12-repo-wide-sync.md` (active half), `rules/06-verify-convergence.md` + `rules/09-systematic-modification.md` (the disciplines its steps invoke), this doc §5, **and `commands/sync-gate.md` + `hooks/scripts/manage_sync_gate.py` (v0.32.2)** — Step 6 tells the agent to register findings as sync-gate groups, so it must name the CLI that does it and the `check` that verifies it. This pair drifted for two releases in one direction only: `commands/sync-gate.md` asserted the skill would call it while the skill still said hand-edit the TOML. A cross-document claim is a coupling; verify it from **both** ends. |
| `hooks/scripts/bash_guard.py` | `hooks/hooks.json` (matcher entry), this doc §2 (bypass-pattern table + register-flow), `tests/test_bash_guard.py` (positive + nearby negative for every new pattern; register-flow regression cases) |
| `hooks/scripts/stop_guard.py` | `hooks/hooks.json` (event registration; no matcher), `hooks/scripts/lib/state.py` (one-shot guard helpers + `did_edit_this_turn`), this doc §2 ("`Stop` guard" subsection), `tests/test_stop_guard.py` (every new done-claim or evidence pattern needs both directions; one-shot guard regression cases; rule 08 / rule 09 layer (e)+(f) cases) |
| `hooks/scripts/gc_state.py` | `commands/gc.md` (`/cc-enforcer:gc` slash command), `hooks/scripts/lib/state.py` (consumes `state_dir()` to scope the GC), `tests/test_gc_state.py` (arg validation + dry-run + apply + threshold semantics) |
| `hooks/scripts/register_read.py` | `hooks/scripts/bash_guard.py` (the actual register handling lives there), this doc §2 "Read-cache escape hatch", `tests/test_register_read.py` |
| `hooks/scripts/bench_hooks.py` (v0.35) | `README.md` + `README.zh.md` (the benchmark section quotes its output and names it as the reproduction — numbers are machine-specific, so no CI gate pins them and the script IS the citation), the structure trees in all three inventory surfaces. Not a hook: it is the sixth auxiliary entry point, and `hooks.json` must NOT register it — `test_doc_sync` checks that registration in both directions. |
| `hooks/hooks.json` | `.claude-plugin/plugin.json` (hooks pointer), this doc §2 (event table) |
| `.claude-plugin/plugin.json` | `README.md` (install steps), `CHANGELOG.md`, `.claude-plugin/marketplace.json` (version sync), version-bump must match an actual change. **Do not** re-add the `commands` / `agents` / `skills` / `hooks` path fields for standard locations: they cause `claude plugin install` to fail with `Duplicate hooks file detected` or `agents: Invalid input` because Claude Code auto-discovers `./commands/`, `./agents/`, `./skills/`, and `./hooks/hooks.json`. Those manifest fields are only for *non-standard* layouts. |
| `.claude-plugin/marketplace.json` | `README.md` (install steps), `.claude-plugin/plugin.json` (version), this doc |
| `commands/*.md` | `.claude-plugin/plugin.json` (commands path), this doc, `README.md` |
| `agents/verifier.md` | `commands/verify.md` (invocation), this doc |
| `skills/systematic-debug/SKILL.md` | `rules/02-systematic-not-reactive.md`, `rules/03-root-cause.md`, this doc |
| `tests/_helpers.py` | every `tests/test_*.py` file (they all import from here) |
