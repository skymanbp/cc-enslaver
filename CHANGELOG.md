# Changelog

All notable changes to **cc-enforcer** (named **cc-enslaver** through v0.32.2,
**anti-laziness** through v0.2.x) are documented here. Entries below render
the current name throughout: on the user's 2026-08-18 ruling the old name was
retconned out of the historical entries — the v0.33.0 entry is the record of
the rename itself.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and
this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [Unreleased]

Nothing planned. The roadmap is empty by decision, not by neglect — see
v0.32.1 for why its last two entries were retired rather than carried.

---

## [0.34.0] — 2026-08-18

**Env-file hygiene: SessionStart bounds `CLAUDE_ENV_FILE` growth.**

The field failure (2026-08-17, booked from a CodeEraser session): Claude
Code hands every hook a `CLAUDE_ENV_FILE` that is sourced into subsequent
Bash calls, and SessionStart fires on every compact/resume — so a plugin
that appends its `export` lines unconditionally on that event grows the
file without bound. The codex companion plugin re-appended three exports
per compact until ~8 KB of duplicate environment killed every Bash call
silently: the session lost its hands with no diagnostic.

The true origin is that plugin's non-idempotent append — outside this
repo's control, and a patch to a cached third-party copy dies on its next
version pin. The CLASS, though, is squarely this plugin's remit: session
protection. New [`lib/envfile.py`](hooks/scripts/lib/envfile.py) dedupes
the file on every SessionStart (the same slot and cadence as auto-GC —
and as the defect), keeping the LAST occurrence per variable name, which
is byte-equivalent to what sourcing the whole file already yields (later
exports win): nothing observable changes, only the growth goes. Hook
ordering against the offending appender does not matter — whichever runs
first, accumulation is bounded at one generation per variable instead of
one per compact.

Failing open throughout, refusal over gamble: any line that is not an
export / blank / comment, or any quoted value spanning lines, refuses the
WHOLE pass and leaves the file byte-identical — dropping the opening line
of a multi-line value would corrupt the file, and a hygiene pass that can
corrupt or crash the injection is worse than the disease it treats. Each
acceptance case ships with its refusal twin. 604 → 615 tests.

---

## [0.33.0] — 2026-08-18

**Project rename: `cc-enslaver` → `cc-enforcer`** (user decision, 2026-08-18).
Same twelve rules, same hooks. The old name had become a liability everywhere
the project was cited — the resume vault carries a standing ruling that the
string "enslaver" never renders on paper — and `cc-enforcer` both says what
the plugin does and preserves the established `cce` abbreviation.

### What moved (everything derived from the name)

- **Plugin identity**: `plugin.json` / `marketplace.json` `name` fields → the
  slash namespace `/cc-enforcer:*` follows automatically (no `commands/*.md`
  carries a `name:` frontmatter), and the install coordinate becomes
  `cc-enforcer@cc-enforcer`.
- **Environment variables**: `CC_ENSLAVER_LANG` / `CC_ENSLAVER_DISABLE_LAYER_G`
  / `CC_ENSLAVER_AUTO_GC_DAYS` → `CC_ENFORCER_*`.
- **Per-project config dir**: `.claude/cc-enslaver/{edicts,sync-gate}.toml` →
  `.claude/cc-enforcer/…` (`_PLUGIN_NAME` constants in `lib/edicts.py`,
  `lib/sync_gate.py`, `lib/state.py`; this repo's own config `git mv`'d in the
  same commit so the dogfooded layer (i) never lapses).
- **GitHub**: repository renamed to `skymanbp/cc-enforcer`; GitHub serves
  permanent redirects for the old clone/web URLs.

Mechanics, per the rule 09 bulk-edit discipline: a 4-agent survey first
(492 case-insensitive matching lines across 53 tracked files, categorized
functional vs cosmetic), then a byte-level codemod (`cc-enslaver` →
`cc-enforcer`, `CC_ENSLAVER` → `CC_ENFORCER`) — **412 replacements across 52
files, residual `(?i)enslaver` count 0** outside the one deliberate exclusion.

### BREAKING — and the failure mode is silent, so migrate loudly

Both config loaders are failing-open: an unmigrated `.claude/cc-enslaver/`
directory does not error, it just **stops enforcing** (edicts vanish from
injection, Stop layer (i) goes inert). There is deliberately no compat shim
reading the old directory — a quiet fallback would leave two truth locations
forever, and this is the "unenforced gate you still trust" failure v0.31.0
exists to prevent. Migration for a consuming project is one rename:

    mv .claude/cc-enslaver .claude/cc-enforcer

plus re-adding the marketplace under its new name and re-exporting any
`CC_ENSLAVER_*` env vars as `CC_ENFORCER_*` (this machine had none set —
verified against both process and persisted User scope).

### The unified fix the rename flushed out (601 → 604 tests)

Two CLI sites composed the config path from **their own copy of the
plugin-name literal** instead of the shared `_PLUGIN_NAME` constant — the
exact class that turns a rename into a silent read/write split:

- `manage_edicts.py:_global_path()` hand-built
  `~/.claude/cc-enslaver/edicts.toml`, so a constants-only rename would have
  left `--global` **writing** to the old directory while `lib/edicts.load()`
  **reads** the new one. Fix at the mechanism: `lib/edicts.py` gained a public
  `global_path()` (single definition, used by both the loader's home fallback
  and the CLI).
- `manage_sync_gate.py:cmd_path()` printed a would-be path hand-joined from
  the **process cwd**, while `add` / `init` write through
  `sg.default_project_path()` (which honours `CLAUDE_PROJECT_DIR` first). With
  the env naming repo A and the shell sitting in repo B, `path` printed a
  location in B that no write would ever touch — the same print-vs-write
  divergence class as v0.31's birth defect, one command over. `cmd_path` now
  prints through the deterministic write resolver, and the dead `projroot`
  import is gone.

Each fix is pinned by a regression test plus its twin
(`test_edicts.TestGlobalPathSingleDefinition` — equality alone would still
pass if both sides re-inlined the same literal, so the second assertion
requires the constant in the path;
`test_manage_sync_gate.TestPathPrintsTheWriteTarget`).

### What was deliberately NOT rewritten

- **This file's past entries — at release time.** They kept `cc-enslaver`, on
  the argument that a dated record claiming `/cc-enforcer:gc` shipped in
  v0.6.1 would be a lie with a version number on it. Hours later the user
  ruled the other way — retcon everywhere, "as if the name was always
  cc-enforcer" — so the entries below now render the current name, and this
  entry plus the header note are the only in-repo record that a rename
  happened. Git commit history and the published GitHub release objects are
  NOT rewritten: that would take force-pushes and break external references.
- **Frozen software-copyright deposits** (CodeEraser-ip) — the one exclusion
  the user kept when ordering the retcon; every other dated record on this
  machine was swept to the new name in the same ruling.

### Verification

- `python -m unittest discover -s tests` → **604 tests, OK** (601 + 3: the
  two unified-fix pins and their twin).
- `hooks/scripts/i18n_check.py` → clean (codemod touched en + zh skeletons
  symmetrically).
- `test_version_sync` green after the manifest/badge sweep;
  `test_manage_sync_gate` re-runs `check` against this repo's renamed config.

---

## [0.32.2] — 2026-08-17

**Answering "are all the docs updated, including the README?" by checking
instead of asserting — and finding two that were not.** No code change.

### How they were found

The previous four releases touched sixteen markdown files. The audit that
matters is the complement: `git diff --name-only v0.29.0..HEAD -- '*.md'`
against `git ls-files '*.md'`, then reading the **untouched** thirty-three for
claims that v0.30–v0.32.1 invalidated. Both defects were in that set. Neither
was reachable from "did I update the README" — the README was fine.

### 1 · A cross-document claim that was true in only one direction

`commands/sync-gate.md` (added v0.31.0) tells the reader:

> [`repo-refresh`] should call this command's `add`, and close with `check`.

`skills/repo-refresh/SKILL.md` Step 6 still said *"register the couplings you
found into `.claude/cc-enforcer/sync-gate.toml`"* — hand-edit the TOML, no
mention of the CLI that had existed for two releases, and none of `check`.

**Document A asserted that document B does X; document B did not know.** I
introduced that drift in v0.31.0 by documenting the new coupling on one side
only. Step 6 now carries the `add` + `check` invocation, states that `check` is
the step's convergence check rather than an optional extra (the loader is
failing-open: a mistyped glob never fires and never complains), and repeats the
rule that groups are **asserted by a human**, never guessed by the agent.

`docs/ARCHITECTURE.md` §8 gains the coupling as a row, with the lesson: a
cross-document claim *is* a coupling, and it has to be verified from **both**
ends.

### 2 · The rule → component map omitted rule 12's newest components

`docs/RULES.md`'s component table listed `lib/sync_gate.py` for rule 12 and
nothing else, so the CLI and slash command that manage its config were absent
from the one table whose whole job is mapping a rule to the things that enforce
it. Added, along with `sync_gate`'s v0.31 write-target and glob-matching roles.

### Why no new gate for this

`test_doc_sync` derives every pinned fact **from the code**. This table maps a
*judgement* — "does this component enforce this rule" — which no derivation can
produce; a gate over it would compare one hand-maintained list against another,
which is precisely the doc-to-doc comparison that file's design notes forbid
("two docs can drift together, and in this repo they demonstrably did"). Stated
as a known uncovered surface rather than papered over with a gate that would
only look like coverage.

### Verification

- `python -m unittest discover -s tests` → **601 tests, OK** (unchanged).
- `python hooks/scripts/i18n_check.py` → in sync.
- `python hooks/scripts/manage_sync_gate.py check` → exit 0.
- Second sweep over the still-untouched files (`agents/`, the four other
  `commands/`, `docs/I18N.md`, both `00-index.md`, `systematic-debug`) for
  version strings, test counts and sync-gate claims: clean. The rule-12
  one-line summaries in `00-index.md` describe the gate, not the marker
  semantics, so v0.32's tightening does not reach them.

---

## [0.32.1] — 2026-08-17

**Closing the project out: the roadmap is retired and the rule text catches up
with what the code enforces.** No behaviour change.

### The rule pack was describing weaker enforcement than it ships

This is the one that mattered. `rules/` is not internal documentation — it is
the **LLM-agnostic product**: `cat rules/*.md` is a documented install path for
agents that do not speak Claude Code's plugin protocol. v0.32 tightened layer
(i) so that a quoted marker, or a placeholder value, no longer settles a group;
`rules/12-repo-wide-sync.md` still described the v0.27 behaviour.

An agent reading the rule pack was therefore told the escape hatch was looser
than the hook actually is — the same class of defect as v0.26's "the docstring
claimed nesting was handled", one layer out. Both the English skeleton and the
`zh` mirror now state the v0.32 rule, and `commands/checklist.md` H4 says it at
the point of use.

### The roadmap is empty, by decision

A feature list carrying entries nobody will ever build is exactly the staleness
this repo exists to catch. Both remaining entries are retired with a reason,
in all three places they were listed (`CHANGELOG`, `CLAUDE.md`, `docs/EDICTS.md`
— the third would have been missed by anyone editing only the first two):

- **Per-session ephemeral edicts** — *dropped* (user decision, 2026-08-17). The
  blocker is structural, not effort: the edict CLI is a Bash subprocess with no
  `session_id`; only a hook payload carries one, which is why
  `register_read`'s authoritative half lives inside `bash_guard.py`. Building
  it means a second hook-mediated write path for a feature whose entire value
  is being temporary, and `--should` already covers the light-touch case.
- **Layer (g) content-hash upgrade** — *retired, premise measured false.* The
  entry assumed 1-second mtime granularity. Measured on this plugin's primary
  platform (Windows / NTFS), consecutive writes are distinguishable at **1 ms**,
  while layer (g) compares a *first-encounter baseline* against *closing time* —
  seconds apart in any real turn, three orders of magnitude clear of the
  collision window. The failure mode has never been observed. Reopen on a
  reproduction, not on a hypothesis.

### Verification

- `python -m unittest discover -s tests` → **601 tests, OK** (unchanged; this
  release adds no code).
- `python hooks/scripts/i18n_check.py` → in sync, including the `zh` mirror of
  the new rule-12 paragraph.
- `python hooks/scripts/manage_sync_gate.py check` → exit 0.
- Editing `rules/12` armed the repo's own `rules-fanout` group; satisfied by the
  `commands/checklist.md` co-update in the same session — the gate exercised on
  its own rule text.

---

## [0.32.0] — 2026-08-17

**Two things v0.31 recorded instead of closing.** Both were surfaced as open
items and both were decided by the user on 2026-08-17; neither is a defect fix,
so this is a minor rather than a patch.

### 1 · Layer (i) rejects an acknowledgement that answers nothing

v0.31.1 made `sync-check` a schema field and named the consequence in its own
release notes: a mandatory field invites boilerplate, and `sync-check: n/a`
settled a named group exactly as firmly as a real sweep report. The check was
`any(pattern.search(text))` — presence, nothing more.

`_has_sync_marker` now asks two further questions, both of which layer (h)
already asks about `tldr`, and both answered by the same shared model:

