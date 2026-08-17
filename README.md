# cc-enslaver

> **Rules your coding agent physically cannot ignore.**
> A Claude Code plugin (and LLM-agnostic rule pack) that stops reactive patches,
> guessed citations, surface-level "fixes", and premature "done" claims — by
> intercepting the agent's own tool calls, not by asking it nicely.

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Plugin Version](https://img.shields.io/badge/version-0.31.0-blue.svg)](CHANGELOG.md)
[![Tests](https://github.com/skymanbp/cc-enslaver/actions/workflows/test.yml/badge.svg)](https://github.com/skymanbp/cc-enslaver/actions/workflows/test.yml)
[![Claude Code Plugin](https://img.shields.io/badge/Claude%20Code-plugin-purple.svg)](https://code.claude.com/docs/en/plugins.md)

**[中文文档 →](README.zh.md)**

---

## The 30-second version

Every "be rigorous" instruction you put in a prompt has the same flaw: the model
decides whether to follow it. Under pressure — a long session, a compacted
context, a failing test at 2am — it decides not to, and tells you it did.

cc-enslaver moves the important half of that contract **out of the prompt and
into the harness**. Claude Code hooks run *before* each tool call and *before*
each reply is allowed to end. A violation returns a real `deny` / `block`
verdict, so the agent cannot reason, apologise, or "just this once" its way
past it:

```text
cc-enslaver · rule 09 violation (rolling-patch interception)

Tool: Edit
Target: hooks/scripts/stop_guard.py
Rolling-patch counter: 3 small edit(s) already applied this session;
this would be attempt #4 — at or above the threshold of 4.

To proceed, do one of:
  (1) Systematic rewrite: combine your pending small fixes into a single
      Edit of ≥ 50 lines / ≥ 1500 chars. Resets the counter.
  (2) Batch multiple typo-class fixes into one larger Edit.
  (3) Stop and surface: tell the user this file needs a rewrite.
```

That message is not advice printed after the fact. The edit **did not happen**.

Three things follow from that design:

| | |
|---|---|
| **It survives compaction** | Rules are re-injected every turn, and the hard layers live in code that does not depend on the model remembering anything. |
| **It cannot be self-whitelisted** | Built-in guards run *before* user rules, and the read-registration escape hatch is SHA-256 verified against disk — an agent that never opened a file cannot produce its digest. |
| **It fails open, never closed** | Any exception inside a guard logs to stderr and *allows* the call. A bug in the discipline can never brick your agent. |

---

## What problem it solves

LLM coding agents (Claude Code, Cursor, Copilot, Cline, Aider…) fall into
predictable lazy patterns:

| Lazy pattern | What it looks like | Answer |
|---|---|---|
| **Reactive patching** | Sees a bug, wraps it in `try/except`, declares done. | rule 03 + 09, `PreToolUse` DENY |
| **Guessed citations** | Cites files, line numbers or APIs that do not exist. | rule 01 + 05, Stop layer (b)/(g) |
| **Keyword-search-only** | Greps once, edits, never reads the surrounding architecture. | rule 04 + 08, `PreToolUse` DENY |
| **Memory dependence** | Acts on stale recollection instead of re-reading the file. | rule 04 + 08, read-before-edit gate |
| **Root-cause bypass** | `sleep` for races, `--no-verify` for hooks, swallowed exceptions. | rule 03, `PreToolUse(Bash)` DENY |
| **Half-finished work** | Stops at "should work", leaves TODOs, skips the whole flow. | rule 07, Stop layer (d) |
| **Premature done-claim** | "Fixed" without re-running the failing case or comparing evidence. | rule 06, Stop layers (a)/(c) |

---

## Install

### As a Claude Code plugin (recommended)

The repo ships `.claude-plugin/marketplace.json`, so it registers as a
single-plugin marketplace:

```bash
git clone https://github.com/skymanbp/cc-enslaver.git /path/to/cc-enslaver
```

Then in any Claude Code session (CLI or IDE):

```
/plugin marketplace add /path/to/cc-enslaver
/plugin install cc-enslaver@cc-enslaver
```

Verify with `/plugin` → **Installed** should list `cc-enslaver@cc-enslaver`.
Commands then surface as `/cc-enslaver:checklist`, `/cc-enslaver:verify`, …

> **Requirements:** Python on PATH (tested on 3.13). Hook scripts use the
> standard library only — no pip step, no third-party packages.

### As a rule pack for any other LLM

You do not need Claude Code. The rules are plain Markdown in [`rules/`](rules/)
(English is the source of truth; [`rules/zh/`](rules/zh/) is the Chinese
translation):

```bash
cat rules/*.md    > cc-enslaver.txt     # English skeleton
cat rules/zh/*.md > cc-enslaver.txt     # Chinese translation
# feed as system prompt / pre-context to the agent of your choice
```

You lose the hard layers (they are Claude Code hooks) and keep the reasoning
discipline. Integration patterns for OpenAI / Gemini / local models are in the
**LLM portability** section of [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).

---

## What it enforces

Five categories, in order of how hard they bite.

### 1 · The 12 rules

The reasoning contract. Roughly half are backed by a hook; the rest are
text-level discipline the Stop gate grades indirectly.

| # | Rule | What it demands | Enforcement |
|---|---|---|---|
| 01 | **Verify, don't guess** | Every claim about a file, API, version, error or citation is checked *in the same turn* it is written. "I don't know" beats a confident wrong answer. | soft + Stop (b)(g) |
| 02 | **Systematic, not reactive** | Answer seven questions before editing: architecture, responsibility, root cause, plan, ripple, risk, global validity. Ships a worked example, not an exhortation. | soft (graded by (e)) |
| 03 | **Root cause, not symptom** | Climb the causal chain — symptom site → propagation path → **origin** — until the answer is a mechanism. Stopping early is legal only if you name the true origin and say why. | **Bash DENY** + soft |
| 04 | **Read fully, not keywords** | Grep locates; understanding requires the whole file plus its callers. | **Edit/Write DENY** |
| 05 | **Cite traceable sources** | `file:line` for code, URL/DOI for literature, command + output for runtime claims. | soft |
| 06 | **Verify convergence** | Re-trigger the original symptom, exercise boundary and negative cases, run existing tests, answer four self-quiz questions. **Check 2b:** "no regression" must be a per-item set diff, never a matching total. | **Stop (a)(c)** |
| 07 | **Task fidelity** | Decompose the user's request into checkable sub-items; every modifier word they used ("all", "strict", "mandatory") must land as a hard action, not a doc line. | **Stop (d)** |
| 08 | **Read before edit, think before write** | Full read going in; root cause / architecture / impact stated coming out. | **DENY + Stop (e)** |
| 09 | **Systematic modification** | One root cause, one unified fix — sweep the whole class, never N patches. Suppression markers need an adjacent *why*. | **DENY ×2 + Stop (f)** |
| 10 | **No non-essential hardcoding** | Secrets, tokens, private keys and credentials-in-URLs never become source literals. | **Edit/Write DENY** |
| 11 | **No non-essential path dependency** | No `C:\Users\…` / `/home/you/` / `$HOME` baked into code; derive paths at runtime. | **Edit/Write DENY** |
| 12 | **Repo-wide sync** | An edit is done only when every reference to it — docs, tests, downstream code, translations — is co-updated or explicitly verified current. | **Stop (i)**, opt-in |

Full text: [`rules/`](rules/) · index: [`docs/RULES.md`](docs/RULES.md)

### 2 · Hard gates at the tool boundary (`PreToolUse` → DENY)

These refuse the call outright. Every one ships a named escape hatch, so they
are bypassable **by saying why**, never by accident.

| Gate | Triggers on | Escape hatch |
|---|---|---|
| **Read-before-edit** | Editing a file that exists on disk but was never opened this session. | Read it; or register a SHA-256-verified read. |
| **Suppression markers** | `# noqa`, `# type: ignore`, `@ts-ignore`, `@ts-expect-error`, `eslint-disable`, `time.sleep(…)` workarounds. | Adjacent why-comment (English *or* Chinese), or fix the cause. |
| **Bare `try/except: pass`** | An exception handler whose body is just `pass` — detected across lines, comments in between included. | Same why-comment hatch. |
| **Hardcoded secrets** | Secret-named literal, PEM private-key header, `AKIA…`, `ghp_…` / `xox…` / `AIza…`, `user:pass@host` URLs. | Env var, marked placeholder, or why-comment. |
| **Machine-specific paths** | `C:\Users\…`, `/home/<user>/`, `/Users/<user>/`, `$HOME`, `%USERPROFILE%`, quoted `~/…`. | Derive at runtime, or why-comment. Prose docs and lockfiles exempt. |
| **Rolling patches** | The 4th small edit (< 200 chars **and** ≤ 10 lines) to one file with no systematic rewrite in between. | One rewrite of ≥ 50 lines / ≥ 1500 chars resets the counter. |
| **Dangerous shell** | `--no-verify`, `--no-gpg-sign`, `git push --force` (not `--force-with-lease`), `chmod 777`, `git rebase --skip`, `--break-system-packages`, `rm -rf` on `/` `$HOME` `~`. | Fix the hook failure / permission / conflict instead. |
| **Your own edicts** | Any regex you registered as a `must` edict. | Only you can relax it. |

### 3 · The done-claim gate (`Stop` → BLOCK, nine layers)

The Stop hook reads the reply the agent is about to finish with. If it contains
a completion claim, nine layers grade it. Layers (e)(f)(g)(i) apply only to
turns that actually edited a file.

| Layer | Rule | Blocks when the reply… |
|---|---|---|
| (a) | 06 | claims done with **no evidence** — no command, no output, no counts. |
| (b) | 01 | pairs a done-claim with a **hedge** ("should be fine", "probably", "应该"). |
| (c) | 06 | shows evidence but never answers the **four convergence questions**. |
| (d) | 07 | passes convergence but never reconciles against the **user's original request**. |
| (e) | 08 | edited a file without surfacing ≥ 3 of root cause / architecture / solution / impact / risk. |
| (f) | 09 | edited a file without the **root cause + impact + solution** triplet. |
| (g) | 01+06 | says "I edited X" while X's **mtime on disk is unchanged**. |
| (h) | — | has **no `tldr`**, or a `tldr` item longer than 160 characters. |
| (i) | 12 | tripped a project **sync-gate** group with no co-update and no `sync-check:` line. |

A block renders as a uniform status table naming the failing row, a
`[Recovery — …]` section with concrete fix steps, and a one-line plain-language
summary. **Grace is per layer** (v0.29): the layer that just blocked is forgiven
on the next attempt — you can never be blocked twice for the same row — but a
*different* layer you are still violating will still fire. Escalation is bounded
by the layer count and any clean reply resets it.

The table reports **evaluation** order, not the alphabet (v0.30). (b) runs first,
because a hedge invalidates a done-claim however much evidence sits beside it, so
a layer-(a) block shows "(b) ✅ Pass" and a layer-(b) block shows "(a) ⏸ pending".
Until v0.30 both verdicts came from the display index, so a hedge block printed
"(a) ✅ Pass" — asserting evidence had been found on a turn where the evidence
check never ran. A gate built to catch unfounded claims does not get to make one.

### 4 · Imperial Edicts (圣旨) — your own hard rules

Most "custom rules" features are just more text in a prompt. Here your rule
becomes a regex a hook matches against the literal content of every Edit, Write
and Bash call before it lands:

```bash
/cc-enslaver:edict add E01 "no mongoose, use prisma" --must \
    --deny-edit 'from ["'"'"']mongoose["'"'"']' \
    --deny-bash 'npm\s+(i|install)\s+mongoose'
```

- **Two severities, mechanically different.** `must` + a regex → `PreToolUse`
  DENY naming the edict id. `should` → reminder text only, never denies.
- **Two scopes.** `.claude/cc-enslaver/edicts.toml` (project, commit it so the
  team shares the red line) or `~/.claude/cc-enslaver/edicts.toml` (`--global`).
- **Hot-reloaded** — the loader re-reads on every hook event, so you can iterate
  on a regex mid-session.
- **Re-injected every turn**, so compaction cannot quietly drop your rules.
- **Ordered after the built-ins by design**: an edict can add restrictions,
  never subtract them.
- **Fails safe, not quiet**: an unparseable severity falls back to `must`, and a
  malformed edict drops itself with a stderr diagnostic instead of blocking work.

Details: [`docs/EDICTS.md`](docs/EDICTS.md)

### 5 · What you invoke yourself

**6 slash commands**, one subagent, two auto-triggered skills:

| Surface | What it does |
|---|---|
| `/cc-enslaver:checklist` | Prints the **8-section checklist** (pre-edit → post-edit → convergence → fidelity → read/think → systematic → TL;DR → repo sync). Its patch-marker item is a *closed set* synchronised with the hook's real constant, so you cannot tick every box and still get denied. |
| `/cc-enslaver:verify` | Turns the agent's last reply into untrusted input: extracts every factual claim, buckets it (code location / behaviour / external / run result) and prescribes a re-verification method per bucket. Recall is explicitly not allowed. |
| `/cc-enslaver:edict` | `list / add / remove / reload / path` for Imperial Edicts (`--global` for personal scope). |
| `/cc-enslaver:gc` | Lists — or with `--apply`, deletes — session-state files older than N days. Dry-run by default, and the command file forbids the agent from choosing `--apply` for you. |
| `/cc-enslaver:i18n` | Checks every translation still matches the English skeleton file-for-file and heading-for-heading. |
| `/cc-enslaver:sync-gate` | `init / list / check / add / remove / path` for this project's rule-12 co-update groups. **`check` is the point**: the gate's loader is failing-open, so a dropped group or a glob that matches no file makes it stop guarding *silently* — an unenforced gate you still trust is worse than none. `check` names both and exits 1, so it works in CI. |
| **`verifier` subagent** | A deliberately crippled read-only checker (Read/Grep/Glob only — a permission fact, not an instruction). Returns *intact / drift / missing / mismatch / unverifiable* per claim. It cannot become the fixer, so it has no incentive to quietly patch a discrepancy. |
| **`systematic-debug` skill** | Auto-triggers on bug-fix language and takes over the workflow: build a fast deterministic reproduction loop **first**, then hypothesise. "A 30-second intermittent flaky loop is barely better than no loop; a 2-second deterministic loop is a debugging superpower." |
| **`repo-refresh` skill** | Auto-triggers on repo-audit language: sweeps code *and* prose together for stale / outdated / redundant / wrong / drifted content, then asks you to convert whatever coupling it found into a sync-gate group. |

---

## Why this isn't a prompt file — or a linter

The interesting engineering is in the detectors, and most of it exists because
the naive version demonstrably failed:

- **Source is lexed, not regexed.** `line.find("#")` finds the `#` inside a URL —
  which once let a single neighbouring `API = "https://api.example.com"` line
  disable the *secret* detector entirely (`example` reads as a rationale token).
  [`lib/srclex.py`](hooks/scripts/lib/srclex.py) distinguishes code from comment
  from docstring from data literal, with literal masking and bracket-joined
  logical lines.
- **Shell is tokenised, not string-matched.** [`lib/shellcmd.py`](hooks/scripts/lib/shellcmd.py)
  splits a compound command into per-invocation argv, resolves git global options
  to the true subcommand, and recurses into `bash -c` payloads. So
  `rm -f build.log && git push origin main` never attributes `-f` to the push,
  `$(git push --force)` is still denied, and `echo git commit --no-verify` is
  correctly *allowed*.
- **Markers end at real token boundaries.** `\b` treats a hyphen as a boundary,
  so a naive matcher denied `@ts-ignore-generated` and `# noquality`. The
  detectors use `(?![\w-])`.
- **The escape hatch is self-securing.** The read-registration hatch recomputes
  the file's SHA-256 from disk; an agent that never opened it cannot produce the
  digest. `false && register_read.py …` earns no credit either — the hook fires
  before execution and cannot know which branch the shell takes.
- **Rationales must be substantive.** A leading `TODO` / `FIXME` / `HACK` is a
  deferral, not a reason, and still denies. Decorative padding is stripped first,
  and CJK rationales are measured by distinct-character count.
- **Concurrency is handled, with numbers.** Every hook invocation is a separate
  OS process and Claude Code fires tools in parallel. Mutations hold a
  cross-process advisory lock and save atomically — measured before the fix:
  2–3 of 10 recorded reads lost at 10-way parallelism, and 192/200 saves lost to
  Windows `os.replace`-vs-open-reader collisions.
- **The repo is held to its own rules.** Three CI gates make documentation claims
  un-drift-able: a version gate (every version pointer, the badge and the newest
  CHANGELOG heading pinned to `plugin.json` by a *closed set* — "a blacklist
  would have let it through"), a doc gate (every number in this README derived
  from the code at test time), and an i18n gate.

---

## How it works

| Event | Matcher | Behaviour | Implementation |
|---|---|---|---|
| `SessionStart` | — | Inject the 12-rule discipline summary + reply schema + Imperial Edicts (English by default, any language via `CC_ENSLAVER_LANG`). | [`inject_context.py`](hooks/scripts/inject_context.py) |
| `UserPromptSubmit` | — | Re-inject per-turn decision triggers + edicts — the defence against context compaction. | [`inject_context.py`](hooks/scripts/inject_context.py) |
| `PreToolUse` | `Read\|Edit\|Write` | Record reads, capture mtime baselines, and run the content + frequency + edict gates listed above. | [`read_guard.py`](hooks/scripts/read_guard.py) |
| `PreToolUse` | `Bash` | Tokenise the command, deny bypass flags and destructive operations, process read registrations, scan edicts. | [`bash_guard.py`](hooks/scripts/bash_guard.py) |
| `Stop` | — | The nine-layer done-claim decision, rendered as a status table + recovery + plain-language line. | [`stop_guard.py`](hooks/scripts/stop_guard.py) |

Both injections are budgeted against Claude Code's 10,000-character hook-output
cap: the contract is protected and the (unbounded) edict list is what yields,
elided at whole-edict boundaries with a pointer — because half an edict still
reads as a complete instruction.

Nine scripts under [`hooks/scripts/`](hooks/scripts/) sit on eight shared
[`lib/`](hooks/scripts/lib/) modules. Only the four in the table above are
registered as hooks; the other five (`register_read.py`, `manage_edicts.py`,
`manage_sync_gate.py`, `gc_state.py`, `i18n_check.py`) back the escape hatch,
the slash commands and CI. They deliberately stay in the same directory rather
than moving to a `tools/` tree: `gc_state.py` is imported by
`inject_context.py` for auto-GC and `register_read.py`'s real logic lives
inside `bash_guard.py`, so neither is a standalone CLI, and separating them
would buy a tidier directory name with a cross-tree `sys.path` splice. Full
contracts: [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) §2.

---

## Configuration

| Variable | Effect |
|---|---|
| `CC_ENSLAVER_LANG=<code>` | Injection language for prompts, edicts and deny reasons. Unset / `en` = English skeleton; `zh` = Chinese; any other code reads `<dir>/<code>/` with per-file fallback to English. |
| `CC_ENSLAVER_DISABLE_LAYER_G=1` | Turn off Stop layer (g) file-claim verification. The other eight layers still apply. |
| `CC_ENSLAVER_AUTO_GC_DAYS=N` | Auto-prune session state older than N days at SessionStart, rate-limited to once per 24h. Unset / `0` → disabled. |
| `CLAUDE_PLUGIN_DATA` | Session-state base dir. Set by Claude Code; falls back to `${CLAUDE_PROJECT_DIR}/.claude/local/cc-enslaver/`, then `~/.claude/local/cc-enslaver/`. |
| `CLAUDE_PROJECT_DIR` | Project root, used to resolve `.claude/cc-enslaver/edicts.toml` and `sync-gate.toml`. |

**Per-project sync gate** (rule 12) is opt-in: declare co-update groups in
`.claude/cc-enslaver/sync-gate.toml` and Stop layer (i) enforces them.

---

## Limits — what it does *not* do

Stated plainly, because a discipline plugin that oversells itself is the failure
mode it exists to prevent:

- **Everything fails open.** A guard that throws logs to stderr and allows the
  call. Unreadable state is treated permissively. This is deliberate — a bug in
  the plugin must never brick your agent — but it means enforcement is
  best-effort, not a security boundary.
- **The Stop layers only engage on a completion claim.** A reply that never says
  "done" is never graded.
- **Rules 02 and 05 have no hook of their own**, and the reasoning half of rules
  03, 09 and 12 is text-level. No hook can verify that you *actually* swept a
  defect class; it can only verify that you said you did.
- **The hard layers are Claude Code-specific.** Other agents get the rule pack.
- **Detectors prefer misses to false alarms** — `宁可漏报不误报`. Documented gaps
  live in each rule file rather than being quietly patched.

---

## Repository structure

```
cc-enslaver/
├── rules/                       # 12 rules + index — English skeleton (source of truth)
│   └── zh/                      # Chinese translation, structurally CI-gated
├── prompts/                     # SessionStart + per-turn injections (+ zh/)
├── hooks/
│   ├── hooks.json               # event → script wiring
│   └── scripts/
│       │                        # -- hook entry points (the four in hooks.json) --
│       ├── inject_context.py    # soft layer: SessionStart + per-turn injection
│       ├── read_guard.py        # hard layer: read-before-edit, content + frequency gates
│       ├── bash_guard.py        # hard layer: command discipline, read registration
│       ├── stop_guard.py        # hard layer: the nine-layer done-claim gate
│       │                        # -- auxiliary entry points (not hooks) --
│       ├── register_read.py     # SHA-256-verified read-cache escape hatch
│       ├── manage_edicts.py     # Imperial Edicts CRUD CLI
│       ├── manage_sync_gate.py  # rule-12 co-update groups: CRUD + `check` diagnostics
│       ├── gc_state.py          # session-state GC: CLI + auto-GC callee
│       ├── i18n_check.py        # skeleton ↔ translation structural parity
│       └── lib/                 # -- eight shared modules --
│           ├── srclex.py        # judgement: code vs comment vs docstring vs literal
│           ├── mdctx.py         # judgement: markdown fence / blockquote context
│           ├── shellcmd.py      # judgement: tokenise → segments → argv → subcommand
│           ├── state.py         # state: per-session, cross-process lock, atomic save
│           ├── tomlio.py        # config: tolerant TOML reader + the shared writer
│           ├── projroot.py      # config: project-root detection, shared by both loaders
│           ├── edicts.py        # feature: Imperial Edicts loader / matcher / renderer
│           └── sync_gate.py     # feature: rule-12 groups — read, write and match
├── commands/                    # 6 slash commands
├── agents/verifier.md           # read-only citation checker subagent
├── skills/                      # systematic-debug, repo-refresh (auto-invoked)
├── docs/                        # index + ARCHITECTURE, RULES, EDICTS, I18N
└── tests/                       # 590 black-box + unit tests (python -m unittest discover tests)
    │                            # each file is named after what it covers — see tests/README.md
    ├── _helpers.py              #   shared run_hook(...) subprocess fixture
    ├── test_<hook>.py           #   black-box subprocess tests, one per hook entry point
    ├── test_<lib|cli>.py        #   unit tests for shared modules and auxiliary scripts
    ├── test_version_sync.py     #   drift gate: every version pointer vs plugin.json
    ├── test_doc_sync.py         #   drift gate: documented counts + inventories vs code
    ├── test_i18n_sync.py        #   drift gate: every translation vs the English skeleton
    └── test_audit_*.py          #   per-audit-round regression suites (v026 x2, v027)
```

All scripts are covered by **590 tests** in [`tests/`](tests/) — black-box
subprocess tests that launch each hook exactly as Claude Code does (module-level
state, stdin, stdout buffering and exit codes all differ when a script is
imported instead), plus unit tests for the shared models and the three drift
gates. CI: ubuntu-latest × windows-latest × Python 3.13, `fail-fast: false`,
zero dependencies. The Windows leg is not box-ticking — several regressions here
are Windows-only by construction (`os.replace` sharing violations, `\r\n`
defeating end-of-line anchors, unquoted drive paths).

---

## New in v0.31.0

**The sync gate became inspectable.** Rule 12's co-update groups have been
enforceable since v0.23 and *authorable* only by hand-writing TOML — with no way
to see what the loader made of it. That gap mattered because
[`lib/sync_gate.py`](hooks/scripts/lib/sync_gate.py) is failing-open by design:
a dropped group, or a glob that matches no file, does not raise. It just stops
guarding, and prints one stderr line nobody reads.

**An unenforced gate you still trust is worse than no gate**, because you have
stopped looking. So:

```
$ /cc-enslaver:sync-gate check
  ok hooks-tests.when     'hooks/scripts/*.py' → 18 file(s)
  !! code-docs.require    'nowhere/*.rst'      → 0 file(s)

1 problem(s):
  • group code-docs: require glob 'nowhere/*.rst' matches NO file in the repo.
```

`check` reports every group the loader kept, every group it **dropped and why**,
and every dead glob — exiting 1, so it runs in CI. `init / add / remove / list /
path` round it out, mirroring the Imperial-Edict CLI that has had exactly this
treatment since v0.12.

**Deliberately not auto-created.** No hook writes into your project directory —
that invariant has held for every release, and an auto-created empty template
would be functionally identical to no file (zero groups means layer (i) stays
inert), bought at the price of an unrequested file in everyone's `git status`.
`init` creates it when *you* ask.

**Writes are verified twice.** Not just "does this parse" but "does the loader
still see every group" — a `require = []` entry is valid TOML that
`sync_gate.load()` silently discards, so a parse-only check would let the CLI
report success over a group that guards nothing. On failure the previous file is
restored byte-for-byte.

**A defect found in this feature's own first smoke test, reported here rather
than quietly fixed.** The CLI picked its write target with `config_path()` — the
resolver built for *reading*, which tries several roots and takes the first that
already holds a file. Run against a project with no config yet, it fell through
to the process cwd and wrote two groups into *this plugin's own* config. Root
cause: **"where do I read from" and "where do I write to" are different
questions**, and a read-resolver's fallback chain is precisely what makes it the
wrong answer to the second. Fixed at the mechanism — `default_project_path()`
(deterministic) and `load_file()` (no fallback) — with the class swept: both
call sites, both pinned by regression tests, and the read resolver's fallback
explicitly pinned too, so "fixing" it later by making everything deterministic
cannot silently break the hook path.

Also: `lib/tomlio.py` now owns the TOML *writer* as well as the reader, so the
edict CLI and the sync-gate CLI share one encoder instead of the second copy
missing the next fix. Suite 565 → 590 tests.

Earlier releases: [`CHANGELOG.md`](CHANGELOG.md).

---

## Contributing

The plugin enforces its own rules on its own development — expect to be denied
by it while working on it. Read [`CLAUDE.md`](CLAUDE.md) §4 before opening a PR:

1. Read every related file end-to-end before editing.
2. Trace downstream impact — editing a rule means updating the prompt, the docs,
   the checklist and the translation in the same change.
3. Cite `file:line`; never "I think" / "should be".
4. Fix root causes. No `--no-verify`, no swallowed errors.

---

## License

MIT — see [`LICENSE`](LICENSE).
