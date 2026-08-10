# Architecture

> Audience: developers extending or auditing the plugin.
> Companion docs: [`../CLAUDE.md`](../CLAUDE.md) (project-level rules),
> [`./RULES.md`](./RULES.md) (catalog of every rule).

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
- Hardened TOML reader shared by both config loaders (v0.25): [`../hooks/scripts/lib/tomlio.py`](../hooks/scripts/lib/tomlio.py) — strips a UTF-8 BOM and turns a non-UTF-8 config into a stderr diagnostic instead of an uncaught `UnicodeDecodeError`. Both configs drive hard guards, and in both the failure was *silent disablement* of enforcement: a GBK-saved `edicts.toml` escaped `edicts.load()` and unwound past every downstream check in `read_guard`, switching off read-before-edit for the whole session.

Five hook entries across four events:

| Event | Matcher | Script | Purpose |
|---|---|---|---|
| `SessionStart` | — | `inject_context.py` | Inject full discipline summary at session boot |
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
result is known). A Read of a non-existent path leaves a phantom record,
but Edit's `os.path.exists` short-circuit covers it (Edit on a missing
file is allowed and Claude Code rejects it downstream).

#### Why three scripts (not one)

Each script has a different responsibility and a different failure mode:
- `inject_context.py` is purely additive: always exit 0, only emit
  `additionalContext`. Never reads or writes disk state.
- `read_guard.py` owns per-session disk state, with both recording and
  gating in PreToolUse (Read/Write/Edit). Its failure mode is state-file
  corruption.
- `bash_guard.py` is stateless string inspection. Its failure mode is regex
  bug.

Collapsing them into one script would chain three independent failure modes
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

Never blocks; only injects.

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
    "permissionDecisionReason": "cc-enslaver · rule 04 violation ..."
  }
}
```

The reason text tells the agent precisely how to recover (Read first, then retry).

#### Per-session state storage

The guard uses **session_id** from the hook payload as the state key. Storage
location resolves in this order:

1. `${CLAUDE_PLUGIN_DATA}/sessions/<sid>.json` — preferred, set by Claude Code
   for plugin hooks.
2. `${CLAUDE_PROJECT_DIR}/.claude/local/cc-enslaver/sessions/<sid>.json` —
   per-project fallback.
3. `~/.claude/local/cc-enslaver/sessions/<sid>.json` — final fallback.

State files are git-ignored (`.gitignore` line 26). Paths within state are
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
| 2 | Hedge regex within 50 chars of done-claim (rule 01) | **Block** (`HEDGED_DONE_REASON`) |
| 3 | No evidence regex matched (v0.6.0 base) | **Block** (`NO_EVIDENCE_REASON`) |
| 4 | No convergence marker AND fewer than 2 self-quiz questions (rule 06 deep) | **Block** (`MISSING_QUIZ_REASON`) |
| 5 | No fidelity marker AND fewer than 2 of 3 fidelity questions (rule 07) | **Block** (`MISSING_FIDELITY_REASON`) |
| 6 | edit turn (`edited_since_last_stop` flag, or `last_edit_turn == turn_count` when supplied) AND no rule-08 marker AND fewer than 3 of 6 rule-02 keywords (rule 08, **v0.11**; edit signal fixed for production in **v0.23**) | **Block** (layer (e)) |
| 7 | edit turn AND no rule-09 marker AND triplet (root-cause + impact + solution) incomplete (rule 09, **v0.11**) | **Block** (layer (f)) |
| 8 | edit turn AND a file-edit/create claim is **definitively contradicted** by the on-disk mtime baseline (rule 01 + 06, **v0.16**; `CC_ENSLAVER_DISABLE_LAYER_G=1` to skip) | **Block** (layer (g)) |
| 9 | No TL;DR marker (`tldr:` / `大白话` / `一句话总结` / `TL;DR`) — fires on **every** done-claim turn, not just edit turns (**v0.20**) | **Block** (layer (h)) |
| 10 | A tldr item longer than `TLDR_MAX_ITEM_CHARS` (160) — one sentence per item, cause + action + outcome; several things → one short line each (**v0.23**) | **Block** (layer (h), "overlong" note + dedicated recovery) |
| 11 | edit turn AND a sync-gate group's `when` glob matched an edited file with its `require` side unsatisfied (per the group's `mode`: any-of by default, all-of for lock-step invariants) AND the group is not in the session's `sync_acked_groups` AND no sync marker (`同步核对` / `sync-check` / `rule 12` / `全库同步` / `连带核对` / `repo-wide sync` — deliberately NOT `sync-gate`, which is the config file's name, not a claim) in the reply (rule 12, **v0.23**; per-project opt-in via `.claude/cc-enslaver/sync-gate.toml` — no config, never fires). A marker escape records the pending groups as acknowledged for the session, so one explicit answer per group suffices. | **Block** (layer (i)) |
| 12 | All gates passed | Allow |

**Done-claim patterns**: `已解决` / `已修复` / `[修改弄搞]好了` / `完成了` /
`完工` / `搞定` / `\bfixed\b` / `\bdone\b` / `\bcompleted\b` /
`\bresolved\b` / `all set` / `should work now` / `that should do it`.

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
收敛 / 忠实 / 收尾 / tldr`, English: `before / edits / convergence /
fidelity / closing / tldr`) ARE the layer markers above — so a
schema-conformant reply passes (a)-(h) with no detector changes.