- **Attribution** — lines are read through [`lib/mdctx`](hooks/scripts/lib/mdctx.py),
  so a marker inside a non-canonical fence or a blockquote is illustrative text,
  not the agent's own claim. Quoting someone else's `sync-check` no longer
  settles your group. (One judgement, one implementation — separate private
  copies are exactly how layer (h)'s two halves came to disagree in v0.26.)
- **Substance** — the marker must introduce content, on its own line or the
  next non-blank one. A bare placeholder is treated as absent:

  ```
  同步核对: prompts 侧核对过，本次改动不影响注入文案。   → settles the group
  sync-check: n/a                                        → BLOCK (v0.32)
  sync-check: 无 / - / (empty)                           → BLOCK (v0.32)
  sync-check: n/a
  随便一句无关的话。                                      → BLOCK — a non-answer
                                                            cannot borrow the
                                                            following line
  ```

**What this does NOT do, pinned by its own test so the limit cannot drift into
an implied guarantee:** `同步核对: 核对过了` ("checked it") is just as empty and
still passes. `_SYNC_NON_ANSWERS` closes the bottom tier — bare negations and
placeholders — and claims nothing more. Judging whether prose says something
real is not attempted, because over-reaching here refuses honest reports, and a
false block on a correct reply is the worse error.

This is a **deliberate strictness increase**, recorded as such.

### 2 · `check` now runs against this repository, in CI

v0.31.0 shipped `check` on the argument that *an unenforced gate you still
trust is worse than none*, and gave it a non-zero exit specifically so it could
run in CI — and then this repo never ran it on itself. The same defect one
level up: a diagnostic nobody runs reports nothing.

Wired as a test rather than a workflow step, matching `test_i18n_sync.py`,
which calls `check_sync()` on the real tree — so `python -m unittest discover
tests` covers it locally too. A workflow-only step is invisible until push.

It ships with the twin that keeps it from going vacuously green: a passing
`check` must also mean groups *exist*. Deleting every group from the config
would otherwise satisfy "no failures" — the empty-set green `test_doc_sync`
warns about.

### Also

Both `user-prompt` injections (en + zh) now state the placeholder rule as an
enforced outcome rather than advice, since it is one.

**Explicitly unchanged, per the same round of decisions:** the four non-hook
scripts stay in `hooks/scripts/` (two are imported from inside hooks; moving
them buys a directory name and costs a cross-tree `sys.path` splice), and
`rules/12-repo-wide-sync.md` still describes the discipline without naming the
CLI that manages its config.

**Still open, with the blocker named rather than left vague:** per-session
ephemeral edicts (`/cc-enforcer:edict add --session`) cannot be built with the
current CLI shape — the CLI is a Bash subprocess with no `session_id`, which is
precisely why `register_read`'s authoritative half lives inside `bash_guard`.
It needs its own design round, not a corner of this one.

### Verification

- `python -m unittest discover -s tests` → **601 tests, OK** (594 → 601 tests).
- `python hooks/scripts/i18n_check.py` → all translations in sync.
- `python hooks/scripts/manage_sync_gate.py check` → exit 0 on this repo (now
  asserted, not just run by hand).
- A 13-case probe over the marker shapes that matter — real answers in both
  languages, placeholders, empty values, next-line values, fenced and
  blockquoted markers, and the canonical ```yaml block — before any test was
  written; the suite pins the same matrix in both directions.

---

## [0.31.1] — 2026-08-17

**`sync-check` became a field in the reply schema instead of loose prose.**

### The asymmetry this closes

Every closing obligation this plugin imposes has been a *field* in the
canonical YAML schema since v0.20 — and the v0.20 design is that **the field
name IS the Stop-hook detection marker**:

| Obligation | Rule | Schema field |
|---|---|---|
| think-before-write | 02 / 08 | `before` |
| what changed | 09 | `edits` |
| convergence | 06 | `convergence` |
| task fidelity | 07 | `fidelity` |
| root cause + impact + solution | 08 / 09 | `closing` |
| plain-language takeaway | — | `tldr` |
| **repo-wide sweep** | **12** | **— nothing —** |

Rule 12 landed in v0.23, three releases after the schema was fixed, and was
never folded in. Its acknowledgement stayed free prose the agent had to
remember to write *somewhere* — the only duty with no slot to write it in, and
therefore the only one whose omission looked like an ordinary reply.

It is now a field, in all four injected prompts:

```yaml
  closing: {root cause: ..., impact: ..., solution: ...}
  sync-check: <co-files updated, or why none needed>   # rule 12, edit turns
  tldr: "<one plain sentence>"
```

Chinese uses `同步核对:`, which is the zh member of `SYNC_MARKERS`.

### Why this is a patch release, and why it does not weaken layer (i)

**Zero code changed in any hook.** No new detector, no new layer, no altered
verdict: the key already matches `SYNC_MARKERS`, exactly as the v0.20 design
intended. What changed is the prompt text.

The obvious worry is that a schema field mandating `sync-check` on every
modification turn would make layer (i) unfireable. **Verified by probe rather
than by reading the code**, on a two-repo fixture with a real unmet group:

```
edit verdict: ALLOW
  WITH sync-check  -> BLOCK at (i)
  WITHOUT          -> ALLOW          (grace: layer (i) already spent, v0.29)
```

A first violation still blocks, because since v0.27 a marker settles only
groups a previous block actually **named**. The schema field is where the
answer to *that named group* goes on the next turn — which is precisely the
"one informed answer per group" contract, now with somewhere to write it.

**Not changed, and recorded rather than silently skipped:** a vacuous
`sync-check: n/a` still satisfies a named group. That is true of free-prose
markers today too, so this release does not make it worse — but a mandatory
field does invite boilerplate, so both prompts now say so in as many words.
Adding a `has_substance` check like layer (h)'s would be a strictness contract
change and is **not** made here.

### A pre-existing drift the release found

`README.zh.md`'s version badge said **0.29.0** while the plugin was at 0.31.1 —
two releases stale, with every gate green. `test_version_sync` pinned
`README.md`'s badge and not its mirror.

Same lesson as `EXPECTED_VERSION_POINTERS` in that very file: **checking the
site you happened to think of lets its mirror rot.** The badge check now
discovers every `README*.md` from disk, so a `README.<lang>.md` added later is
pinned the day it appears rather than the day someone remembers to register it.
Red-first: the new assertion reports `{'README.zh.md': '0.29.0'}` on the
unfixed tree.

### Budget

Adding a field costs characters, and SessionStart had ~978 to spare against
Claude Code's 10,000-char hook-output cap. The first draft spent ~500 of them
on a prose caveat — and `test_edicts_appear_in_session_start_injection` went
red, because the contract then squeezed the **edict block** out of the
injection entirely. That is a real regression: user-defined hard rules
vanishing from SessionStart.

The caveat was duplicating what the per-turn injection already says, which is
exactly what v0.29 deleted §4 for. Condensed, the field costs **75 characters
net**:

| Injection | before | after | headroom |
|---|---:|---:|---:|
| SessionStart (en) | 9,022 | 9,097 | 903 |
| UserPromptSubmit (en) | 6,424 | 6,672 | 3,328 |
| SessionStart (zh) | — | 6,007 | 3,993 |
| UserPromptSubmit (zh) | — | 4,086 | 5,914 |

### Verification

- `python -m unittest discover -s tests` → **594 tests, OK** (590 → 594 tests).
- `python hooks/scripts/i18n_check.py` → all translations in sync.
- New `TestSyncCheckIsASchemaField` pins both halves that neither implies:
  the field is present in all four prompts, **and** its name still matches a
  real `SYNC_MARKERS` pattern — with a twin asserting a renamed field
  (`sync-sweep:`) would *not* satisfy the gate, so the first assertion cannot
  pass vacuously. Cap-fit is asserted for both languages.

---

## [0.31.0] — 2026-08-17

**The sync gate became inspectable.** Rule 12's co-update groups have been
*enforceable* since v0.23 and *authorable* only by hand-writing TOML — with
nothing that could tell you what the loader made of it.

### Why that gap was the dangerous kind

`lib/sync_gate.py` is failing-open by design, and correctly so: a config bug
must never brick a session. But look at what "failing open" means for each way
a config can be wrong:

| What you wrote | What happens | What you see |
|---|---|---|
| `require = []` | group silently DROPPED by the loader | one stderr line |
| `when = ["src/*.pyy"]` | group loads, matches nothing, never fires | nothing |
| non-UTF-8 save | whole file ignored, every group inert | one stderr line |

In all three the gate looks exactly like a healthy one from the outside.
**An unenforced gate you still trust is worse than no gate at all**, because
you have stopped looking at that part of the repo.

Compare Imperial Edicts, which got an authoring CLI in v0.12: validated writes,
and a `list` that shows what the loader *actually parsed*. Sync-gate had
neither, while `skills/repo-refresh/SKILL.md` has been instructing agents since
v0.23 to "register the couplings you found into sync-gate.toml" — with no tool
to do it and no way to check the result.

### `/cc-enforcer:sync-gate`

New [`hooks/scripts/manage_sync_gate.py`](hooks/scripts/manage_sync_gate.py) +
[`commands/sync-gate.md`](commands/sync-gate.md):
`init / list / check / add / remove / path`.

`check` is the point of the whole feature:

```
$ /cc-enforcer:sync-gate check
config: .../.claude/cc-enforcer/sync-gate.toml
3 group(s) loaded:
  hooks-tests
    when    = ['hooks/scripts/*.py']
    require = ['tests/*.py']

scanned 114 file(s) under D:\Projects\anti-laziness

  ok hooks-tests.when     'hooks/scripts/*.py' → 18 file(s)
  ok hooks-tests.require  'tests/*.py'         → 16 file(s)

OK — every group loaded and every glob matches something.
```

It reports the groups the loader kept, the groups it **declared-but-dropped**
(with why), and every glob matching no file in the repo — exiting 1, so it is
usable as a CI step rather than only as a human courtesy.

### Deliberately NOT auto-created

The question that prompted this release was "should `sync-gate.toml` be created
automatically?". It should not, for three reasons worth recording so it is not
re-litigated as an oversight:

1. **No hook writes into the user's project directory.** That invariant has held
   for every release; the only writer of user-repo files is `manage_edicts.py`,
   which the user invokes. A plugin that tells agents not to produce unrequested
   side effects does not get to drop a file into your git repo.
2. **An empty template is functionally identical to no file.** Zero groups means
   layer (i) still never fires, so auto-creation buys discoverability only — at
   the cost of an unrequested file in every user's `git status`, and a
   delete-and-it-returns loop unless yet more state is added to suppress it.
3. **Auto-*inferred* groups would be worse.** The gate's value is that a *human*
   asserted "these must move together". A heuristic guess is manufactured
   confidence — exactly what rule 01 forbids.

`init` creates the file when *you* ask. That is the "auto" part, triggered by
the person who knows the invariant.

### Writes are verified twice, not once

`manage_edicts._write_edicts` checks that its output PARSES. Necessary, not
sufficient here: a group with an empty `when` or `require` is **valid TOML that
`sync_gate.load()` silently discards**. A parse-only check would let the CLI
print "added" over a group that guards nothing — the precise failure this tool
exists to make impossible.

So `_write_groups` round-trips the result through the real loader
(`sync_gate.load_file`) and requires every group to come back. On failure the
previous file is restored byte-for-byte; a file the CLI itself created is
removed rather than left as debris.

### A defect found in this feature's own first smoke test

Reported rather than quietly fixed, because it is instructive and because this
repo's rules require it.

The first draft resolved its write target with `sync_gate.config_path()`. That
function is a **read** resolver: it tries payload cwd → `CLAUDE_PROJECT_DIR` →
process cwd, testing each with `.is_file()`, and takes the first that already
holds a config. Correct for a hook, which must find whatever config governs the
session even when the env var is missing.

Run against a project that has **no config yet**, every candidate fails
`.is_file()` and resolution falls through to the process cwd. Under test with
`CLAUDE_PROJECT_DIR` pointed at a scratch repo, from a shell sitting in this
one, the CLI appended two groups to **cc-enforcer's own `sync-gate.toml`**.

**Upstream ladder.** Symptom: wrong file written. Propagation: `_write_target`
trusted a resolver whose contract is "find an existing config". Origin: *"where
do I read from" and "where do I write to" are different questions*, and a read
resolver's fallback chain is precisely what makes it the wrong answer to the
second. `lib/edicts.py` has modelled this split since v0.18.1
(`edicts_path` vs `default_project_path`); the new module simply failed to
mirror it.

**Unified fix, class swept.** The diagnosed root cause has two instances, both
closed in one change:

- `sync_gate.default_project_path()` — deterministic: resolve the ROOT, then
  derive the path. Never asks whether a file is already there.
- `sync_gate.load_file(path)` — parses exactly one file. `_load_groups` used
  `load(str(path.parents[2]))`, which re-enters the searching resolver, so
  verifying a config we had just written could have reported on a different one.

Both directions are pinned by `tests/test_manage_sync_gate.py`, including the
counterpart contract — `config_path` **keeps** its fallback — so that "fixing"
this later by making everything deterministic cannot silently break the hook
path that depends on it.

### Shared primitives (rather than a second copy)

- **`lib/tomlio.py` now owns the TOML writer as well as the reader**:
  `basic_string` (moved from `manage_edicts`, whose two historical defects — a
  raw newline in a single-line basic string, and DEL passing a `>= " "` guard —
  are documented at the new home), `dumps_check`, and `available()`.
  `manage_edicts.py` lost its two defensive `try: import` blocks in the process;
  the direct `import tomllib` was a **third** copy of the same availability
  sentinel, which is the shape v0.30 spent a release collapsing.
- **`sync_gate.matches_any`** — one definition of "does this path belong to this
  glob", shared by `evaluate()` and the CLI's diagnostics. A `check` that
  answered that question differently from the gate would certify a config the
  gate then ignores.
- **`sync_gate.project_root`** — both call sites stop counting `.parents[2]`
  for themselves.

### Documentation

Both READMEs (command tables, structure trees, the "New in" section), `CLAUDE.md`
(tree, §6 table, capability list), `docs/ARCHITECTURE.md` §3 (six commands now)
and §8 (rows for `manage_sync_gate.py` and the `tomlio` writer half), and
`tests/README.md`.

**Not touched, deliberately:** `rules/12-repo-wide-sync.md` and its `zh` mirror.
The rule defines the *discipline*; the CLI is tooling for the config the rule
already describes. Editing it would fan out to `prompts/` + `docs/RULES.md` +
`commands/checklist.md` for no gain in what the rule says.

### Verification

- `python -m unittest discover -s tests` → **590 tests, OK** (565 → 590 tests).
- `python hooks/scripts/i18n_check.py` → all translations in sync.
- Live probes on a two-repo fixture: the write lands in the named project with
  the other repo byte-identical; `check` exits 1 on a dead glob and 0 when
  clean; a `require = []` add is refused with the file unchanged.
- The plugin blocked its own author four times while this was written — twice
  for a `# noqa` whose rationale had drifted outside the ±1-line window, twice
  for rolling small edits into one README instead of one systematic pass. Both
  were correct catches and are recorded rather than worked around.

---

## [0.30.0] — 2026-08-16

**A structural audit of the plugin itself.** No new rule, no new detector, no
change to what is enforced — except one place where the enforcement was
describing itself inaccurately. Three findings on one theme: **a thing that is
written down is not a thing that is enforced.**

Every previous audit round (v0.24 → v0.27) looked for *defects in behaviour*.
This one looked at *structure*: what is reachable, what is duplicated, what is
classified where, and whether the documentation that claims to enumerate the
codebase actually does. It found that the repo had accumulated exactly the
shapes its own rule 09 forbids — dead siblings kept "just in case", the same
judgement transcribed into three files, and a status table asserting something
it had not checked.

### Dead code deleted, not annotated

Seven production symbols were unreachable from anywhere in the tree (verified
with an AST reachability scan over `hooks/` and `tests/`, not by grepping):

| Removed | Where | Why it was still there |
|---|---|---|
| `_split_command` | `bash_guard.py` | v0.26 reduced its body to a one-line delegation to `shellcmd.tokenize`; nothing called it after that. Its docstring narrated the v0.25 / v0.25.1 tokenising bugs, which is what made it *look* load-bearing. |
| `_CMD_SEPARATOR`, `_SHORT_FLAG_CLUSTER` | `bash_guard.py` | The v0.25 text heuristic's separator list and short-option matcher, orphaned when the parse model replaced it. `import re` and `import shlex` went with them. |
| `_has_rationale`, `_comment_text`, `_cjk_count` | `read_guard.py` | `_has_rationale` was superseded by `_has_rationale_at` in v0.26 (which judges the window against the *whole* text's lexical state — a three-line window inside a docstring carries no delimiter of its own). Every call site moved; the function did not. |
| `_escape_triple_quoted` | `manage_edicts.py` | Marked *"Deprecated… kept only so an external caller does not break."* There is no external caller and there cannot be one: it is a module-private helper in a script this repo never installs as an importable package. |

Plus a function-local `import os` in `stop_guard._verify_claims` shadowing the
module-level one with an identical binding, and three unused test-module
symbols (`TILDE`, `MARKETPLACE_MANIFEST`, an `import json`).

This is not housekeeping. A *retired rationale checker standing beside the live
one* is an active hazard: the two answer the same question differently, and the
next reader has no way to tell which one the guard consults. Rule 09's
"deprecated but kept" is the same excuse as "suppressed but justified".

### Three duplicated judgements, one definition each

- **Markdown fence geometry existed three times** — `stop_guard._fence_marker`,
  `mdctx.fence_marker`, `i18n_check._fence_run` — each carrying its own
  transcription of the same v0.25 CommonMark fix (*a closing fence must be at
  least as long as its opener*), and `i18n_check`'s copy annotated "Mirrors
  stop_guard._fence_marker — both files track markdown fences and must agree."
  Writing that down did not make it so: the fix had to be applied to each copy
  separately. `mdctx.fence_marker` is now the one definition and the other two
  call it. Zero behaviour change — the helper is byte-equivalent; what changed
  is that the next correction lands in one place.
- **The project-root predicate existed twice** — `lib/edicts.py` and
  `lib/sync_gate.py` — the second annotated *"Same project-root heuristic as
  lib/edicts.py"*. A comment that names an invariant without holding it: widen
  one copy (to recognise `.hg`, a `pyproject.toml` marker) and the other is
  silently left behind. **New: [`lib/projroot.py`](hooks/scripts/lib/projroot.py)**,
  the same answer `lib/tomlio.py` gave one layer down. This one is
  security-shaped rather than cosmetic — the predicate decides whether a
  session started in `~/Downloads` may load a stranger's `must` edicts.

Deliberately **not** unified: `_compute_sha256` (six stdlib lines, duplicated
in `bash_guard` and `register_read`) and `_emit_raw_deny`. The first sits under
this repo's own bar — CLAUDE.md §2.6, *"three lines of duplication beat a
premature abstraction"* — and the second is duplicated on purpose so the two
guards' failure modes stay independent. Unifying everything that looks alike is
the mirror image of the defect above, not its cure.

### The Stop status table stopped making an unfounded claim

Layers are **displayed** (a)…(i) because that is how every doc, recovery blurb
and test names them. They are **evaluated** with (b) first: a hedge invalidates
a done-claim however much evidence sits beside it, so grading the evidence
first would be wasted work.

`_render_status_table` derived both verdicts from the **display** index. So
every layer-(b) block printed:

```
| (a)   | 06   | ✅ Pass     |                                   |
| (b)   | 01   | ❌ **FAIL** | hedge near done-claim             |
```

— a positive assertion that convergence evidence had been found, printed on a
turn where `_has_evidence` was never called. A gate whose entire purpose is
catching claims made without checking does not get to make one in its own
output. Verdicts now come from a `_EVAL_ORDER` tuple; the display order is
untouched.

Two tests changed, and the direction matters. `test_layer_a_failure_table_shape`
asserted that (b) must **not** show ✅ on a layer-(a) block, under the comment
"they were never evaluated" — false for (b), which runs first and had genuinely
passed. It now pins the accurate contract, and a new twin,
`test_layer_b_failure_does_not_claim_a_passed`, pins the other direction. No
enforcement decision changes; only what the table reports about itself.

### File tree: reclassified, not rearranged

- **Tests are indexed.** [`tests/README.md`](tests/README.md) was three years of
  stale — it described "the three hook scripts" (there are eight) and listed
  four of sixteen files. It is now the complete, per-file index: what each file
  covers, its test count, and the two house rules (every "allowed" assertion
  needs a DENY twin; fixtures are assembled at runtime because the plugin scans
  its own test files). Three release-stamped filenames became category-stamped:
  `test_v026_models.py` → `test_audit_v026_models.py`, `test_v026_audit2.py` →
  `test_audit_v026_round2.py`, `test_v027_contracts.py` →
  `test_audit_v027_contracts.py`.
- **`hooks/scripts/` labels its three roles inline** — four hook entry points,
  four auxiliary entry points, eight shared `lib/` modules (themselves grouped:
  judgement models / state + config / features).
- **New [`docs/README.md`](docs/README.md)** — an index of the four documents
  and where everything else lives.
- **The four non-hook scripts deliberately did NOT move to a `tools/`
  directory.** The tidy-looking split is wrong here: `gc_state.py` is imported
  by `inject_context.py` for auto-GC, and `register_read.py`'s authoritative
  logic lives inside `bash_guard.py`. Neither is a standalone CLI, and moving
  them would replace a same-directory `from lib import …` with a cross-tree
  `sys.path` splice — trading a real fragility for a directory name. Recorded
  here so the question does not get re-opened as an oversight.

### `CLAUDE.md`: 87 KB → 39 KB

Its "current version" section had grown into a **verbatim second copy of this
changelog** — 545 lines, ~62 KB. `CLAUDE.md` is loaded in full at the start of
every Claude Code session in this repo, so the real cost was roughly 18k tokens
of context per session, spent on text that already exists here. Worse, it was a
second source of truth: two narratives free to drift, which is precisely how
v0.22.1 shipped a stale `marketplace.json` and v0.26 shipped five stale test
counts.

§6 is now a one-line-per-release table plus the standing capability inventory.
The splice was mechanical (`sed` range delete) and both kept regions were
diffed byte-for-byte against the pre-edit file before the suite was re-run.

### Documentation

- `docs/ARCHITECTURE.md` §3 said **"Two user-invokable surfaces"** and listed
  `checklist` + `verify`. Three more commands shipped between v0.6.1 and v0.21,
  documented everywhere *except* the architecture doc that claims to enumerate
  that layer. Now five, each with its backing script.
- §8's connected-files map gained rows for `lib/projroot.py` and the shared
  fence helper, and its `test_v026_models.py` references follow the rename.
- Both READMEs: structure trees, the `lib/` inventory (seven → eight modules),
  the `hooks/scripts/` role split, the status-table note, and a rewritten
  "New in" section.
- The `plugin.json` / `marketplace.json` `description` fields were 11 KB and
  15 KB of accumulated release narrative — in the field a user reads in the
  `/plugin` picker. Rewritten to describe the plugin, then this release.

**Refuted, not fixed:** an early sweep flagged 46 markdown links in
`prompts/`, `commands/`, `skills/` and `agents/` as broken, because they are
written relative to the repo root while living in subdirectories. They are
correct: those files are *prompt payloads*, resolved by an agent whose cwd is
the project root, not pages rendered by GitHub. `test_doc_sync.py` resolves
links from either base for exactly this reason. Documented in ARCHITECTURE §3
rather than "fixed" into breakage.

### Verification

- `python -m unittest discover -s tests` → **565 tests, OK** (564 → 565 tests).
- `python hooks/scripts/i18n_check.py` → all translations in sync.
- The doc gate caught two of this release's own errors while it was being
  written: a missing `projroot.py` in both structure trees, and a
  `test_*_sync.py` glob whose `_sync.py` fragment read as a file that does not
  exist. Both are recorded rather than quietly corrected — they are the gate
  working, and the second is the same class of mistake (a written-down pattern
  that does not match reality) this whole release is about.

---

## [0.29.0] — 2026-08-15

**The contract could not reach the agent it governs.** Two instances of
one root cause — enforcement-critical text placed where it cannot be
seen or reached — swept together as a single unified fix (rule 09).

### Fixed — the injection outgrew the hook-output cap

Claude Code caps hook output, `additionalContext` included, at **10,000
characters** (not bytes; UTF-8 multi-byte content counts one per
character). Anything longer is written to a file and replaced inline by
a path plus a short preview
([docs](https://code.claude.com/docs/en/hooks#json-output)). The limit
is **not configurable** — no env var, no settings key.

Measured on a live session: **SessionStart 18,761 characters,
UserPromptSubmit 11,350**. Both were being persisted, so the agent only
ever saw the head of each. §3 — the mandatory YAML reply schema, whose
field names are the Stop-hook detection markers — sat past the preview
boundary and went unread for an entire session while every hook reported
green. The plugin had no way to notice: nothing measured its own
injection.

Four coordinated changes rather than four patches:

1. **`prompts/session-start.md` §4 deleted.** Its decision-trigger list
   was a strict subset of the per-turn `user-prompt.md` table, which is
   re-injected on *every* turn. The contract was paying ~2,700
   characters to duplicate something the agent already receives.
2. **`prompts/user-prompt.md` inlines the YAML schema.** It used to say
   "see SessionStart injection §3" — a cross-reference into precisely
   the region that was invisible. The skeleton now lives in the per-turn
   injection itself, so the schema survives whatever happens to
   SessionStart.
3. **Self-locating header on every injection.** The first thing in every
   payload is the absolute plugin root plus the prompt filename, so even
   a truncated preview carries an actionable pointer to the full text.
   Static markdown cannot know its own absolute path; the hook can.
4. **`build_context` enforces the cap structurally.** A fixed budget
   goes stale the moment either side changes length, so the assembly
   measures the actual strings. The contract is protected; the edict
   block is the unbounded part (it grows with every edict, and 16
   project edicts ≈ 5.6k characters is what pushed this over), so when
   the budget is tight the edicts are elided to a pointer — at **whole-
   edict boundaries**, because half an edict still reads as a complete
   instruction — and the contract is never cut. If the contract alone
   exceeds the cap it is emitted whole, with the header fail-safe
   covering the degradation.

Result: **SessionStart 18,761 → 9,826, UserPromptSubmit 11,350 →
7,225**, both inline. With 200 synthetic edicts the payload still lands
at 9,817 with the contract tail intact.

### Changed — Stop grace is now per LAYER, not per sequence

`state.was_just_blocked()` returning True made `stop_guard` `return 0`
**before evaluating a single layer**. The grace window forgave the whole
check rather than the row that failed, so a recovery reply that fixed
the layer it had been shown while still violating another was never
tested against the other.

Observed live: layer (a) blocked for missing evidence; the recovery
reply supplied the evidence but carried no `tldr`; layer (h) — never
named, never spent — was skipped entirely. Every un-named layer was
unenforceable in exactly the situation it exists for.

Grace is now scoped to the layers already spent in the recovery sequence
(`state.blocked_layers`, `get_forgiven_layers`, `clear_blocked_layers`).
A spent layer stays forgiven, which is the anti-deadlock property the
one-shot guard was built for — no layer blocks twice for one recovery.
An unspent layer may still block once, and doing so spends it, so
escalation is bounded by the layer count and terminates. Any allowed
Stop clears the set; the next sequence starts with all layers live.

**This is a strictness increase**, recorded as such: replies that
previously slipped through the grace window are now blocked for the
layers they still violate.

### Tests

**556 → 564.** The two tests asserting the old whole-check grace were
rewritten to assert the per-layer contract — not deleted, since the
behaviour they pinned is the defect. New coverage: per-layer
escalation, bounded termination, clean-Stop reset, cap arithmetic under
0/1/2/5/20/200 edicts, whole-edict clipping, the header fail-safe, and
the body-alone-over-cap degradation path. `prompts/zh/` co-updated;
`i18n_check` exit 0.

---

## [0.28.0] — 2026-08-12

**Rules 03 + 09 upgraded: trace upstream → diagnose → one unified fix.
Point-to-point patching is banned outright.** (User directive, 2026-08-12.)

When a problem appears, the only accepted shape of a fix is now:

1. **Trace to the most-upstream root cause.** Rule 03 gains an *upstream
   tracing ladder*: every failure has three kinds of location — the
   **symptom site** (where it surfaces), the **propagation path** (what
   the bad state flowed through), and the **origin** (the mechanism /
   design decision / missing invariant that generates it). Fixing at the
   first two levels is a patch, even when the observed failure
   disappears. Climb the chain until the answer is a mechanism; stopping
   short is legitimate only with the true origin named and the reason
   stated.
2. **Diagnose before treating (确诊).** The root-cause hypothesis must be
   demonstrated by a first-party probe / reproduction / failing test
   *before* the first line of the fix is written.
3. **One root cause, one unified fix.** Rule 09 gains the unified-fix
   discipline: a diagnosed root cause defines a *class* of defects — the
   observed instance is merely the one that surfaced first. Sweep the
   repo for every sibling of the class, fix the generating mechanism
   once, cover all instances in the same pass, and prove the class is
   closed by re-triggering at least one *other* instance. N symptoms
   sharing one root = **one** fix, never N patches.

The motivation is this repo's own measured history: v0.25.1 *named* a
root cause — detectors that described a *string* instead of the
*concept* — and then fixed only the instances it had seen; the
mechanism survived and regenerated a fresh crop of the same class by
v0.26 — including one regression. v0.26 closed it by replacing the
mechanism (33 findings → 3 root causes → 4 shared models). v0.28
codifies that shape as the mandatory form of every fix.

Surfaces updated in lock-step: `rules/03` + `rules/09` (English skeleton
+ zh mirrors), `prompts/session-start.md` + `prompts/user-prompt.md`
(+ zh — new one-liners and decision-trigger rows), `docs/RULES.md`,
`commands/checklist.md` (new items F9 most-upstream / F10
diagnosis-first / F11 class-sweep unified fix),
`skills/systematic-debug/SKILL.md` (Steps 5/6/7 + forbidden list now
carry the ladder and the unified fix — the auto-invoked runtime surface
for exactly the "a problem appears" scenario, caught missing by the
pre-release review), `CLAUDE.md` §2.4 / §2.11.

**The upgrade diff was itself adversarially reviewed before shipping**
— four parallel read-only lenses (en↔zh semantic parity / internal
consistency / factual claims / task fidelity) with per-finding
adversarial verification, plus one independent external review: 27
findings, **14 confirmed and fixed in one unified pass**. The confirmed
set included: the new injection rows' "physical consequence" cells
overstating what the hooks can verify (now stated honestly as
text-level — an agent acts on what it is told); the `systematic-debug`
skill never receiving the upgrade; a single-instance class making the
termination condition unsatisfiable (explicit single-member branch
added); the rule 07 scope-precedence conflict left unadjudicated
(precedence note added: the class sweep is part of the fix, but a
materially scope-expanding class goes to the user first); a quote
attributed to v0.25.1 in v0.26's wording; and README's v0.27 block
saying `556 → 556` where four other surfaces say 543 → 556. Rejected
with reasons: "四个统一件" is this repo's own established zh term for
the v0.26 delivery, and `rules/00-index.md` updates only on rule-set
changes by six-version precedent.

**Zero new detectors — deliberately**, on the v0.22.1 precedent: this is
a reasoning shape, not a syntax shape a hook can match (no hook can tell
whether an edit sits at the top of a causal chain). The existing hard
layers — the patch-marker content scan, the rolling-patch frequency
layer, and Stop layer (f)'s root-cause triplet — remain the physical
floor under the upgraded text. One candidate hard extension (requiring
an explicit "most-upstream / class-sweep" marker on edit turns at Stop
layer (f)) is a strictness contract change and is **recorded for the
user's decision rather than shipped unilaterally**, per the v0.25.1
precedent for contract changes.

Tests hold at **556** (no code changed; the doc gates re-verify the
updated surfaces).

## [0.27.0] — 2026-08-10

**The three items v0.26 recorded as "known, not fixed" — closed.**

Each was deferred with a stated reason. Deferring twice is how a
documented limitation becomes permanent, so each is settled here, and in
every case the direction was decided by evidence rather than preference.

### The tokeniser follows the SHELL, not the host OS

v0.25.1 disabled backslash escaping when `os.name == "nt"`, reasoning
that an unquoted drive-letter path would otherwise lose its separators.
That treated the host OS as a proxy for the shell grammar. Claude Code's
Bash tool on Windows runs Git Bash / MSYS, and measuring it settled the
question:

```
$ echo "$BASH_VERSION / $OSTYPE"
  5.2.37(1)-release / msys
$ set -- C:\Users\me\note.txt ; printf '<%s>' "$1"
  <C:Usersmenote.txt>          # the shell eats them too
$ set -- --for\ce ; printf '<%s>' "$1"
  <--force>                    # a REAL force-push evasion
```

The branch was wrong in both directions. It never rescued the path case —
the shell mangles an unquoted drive path identically, so the file does not
exist under the name as typed, and the recovery is to **quote it** (which
every test already did). And it hid a live bypass: a backslash-split force
flag reached git intact while `_detect_force_push` saw a token it did not
recognise.

POSIX escaping now applies unconditionally. The `windows` parameter
survives only so a regression test can pin *why* the old behaviour was
abandoned. `test_all_four_spellings_register` became
`test_shell_safe_spellings_register`: "native unquoted" was removed from
the supported set and given its own test asserting it does **not**
register — a correction to match the shell, not a relaxation.

### Layer (h): presence and measurement are separate verdicts

`mdctx.LineCtx` now carries `attributable` alongside `countable`:

- **`attributable`** (generous) — could a reader plausibly read this as
  the agent's own words? Used by the presence half. A false negative here
  blocks a reply for a "missing" tldr that is visibly present, which the
  agent cannot diagnose from the block reason.
- **`countable`** (conservative) — is this definitely the agent's own
  words, safe to measure against the 160-char cap?

They differ only on CommonMark **lazy continuation**, which v0.26
deliberately skipped precisely because one flag could not express both:
implementing it made a visible `tldr:` under a blockquote uncountable, so
presence then blocked the reply. With the split, lazy continuation is
implemented — such a line is not measured, but still counts as present.

### Layer (i): one INFORMED answer per group

The primary path acked **every** pending group when a marker appeared,
while the grace path (narrowed in v0.25.1) acked only the groups actually
presented. That inconsistency was itself the bypass: outlast the grace
window and the looser path silenced groups the agent had never seen named.

Both paths are now scoped to the presented set. The cost is bounded and
intentional: a group blocks once, the block names it, and the next reply's
marker settles it for the session. One informed answer per group is what
rule 12 asks for; one blanket sentence covering groups you never
considered is the laziness it exists to stop.

This is a **strictness increase**, not a bug fix — recorded as such.

Tests **543 → 556**.

## [0.26.0] — 2026-08-10

**Fourth-round audit — the previous release's own fix diff was reviewed, and
the mechanism was replaced instead of the symptoms.**

Three parallel read-only reviews of the uncommitted v0.25.1 fix diff, plus a
first-party pass, produced **37 findings**. Every claim was re-adjudicated
against the real code with first-party runtime probes before being accepted:
**33 reproduced**, **3 were recorded as by-design** (a permissive inline-reason
heuristic; the deliberate prose-doc exemption; the Bash write-path, carried
over), and **1 was refuted** — a reviewer called
`test_negated_statements_are_not_done_claims` vacuous when it in fact fails
with 4 failures on the pre-fix tree.

The 33 collapse into three root causes, so the release ships **four shared
models** rather than ~30 individual patches.

### Root cause α — the detector encoded a *spelling*, not the concept

Every guard substituted a text test for a structured idea, and each audit round
produced a fresh crop of the same defect. v0.25.1 named this exact root cause
and then fixed *instances* of it; the mechanism survived and regenerated.

- **`#` / `//` inside a string counted as a comment.** One neighbouring
  `API = "https://api.example.com"` line silenced the **rule-10 secret
  detector** outright — `example` is a rationale token and `example.com` is the
  IANA example domain, so the leak fired precisely where committed credentials
  live. Same leak disabled **rule 11**. Block comments (`/* because … */`) were
  invisible in the other direction, falsely denying legitimate JS/TS.
- **Block structure read from *physical* lines.** A multi-line string body
  re-anchored indentation and hid a later swallow; a bracketed
  `except (\n …\n):` header was never inspected; and a handler clause suppressed
  **every** stack pop, which **REGRESSED** nested `try/except` from deny
  (v0.25.0) to allow (v0.25.1) — while the rewrite's own docstring claimed
  nesting was now handled by a stack.
- **Force-push detection over co-occurring words.** Denied an `echo` of a
  force-push string and `git config alias.deploy "push --mirror"` (subcommand
  is `config`); missed `git push origin +main` (a force refspec needs no
  colon), `+:refs/heads/main`, and any push whose global options outran a
  120-character window.
- **"Command position" by walking backwards over dashes.** `python -c
  register_read.py …` registered a file as read though the script never ran;
  `python -X utf8 register_read.py …` — the spelling its own docstring
  advertised — and `python3.13` were rejected; shlex's default `#` commenter
  truncated a legal Windows path.

Replaced by three new shared models plus a schema:
[`lib/srclex.py`](hooks/scripts/lib/srclex.py) (tolerant source lexer:
comments vs docstrings vs data literals, literal masking with preserved
offsets, bracket-joined logical lines),
[`lib/mdctx.py`](hooks/scripts/lib/mdctx.py) (markdown fence/blockquote
context — now consumed by **both** halves of Stop layer (h), which previously
disagreed about which fences count, letting a `tldr:` in a ```text example
satisfy presence while the length half measured nothing), and
[`lib/shellcmd.py`](hooks/scripts/lib/shellcmd.py) (tokenise → segments →
argv → git subcommand / python script operand).

### Root cause β — hardening scoped to the observed instance, never the class

- `lib/state.py` `_normalized` repaired `read_files` and left `session_id`
  raising `KeyError` from `save()` — swallowed as failing-open, so the Read was
  never recorded and the **next edit was falsely denied as unread**. Its own
  docstring claimed a top-level `{}` was repaired. Now schema-driven across
  every collection and numeric field, and the stored `session_id` is written
  back authoritatively (a record whose stored id disagreed with its filename
  redirected every later write to a different file).
- auto-GC compared a **raw** session id against **sanitised, 64-truncated**
  filenames, so for any non-canonical id the live session was not excluded.
- `manage_edicts._dump_edict` coerced only `id`; a wrongly-typed `text` /
  `severity` / `note` raised, and `_write_edicts` re-serialises **every** edict
  on any add/remove, so one bad field broke the whole CLI.

### Root cause γ — the claim outran the change

- Four v0.25.1 tests passed unchanged on the pre-fix tree; each now carries a
  twin assertion (remove the rationale → must DENY; the detector is armed).
- `TestPluginIsSelfRewritable` said it pinned "the whole tree" but globbed only
  `hooks/scripts` — **six of the ten test modules were self-locked** by the
  same bare lint suppression on their own `sys.path` bootstrap (verified by
  replaying the pre-fix detector over the pre-fix content of every
  `tests/*.py` at `83e5487`). Glob widened; the offending sites now carry
  house-style adjacent rationales.

### Also fixed

- Marker regexes end at **token boundaries**: `# noquality`,
  `@ts-ignore-generated` and `eslint-disablement` were false **DENIES**.
- The rationale hatch accepts **Chinese** (`因为` / `故意` / `理由` / …). Only
  the noun `原因` was listed, so the most natural Chinese "because" was denied
  while English `because` passed — in a Chinese-primary repo. The
  "substantive inline reason" heuristic required an ASCII space, which no
  Chinese sentence has; it now measures CJK length instead.
- The rationale search is evaluated against **whole-text** lexical state
  (`_has_rationale_at`) rather than re-lexing the ±1-line window in isolation,
  where a docstring has no delimiter of its own and looked like bare code.
- Done-claim negation: `not yet done`, `isn't done` / `aren't fixed` (the old
  `\bn't\b` could never match — there is no word boundary before `n` in
  "isn't", so it was unreachable dead code) and `Nothing is done.` A clause
  boundary now bounds the search, which keeps `没有遗漏，已完成` a genuine claim.
- Layer (h): a punctuation-only `tldr: !!!` and a blockquote nested under a
  list item (`- > tldr: …`) no longer satisfy the gate.

### Not changed (recorded, not silently decided)

- **Layer (i)'s primary ack path still acknowledges every pending group.**
  v0.25.1 scoped only the *grace* path. Applying that scoping here would
  contradict the documented v0.23 design ("a marker covers the pending
  groups"); leaving them different means waiting out the grace window bypasses
  the scoping. This is a **contract question**, not a defect — surfaced rather
  than decided unilaterally.
- **Windows-prompt evidence inside a fenced example** was reported as a defect
  and is **refuted here**: evidence patterns are *meant* to match pasted
  transcripts, which live in fences, and the pre-existing POSIX `$` prompts
  behave identically. Flagging only the Windows spelling would be inconsistent.

### Re-audit of this release's own fix code

The fix was itself put through a second read-only review before shipping —
because the defect this release exists to correct was *introduced by the
previous release's fix*. It found **8 more real defects in the new code**, all
fixed here, plus one mistake of mine that the existing suite caught:

- **HIGH — `$( … )`, backticks and `( … )` were not segmented.** The text
  heuristic the shell model replaced caught these *by accident*, so the model
  would have been a **regression**: `$(git push --force)` executes a force push.
  Grouping and substitution delimiters are now separators, and a shell's `-c`
  operand is tokenised recursively.
- **HIGH — an escaped `\"""` ended a triple-quoted block early**, exposing the
  rest as code and comments, so string content could satisfy the rationale
  hatch. Delimiters preceded by an odd number of backslashes no longer close.
  Relatedly, a triple-quoted block only counts as *documentation* when it
  starts its own line — `SQL = """… because …"""` is data.
- **MED ×3 in the markdown model** — a closing fence carrying an info string
  (```` ```still-inside ````) closed its parent, making quoted fixture content
  countable; `yaml-not` / `yamlish` matched the canonical `yaml` by prefix; a
  4-space-indented fence opened a fence (CommonMark allows at most 3).
- **MED ×2 in done-claim negation** — `cannot` / `unable` / `绝非` / `并非` were
  missing (the damaging direction: an honest "not done" report gets blocked),
  while `not only fixed but tested`, `no longer broken - fixed` and the double
  negative `不得不承认已完成` were wrongly suppressed.
- **MED — punctuation padding reached the rationale length bar**
  (`改了改了改了!!!!!!`, `变量名字变量名字____`), as did pure repetition.

**Reverted:** an attempt to make a bare ``` fence countable, on the theory that
an untagged schema block would be missed. It broke
`test_non_yaml_fence_fixture_is_not_measured` — a deliberate v0.23 contract
(quoting someone else's overlong tldr in a bare fence must not self-trip). The
existing pinned contract won over the speculative false positive.

**Accepted as documented limitations** (not fixed): `//` inside a JavaScript
regex character class reads as a comment; a JS template literal's `${…}`
interior is treated as string data; and the blockquote-peeling loop is bounded
at 8 nested list markers. Each needs a real JS parser or an unbounded scan to
do properly, and each fails in the conservative direction.

### Documentation audit — 41 confirmed defects, and the gate that stops them recurring

A separate whole-repo documentation audit ran against this release before it
shipped: 7 surface auditors, each finding adversarially re-verified, **41
confirmed**. A first-party spot-check of the ten mechanically verifiable
claims reproduced all ten, including two that indict this release's own
notes (see below).

They are not 41 independent oversights. Every one is a hand-maintained
**closed-set enumeration** — how many rules, how many slash commands, how many
Bash patterns are denied, which `lib/` modules exist, how many tests run — with
nothing deriving it back from the code. The counts were last correct at v0.24.0
and drifted through three releases unchallenged. This repo already solved that
problem once, for versions: v0.22.1 shipped a stale manifest and the fix was a
*gate*, not a corrected number. Documentation had no gate.

- **New: [`tests/test_doc_sync.py`](tests/test_doc_sync.py)** — derives every
  pinned fact from the code at runtime (rule files on disk, command files,
  `bash_guard.STATIC_PATTERNS`, `hooks/scripts/lib/*.py`, `hooks.json`,
  the checklist's own section headers, `unittest discover`). Claim sites are a
  **closed set**: a registered regex that matches nothing fails as "stale
  registration", so rewording a pinned sentence breaks the build instead of
  escaping the gate. It also pins the Bash deny inventory across all six
  surfaces that present it as complete, the structure trees' module
  inventories, and that every repo-relative markdown link resolves.
- **`i18n_check.py` gained enforcement-token parity** — every backtick code
  span on a line that states a `DENY` must appear in each translation. File-set
  and header-structure parity were both green while `prompts/zh/` listed four
  of the seven patterns `bash_guard` denies: a zh session was handed a strictly
  smaller deny set than an en session, on every single turn. Scoped to DENY
  lines deliberately — comparing all code spans produces 24 false positives
  across `rules/`.
- The gate immediately found a defect the 57-agent audit missed:
  `prompts/user-prompt.md`, the **English skeleton**, also omitted
  `--no-gpg-sign`.
- **Two corrections to this release's own notes**, both first-party verified,
  both instances of root cause γ above: "all seven test modules were
  self-locked" was wrong in both halves (**six**, of **ten**), and the rationale
  hatch was described as "previously English-only" when the pre-fix token tuple
  already contained `原因` and `正当` — only the *noun* forms were listed.
- Also corrected: rule 10 / 11 documented an escape hatch two releases out of
  date (it has been comment-only since v0.25.1 and lexically decided since
  v0.26.0); `docs/EDICTS.md` documented the pre-v0.25 bash_guard ordering, which
  is observably different; `docs/ARCHITECTURE.md` still asserted the phantom
  read-record reasoning that v0.25 disproved, called `bash_guard` stateless, and
  counted three hook scripts where four are registered; the checklist's F5
  closed-set omitted `@ts-expect-error`, so an agent could tick every box and
  still be denied; and `systematic-debug` cited "规则 02.6" for a principle that
  lives in rule 07.

### Second audit round — 16 parallel read-only reviews

A further sixteen independent read-only reviews were run over the whole
codebase, each with a different lens. Fifteen reported; the sync-gate lens
returned nothing and **was not run** — that gap is recorded rather than
papered over. Most of what came back was already-documented limitations or
inherent to a regex hook; what follows is what was independently confirmed
against the real code and fixed at the root:

- **`lib/srclex`** — a bare triple-quoted *expression* was treated as a
  docstring, so `"""because …"""` dropped anywhere silenced the secret
  detector; docstring status is now decided by POSITION (module/class/
  function-leading), which also makes `r"""…"""` work. A lone CR no longer
  lets a `#` comment run to end-of-file, and POSIX single quotes no longer
  honour backslash escapes.
- **`lib/mdctx` + layer (h)** — `_tldr_items` did not apply the `countable`
  test to CONTINUATION lines, so a blockquoted continuation was measured as
  the agent's own tldr: the two-halves-disagree bug this module was created
  to end, recurring one level down. Fence geometry corrected for tab
  indentation (a tab is 4 columns), list-nested fences, and backticks in a
  backtick fence's info string. Lazy blockquote continuation is
  deliberately NOT implemented — see the note in `_is_quoted`.
- **Done-claim semantics** — `far from done` / `hardly done` read as
  completions and BLOCKED honest failure reports; a Chinese double negative
  anywhere in the clause disabled a nearer real negation; Chinese
  connectives (`所以`, `但是`, …) are now clause boundaries, so
  `没有遗漏…所以…已经完成了` is correctly a claim; `Work complete` matched
  nothing and therefore skipped all nine layers.
- **Layer (g)** — `我确认 v0.23 修改了 X` parsed as a self-claim because a
  version could sit in the 12-character subject gap.
- **`lib/state`** — a `JSONDecodeError` reset the session to an empty
  record and the next mutator saved it back: total, SILENT amnesia. It now
  retries, then quarantines the file and says so. `save()` and `add_read()`
  return whether the write landed, so `register_read` can no longer print
  `ok` for a registration that evaporated.
- **`bash_guard`** — the six static patterns still matched raw text while
  force-push had a parse model. They now match parsed argv: `chmod -v 777`,
  `git -C . rebase --skip`, `rm -rf -- "$HOME"` and quoted flags are caught;
  `echo git commit --no-verify` no longer denies.
- **`register_read`** — a registration inside a compound command
  (`false && …`) earned read credit for something the shell never runs;
  only a single unconditional invocation counts now. `python -cpass foo.py`
  and `python --version foo.py` no longer register.
- **`manage_edicts`** — regex fields moved from triple-quoted literals to
  basic strings (the literal form silently rewrote any pattern containing
  `'''`), DEL is escaped, and the result is parsed before it is committed,
  so one bad field can no longer disable every edict while the CLI reports
  success.
- **`i18n_check`** — enforcement parity only recognised the literal `DENY`,
  leaving rule 12's entire `BLOCK` contract unchecked. It now covers
  BLOCK/拒绝/拦截 and requires only machine-shaped tokens, after a first cut
  demanded translators reproduce English prose examples.
- **The doc gate's own holes** — the current release's narrative was
  exempted as "history" while it describes the release being shipped, which
  is how five stale `378 → 474` statements sat next to a green gate;
  inventories were one-way (a deleted module could linger in the tree);
  `hooks.json` was regex-scraped into a subset check an empty set satisfied;
  and `rules/09` was missing from the Bash-deny surfaces, which is why its
  row still named four patterns after every other surface was fixed.
- **Its docstring overstated itself** — "closed set", "every value derived
  at runtime" and "the numbers were last correct at v0.24.0" were all false
  (v0.24's README already said "9-rule"). Corrected in place, with the
  uncovered areas enumerated.

Tests **474 → 543**.

**Verification honesty:** unlike the first round, these assertions were NOT
replayed against a pre-fix tree — both rounds are uncommitted, so no such
tree exists to replay against. The evidence is per-fix runtime probes on the
real code plus the reviewers' own reproductions; two regressions were caught
by the existing suite during the work (`rm -rf /usr/local/share`, and this
release's new test module self-locking twice).

## [0.25.1] — 2026-08-10

**Third-round audit: 94 review findings → 21 first-party reproductions →
SIX root-cause fixes. Zero new features.**

Process: three parallel read-only reviews of the `83e5487` tree, split by
subsystem (read_guard/register_read · Stop layers + sync_gate + i18n ·
bash_guard + state + config IO). They returned **94 findings (29 HIGH)**.
Rather than trust that, every high-signal claim was re-run against the real
code by a first-party probe: **21 reproduced**. Those 21 are not 21 bugs —
they collapse into **six root causes**, and are fixed as six systematic
changes, per rule 09's own "systematic ≫ patching". Red-first evidence:
the new assertions replayed on the pre-fix tree produce **37 failures + 4
errors**; the fixed tree is **378/378 green** (350 → 378).

### Root cause 1 — the detectors described a *string*, not a *concept*

Nine of the 21 were one spelling away from the pattern:

- **CRLF defeated all five single-line rule-09 markers.** They anchored on
  `[ \t]*(?:\n|$)`, which cannot match `\r\n` — so on this plugin's own
  primary platform every one of them was silently off for a CRLF file.
- **Any trailing text made a marker invisible.** `// @ts-ignore` followed by
  a bare deferral keyword matched *nothing*, so it was allowed without the
  rationale check ever running — while the bare form was denied. The same
  hole made the deny message's own "acceptable form" examples pass for the
  wrong reason, and made `test_ts_ignore_with_rationale_is_allowed` a
  vacuous test. The anchors are gone; trailing text now goes to
  `_inline_reason_is_substantive`, which accepts an explanation and rejects
  a deferral.
- **`time.sleep(max(0, delay))` slipped past** — `[^)]*` stopped at the
  inner `)`.
- **Doubled backslashes bypassed rule 11.** `[\\/]` matched only a raw
  single-separator spelling; in real Python / JSON / JS source the
  separator is doubled (`"C:\\Users\\bob"`), which is how a user-home path
  actually appears in committed code. The detector caught the rare spelling
  and waved through the normal one.
- **The rule-10 type-annotation relief leaked.** v0.24 added a skip for
  `password: "SecretStr"` (a forward reference, not a credential) but
  applied it to `=` as well, so a plain-alphabetic credential assigned with
  `=` was allowed. The relief is now scoped to the `:` spelling it was
  written for.
- **Four force-push shapes were missed** — `git -C repo push --force`
  (a global option between `git` and `push` hid the whole segment),
  quoted `"--force"`, `git push origin +main:main` (git's own spelling of
  "force this ref"), and `git push --mirror`.
- **`except Exception: pass` one-liners were invisible**, as was any
  `try/except/pass` nested inside another `try` (a single pending indent
  cannot represent nesting; it is now a stack), and only the *first* hit
  in an edit was ever inspected.

Additionally: provider-issued token shapes (`ghp_…`, `xox…`, `AIza…`) are
now denied on sight, chosen over widening the keyword list with a bare
`token` — the value shape is self-identifying, whereas `token = "…"` would
fire on ordinary lexer code. Placeholder filtering now also covers
standalone literals, so an obviously fake `postgres://user:redacted@host/db`
stops being denied while the identical value behind `password = …` was not.

### Root cause 2 — parsed config values used without a type check

`severity = ["must"]` and `mode = []` are **valid TOML**, and
`value not in SET` raises `TypeError: unhashable type: 'list'`. That escaped
`edicts.load()` and `sync_gate.load()` — both documented as never raising —
and unwound into the outer failing-open handlers: rules 04 + 08 switched
**off for the entire session**, and Stop layer (i) went down together with
the turn-boundary `clear_edit_flag` on the same path. This is the v0.25
`UnicodeDecodeError` finding recurring through a different door: that fix
hardened *how the file is read*, this one hardens *what the parsed values
may be*. Session state is now shape-normalised too — a top-level `[]` used
to raise inside `has_read` (failing open → an unread file became editable)
and a top-level `{}` raised inside `add_read` (a successful Read went
unrecorded → the next edit was falsely denied).

`manage_edicts` also still called raw `tomllib.load`: v0.25 created
`lib/tomlio.py` precisely so a BOM or a non-UTF-8 save could not disable
enforcement, wired the two hook-side loaders to it, and never swept the
tree — so the same file the hooks read fine still crashed
`edict list / add / remove`. That is the repo-wide-sync omission rule 12
exists to catch, committed by the release that introduced the shared module.

### Root cause 3 — the rationale escape hatch was wrong in both directions

`_has_rationale` lowercased the entire raw window, so a token anywhere in
executable code satisfied it (`reason = compute()` next to a bare marker);
rules 10 + 11 leaked the same way through an adjacent identifier or a secret
*value* containing `sample`. Meanwhile the hatch was **unreachable** in its
most natural spelling, because a comment line between `except:` and `pass`
moved the swallow out of the scanner's sight — v0.25 fixed the same-line
variant and shipped a regression test that passed for the wrong reason.
Rationale is now read from comment text only, comment lines no longer mask
the swallow, and every "a rationale allows this" test carries a **twin** that
strips the rationale and asserts DENY.

Prose docs (`.md` / `.rst` / …) keep their pre-v0.25.1 behaviour exactly:
only the bare marker form counts there. This repo's own docs mention the
marker spellings 54 times; the permissive form would have flagged them all.

### Root cause 4 — presence checks standing in for meaning

- **`_has_done_claim` gates all nine Stop layers**, and `已完成` /
  `Implemented the fix` / `Finished the refactor` / `the migration is
  complete` were not in `DONE_PATTERNS`. A completion phrased that way did
  not skip one check — stop_guard returned immediately and cleared the edit
  flag on the way out.
- **Negated text counted as a claim.** `Not done; tests failed.` and
  `This is not fixed` were read as completions, so an honest report of
  failure could be blocked; `all set` as an unbounded substring even matched
  inside "Not all settings are loaded".
- **An empty `tldr:` satisfied layer (h).** The presence test looked for the
  keyword anywhere, the length test then measured nothing, and the emptiest
  possible summary — including a blockquoted `> tldr:` quoting someone
  else — passed both halves.
- **Windows transcripts were not evidence.** `PS C:\repo>` and `C:\repo>`
  matched none of the POSIX-only prompt patterns, so a Windows user pasting
  a genuine command transcript was told they had produced none.

### Root cause 5 — state lifecycle

`_maybe_auto_gc` passed `exclude_session=None`, reasoning that the live
session's file is too new to cross the threshold. True for a session that
just started; **false for a resumed one**, whose reads, baselines, rolling
counters and sync acknowledgements auto-GC would delete out from under it.
The id now comes from the hook payload `main()` already drains. Separately,
a GC marker that *parses* but carries a non-numeric `ts` raised `TypeError`
outside the guarding `try`, escaping `_maybe_auto_gc` — which `main()` calls
**before** `emit()`, so one mistyped marker file silently suppressed the
entire SessionStart injection, edicts included.

### Root cause 6 — the grace-window sync ack was unscoped

A recovery turn is still an editing turn. If it touched files violating a
*different* group, that group became pending after the block, was never
presented, and was never answered — yet the ack silenced it for the rest of
the session. The layer-(i) block now records which groups it presented
(`last_blocked_groups`), and the ack intersects with that set.

### Deliberately not changed

- **Bash writes still bypass the edit-tracking signal** (all three reviews
  reported it). Two different things wear one hat here. "An agent uses
  `python -c` to dodge read_guard" is *adversarial evasion*, which this
  plugin's threat model — a lazy-but-cooperative agent, soft injection plus
  a physical backstop, failing-open throughout — does not claim to stop. The
  half that *is* worth fixing is ordinary use: a `sed` / codegen / formatter
  run genuinely edits files, and those edits do not reach Stop layers
  (e)/(f)/(g)/(i). That needs its own design round and false-positive
  tuning, not a corner of a defect release.
- **Marker polarity** (`tldr: I did not perform a sync-check` satisfies the
  markers) and **grace-window scoping to a recovery chain** are contract
  changes about enforcement strictness, not defects. Recorded for the user.
- The **layer-(i) grace ack stays scoped to layer-(i) recoveries** —
  reaffirmed by the user on 2026-08-10 after v0.25 surfaced it.

Tests **350 → 378**.

---

## [0.25.0] — 2026-08-10

**Second-round audit release: 12 confirmed defect fixes, zero new features.**

Process: a full own-architecture re-read of every hook script → a five-lens
parallel read-only model review of the v0.24 tree (state/concurrency,
Stop layers, read_guard detectors, bash/edicts bypass, periphery), each
finding then put through an independent adversarial verification pass →
**every surviving finding re-reproduced by my own runtime probe before any
code changed** → red-first regressions → fixes → 346/346 green. Red-first
evidence is unusually strong this round: the new assertions were replayed
against a pristine v0.24.0 worktree and produced **32 failures + 1 error**
there, all green here.

The theme is **guards that could be walked around**. v0.24 audited whether
the machinery *worked*; v0.25 audited whether it could be *evaded* — and
every one of the HIGH findings is a guard that was silently not guarding.

### Fixed

- **HIGH — a successful `register_read` shielded the entire bypass catalog**
  (`bash_guard.py`). `main()` returned the moment a registration succeeded,
  so every static pattern, the force-push detector and every 圣旨 were
  skipped for the *whole* command string. Verified by probe:
  `python …/register_read.py --file F --hash H && git push --force` →
  **ALLOWED**; same for `--no-verify`, `chmod 777`, `git rebase --skip`.
  Registration and bypass-scanning are orthogonal concerns; the deny checks
  now run first and registration happens only once the command is known
  clean — so a command destined for denial also no longer mutates session
  state (the same ordering principle as v0.24's read_guard fix).
- **HIGH — any trailing comment defeated the `try/except: pass` detector**
  (`read_guard.py`). The swallow line had to be *exactly* `pass`, so
  `pass  # TODO later` was ALLOWED. Worse, this made rule 09's documented
  why-comment escape hatch **unreachable for its flagship marker**: a
  rationale comment silenced the detector by changing the string, so
  `_has_rationale` was never consulted — the existing test that claimed to
  pin that behaviour was passing vacuously. The detector now compares the
  *code* on the line.
- **HIGH — only the first `except` clause was ever inspected**
  (`read_guard.py`). The try-watch was cleared after the first clause, so
  the canonical antipattern — a narrow handler followed by a catch-all that
  swallows everything — was invisible. Subsequent clauses at the same
  indent are now checked.
- **HIGH — reading a path before it existed granted permanent blind-edit
  authorization** (`read_guard.py`). `add_read` ran unconditionally,
  justified in-code by "a phantom record of a non-existent path is harmless
  (Edit's `os.path.exists` short-circuit covers it)". That short-circuit
  only fires while the file is *still* absent: read a generated artifact
  before generating it (an everyday flow), let a build step create it, and
  the stale entry satisfied `has_read` — so an Edit *or a whole-file Write*
  landed on content the session never saw, with rule 04 off for that path
  for the rest of the session. Only existing targets are recorded now; the
  mtime baseline is still captured for missing ones, which is what layer
  (g) needs to adjudicate a later "I created X" claim.
- **HIGH — an unreadable-but-present state file became a false DENY**
  (`lib/state.py`). `load()` degrades an unreadable record to an EMPTY one,
  and for `has_read` "empty" is a positive assertion of "never read", which
  read_guard turns into a hard DENY. A transient Windows sharing violation
  — the same cause `save()` already retries against — therefore produced
  the exact false "you have not Read this file" DENY that v0.23/v0.24 were
  chasing, while stderr simultaneously announced "failing open". `has_read`
  now distinguishes "no state yet" (deny, correct) from "state unreadable"
  (allow).
- **HIGH — layer (g) blocked truthful third-party attributions in Chinese**
  (`stop_guard.py`). `_FILE_CLAIMS_EN` requires the subject `I`;
  `_FILE_CLAIMS_ZH` had no subject constraint at all, so
  `上一版修改了 lib/state.py，本次没动` was parsed as *this* agent claiming
  the edit — and since read_guard baselines every file merely READ this
  session, layer (g) could then "disprove" it and BLOCK, accusing the agent
  of lying in the very sentence where it correctly said it had not touched
  the file. This repo's primary language is Chinese and version
  attributions (`v0.23 修改了 X`) are pervasive in its own docs. The
  negation guard was independently broken for CJK: it required whitespace
  after the negator, which Chinese does not use, so `我没有修改了 X` still
  produced a claim. Both fixed (first-person anchor + a second negation
  check on the subject→verb gap, which a look-behind structurally cannot
  reach).
- **HIGH — a mis-encoded `edicts.toml` switched off read-before-edit**
  (`lib/edicts.py`). `tomllib.load()` decodes the stream itself and raises
  `UnicodeDecodeError` (a `ValueError`) that neither the `OSError` nor the
  `TOMLDecodeError` clause caught. It escaped `load()` — contradicting that
  function's own "never raises" docstring — and unwound past every
  downstream check in `read_guard._handle_pre_tool_use`, which calls it as
  the *first* statement of the Edit/Write path, into the outer failing-open
  handler. One edicts.toml saved as GBK/ANSI therefore disabled rules 04 +
  08 for the entire session. Hand-editing is explicitly blessed by
  manage_edicts' own header.
- **MED — a UTF-8 BOM silently dropped every rule** in both configs. tomllib
  does not strip it, so the first `[[table]]` became an invalid statement:
  `/cc-enforcer:edict list` reported "(edicts file is empty)" while every
  `must` rule sat unenforced. A BOM is what several standard Windows save
  paths emit.
- **MED — `sync_gate.load()` crashed on a non-UTF-8 config**, taking Stop
  layer (i) down with it — and with it the turn-boundary `clear_edit_flag`.
  Both loaders now share one hardened reader,
  [`lib/tomlio.py`](hooks/scripts/lib/tomlio.py), rather than the same
  patch applied twice (this repo keeps getting bitten by hand-copied logic
  drifting apart — read_guard's three write branches in v0.24, the fence
  tracker below).
- **MED — quoted-key secrets passed rule 10** (`read_guard.py`). The
  separator had to follow the keyword with only spaces between, so the
  key's own closing quote blocked every match in JSON and quoted-key
  YAML/TOML: `"api_key": "…"` — the most common shape a committed
  credential takes, in a fully scannable file type — was ALLOWED while the
  rarer bare-key spelling was caught.
- **MED — force-push detection was scoped to the whole command string**
  (`bash_guard.py`), giving both a false DENY and a false ALLOW:
  `rm -f build.log && git push origin main` was denied as a force push
  (the `-f` belongs to `rm`; same for `make -f`, `docker build -f`), while
  `git push -fu origin main` — a genuine force push, since git accepts
  stacked short options — never matched the whitespace-delimited token
  regex. Detection now splits on shell separators and inspects only the
  `git push` segments, looking for `f` inside single-dash option clusters.
- **MED — the read-cache escape hatch was unusable on this plugin's own
  primary platform** (`bash_guard.py`). `shlex.split(posix=True)` treats a
  backslash as an escape, so an unquoted `C:\Users\me\note.txt` came back as
  `C:Usersmenote.txt` and the registration was denied with "file does not
  exist on disk" — i.e. the documented recovery path for a false rule-04
  DENY was itself broken. It survived 21 releases because every existing
  test quotes the path, and quoting happens to survive posix splitting.
  Windows now splits in non-posix mode with quote-stripping. The
  `--file=VALUE` spelling is also understood now: argparse accepts it, this
  hand-parser did not, so the hook classified such a command as "not a
  registration", never called `add_read`, and let the stub script print
  `register_read: ok` for a registration that never happened.
- **MED — a nested code fence closed its parent** in both markdown scanners
  (`stop_guard.py`, `i18n_check.py`). Fence markers were truncated to three
  characters, so an inner ``` inside an outer ```` compared equal to the
  opener and closed it; CommonMark requires a closing fence to be at least
  as long as the opening one. Downstream, layer (h) measured `tldr:` lines
  inside *quoted fixture text* and blocked with "tldr item overlong" on
  content the reply merely quoted, and i18n_check registered phantom ATX
  headers from `#` comments in the orphaned body.
- **MED — `manage_edicts` corrupted the file when re-emitting a multi-line
  edict.** `_dump_edict` escaped only `\` and `"` before interpolating into
  a single-line TOML basic string, where a newline is illegal — and
  `_write_edicts` re-emits *every* edict on any add/remove, so one
  hand-written `text = """…"""` was enough to make the whole file
  unparseable. The CLI printed "Added edict …" over a config tomllib then
  rejected, silently unenforcing every `must` rule with only a stderr line
  no user sees. Control characters are now escaped properly.
- **MED — five of twelve hook scripts were self-locked.** `bash_guard`,
  `gc_state`, `manage_edicts` and `read_guard` carried bare `# noqa: E402`
  on their sys.path-bootstrap imports, and `inject_context` a bare
  `try: … except: pass` — so a full-file Write of any of them was DENIED by
  this plugin's own content detectors: **no agent running cc-enforcer could
  rewrite them.** v0.23 recognised the failure mode and fixed exactly one
  file (`lib/sync_gate.py`), then never swept the tree — precisely the
  repo-wide-sync omission rule 12 exists to catch. All five now carry the
  house-style adjacent rationale, and
  `TestPluginIsSelfRewritable` pins the invariant for the whole tree so a
  new script cannot reintroduce it. (Fixing the `# noqa` layer immediately
  exposed a second, previously-shadowed hit in `bash_guard`: its `rm -rf`
  detector embeds `$HOME` as *subject matter*, which rule 11 flagged — now
  carrying an `essential:` rationale, mirroring how read_guard splits its
  own home-var literal across concatenation.)
- **LOW — stale docstrings**: `stop_guard` said "eight" laziness signals
  (nine layers exist), `lib/edicts` said "built-in 11 rules" (12), and
  `state._load_shared` claimed mutators "keep calling plain `load()`" when
  v0.24 had moved them to `_load_for_mutation`.

### Notes

- **Not everything the review proposed was accepted.** The five-lens pass
  returned 33 candidate findings and its own verifiers confirmed 30 — a
  confirmation rate high enough to distrust on its face (they even
  "refuted" a defect I had already reproduced with a probe). Each was
  re-adjudicated here against the actual code; the ones fixed above are
  those I reproduced myself. Deliberately **not** changed: the layer-(i)
  grace-path ack remains scoped to layer-(i) recoveries. The report that
  this drops acknowledgements when layer (h) blocks first is correct, but
  widening it re-opens the v0.24 guardrail against a reply that merely
  *quotes* "sync-check" while recovering from an unrelated block. That is a
  contract change about enforcement strictness, not a bug fix, so it is
  recorded for the user rather than decided unilaterally.
- Tests **323 → 346**.

---

## [0.24.0] — 2026-08-10

**Health-audit release: architecture review + multi-path adversarial model
review → 10 confirmed defect fixes (3 HIGH), zero new features.**

Process (the release IS the audit): AST-based health scan (function length /
cyclomatic complexity over all production code) → version-growth review
(v0.18→v0.23 production lines +44%, accretive) → a full own-architecture
read of every hook script → multi-path parallel read-only model reviews
(gpt-5.6-sol at maximum reasoning effort, per-subsystem scopes) → every
candidate finding independently re-verified with a runtime probe before any
fix → red-first regression tests (8 red on the unfixed tree) → fixes → a
**second adversarial review round targeting the fix diff itself**, which
found 2 more real defects in/behind the fixes (both fixed + pinned) →
323/323 green. Two of the three HIGH bugs were **live-reproduced inside the
audit session itself** (the plugin denied its own auditor's Edit because
its state save had silently lost the Write record).

### Fixed

- **HIGH — Windows state saves silently lost to the plugin's own readers
  (`lib/state.py`).** The v0.23 session lock serialized writer-vs-writer
  only; every read accessor (`has_read` / `was_just_blocked` /
  `get_edited_files` / …) called `load()` lock-free. On Windows,
  `os.replace` fails with `PermissionError` while ANY process holds the
  target open (CPython's `open()` does not request `FILE_SHARE_DELETE`), so
  the hooks' own readers collided with their own writers: the mutator
  raised, the hook failed open, and the mutation vanished. Probe: 300/300
  saves lost under 8 tight-loop readers; live state dirs carried orphan
  `<sid>.json.<pid>.tmp` debris from these failures, and the audit session
  itself lost two Write records this way (symptom: a false rule-04 DENY on
  a file the session had created). Root-cause fix: read accessors now route
  through the same lock (`_load_shared`); `save()` retries the replace with
  a short backoff against non-cooperating *external* readers (antivirus /
  indexers) and unlinks its temp file if it ever gives up; `load()` retries
  once on transient `OSError` (a bare degrade returns an empty record which
  a locked mutator would save back — full session amnesia); `gc_state`
  sweeps day-old orphan `*.tmp`. Pinned by `TestReaderWriterCollision`
  (4 real-accessor reader threads + 200 sequential saves → zero loss, zero
  orphans; red pre-fix at 192/200 lost).
- **HIGH — layer-(i) sync acknowledgement lost in the one-shot grace window
  (`stop_guard.py`).** The primary real-world flow — blocked at (i), then a
  recovery reply carrying `同步核对:` — never recorded the ack: the grace
  path returned before the message was even extracted, so the same group
  re-blocked the next post-grace edit turn, breaking the v0.23 "one
  explicit answer per group per session" contract in exactly the flow it
  was built for (probe: BLOCK → marker-recovery allowed with
  `sync_acked_groups` still empty → same group BLOCK again). Fix: message
  extraction hoisted above the guard; a grace-window reply with a sync
  marker acks the pending groups (`_pending_sync_violations` /
  `_ack_pending_sync_groups`, shared with layer (i)). Pinned by
  `test_marker_in_grace_window_recovery_acks_group`.
- **HIGH — a DENIED Write-new still registered its target as read
  (`read_guard.py`).** The new-file branch called `add_read` *before* the
  content checks, so a Write denied for a patch marker / secret / path
  still granted read-before-edit authorization for content the agent never
  saw (if another process later created that file, a Write-existing sailed
  past `has_read`). `add_read` now runs only after every check passes.
- **MED — rolling-patch decide-and-record made atomic (`lib/state.py`).**
  The two-step API (`get_edit_count` then `record_small_edit`, each locked
  separately) let two parallel hooks both read count=2 and both allow —
  landing the forbidden 4th small edit. Replaced by
  `try_record_small_edit(sid, path, threshold)`: one lock acquisition
  covers decision + increment; refusal does not increment (unchanged).
- **MED — rule-10 false positive on Python forward-reference annotations
  (`read_guard.py`).** `password: "SecretStr"` was denied as a hardcoded
  credential. Pure-alpha CamelCase values (`^[A-Z][A-Za-z]*$`) are now
  skipped — a type-name shape, not a secret (real secrets carry digits /
  symbols; the deliberate-false-negative trade matches the detector
  philosophy). Digit-bearing values still deny (regression-pinned).
- **MED — rule-11 false positive on URL routes (`read_guard.py`).**
  `https://host.test/home/alice/dashboard` was denied as a POSIX user-home
  path. The pattern now rejects matches glued to a hostname segment
  (`(?<![\w.-])`); `file:///home/…` still denies (it IS a machine path).
- **MED — `.txt` blanket exemption hid dependency-manifest credential leaks
  (`read_guard.py`).** `requirements*.txt` / `constraints*.txt` are now
  scannable despite `.txt` (an `--extra-index-url https://user:pass@…` line
  is a real leak vector); plain `.txt` prose stays exempt, and `.asciidoc`
  joins the prose set (same format as the already-exempt `.adoc`).
- **MED — stale rolling counter survived delete-and-recreate
  (`read_guard.py`).** A Write creating a fresh file at a previously-edited
  path now resets the per-file small-edit counter (its first small edit
  used to be denied as "attempt #4").
- **MED — grace-path ack was not scoped to layer-(i) recoveries
  (found by the second review round, on the C1 fix itself).** The new
  grace-window acknowledgement fired on ANY sync-marker substring: a reply
  merely *quoting* "sync-check" while recovering from an unrelated block
  (e.g. layer (a)) would silently ack every pending group.
  `record_stop_block` now records the blocking layer
  (`last_blocked_layer`), and the grace-path ack requires it to be "(i)".
- **MED — transient-unreadable state could still be wiped by a locked
  mutator (found by the second review round).** `load()`'s
  retry-then-empty-record degrade meant two consecutive `OSError`s (e.g.
  an external scanner) handed a mutator an empty record, which it then
  SAVED — erasing every recorded read / edit / baseline / counter.
  Mutators now load via `_load_for_mutation`, which returns `None` on an
  unreadable-but-existing file, and skip the mutation entirely (losing one
  mutation is the strictly smaller failure). Pinned by a mock-based
  regression test asserting the state file survives byte-identical.

### Changed

- **`read_guard.py` write branches deduplicated.** The three hand-copied
  check sequences (Write-new / Write-existing / Edit) collapsed into one
  shared `_run_content_checks` pipeline (patch markers → rule 10/11 →
  edicts) — the copy-drift that produced the Write-new ordering bug is now
  structurally impossible.
- `gc_state.prune_old_sessions` reports orphan-tmp cleanup under a new
  `tmp_deleted` summary key (session-file counts unchanged — the CLI
  output and its test contract are untouched).
- Docs sync: rule 10/11 detector catalogs (+ zh mirrors) document the new
  carve-outs; `ARCHITECTURE.md` §2 concurrency and decision-tree notes
  updated; two stale references fixed (`docs/RULES.md` said rules span
  `01–11`; `ARCHITECTURE.md` still called layer (g) "a v0.9+ candidate"
  nine versions after it shipped in v0.16).

### Triaged as documented limitations (deliberately not "fixed")

- Patch markers / `try-except-pass` inside string literals are still
  scanned (a `new_string` is a file *fragment* — reliable lexical
  string-context tracking is impossible; the why-comment escape hatch
  covers fixtures).
- A PEM-header sentinel constant still denies (test-pinned design; escape
  hatch available).
- PreToolUse-time recording vs. actual tool success stays as-is (the
  v0.3.2 scope precedent; bounded cost documented in `lib/sync_gate.py`).

Tests **310 → 323** (+13: grace-window ack, non-(i) grace-ack guard,
denied-Write-new non-registration, stale-counter reset, annotation /
URL-route / requirements / plain-txt / asciidoc detector matrix,
digit-value guard, file-scheme guard, reader-writer collision,
unreadable-state mutation guard).

---

## [0.23.0] — 2026-08-07

**Rule 12 (repo-wide sync: 全库更新) + a hard TL;DR length contract.**

Two field complaints drove this minor: (1) the v0.20 `tldr` field kept growing
into paragraphs, defeating its purpose; (2) nothing — soft or hard — forced an
edit to carry the rest of the repository with it (references, downstream code,
docs, tests, translations), so stale siblings kept shipping.

### Added

- **rule 12 — repo-wide sync**
  ([`rules/12-repo-wide-sync.md`](rules/12-repo-wide-sync.md) +
  [`rules/zh/12-repo-wide-sync.md`](rules/zh/12-repo-wide-sync.md)). "Done"
  now means "every repo-wide reference of the changed content is co-updated or
  explicitly verified current", with the sweep reported via a `同步核对:` /
  `sync-check:` closing line. Two halves:
  - **Passive — sync gate (per-project 代码门禁)**. Projects register known
    co-update invariants in `.claude/cc-enforcer/sync-gate.toml`
    (`[[groups]]` with `when` / `require` globs; fnmatch on project-relative
    paths, `*` crosses separators; optional `mode = "all"` demands *every*
    require glob be matched — the lock-step semantics that catches the
    v0.22.1 "one stale sibling" shape, which any-of would wave through). New
    [`hooks/scripts/lib/sync_gate.py`](hooks/scripts/lib/sync_gate.py) loads
    and evaluates it; [`read_guard.py`](hooks/scripts/read_guard.py) records
    every ACCEPTED Edit/Write into a new per-session `edited_files` state set;
    **Stop layer (i)** blocks an edit-turn done-claim whose `when` group
    matched with its `require` side unsatisfied and no sync-acknowledgement
    marker in the reply. Marker escape is by design: "checked, no change
    needed" is a legitimate outcome that must be *said*, not silently
    assumed — and escaped groups are persisted per session
    (`sync_acked_groups`), so one explicit answer per group suffices (the
    cumulative `edited_files` set would otherwise re-block the same group on
    every post-grace edit turn for the rest of the session). `sync-gate` is
    deliberately NOT a marker — it is the config file's name, not a claim.
    No config → the layer never fires (opt-in); loader/evaluator
    failing-open. This repo dogfoods its own gate:
    [`.claude/cc-enforcer/sync-gate.toml`](.claude/cc-enforcer/sync-gate.toml)
    (rules→prompts/docs/checklist, hooks→tests, plugin.json→marketplace+CHANGELOG
    with `mode = "all"`).
  - **Active — `repo-refresh` skill**
    ([`skills/repo-refresh/SKILL.md`](skills/repo-refresh/SKILL.md)),
    auto-invoked on "全库更新 / stale scan / audit the repo" language: a
    systematic whole-repo sweep (docs **and** code) across five defect
    categories — stale (陈旧) / outdated (过时) / redundant (冗余) / wrong
    (错误) / drifted (漂移) — every finding with `file:line` evidence,
    deletions gated on user confirmation, closing with a nudge to register
    recurring pairs as sync-gate groups.
- **TL;DR length contract (layer (h) part 2)**. Each `tldr` item must be one
  sentence — cause, action, outcome — within **160 characters**
  (`TLDR_MAX_ITEM_CHARS`); several things → one item per line, each within
  the cap. Extraction is line-based and conservative, and (after an
  adversarial review pass) covers the natural forms: `tldr: value` with
  optional list / ATX-heading prefix and emphasis wrappers (`**tldr:**`),
  value-less `tldr:` followed by more-indented *or same-indent* `- ` list
  items (the legal YAML block sequence), and the colon-less `## TL;DR`
  heading followed by a paragraph. Deliberately NOT measured (fail open):
  blockquoted lines, non-YAML code fences (fixtures/examples — the canonical
  ```yaml schema fence stays measurable), and nested list detail under a
  marker line that already carried its sentence. An overlong item blocks at
  Stop layer (h) with a dedicated `overlong` table note + recovery
  (`_RECOVERY_H_LONG`).
- Docs/prompts fan-out: rule tables + trigger rows + closing-schema length
  note in all four injected prompts (en + zh), checklist section **H
  (全库同步)** + item **G4 (tldr length)**, `docs/RULES.md`,
  `rules/00-index.md` (+ zh), `docs/ARCHITECTURE.md` §2/§5/§8, `CLAUDE.md`
  §2.14 / §3 / §6.

### Fixed

- **Edit-gated Stop layers had NEVER fired in production (pre-existing since
  v0.11, HIGH — found by a live-state E2E audit).** Production hook payloads
  carry no `turn_count`: a real session with 27 edits recorded in
  `edited_files` had no `last_edit_turn` key at all, proving every
  `record_edit_turn` stamp had silently no-op'd — so layers (e)/(f)/(g)/(i)
  only ever ran inside the test suite (which always passes a turn_count),
  and the one-shot grace window was equally vacuous
  (`was_just_blocked(sid, None)` can never match). Root-cause fix:
  `record_edit_turn` now unconditionally sets an `edited_since_last_stop`
  flag (`did_edit_this_turn` honors flag OR exact turn match — existing
  tests unbroken); stop_guard synthesizes a monotonic turn number from a
  per-session `stop_counter` when the payload lacks one (Stop fires once
  per turn, so the counter IS a turn number and the [last+1, last+3] grace
  arithmetic is restored); every ALLOWED Stop clears the flag (turn
  boundary), blocked Stops keep it (the recovery reply is the same logical
  turn). A production-shape E2E harness (no turn_count, transcript-only
  Stop messages, full Read→Edit→Stop lifecycle chains, 11 scenarios) went
  red-then-green and is pinned as `TestProductionShapePayloads`.
- **Session-state lost-update race (pre-existing, HIGH; blast radius widened
  by this release).** Every hook invocation is a separate OS process and
  Claude Code fires parallel tool calls as concurrent hook subprocesses
  sharing one session JSON; the unlocked load→mutate→save cycle lost
  measured **2-3 of 10** recorded paths per 10-way-parallel round. Visible
  symptom: a false rule-04 DENY ("file not Read this session") immediately
  after the file WAS read — reproduced live during this release's own
  development; since v0.23 a lost `edited_files` entry could also corrupt
  the layer-(i) verdict in either direction. Root-cause fix in
  [`lib/state.py`](hooks/scripts/lib/state.py): every mutator now holds a
  per-session cross-process file lock (`msvcrt.locking` / `fcntl.flock` on a
  sibling `<sid>.json.lock`; acquisition failure degrades failing-open with
  a stderr diagnostic) and `save()` writes atomically (unique temp file +
  `os.replace`, so a reader can never see torn JSON that load() would
  silently "repair" into amnesia). After the fix: 5 × 10-parallel rounds,
  **0 lost**; pinned by `TestConcurrentStateRecording` (12-way).
- Full-debug probe round: `## TL;DR:` (value-less heading marker WITH a
  colon) was not measured (silent false negative — now falls through to
  paragraph collection); a `~~~` line inside a ``` fence mis-toggled the
  fence state (false-positive block on the quoted fixture — fences now
  close only on their own opening marker, same contract as `i18n_check`);
  a `./`-prefixed sync-gate glob could never match a project-relative path,
  leaving a `require` side permanently unsatisfiable (loader now
  normalizes); `docs/EDICTS.md` + `commands/edict.md` + the edicts.py
  injection titles still said "11 rules", and the EDICTS.md language table
  still described the pre-v0.21 default-Chinese mapping (both brought
  current).

### Verification

Red-before-green on the version gate (marketplace ×2 + README badge +
CHANGELOG heading all named at `0.22.2` after the plugin.json bump); an
injection probe proved the new markers actually reach
`hookSpecificOutput.additionalContext` (11/11 needles); a pre-release
adversarial review (12 findings, each reproduced by executing the shipped
code) drove the extraction-form matrix, the session acknowledgement, the
`mode = "all"` semantics, and the marker tightening above; a full-debug
round (race probe 10-parallel × 5, edge-probe matrix 7 cases, repo-wide
staleness grep) drove the Fixed section above and re-converged at 0 losses
and 7/7 probes; a live-state + production-shape E2E round (11 scenarios)
exposed and fixed the dormant edit-gated layers. Full suite **253 → 310**
green + i18n gate green; new tests: `TestProductionShapePayloads`,
`TestTldrLengthLayerH` (incl. form matrix + heading-colon + mixed-fence),
`TestSyncGateLayerI` (incl. ack-stickiness, mode=all, filename-non-escape
regressions), `TestEditedFilesRecording`, `TestConcurrentStateRecording`,
`tests/test_sync_gate.py` unit coverage (incl. `./`-glob normalization),
plus (i)-row status-table contract rows.

---

## [0.22.2] — 2026-08-05

**v0.22.1 shipped broken, and its own new rule is what should have caught it.**

`plugin.json` was bumped to `0.22.1`. `.claude-plugin/marketplace.json` — the file
the Claude Code plugin installer reads — was not, in **either** of its two version
fields. So the installed plugin reported `0.22.0`, and the release was invisible on
the one surface a user looks at. The 248-test suite was green, CI was green, the tag
was pushed. Nothing was wrong with any of that evidence; it simply never opened those
two files. That is exactly the corollary rule 06 Check 2b had just been written to
name — **scope of evidence ≠ scope of claim** — committed by the release that
introduced it.

Second, separate defect found the same way: **a git tag is not a release**. The
`v0.22.1` tag was pushed to the remote, but no GitHub Release object was created, so
`gh release list` still showed `v0.22.0` as `Latest`. "Released" had been treated as
"tagged + pushed".

### Added

- **Version-drift gate** ([`tests/test_version_sync.py`](tests/test_version_sync.py),
  5 checks). `.claude-plugin/plugin.json` is the single version authority; everything
  else is compared **to it**, never site-to-site (a pair can drift together).
  Pinned: both manifest version fields, the README shields badge, and the newest
  *released* `## [X]` heading in this file. Deliberately **not** pinned: prose. The
  README's "New in vX.Y.Z" sections and the changelog bodies are history and must be
  free to name old versions.
- **Closed-set guard on the manifest sites** — the direct application of the
  closed-set discipline added to rule 09 in v0.22.1. The gate does not check a
  hand-listed pair of paths; it walks both manifests recursively for *every*
  `"version"` key and asserts the discovered JSON-pointer set equals the registered
  set (`EXPECTED_VERSION_POINTERS`). A version field added to a manifest later fails
  the test until it is registered — with a checklist of two paths, that new field
  would have escaped silently, which is the same shape as the original bug.
- **Release checklist** in [`CLAUDE.md`](CLAUDE.md) §4.1, ending at
  `gh release create` rather than `git push --tags`, with the version-drift gate as
  its first step.

### Fixed

- `.claude-plugin/marketplace.json`: `metadata.version` and `plugins[0].version`
  `0.22.0` → `0.22.2`, and the storefront `description` (which had also stopped at
  the v0.22.0 feature set) brought current through v0.22.2.
- Backfilled the missing GitHub Release for `v0.22.1`, so the releases page stops
  claiming `v0.22.0` is the newest tag with a release.

### Verification

Red-before-green, on the unfixed tree:

```
$ python -m unittest discover -s tests -p "test_version_sync.py" -v
FAIL: test_every_manifest_version_matches_plugin_json
AssertionError: version drift: plugin.json says 0.22.1, but
  {'.claude-plugin/marketplace.json/metadata/version': '0.22.0',
   '.claude-plugin/marketplace.json/plugins/0/version': '0.22.0'}
```

The gate names both drifted pointers by JSON pointer, which is the evidence that it
would have blocked the v0.22.1 release.

---

## [0.22.1] — 2026-08-05

**Two rules sharpened from real field failures. No new detector, no new Stop layer — this is why it is a patch, not a minor.**

Both additions come from one large refactor session where the existing rules were
followed and *still* let two defects through. They are written as rule text +
injection rows because the failure mode is a reasoning shortcut, not a syntactic
pattern a hook can match.

### Added

- **rule 06 → Check 2b — "aggregate-equal is not unchanged"**
  ([`rules/06-verify-convergence.md`](rules/06-verify-convergence.md) +
  [`rules/zh/06-verify-convergence.md`](rules/zh/06-verify-convergence.md)).
  A scalar summary holding steady is not evidence that nothing moved. The
  comparison must be over the **item set** — category names, test IDs, the
  identity of each failing assertion, per-file hashes — never over a count.
  Field evidence: a validator printed `Total issues: 754` both before and after a
  ~9,500-substitution refactor, byte-identical, while a per-category diff showed
  one category had flipped `OK …: INFO:1` → `X …: CRITICAL:1`. A totals-only
  comparison would have shipped that CRITICAL as "no change".
  The same check carries the corollary **scope of evidence ≠ scope of claim**: a
  gate that validates part of an artifact says nothing about the rest, so the
  ungated remainder must be hand-audited. Field evidence: a plan-replacement gate
  guarding a `steps` list passed cleanly while two entries of the ungated
  `success_criteria` list were silently dropped.
- **rule 09 → bulk mechanical edits (rename / codemod / sed)**
  ([`rules/09-systematic-modification.md`](rules/09-systematic-modification.md) +
  [`rules/zh/09-systematic-modification.md`](rules/zh/09-systematic-modification.md)).
  Six-step discipline: survey what actually surrounds every occurrence *before*
  writing the rule; rewrite only allowlisted forms; emit a **refusal report** of
  everything declined; reconcile `total = rewritten + skipped + refused`; expect
  shapes the pattern is structurally blind to (the token inside a regex
  alternation, as a standalone argument, and the symbol named after it); and
  **never rewrite a path that addresses history** (`git show <fixed-rev>:<path>`
  resolves against a tree where the old layout is still correct).
  Field evidence: in one directory rename a blind sed would have corrupted an API
  version in a URL, a DB table version, a schema range, a math variable, a
  function parameter and a report id.
- **rule 09 → closed-set guards**: when an invariant is specified as "only these
  names are legal", enumerate the legal set and reject everything else. A
  blacklist of stray shapes lets the next shape through — observed on a gate's
  own first live run, where two non-dot-prefixed stray directories walked past a
  dot-prefix blacklist.

### Changed

- Both per-turn and session-start injections carry the new material:
  three new rows in [`prompts/user-prompt.md`](prompts/user-prompt.md) (+ zh
  mirror), and the rule 06 / rule 09 one-liners in
  [`prompts/session-start.md`](prompts/session-start.md) (+ zh mirror) now name
  Check 2b and the bulk-edit discipline.
- rule 06's termination condition gains item 2b; rule 09's "after modification"
  step now explicitly routes through Check 2b, since a bulk edit is precisely the
  case where totals stay equal while composition shifts.

### Verified

- `python hooks/scripts/i18n_check.py` → `all translations in sync with the
  English skeleton` (exit 0) — the en/zh header structures stay aligned after the
  new `###` subsections.
- `python -m unittest discover -s tests -q` → `Ran 248 tests … OK`.

---

## [0.22.0] — 2026-07-11

**Two new write-time content detectors: rule 10 (no non-essential hardcoding) + rule 11 (no non-essential path dependency).**

Both extend the rule-09 `PreToolUse(Edit|Write)` content-detector mechanism: when an
Edit or Write targets a *code* file, the `new_string` / `content` is scanned and an
unjustified match is physically DENied before it lands. "Non-essential" is
operationalized by the shared **adjacent why-comment escape hatch** — a flagged
literal or path accompanied by a rationale comment (`because` / `原因` / `essential`
/ `example` / `fixture` / `placeholder` / `占位` / …) is allowed; without one it is
denied. Neither rule adds a Stop layer — content detectors are PreToolUse-only,
mirroring the rule-09 patch-marker precedent (the noqa / ts-ignore sibling has no
Stop twin either).

### Added

- **rule 10 — no non-essential hardcoding** ([`rules/10-no-hardcoding.md`](rules/10-no-hardcoding.md)
  + [`rules/zh/10-no-hardcoding.md`](rules/zh/10-no-hardcoding.md)). `_find_hardcoded_secret`
  in [`hooks/scripts/read_guard.py`](hooks/scripts/read_guard.py) flags: a secret-named
  identifier (`password` / `secret` / `api_key` / `access_key` / `auth_token` /
  `client_secret` / `private_key` / `bearer`) assigned a quoted literal ≥ 8 chars
  (obvious placeholders and env-reads excluded); a PEM private-key header; an AWS
  access-key literal (`AKIA…`); and credentials embedded in a connection URL
  (`://user:pass@`).
- **rule 11 — no non-essential path dependency** ([`rules/11-no-path-dependency.md`](rules/11-no-path-dependency.md)
  + [`rules/zh/11-no-path-dependency.md`](rules/zh/11-no-path-dependency.md)).
  `_find_path_dependency` flags machine-specific user-home absolute paths (Windows
  `C:\Users\…`, POSIX `/home/…` and `/Users/…`), shell home variables (`$HOME`,
  `%USERPROFILE%`), and quoted `~/…` tilde paths.
- Prose-doc (`.md` / `.markdown` / `.rst` / `.txt` / `.adoc`) and lockfile targets are
  exempt from both detectors (`_is_scannable_target`), so illustrative example paths
  and placeholder values in documentation, and machine-generated lockfiles, do not
  trip the guard. The rule-09 patch-marker detector keeps its all-files behavior.

### Changed

- Rule count 9 → **11** across the injected prompts
  ([`prompts/session-start.md`](prompts/session-start.md),
  [`prompts/user-prompt.md`](prompts/user-prompt.md), and their `zh/` translations),
  [`rules/00-index.md`](rules/00-index.md), [`docs/RULES.md`](docs/RULES.md),
  [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md), [`README.md`](README.md), and
  [`CLAUDE.md`](CLAUDE.md) (new §2.12 / §2.13). The numbering range is now `01–11`;
  new rules start at 12.

### Tests

- **229 → 248.** Added `TestHardcodedSecretEdit` + `TestPathDependencyEdit` (19 tests)
  in [`tests/test_read_guard.py`](tests/test_read_guard.py): DENY on a hardcoded
  secret / path dependency, allow with an adjacent why-comment, allow clean code,
  new-file `Write` coverage, and the prose-doc exemption. Offending fixtures are built
  by runtime string concatenation so this test file's own source never self-trips.
  [`tests/test_i18n_sync.py`](tests/test_i18n_sync.py) auto-enforces
  `rules/zh/10-*.md` + `11-*.md` structural parity against the English skeleton.

---

## [0.21.1] — 2026-07-11

**Hotfix: Stop layer (g) silently no-op'd on the GitHub Windows runner (pre-existing CI red).**

Layer (g) (file-claim verification, v0.16) extracts claimed paths from the
agent's done-claim with `_PATH_TOKEN`. Its character class was `[\w./\\-]`,
which **excludes the tilde `~`**. The GitHub `windows-latest` runner's `$TEMP`
is a DOS 8.3 short path whose user segment carries a tilde
(`C:\Users\RUNNER~1\AppData\Local\Temp\...`). The regex broke at the `~`, the
whole path token failed to match, and `_extract_file_claims` returned `[]` for
**every** path on the runner — so layer (g) silently did nothing there, while
working normally on tilde-free developer machines (e.g. `C:\Users\skyma\...`).

Effect: the three `TestRule10FileClaimVerification` "must block" cases
(edit / create / Chinese) went red **only on windows-latest** from v0.16
onward, passing on local Windows and on ubuntu CI. This was **not** introduced
by v0.21 (which only changed a one-line comment in `stop_guard.py`); it was
latent since v0.16.

Severity is low for real users: layer (g) is deliberately conservative (it is
designed never to false-*block*), so the failure mode is a false-*negative*
(a dishonest file-claim about a tilde-path file could slip through) — the safe
direction. The main cost was the misleading red CI badge.

### Fixed

- **Root cause (one char):** `_PATH_TOKEN` character class `[\w./\\-]` →
  `[\w./\\~-]` in [`hooks/scripts/stop_guard.py`](hooks/scripts/stop_guard.py).
  The trailing extension anchor (`\.[A-Za-z]...`) is unchanged, so `~` cannot
  make casual prose (e.g. "~5 seconds") match as a file path. A `why` comment
  documenting the 8.3-short-name rationale is placed adjacent to the regex.

### Tests

- **225 → 229.** Added `TestTildePathClaimRegression` (4 tests) in
  [`tests/test_stop_guard.py`](tests/test_stop_guard.py). It calls
  `_extract_file_claims` directly with a hardcoded tilde path, so the
  regression reproduces **deterministically on any machine** (RED on the old
  regex, GREEN on the new), independent of what the local `$TEMP` happens to
  be. Includes a non-tilde control to guard against over-narrowing.

---

## [0.21.0] — 2026-07-11

**i18n architecture inverted to English-skeleton + hard, CI-enforced language
version control.**

Until now the plugin was **Chinese-canonical**: `rules/*.md` + `prompts/*.md`
were the source of truth, `rules/en/` + `prompts/en/` were best-effort mirrors,
the runtime default was `zh`, and ~6 docs declared "on drift, Chinese wins".
v0.21 flips this to **English is the skeleton (source-of-truth) language, any
language is a translation, and drift is blocked by CI** — while keeping the
enforcement machinery and every human doc's prose language exactly as they were.

### Changed — English is now the skeleton

- **Directory layout inverted** (via `git mv`, structure-preserving):
  - `rules/en/{00..09}-*.md` → `rules/*.md` (English skeleton, at the root).
  - `rules/*.md` → `rules/zh/*.md` (中文 translation).
  - `prompts/en/{session-start,user-prompt}.md` → `prompts/*.md` (English skeleton).
  - `prompts/*.md` → `prompts/zh/*.md` (中文 translation).
  - Removed the now-empty `rules/en/` + `prompts/en/`.
- **Runtime default flipped to English.** `DEFAULT_LANG = "en"` added to
  [`hooks/scripts/inject_context.py`](hooks/scripts/inject_context.py) and
  [`hooks/scripts/lib/edicts.py`](hooks/scripts/lib/edicts.py). Unset /
  `CC_ENSLAVER_LANG=en` → read the root English skeleton;
  `CC_ENSLAVER_LANG=<code>` → read `<dir>/<code>/<file>`, **falling back to the
  root English skeleton** (with a stderr note) when that translation is missing.
  The old hardcoded `{zh,en}` gate is gone — **any** language code passes through.
- **Edict UI chrome (`_INJECT_STRINGS` / `_DENY_REASON_TEMPLATES`)** now defaults
  to `en` and `.get(lang, en)` for unknown codes; edict *text* stays free-form
  (any language). On drift between skeleton and translation, **English wins**.

### Added — language version control (the hard deliverable)

- **[`hooks/scripts/i18n_check.py`](hooks/scripts/i18n_check.py)** —
  `check_sync() -> list[Drift]` + `main()` CLI. For each translation subdir under
  `rules/` and `prompts/` it verifies (1) **file-set parity** vs the root skeleton
  (missing / orphan files) and (2) **ATX-header level-sequence parity** per shared
  file (structure, not translated text; fenced code blocks skipped). Exits non-zero
  on any drift and names it.
- **[`tests/test_i18n_sync.py`](tests/test_i18n_sync.py)** (7 tests) —
  `assertEqual(check_sync(), [])`, auto-discovered by `unittest discover` → runs in
  the existing GitHub Actions matrix (ubuntu + windows, Python 3.13) on every
  push/PR. This makes "语言版本控制" a *hard action*, not soft docs (rule 07).
- **[`commands/i18n.md`](commands/i18n.md)** — `/cc-enforcer:i18n` runs the check.
- **[`docs/I18N.md`](docs/I18N.md)** — manifest: declares English as the skeleton,
  the translatable surface, how to add a language (`rules/<code>/` +
  `prompts/<code>/` [+ an optional UI-string block]), the sync contract, and the
  on-drift winner.

### Tests

- Inverted the default-mode assertions in
  [`tests/test_inject_context.py`](tests/test_inject_context.py) and
  [`tests/test_edicts.py`](tests/test_edicts.py) from Chinese needles to the
  English skeleton, and **re-homed** (not deleted) the Chinese assertions onto
  `CC_ENSLAVER_LANG=zh` counterpart tests — coverage preserved on both languages.
- Full suite **216 → 225** (+7 `test_i18n_sync`, +2 net from inject/edict
  bilingual restructure). Guard scripts (`stop_guard` / `read_guard` /
  `bash_guard`) and their **bilingual** marker lists were left untouched, so
  physical enforcement is unaffected by the flip.

### Docs

- Reconciled the *structural* facts (source-of-truth designation, `rules/en/` ↔
  `rules/` ↔ `rules/zh/` paths, on-drift winner) across
  [`README.md`](README.md), [`CLAUDE.md`](CLAUDE.md),
  [`docs/RULES.md`](docs/RULES.md), and
  [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md); the Chinese prose bodies of the
  human docs were **kept Chinese** ("content can be any language").

---

## [0.20.0] — 2026-06-07

**YAML reply schema + hard-enforced plain-language TL;DR (Stop layer (h)).**

The agent's "standard reply skeleton" was free-form markdown (5 sections
🔍✏️✅📋🚨) that drifted in shape every turn — hard for the user to scan.
v0.20 collapses it into a **fixed YAML schema** and adds a hard-enforced
one-sentence plain-language summary at the end of every done-claim reply.

### Added

- **Canonical YAML reply schema** taught in the soft-layer injection
  ([`prompts/session-start.md`](prompts/session-start.md) §3 +
  `prompts/en/session-start.md` §3 — that path was the English mirror at
  the time; v0.21 promoted English to the skeleton at `prompts/`, so the
  link is left unlinked rather than pointed at a file that no longer
  exists):
  a ```yaml `cc-enforcer:` block with fields `改前 / 改中 / 收敛 / 忠实 /
  收尾 / tldr` (English mirror: `before / edits / convergence / fidelity
  / closing / tldr`). Modification tasks use the full schema;
  non-modification done-claim replies use the minimal form
  (`收敛`/`忠实`/`tldr`).
- **Stop layer (h)** in [`hooks/scripts/stop_guard.py`](hooks/scripts/stop_guard.py):
  a done-claim reply that lacks a TL;DR marker (`tldr:` / `大白话` /
  `一句话总结` / `TL;DR`) is blocked. Unlike layers (e)/(f)/(g), (h)
  fires on **every** done-claim turn, not just edit turns — it is the
  final gate, reached only after all discipline checks pass.
- Per-block **`大白话:` line** appended to every Stop block reason
  (before the one-shot footer), so cc-enforcer's own output is symmetric
  with the layer-(h) requirement it imposes.
- New tests (full suite **203 → 216**): `TestTldrLayerH` ×8,
  `TestCanonicalYamlSchema` ×2 (zh + en schemas pass layers a–h),
  status-table (h)-row ×1, inject_context schema/tldr assertions ×2.

### Design — "field names ARE the markers" (zero detector rewrite)

The schema field names/values are exactly the substrings layers (a)-(g)
already match (`重触发` / `收敛` / `自答` / `请求覆盖` / `根因` /
`影响范围` / `方案` …), so **no detection regex changed**. Both the old
emoji-markdown form and the new YAML form pass — graceful migration. The
English schema exploits YAML plain-scalar keys allowing spaces
(`root cause:` / `request coverage:` / `no degradation:`) to hit the
space-separated English markers.

### Not done (deliberate, minimum effective change)

- The Stop **status table stays a markdown table** (already a fixed
  schema; tables beat YAML for a status matrix) — only a `大白话` line
  was added.
- TL;DR is a **closing convention (layer (h))**, not a 10th numbered
  rule — avoids the `rules/*.md` + `rules/en/` + `00-index` + docs
  fan-out a real rule requires.

### Fixed (doc drift)

- [`CLAUDE.md`](CLAUDE.md) §6 was stuck at v0.18.0 with a stale
  "未实现" list (auto-GC / rolling-patch / english-prompts /
  deep-file-claim were all already shipped) and test count 135 →
  updated to v0.20.0, 216 tests, accurate roadmap.

---

## [0.19.0] — 2026-05-28

**Edicts cwd fallback for Windows / env-var-stripped subprocesses.**

Project-level `edicts.toml` was silently invisible to hook subprocesses
and to `manage_edicts.py` whenever `CLAUDE_PROJECT_DIR` failed to
propagate — verified to occur on Windows when Claude Code's Bash tool
spawns child processes. Symptom: a user creates an edict via
`/cc-enforcer:edict add ...`, it appears in the soft-layer injection
(because `inject_context.py` had the env var), but the `PreToolUse`
hooks miss it and the user gets no `must` enforcement. Or worse: the
`add` command itself fails with "set CLAUDE_PROJECT_DIR" even though
the user is sitting in the project root.

### Added

- `_looks_like_project_root(path)` in
  [`hooks/scripts/lib/edicts.py`](hooks/scripts/lib/edicts.py): true
  when `.git` exists (directory **or** file, so worktrees/submodules
  count) or `.claude/` exists as a directory. Either marker alone is
  sufficient — a brand-new clone with no `.claude/` yet still works,
  and a `.claude/`-only workspace without git tracking also works.
- `_cwd_if_project_root()`: returns `Path.cwd()` if it has a marker,
  else `None`. Used by both the loader and the writer.
- **Loader (`edicts_path`)** new resolution order:
  1. `${CLAUDE_PROJECT_DIR}/.claude/cc-enforcer/edicts.toml`
  2. `$(cwd)/.claude/cc-enforcer/edicts.toml` — **new**, only when
     cwd has a project-root marker
  3. `${HOME}/.claude/cc-enforcer/edicts.toml` — personal global
- **Writer (`default_project_path`)** falls back to cwd under the same
  marker conditions; returns `None` only when neither env var nor cwd
  marker is available.
- **CLI (`manage_edicts.py`)** diagnostic at `_project_path()` now
  enumerates every fallback that was tried and what would fix each,
  rather than the previous "set `CLAUDE_PROJECT_DIR`" one-liner.

### Why a narrow heuristic

`_looks_like_project_root` checks two well-known markers and nothing
else. This keeps the fallback safe in `~/Downloads`, `/tmp`, or other
incidental working directories that don't carry a project marker.
The trade-off — a user with no `.git` and no `.claude/` who still
wants project-scoped edicts must `--global` or set the env var
explicitly — is accepted: silent misclassification is worse than an
actionable diagnostic.

### Tests

17 new tests in `tests/test_edicts.py`:

- `TestCwdFallback` (12): marker semantics (`.git` dir / `.git` file
  worktree / `.claude/` dir / neither), loader precedence ordering,
  writer precedence ordering, fall-through to HOME when cwd marker
  exists but no edicts file, env-var-vs-cwd precedence.
- `TestManageCLICwdFallback` (5): subprocess-level coverage — `add`
  writes to cwd when env unset, `add` exits 2 with diagnostic when
  cwd lacks a marker, env-var precedence in the CLI, round-trip
  `add` + `list` via cwd fallback, `path` subcommand reports cwd
  location.

Full test suite (203 tests, was 186) passes in 23.6 s.

### Compatibility

- Existing tests pre-set `CLAUDE_PROJECT_DIR`; their behaviour is
  unchanged because the env var is step 1 in the resolution order.
- Personal-global users (`~/.claude/cc-enforcer/edicts.toml` with no
  project file) are unaffected — they hit step 3 either way.
- The new fallback never overrides an explicit user choice; it only
  fires when the env var is genuinely absent.

---

## [0.18.1] — 2026-05-28

**Hotfix: catastrophic ReDoS in PATCH_MARKERS[0] (bare try/except/pass).**

The "Python: bare try / except: pass" patch-marker detector
([`hooks/scripts/read_guard.py`](hooks/scripts/read_guard.py)) used a
multi-line regex of the form

```
(^|\n)[ \t]*try[ \t]*:[ \t]*\n
(?:[ \t]+[^\n]*\n)+?
[ \t]*except\b[^:\n]*:[ \t]*\n
[ \t]*pass[ \t]*(?:\n|$)
```

The non-greedy line-repeater `(?:[ \t]+[^\n]*\n)+?` combined with the
later anchor caused **catastrophic backtracking** on healthy Python
source that contained a `try:` block without a matching bare-pass
closure — essentially all real-world Python code. Measured locally:

| `try:` body lines, no matching `except:/pass` | Wall time |
| ---: | ---: |
|  10 | 0.07 s |
|  20 | > 60 s (timed out) |
|  ≥ 50 | > 10 minutes (user-reported) |
| ≥ 100 | hours / indefinite hang |

User-visible symptom: every `Edit` / `Write` against a non-trivial
`.py` file froze Claude Code for 10 minutes to over an hour, because
the `PreToolUse(Edit|Write)` hook ran `read_guard.py`, which spawned
this regex on the new content, and there is no Claude Code hook
timeout configured for `read_guard` so the host waited indefinitely.

### Fixed

- **`read_guard.py`**: dropped the multi-line bare-try-except-pass
  regex; added `_scan_bare_try_except_pass()`, an O(N) linear,
  regex-free line scanner that detects the same pattern without
  backtracking. The detection contract is preserved:
  - same DENY message (`PATCH_DENY_TEMPLATE` with
    `BARE_TRY_EXCEPT_PASS_LABEL`),
  - same ±1-line rationale window (`_line_window` + `_has_rationale`)
    suppresses the DENY when an adjacent `because` / `原因` / `why`
    comment is present,
  - first-match-wins ordering with the remaining single-line
    `PATCH_MARKERS` entries.
- **Pre-filter fast path**: the scanner exits in O(1) when
  `"try:" not in text`, making the check effectively free for the
  overwhelming majority of edits.

### Verified

- New regression test `test_redos_pathological_input_completes_fast`
  pins the worst case (`try:` + 100 indented body lines, no closure)
  at under 5 s wall time. Pre-fix this input ran for over 60 s on
  N=20 and exceeded 10 minutes on N=100.
- New test `test_bare_try_except_pass_with_rationale_is_allowed`
  pins the rationale-window semantics against the new code path.
- The existing `test_bare_try_except_pass_is_denied` still passes,
  confirming that real bare-pass laziness is still caught.
- Full test suite (186 tests) passes.

### Why `0.18.1` (not 0.19)

This is a fix to a single regex in a single file with no surface-area
change to the hook contract, the deny message, or the rationale
allowance semantics. Per SemVer this is a patch release.
- **Layer (g) content-hash escalation** — currently uses
  `os.path.getmtime` baseline diff; same-second back-to-back edits can
  produce identical mtimes (rare). Escalate to SHA-256 only when the
  first real false-negative surfaces.

---

## [0.18.0] — 2026-05-25

**Auto-GC on SessionStart (opt-in via `CC_ENSLAVER_AUTO_GC_DAYS`).**

Closes the v0.6.1 roadmap entry. The original v0.6.1 GC was manual-only
(via `/cc-enforcer:gc`) with the explicit note that auto-GC was
deferred on three grounds: SessionStart latency, critical-path risk,
debuggability. v0.18 ships auto-GC behind an **opt-in env var** and
addresses each concern:

  - **Latency**: lazy import of `gc_state` (only when the env var is
    set AND rate-limit allows); empty state_dir scan is < 1 ms.
  - **Critical-path risk**: failing-open at every step (env parse,
    state_dir resolution, marker read, GC call, marker write); all
    failures route to stderr and the injection still emits normally.
  - **Debuggability**: shares the exact same `prune_old_sessions()`
    routine as `/cc-enforcer:gc`, so any bug surfaces in the manual
    path too (where it's much easier to diagnose).

### Added — opt-in auto-GC

- **`hooks/scripts/gc_state.py`**:
  - New `prune_old_sessions(threshold_days, *, dry_run=False,
    exclude_session=None) -> dict` — the shared deletion routine,
    extracted from `main()`. Returns a structured summary
    (`scanned / eligible / deleted / bytes_freed / failures / items`).
  - `_GC_INTERNAL_FILES = {"_auto_gc.json"}` — explicit allowlist of
    files in `state_dir` that GC must NEVER delete regardless of age.
  - Manual CLI `main()` refactored to call `prune_old_sessions()` so
    both entry points share identical semantics.
- **`hooks/scripts/inject_context.py`**:
  - `_maybe_auto_gc()` runs only on `SessionStart` events, only when
    `CC_ENSLAVER_AUTO_GC_DAYS=N` (positive int) is set, only if the
    rate-limit marker is older than 24h.
  - Marker file: `<state_dir>/_auto_gc.json` carries `{ts: float,
    deleted: int}`. Rewritten after every real GC attempt (even when
    0 files were eligible) so the 24h window is anchored to "tried"
    not "found something".
  - Lazy import of `gc_state` (only paid by opted-in users).
  - Failing-open: env-parse / state_dir / marker-IO / GC call /
    marker-write all wrapped; stderr only.

### Rate-limit design

The 24h gate prevents the GC from re-scanning on rapid session
restarts (IDE crash recovery, Claude Code restart loops). Without it,
a developer who restarts Claude Code 20 times in an hour would pay
20 × O(state_dir size) glob walks. With the gate, they pay it once.

The marker file is intentionally inside `state_dir` (not somewhere
else) so it co-locates with what it tracks — and it's protected by
`_GC_INTERNAL_FILES` from being GC'd by itself when old.

### Tests: 174 → 184 (+10)

`TestAutoGCOnSessionStart` (8 tests) drives `inject_context.py` as a
subprocess with `CC_ENSLAVER_AUTO_GC_DAYS` in the env:
  - env unset → no GC, no marker
  - env set + old files → files deleted, marker written with `deleted` count
  - rate-limit: fresh marker (< 24h) → no deletion
  - rate-limit: stale marker (> 24h) → deletion proceeds
  - marker file itself never GC'd even when backdated
  - bad env value (non-numeric) → silent skip, no marker, stderr diagnostic
  - zero / negative threshold → disabled
  - UserPromptSubmit event → auto-GC must NOT run (SessionStart-only)

`TestPruneFunctionDirect` (2 tests) covers `prune_old_sessions()`
directly:
  - `exclude_session` spares the named file even when it's old
  - `threshold_days < 1` raises `ValueError`

### Why opt-in (not opt-out)

State files are small (KB-sized) and accumulate slowly. Aggressively
auto-deleting on every install would be a silent behavior change that
could surprise users debugging long-tail issues ("why did my session
state for that bug-repro vanish?"). Opt-in via env var matches the
v0.15 `CC_ENSLAVER_LANG` and v0.16 `CC_ENSLAVER_DISABLE_LAYER_G`
convention — explicit, scriptable, no install-time prompts.

### Changed — docs

- `commands/gc.md`: new section documenting `CC_ENSLAVER_AUTO_GC_DAYS`
  with both Bash and PowerShell setup snippets.
- `README.md`: "New in v0.18" banner; Environment switches table
  (both English and Chinese) gains the auto-GC row; roadmap line
  removes auto-GC and adds completion note.

---

## [0.17.0] — 2026-05-25

**Imperial Edicts (圣旨) bilingual adaptation + Windows portability fixes
+ comprehensive README refresh.**

Two concrete user-reported gaps closed:

1. **"README 严重过期"** — v0.16 added Layer (g) but the README §3 still
   said "**six** layered checks", the repo tree was last updated at
   v0.11, `/cc-enforcer:edict` was missing from every slash-command
   list, and the roadmap entries had ALL been delivered. v0.17 does a
   full content sweep: 9 rules + Imperial Edicts + **7** Stop-hook
   gates (with Layer (g) bullet), updated repo tree (matches actual
   layout: `lib/edicts.py`, `manage_edicts.py`, `prompts/en/`, etc.),
   8-script enumeration, current environment switches table.
2. **"圣旨 should have an English adaptation"** — v0.15 added
   `CC_ENSLAVER_LANG=en` for the base prompts, but `edicts.py`
   hardcoded Chinese banner + Chinese DENY headline so English users
   got mixed-language output. v0.17 extends the same switch to cover
   Imperial Edicts.

### Added — bilingual Imperial Edicts rendering

- **`hooks/scripts/lib/edicts.py`**:
  - `_resolved_lang(explicit=None)` — language resolution helper
    matching `inject_context.py`'s convention.
  - `_INJECT_STRINGS` — Chinese / English translation table for the
    soft-layer injection block (title, intro, footer, severity
    badges, units).
  - `_DENY_REASON_TEMPLATES` — Chinese / English templates for the
    PreToolUse DENY reason.
  - `render_injection(edicts, *, lang=None)` — lang param (defaults
    to env). Chinese default keeps `🏛️ 圣旨...` banner; English emits
    `🏛️ Imperial Edicts (project hard rules; priority > builtin 9)`.
  - `deny_reason(hit, *, kind, tool_or_cmd, lang=None)` — same. Chinese
    keeps `cc-enforcer · 圣旨 E01 violation` headline (preserves
    keyword-contract tests); English emits `cc-enforcer · Imperial Edict
    E01 violation`.
- **`hooks/scripts/inject_context.py`** — passes its already-resolved
  `_resolved_lang()` to `render_injection()` so the base prompt
  language and the edict block language always match (single env-var
  switch flips both).
- **+5 tests** in `TestBilingualRendering`:
  - Default (no env) → Chinese banner in injection
  - `CC_ENSLAVER_LANG=en` → English banner + "User-defined,
    hot-reloadable" English intro + no Chinese 圣旨 banner bleed-through
  - Unknown lang (`fr`) → fail-safe back to Chinese
  - Default → Chinese `圣旨 E01 violation` headline in Bash DENY
  - `CC_ENSLAVER_LANG=en` → English `Imperial Edict E01 violation`
    headline in Bash DENY (no Chinese 圣旨 anywhere in reason)

### Fixed — Windows portability

Two pre-existing bugs surfaced when first running the full suite on
Windows (v0.13–v0.16 were tested only in Linux sandbox):

- **Stop Layer (g) regex missed drive-letter paths.** `_PATH_TOKEN`
  in `stop_guard.py` was `[\w./\\-]+\.[A-Za-z][...]` which did NOT
  include `:`, so `C:\Users\...\x.py` failed to match starting at `C:`.
  Three Layer (g) tests (`test_edit_claim_with_unchanged_mtime_blocks`,
  `test_create_claim_when_file_missing_blocks`,
  `test_chinese_claim_extraction_blocks`) were dormant failures on
  Windows. Fix: prepend optional `(?:[A-Za-z]:)?` — Linux/macOS paths
  still match because the prefix is optional.
- **`manage_edicts.py` print() used cp1252 on Windows.** The `×`
  character in `list` output (`deny_bash × 1`) and any Chinese in
  edict text mangled to mojibake when the parent console wasn't UTF-8.
  Fix: `sys.stdout.reconfigure(encoding="utf-8")` + same for stderr
  at the top of `main()`, guarded by try/except with rationale comment.

### Changed — README.md (comprehensive)

- Banner badges + "New in v0.17" section.
- Header line: "9 built-in rules + Imperial Edicts (圣旨) + **7
  Stop-hook gates** (v0.17.0)" — was "6 Stop-hook gates (v0.16.0)".
- §3 Stop-hook list now seven bullets with Layer (g) description.
- §4 Slash command list: four items (`/cc-enforcer:edict` added).
- §7 LLM-agnostic core: mentions `prompts/en/` v0.15 + v0.17
  bilingual edicts.
- Roadmap line: stale items (deep file-claim verification, rolling-
  patch hard interception, English prompts) removed (all delivered);
  new entries: ephemeral edicts, Layer (g) content-hash, auto-GC.
- Repository structure tree: full rewrite, matches v0.17 actual
  layout including `lib/`, `tests/`, `prompts/en/`, `docs/EDICTS.md`,
  `commands/edict.md`.
- Hooks table: 7-layer Stop description; edicts mentioned on Edit/
  Write/Bash rows.
- "Five scripts" enumeration → 8 scripts (added `gc_state.py`,
  `manage_edicts.py`, `lib/` package).
- New "Environment switches" table documenting `CC_ENSLAVER_LANG`,
  `CC_ENSLAVER_DISABLE_LAYER_G`, `CLAUDE_PLUGIN_DATA`,
  `CLAUDE_PROJECT_DIR`.
- 中文说明 section mirrored: 6 → 7 层 Stop description, layer (g) line,
  4 个 slash 命令, 当前路线图 refresh, 环境变量表.

### Changed — docs/EDICTS.md

- New "Bilingual rendering (v0.17)" subsection in §3 with two-row
  table showing the zh vs en banner / DENY headline.

### Tests: 169 → 174 (+5)

`TestBilingualRendering` in `tests/test_edicts.py`:
  - 3 injection tests (default zh / explicit en / unknown lang fallback)
  - 2 deny-reason tests (default zh keeps `圣旨` / `en` flips to
    `Imperial Edict`)

All 169 pre-existing tests pass unchanged (Chinese is the default; no
env var = no behavior change).

### Why "圣旨" is preserved in Chinese mode (not translated to
"Imperial Edict" everywhere)

The Chinese term is the original project nomenclature and appears in
existing CHANGELOG entries, slash-command help text, and contract
tests. Replacing it would create translation drift. The cleaner
solution is `CC_ENSLAVER_LANG=en` opt-in, just as v0.15 chose for
prompts. Default behavior is identical to v0.16 — users only see
"Imperial Edicts" when they explicitly ask for English.

---

## [0.16.0] — 2026-05-25

**Stop hook Layer (g): file-claim verification (rule 01 + 06).**

Closes the largest remaining "honest claim" hole. The agent can pass
layers (a)-(f) — show evidence, run convergence, surface fidelity,
mark rule 08 + 09 triplets — and still ship a final message that says
"I edited X.py" when X.py was never actually modified. Layers (a)-(f)
all check the *shape* of the reply; none of them check whether
specific file claims in the reply *are true*. Layer (g) closes that
hole by lazily capturing per-file baselines on first
Read/Edit/Write and verifying each file claim against the current
on-disk state at Stop time.

### Added — baseline capture (rule 01/06 plumbing)

- **`hooks/scripts/lib/state.py`**:
  - `record_baseline(session_id, file_path)` — lazy + idempotent;
    first call captures current mtime (or None if file missing);
    subsequent calls are no-ops so the snapshot survives later
    modifications.
  - `get_baseline(session_id, file_path) -> (have_baseline,
    baseline_mtime_or_None)`.
  - New JSON field: `baseline_mtimes: {normalized_path: float | None}`.
- **`hooks/scripts/read_guard.py`** — wires `record_baseline` into
  Read / Write / Edit branches BEFORE any DENY decision, so the
  baseline reflects pre-action disk state even when the action gets
  denied downstream.

### Added — Layer (g) (rule 01 + 06 enforcement)

- **`hooks/scripts/stop_guard.py`**:
  - `_extract_file_claims(message)` — parses two regex families:
    - English: `I (edited|modified|wrote|created|added to) [path]`
      where `[path]` has a file extension.
    - Chinese: `(修改|更新|创建|新增|新建|编辑|写入|添加|生成)了 [path]`.
    - Negation guard: skips "I did NOT edit X" / "没修改 X".
  - `_verify_claims(session_id, claims, cwd)` — for each claim, looks
    up baseline, compares current mtime, returns contradictions only
    for definitively contradicted claims.
  - New Layer (g) wired after (f) in `main()`, fires only on
    `edited_this_turn == True`.
  - `LAYER_META` and `_LAYER_FAIL_NOTE` extended; the status table now
    renders 7 rows; (g) is marked "— n/a" on non-edit turns, same
    convention as (e)+(f).
- **`_RECOVERY_G`** template explains the three plausible causes of a
  contradicted claim (DENIED earlier, wrong file claimed, no-op edit)
  and what to do in each.

### Conservative-by-design contract

Layer (g) prefers false-negatives (missed lies) over false-positives
(blocking honest claims):

| Condition | Behavior |
|---|---|
| No file claims in message | Pass silently |
| Claim about file never tracked (no baseline) | Pass — can't verify |
| Claim verb matches modification but mtime changed | Pass — verified |
| Claim verb "edited" + baseline mtime + current mtime same | **BLOCK** |
| Claim verb "created" + baseline=None + file still missing | **BLOCK** |
| `CC_ENSLAVER_DISABLE_LAYER_G` env var set | Pass — user escape hatch |

The escape-hatch env var exists because file-claim parsing is
fundamentally fuzzy. Users who hit a false-positive in real workflow
can disable just this layer without losing the other 6.

### Tests: 158 → 169 (+11)

`TestRule10FileClaimVerification` covers:
- no claim → pass; unverifiable → pass
- edit-claim with unchanged mtime → BLOCK
- edit-claim with changed mtime → pass
- create-claim with missing file → BLOCK
- create-claim with existing file → pass
- Chinese claim extraction works (`我修改了 \`x.py\``)
- Negation guard works (`I did not edit X` → no claim)
- Path without extension → not extracted
- Escape-hatch env var disables the layer
- Non-edit turn → layer (g) silent (n/a)

Existing 43 stop_guard layer-logic tests + 8 v0.12 table-format tests
pass unchanged; status table just gained a 7th row.

### Why not a new rule file (rules/10-*.md)

This layer is rule 01 (verify don't guess) + rule 06 (verify
convergence) applied to the agent's own action claims. The roadmap
entry called for "deep file-claim verification", not a new rule. The
discipline already exists; v0.16 just adds the hook to enforce it.

### Docs

- `CLAUDE.md` — Stop layer list extended to 7 rows; state field list
  notes `baseline_mtimes`.
- `prompts/{session-start,user-prompt}.md` (+ English mirrors): new
  physical-enforcement row for layer (g).
- `README.md` + `plugin.json` + `marketplace.json`: version 0.15 → 0.16
  with v0.16 banner.

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
  - `_global_path()` returns `~/.claude/cc-enforcer/edicts.toml`.
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
- **File location**: `${CLAUDE_PROJECT_DIR}/.claude/cc-enforcer/edicts.toml`
  (project-level, team-shareable). Falls back to `~/.claude/cc-enforcer/
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
  First matching `must` edict → DENY with `cc-enforcer · 圣旨 <id>
  violation` reason naming the edict + matched pattern + snippet.
- **PreToolUse(Bash) integration** — `bash_guard.py` calls
  `edicts_lib.find_bash_violation` after the built-in static patterns
  (`--no-verify` / `--no-gpg-sign` / force-push / `chmod 777`) so 圣旨
  cannot accidentally whitelist a built-in bypass.
- **`hooks/scripts/manage_edicts.py`** — CRUD helper:
  `list / add / remove / reload / path`. Used by the slash command and
  directly from the shell.
- **`commands/edict.md`** — `/cc-enforcer:edict` slash command wrapping
  the manage script.
- **`docs/EDICTS.md`** — user guide with format, enforcement contract,
  3 worked examples, limitations.

#### Why TOML and not YAML

Python's stdlib has `tomllib` (3.11+) but no YAML parser. cc-enforcer's
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
  cc-enforcer · Stop check FAILED at Layer (X) [rule NN — short label]

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
adapts it to the cc-enforcer verification discipline.

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
cc-enforcer's systematic-debug skill had. Importing those patterns (with
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

**Project rename: `anti-laziness` → `cc-enforcer` (and marketplace
`agent-rigor` → `cc-enforcer`).** All five name layers (plugin name,
marketplace name, GitHub repo, slash-command prefix, on-disk state
directory basename) are now unified under a single identifier. No
behavioural change to any rule, hook, or test — only string
substitution + version bump.

### Why

Pre-0.9.0 the repo had two parallel names by accident of history:
the plugin internal `name` field said `anti-laziness`, while the
marketplace + GitHub repo used `agent-rigor`. New users saw
`/plugin install anti-laziness@agent-rigor` and asked which is "the"
name. v0.9.0 collapses everything to **`cc-enforcer`** so the
marketplace/install/slash-command/import-path all match.

### Breaking changes (rename consequences)

- **Slash commands** prefixes change:
  `/anti-laziness:checklist` → `/cc-enforcer:checklist`,
  `/anti-laziness:verify`    → `/cc-enforcer:verify`,
  `/anti-laziness:gc`        → `/cc-enforcer:gc`.
- **Install command** is now `/plugin install cc-enforcer@cc-enforcer`
  (still works against the same local marketplace path).
- **State directory basename** changes from `anti-laziness` to
  `cc-enforcer` in the fallback paths
  (`~/.claude/local/cc-enforcer/sessions/` and
  `${CLAUDE_PROJECT_DIR}/.claude/local/cc-enforcer/sessions/`).
  The `${CLAUDE_PLUGIN_DATA}` path supplied by Claude Code is keyed
  on the plugin's `name`, so it also moves automatically. **Old
  per-session state files (`last_blocked_turn`, `read_files`) will
  not migrate** — they are effectively orphaned. Acceptable because
  state is short-lived (one Claude Code session) and the orphans are
  harmless KB-sized JSON. Run `/cc-enforcer:gc --apply` against the
  *old* state dir if you want to reclaim space.
- **GitHub repository name** changes from `skymanbp/agent-rigor` to
  `skymanbp/cc-enforcer`. GitHub installs an automatic redirect from
  the old name, so existing clones / CI badges keep working. The
  CHANGELOG `compare` links and `plugin.json` `homepage` /
  `repository` fields now point at the new URL directly.
- **Already-installed copies** of the plugin will continue to work
  on the old name until the user re-installs from the renamed
  marketplace. `/plugin marketplace remove agent-rigor` then
  `/plugin marketplace add /path/to/cc-enforcer`, then
  `/plugin install cc-enforcer@cc-enforcer`.

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

- `anti-laziness` → `cc-enforcer` (117 occurrences across 22 files):
  plugin.json, marketplace.json, CLAUDE.md, CHANGELOG.md, README.md,
  agents/verifier.md, commands/{checklist,gc,verify}.md,
  docs/ARCHITECTURE.md, prompts/{session-start,user-prompt}.md,
  rules/{,en/}00-index.md, hooks/scripts/{bash_guard,gc_state,
  inject_context,read_guard,register_read,stop_guard}.py,
  hooks/scripts/lib/state.py, tests/_helpers.py.
- `agent-rigor` → `cc-enforcer` (homepage/repository URL +
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
`cc-enforcer · rule 0X enforcement (...)` and the injected context
mentions `cc-enforcer` in place of `anti-laziness`.

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
2. Using cc-enforcer as an LLM-agnostic system-prompt fragment with
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
Bash tool call or via the new `/cc-enforcer:gc` slash command.

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
- **`commands/gc.md`** — `/cc-enforcer:gc` slash command. Defaults
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
$ claude plugin install cc-enforcer@cc-enforcer
✔ Successfully installed plugin: cc-enforcer@cc-enforcer (scope: user)
$ claude plugin list
  ❯ cc-enforcer@cc-enforcer
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
  to `${CLAUDE_PROJECT_DIR}/.claude/local/cc-enforcer/sessions/` and
  `~/.claude/local/cc-enforcer/sessions/`). Path normalisation via
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
  `/plugin install cc-enforcer@<marketplace-name>`.

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
- **Slash commands** (`commands/`) — `/cc-enforcer:checklist` prints the
  systematic-thinking checklist; `/cc-enforcer:verify` prompts a
  re-verification pass.
- **Verifier subagent** (`agents/verifier.md`) — independent `file:line` citation
  re-reader, returns drift/missing/intact verdict.
- **Skill** (`skills/systematic-debug/`) — auto-invokes on debugging language and
  forces a root-cause walk-through before any fix is proposed.
- **Repo-standard files** — `README.md` (bilingual), `LICENSE` (MIT),
  `.gitignore`, this `CHANGELOG.md`, `docs/ARCHITECTURE.md`, `docs/RULES.md`.

### Removed

- Original free-form `claude.md` (replaced by the structured `CLAUDE.md`).

[Unreleased]: https://github.com/skymanbp/cc-enforcer/compare/v0.11.0...HEAD
[0.11.0]: https://github.com/skymanbp/cc-enforcer/compare/v0.10.0...v0.11.0
[0.10.0]: https://github.com/skymanbp/cc-enforcer/compare/v0.9.1...v0.10.0
[0.9.1]: https://github.com/skymanbp/cc-enforcer/compare/v0.9.0...v0.9.1
[0.9.0]: https://github.com/skymanbp/cc-enforcer/compare/v0.7.0...v0.9.0
[0.8.0]: https://github.com/skymanbp/cc-enforcer/compare/v0.7.0...v0.9.0
[0.7.0]: https://github.com/skymanbp/cc-enforcer/compare/v0.6.2...v0.7.0
[0.6.2]: https://github.com/skymanbp/cc-enforcer/compare/v0.6.1...v0.6.2
[0.6.1]: https://github.com/skymanbp/cc-enforcer/compare/v0.6.0...v0.6.1
[0.6.0]: https://github.com/skymanbp/cc-enforcer/compare/v0.5.1...v0.6.0
[0.5.1]: https://github.com/skymanbp/cc-enforcer/compare/v0.5.0...v0.5.1
[0.5.0]: https://github.com/skymanbp/cc-enforcer/compare/v0.4.0...v0.5.0
[0.4.0]: https://github.com/skymanbp/cc-enforcer/compare/v0.3.2...v0.4.0
[0.3.2]: https://github.com/skymanbp/cc-enforcer/compare/v0.3.1...v0.3.2
[0.3.1]: https://github.com/skymanbp/cc-enforcer/compare/v0.3.0...v0.3.1
[0.3.0]: https://github.com/skymanbp/cc-enforcer/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/skymanbp/cc-enforcer/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/skymanbp/cc-enforcer/releases/tag/v0.1.0
