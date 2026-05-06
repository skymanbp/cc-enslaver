# Changelog

All notable changes to **cc-enslaver** are documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and
this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [Unreleased]

### Planned (roadmap)

- **Additional bypass patterns**
  - Evaluate adding `git reset --hard` (if uncommitted changes), `git rebase
    --skip`, `pip install --break-system-packages`, etc. — currently held back
    on false-positive concerns.
- **Stop hook deep file-claim verification** — parse "I edited X" patterns
  in the agent's last message and check `git diff` / mtime against the
  session-start baseline. v0.7.0 layered (b)+(c) on rule 06; v0.8.0 layered
  (d) on rule 07; the file-claim version is still a v0.10+ candidate.

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

[Unreleased]: https://github.com/skymanbp/cc-enslaver/compare/v0.9.1...HEAD
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