**v0.20.0 block-reason 大白话 line**: every block reason now appends a
one-line plain-language takeaway (`大白话: ...`) before the one-shot
footer, so cc-enslaver's own output is symmetric with the layer-(h)
requirement it imposes on the agent.

**v0.23.0 layer (h) length cap**: beyond mere presence, each tldr item
must stay within `TLDR_MAX_ITEM_CHARS` (160) characters. Extraction is
line-based and conservative (only lines attributable to a tldr marker —
the marker line's value plus more-indented continuation / `- ` list
lines — are measured; anything ambiguous is not measured, failing open).
The block reuses layer (h) with an "overlong" table note and its own
recovery text (`_RECOVERY_H_LONG`).

**v0.23.0 layer (i) — rule 12 repo-wide sync gate**: `read_guard.py`
records every ACCEPTED Edit / Write path into the session's
`edited_files` set; at Stop, `lib/sync_gate.py` loads the project's
`.claude/cc-enslaver/sync-gate.toml` (resolution: payload cwd →
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
| `_find_hardcoded_secret` | assignment to a secret-named identifier (`password` / `api_key` / `secret` / `token` / `private_key` / …) with a ≥ 8-char string literal; PEM `-----BEGIN … PRIVATE KEY-----`; AWS `AKIA…` access-key; credentials embedded in a connection URL (`://user:pass@`) | 10 |
| `_find_path_dependency` | machine-specific **user-home** absolute paths (`C:\Users\…` / `/home/…` / `/Users/…`), plus `$HOME` / `%USERPROFILE%` / quoted `~/…` inside a string literal | 11 |

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

Unlike rule 09, rule 10 / 11 have **no Stop layer** — content detectors
are `PreToolUse`-only by precedent (the sibling `# noqa` / `@ts-ignore`
detectors have no Stop twin), and a Stop layer would double-jeopardy an
already-blocked write.

#### `Bash` bypass-pattern blocking

`bash_guard.py` (matcher `Bash`) inspects the `tool_input.command` string and
denies four patterns:

| Pattern (regex) | Why |
|---|---|
| `--no-verify` (whitespace-bounded) | Skipping commit/push hooks ships unchecked code. Rule 03. |
| `--no-gpg-sign` | Skipping commit signature verification. Rule 03. |
| `git push --force` / `-f`, *not* `--force-with-lease` | Force-push is irreversible and can overwrite teammates' work. Rule 03. The safer `--force-with-lease` variant is allowed. |
| `chmod (-R)? 0?777` | World-writable permissions never solve the underlying access issue and create security risk. Rule 03. |

Each match emits the same deny shape as `read_guard.py`, with a reason that
explains the rule violation and how to address the real underlying problem.

Word-boundary care: `--no-verify-extra` (longer flag) does not match;
`echo --force >> notes.txt` (no `git push`) does not match;
`git push --force-with-lease` is stripped before the `--force` check, so it
also does not match.

**Sub-command scoping (v0.25).** Force-push detection splits the command on
shell separators (`&&`, `||`, `;`, `|`, newline) and inspects only the
segments that invoke `git push`. Scanning the whole string gave errors in
both directions: `rm -f build.log && git push origin main` was denied as a
force push (the `-f` belongs to `rm`; likewise `make -f`, `docker build -f`),
while `git push -fu origin main` — a real force push, since git accepts
stacked short options — never matched a whitespace-delimited `-f` token.
Within a `git push` segment the check now looks for `f` inside any
single-dash option cluster.

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
- **Argument parsing (v0.25).** The command is tokenised in non-posix mode
  on Windows (with quote-stripping) because `shlex.split(posix=True)` treats
  a backslash as an escape: an unquoted `C:\Users\me\note.txt` came back as
  `C:Usersmenote.txt`, so the hatch denied with "file does not exist on
  disk" — the recovery path for a false rule-04 DENY was itself broken on
  this plugin's primary platform. It went unnoticed for 21 releases because
  every test quoted the path, and quoting survives posix splitting. Both
  `--file X` and `--file=X` are accepted, matching what `register_read.py`'s
  own argparse accepts; previously the `=` spelling made the hook classify
  the command as "not a registration", so nothing was registered while the
  stub script still printed `register_read: ok`.

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

Two user-invokable surfaces:

| Command | Source | Use case |
|---|---|---|
| `/cc-enslaver:checklist` | [`../commands/checklist.md`](../commands/checklist.md) | Print the pre-action / pre-finish discipline checklist. |
| `/cc-enslaver:verify`    | [`../commands/verify.md`](../commands/verify.md)    | Trigger a re-verification pass on the agent's recent claims. |

Slash commands in Claude Code are flat Markdown files in `commands/`. Their YAML
frontmatter declares the command's behaviour; the body is the prompt the agent
receives when invoked.

---

## 4. Layer 3 — Verifier subagent

**Wired in:** [`../agents/verifier.md`](../agents/verifier.md).

A read-only subagent. Given a list of `file:line` citations the main agent
produced, the verifier independently:

1. Reads each cited file.
2. Confirms the line number exists and the cited content matches.
3. Reports `intact` / `drift` / `missing` per citation.

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
cat rules/*.md > /tmp/cc-enslaver-system-prompt.txt

# OpenAI / generic — 中文 translation:
cat rules/zh/*.md > /tmp/cc-enslaver-system-prompt.txt

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
    ├─ tool=Read                                   → record path, ALLOW (silent)
    ├─ tool=Write, target does not exist on disk   → record path, ALLOW (new file)
    ├─ tool=Write, target exists & is recorded     → record (no-op), ALLOW
    ├─ tool=Write, target exists but unrecorded    → DENY (rule 04)
    ├─ tool=Edit,  target does not exist on disk   → ALLOW (Claude Code rejects)
    ├─ tool=Edit,  target exists & is recorded     → ALLOW (silent)
    └─ tool=Edit,  target exists but unrecorded    → DENY (rule 04)

State file: ${CLAUDE_PLUGIN_DATA}/sessions/<sid>.json (or fallback paths)

Agent calls Bash
    │
    ▼
PreToolUse hook fires (matcher Bash) → bash_guard.py
    │
    ├─ command matches --no-verify                       → DENY (rule 03)
    ├─ command matches --no-gpg-sign                     → DENY (rule 03)
    ├─ git push segment has --force / -f cluster (no --force-with-lease) → DENY (rule 03)
    ├─ command matches chmod 0?777                       → DENY (rule 03)
    ├─ command matches a must 圣旨 deny_bash regex       → DENY (edict)
    │        (v0.25: every deny check above runs BEFORE the step below, so a
    │         registration can no longer shield the rest of a compound command)
    ├─ command is a register_read.py invocation          → verify SHA-256:
    │        match   → record file as read, ALLOW
    │        no match / missing file / bad args → DENY
    └─ no bypass pattern matched                         → ALLOW (silent exit 0)

   ─── if user/agent invokes /cc-enslaver:verify ───
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
| `hooks/scripts/read_guard.py` | `hooks/hooks.json` (event registration + matcher), `hooks/scripts/lib/state.py` (state contract + `record_edit_turn`), this doc §2 (deny output contract + patch-style table + hardcoding/path-dependency table), `rules/10-no-hardcoding.md` + `rules/11-no-path-dependency.md` (the rules these detectors enforce), `tests/test_read_guard.py` (read-before-edit cases + patch-style + hardcoded-secret + path-dependency positive/negative/prose-doc-exempt cases + record_edit_turn cases) |
| `hooks/scripts/lib/state.py` | `hooks/scripts/read_guard.py` (consumer of `record_edit_turn` + `record_edited_file`), `hooks/scripts/stop_guard.py` (consumer of `did_edit_this_turn` + `get_edited_files`), `.gitignore` (state dir must stay ignored), this doc §2 (storage location), `tests/test_read_guard.py` + `tests/test_stop_guard.py` |
| `hooks/scripts/lib/sync_gate.py` | `hooks/scripts/stop_guard.py` (layer (i) consumer), `rules/12-repo-wide-sync.md` + `rules/zh/12-repo-wide-sync.md` (the rule it enforces), `.claude/cc-enslaver/sync-gate.toml` (this repo's own dogfood config), `hooks/scripts/lib/tomlio.py` (config reader), this doc §2 ("layer (i)" note), `tests/test_stop_guard.py` + `tests/test_sync_gate.py` (sync-gate cases) |
| `hooks/scripts/lib/tomlio.py` (v0.25) | **Both** TOML config loaders — `hooks/scripts/lib/edicts.py` and `hooks/scripts/lib/sync_gate.py`. A change here changes how *every* hand-edited config degrades, so it needs both `tests/test_edicts.py` and `tests/test_sync_gate.py` re-checked. It exists precisely so the BOM / non-UTF-8 hardening is not hand-copied into two loaders that then drift apart. |
| `.claude/cc-enslaver/sync-gate.toml` | `hooks/scripts/lib/sync_gate.py` (schema), `rules/12-repo-wide-sync.md` (documented example), CLAUDE.md §4 (the co-update map the groups encode) |
| `skills/repo-refresh/SKILL.md` | `rules/12-repo-wide-sync.md` (active half), `rules/06-verify-convergence.md` + `rules/09-systematic-modification.md` (the disciplines its steps invoke), this doc §5 |
| `hooks/scripts/bash_guard.py` | `hooks/hooks.json` (matcher entry), this doc §2 (bypass-pattern table + register-flow), `tests/test_bash_guard.py` (positive + nearby negative for every new pattern; register-flow regression cases) |
| `hooks/scripts/stop_guard.py` | `hooks/hooks.json` (event registration; no matcher), `hooks/scripts/lib/state.py` (one-shot guard helpers + `did_edit_this_turn`), this doc §2 ("`Stop` guard" subsection), `tests/test_stop_guard.py` (every new done-claim or evidence pattern needs both directions; one-shot guard regression cases; rule 08 / rule 09 layer (e)+(f) cases) |
| `hooks/scripts/gc_state.py` | `commands/gc.md` (`/cc-enslaver:gc` slash command), `hooks/scripts/lib/state.py` (consumes `state_dir()` to scope the GC), `tests/test_gc_state.py` (arg validation + dry-run + apply + threshold semantics) |
| `hooks/scripts/register_read.py` | `hooks/scripts/bash_guard.py` (the actual register handling lives there), this doc §2 "Read-cache escape hatch", `tests/test_register_read.py` |
| `hooks/hooks.json` | `.claude-plugin/plugin.json` (hooks pointer), this doc §2 (event table) |
| `.claude-plugin/plugin.json` | `README.md` (install steps), `CHANGELOG.md`, `.claude-plugin/marketplace.json` (version sync), version-bump must match an actual change. **Do not** re-add the `commands` / `agents` / `skills` / `hooks` path fields for standard locations: they cause `claude plugin install` to fail with `Duplicate hooks file detected` or `agents: Invalid input` because Claude Code auto-discovers `./commands/`, `./agents/`, `./skills/`, and `./hooks/hooks.json`. Those manifest fields are only for *non-standard* layouts. |
| `.claude-plugin/marketplace.json` | `README.md` (install steps), `.claude-plugin/plugin.json` (version), this doc |
| `commands/*.md` | `.claude-plugin/plugin.json` (commands path), this doc, `README.md` |
| `agents/verifier.md` | `commands/verify.md` (invocation), this doc |
| `skills/systematic-debug/SKILL.md` | `rules/02-systematic-not-reactive.md`, `rules/03-root-cause.md`, this doc |
| `tests/_helpers.py` | every `tests/test_*.py` file (they all import from here) |
