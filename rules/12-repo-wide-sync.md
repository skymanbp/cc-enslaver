---
id: "12"
title: "Repo-wide sync — co-update every reference"
severity: must
---

# Rule 12 — Repo-wide sync: co-update every reference

## Principle

> **An edit is not finished when the target file is correct — it is
> finished when every place in the repository that references, consumes,
> documents, mirrors, or derives from the changed content has been
> updated in the same change, or explicitly confirmed current.** And a
> repository accumulates rot between edits, so it must also be sweepable
> on demand for stale, outdated, redundant, wrong, and drifted content.

Editing one file and walking away is the single highest-yield laziness
pattern this rule pack had not yet made physical: the code changes, the
README still describes the old behavior, the downstream caller still
passes the old argument, the translation still mirrors the old text,
the test still pins the old count. Every one of those is a lie the repo
now tells its next reader. Rule 04/08 already force reading the
connected files *before* the edit; rule 12 forces *writing* (or
explicitly clearing) them after.

## Scope — two halves

| Half | Trigger | Mechanism |
|---|---|---|
| **Passive** — per-edit co-update | every Edit / Write session | co-update discipline + the project **sync gate** (Stop layer (i), hard) |
| **Active** — whole-repo refresh | on demand ("全库更新" / "repo refresh" / "stale scan") | the `repo-refresh` skill: systematic sweep for stale / outdated / redundant / wrong / drifted content |

## Passive half — per-edit co-update discipline

After (not instead of) the rule 08 read-before-edit work, every edit
must close with a reference sweep:

1. **Enumerate the reference set** — Grep the edited symbols, file
   names, counts, version strings, and concepts across the whole repo
   (code *and* docs *and* tests *and* translations). Grep locates;
   this list is the co-update candidate set.
2. **Classify each candidate** — *must-change* (it encodes the old
   fact) vs. *verify-only* (it references the area but is still
   correct). "I didn't look" is not a class.
3. **Update every must-change in the same session** — downstream code,
   documentation that states the changed fact, tests that pin it,
   mirrors/translations that copy it.
4. **Say the sweep out loud** — the closing reply names what was
   co-updated and what was verified-and-unchanged (a `同步核对:` /
   `sync-check:` line). A sweep that is not reported is
   indistinguishable from a sweep that never happened.

### The sync gate (project-level hard layer)

Each project can register its known co-update invariants in a committed
config — the "代码门禁" that makes the passive half physical:

```toml
# .claude/cc-enslaver/sync-gate.toml
[[groups]]
name = "rules-fanout"
when = ["rules/*.md"]                       # editing any of these ...
require = ["prompts/*.md", "docs/RULES.md"]  # ... requires touching one of these
note = "Editing a rule fans out to the injected prompts + the index."
```

Semantics: if any file edited this session matches a `when` glob and
the `require` side is not satisfied, Stop layer (i) blocks the
done-claim — unless the reply explicitly acknowledges the check with a
sync marker (`同步核对` / `sync-check` / `rule 12`). An optional
`mode = "all"` demands *every* `require` glob be matched by some edit
(for lock-step invariants like version manifests); the default `"any"`
is satisfied by one. The escape hatch is deliberate: "I checked the
require side and it needs no change because X" is a legitimate outcome;
the gate forces the check to be *said*, not the files to be touched
blindly — and an acknowledged group is remembered for the session
(`sync_acked_groups`), so one explicit answer suffices and later
unrelated edits are not re-blocked by it. Globs match project-relative
paths (fnmatch; `*` crosses separators). No config file → the gate is
off for that project (opt-in). The gate is a floor, not the ceiling:
groups encode the *known* invariants; the discipline above still covers
the rest.

## Active half — whole-repo refresh

The passive half keeps each edit honest; it cannot retire rot that is
already there. The `repo-refresh` skill (auto-invoked on "全库更新" /
"stale scan" / "audit the repo" language) sweeps the entire repository
— docs and code — against five defect categories:

| Category | What it looks like |
|---|---|
| **Stale (陈旧)** | references to files / symbols / paths that no longer exist; long-dead TODOs; instructions for removed workflows |
| **Outdated (过时)** | counts, versions, dates, behavior descriptions that were true at some commit and are false at HEAD |
| **Redundant (冗余)** | the same fact stated in N places with no single source; dead code; superseded docs kept "just in case" |
| **Wrong (错误)** | claims contradicted by the current code — wrong defaults, wrong CLI flags, wrong file:line |
| **Drifted (漂移)** | pairs that must mirror each other (doc ↔ code, skeleton ↔ translation, config ↔ consumer) that have diverged |

Every finding must carry `file:line` evidence and be either fixed or
explicitly reported — a scan that only produces vibes is a rule 01
violation.

## Physical interception (hooks)

| Layer | Hook | Trigger | Action |
|---|---|---|---|
| **Stop closing** | `Stop` **layer (i)** | edit turn + a configured `when` group matched with no `require` edit and no sync marker in the reply | **BLOCK** |

Layer (i) is per-project opt-in (no `sync-gate.toml` → never fires),
edit-turns only, and covered by the same one-shot guard / 3-turn grace
window as every other Stop layer. Loader and evaluator are
failing-open: a malformed config can never block by accident.

## Must do (MUST)

1. **Grep before closing** — enumerate the repo-wide reference set of
   everything you changed; classify each hit.
2. **Co-update in the same session** — must-change references, docs,
   tests, mirrors move together with the primary edit.
3. **Report the sweep** — name the co-updated files and the
   verified-unchanged ones in the closing reply.
4. **Register known invariants** — when a co-update pair bites twice,
   add it as a sync-gate group so the third time is physically caught.

## Must not (MUST NOT)

- ❌ Edit the implementation and leave the doc/README describing the old
  behavior.
- ❌ Rename / re-number / re-count something and update only the
  definition site, not the references.
- ❌ Pass the gate with a sync marker that asserts "no change needed"
  without having actually checked (that is a rule 01 lie, and layer (g)
  file-claim style honesty applies).
- ❌ Treat a green sync gate as proof the whole repo is consistent — the
  gate checks its registered groups only (rule 06 Check 2b: scope of
  evidence ≠ scope of claim).

## Relationships

| Relationship | Note |
|---|---|
| 12 vs 04/08 | 04/08 are input-side: read the connected files *before* editing. 12 is output-side: write (or clear) them *after*. Same connected-file map, opposite direction. |
| 12 vs 06 | 06 verifies the edited part converged; 12 verifies the *rest of the repo* moved with it. A fix can pass 06 and still strand ten stale references. |
| 12 vs 07 | 07 audits against the user's request; 12 audits against the repo's internal reference graph — implicit obligations no user message spells out. |
| 12 vs 09 | 09's bulk-edit discipline governs *how* a repo-wide rewrite is executed; 12 governs *whether* the co-update set was covered at all. |

## Self-check triggers

- You changed a count / version / name / path / behavior and are about
  to close without grepping for its other occurrences.
- The phrase "the doc can be updated later" is forming.
- You edited an English skeleton file and did not open its translation
  (or vice versa).
- You are describing the change as "local" in a repo where a sync-gate
  group names that very file pattern.

## Termination condition

An edit session may close only when **one** of:

1. Every repo-wide reference of the changed content was updated or
   verified current, and the closing reply reports the sweep; or
2. The unmet remainder is explicitly surfaced to the user as unfinished
   (rule 07 half-finish declaration), not silently dropped.

Otherwise → stale references are being shipped; return to the sweep.
