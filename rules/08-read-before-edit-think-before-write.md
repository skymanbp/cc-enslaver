---
id: "08"
title: "Read before edit, think before write"
severity: must
---

# Rule 08 — Read-before-edit · think-before-write

## Principle

> **Editing and writing are separately bound by pre-action discipline.**
>
> - **Read before edit** — Before any `Edit`, you must have **fully Read** the target file, `Read` the surrounding context of every call site, and `Grep` the blast radius.
> - **Think before write** — Before any `Edit` / `Write`, you must **explicitly state in chain-of-thought or the final reply** *why* you are writing what you are writing (root cause + impact + alternatives compared).

Rule 04 governs "read fully"; rule 02 governs the "seven questions". Rule 08 **combines them into a single pre-action hard discipline** and adds **physical enforcement** (hooks):

- `PreToolUse(Read|Edit|Write)` already enforces "target file was Read in this session" before allowing Edit/Write (v0.3.2+).
- `PreToolUse(Edit|Write)` content-layer detects "patch-style" markers (see rule 09).
- **Stop hook layer (e)**: at end-of-turn, if any `Edit`/`Write` happened this turn, the final reply **must include a "systematic self-answer" marker** (≥ 3 keywords from rule-02's seven questions: architecture / responsibility / root cause / solution / impact / risk / global). Otherwise → block.

## Must do (MUST)

### Pre-edit (read-before-edit)

1. **Read the target file completely** — not the diff context, not the grep hit line, the **whole file**. For oversized files, partition and read every relevant function / section.
2. **Read the call sites completely** — `Grep` every reference to the symbol; `Read` ≥ 20 surrounding lines for each.
3. **Read connected files** — Editing `rules/*.md` requires Reading `prompts/`, `commands/`, the entries in `docs/ARCHITECTURE.md` §8 connected-files map.
4. **Trust the current file state over memory** — what you Read last session may have changed; re-Read in this session before editing.

### Pre-write (think-before-write)

Before any `Edit` / `Write`, explicitly answer in chain-of-thought or final reply:

1. **Root cause** — Why am I making this change? What is the mechanism behind the problem / requirement? (rule 02 Q3)
2. **Architecture location** — Where in the architecture does the modified part sit? What is its responsibility? (rule 02 Q1-2)
3. **Bottom-out solution** — Does my change actually solve the problem at its base, or merely mask a symptom? (rule 02 Q4)
4. **Impact** — Which downstream / call sites / tests need to change in sync? (rule 02 Q5)
5. **Risk** — Which invariants, contracts, tests might break? (rule 02 Q6)
6. **Alternatives compared** — Which alternative approaches did I consider? Why this one?

> If any of the six answers is **"I don't know / on instinct / probably"** → **Read / Grep / verify first**, then return.

## Physical enforcement (hooks)

| Stage | Hook | Trigger | Action |
|---|---|---|---|
| pre-edit | `PreToolUse(Edit\|Write)` | target file exists but was not Read in this session | **DENY** (v0.3.2 read_guard) |
| pre-write (content layer) | `PreToolUse(Edit\|Write)` | `new_string` contains patch-style markers (un-justified `try:...except:pass` / `# noqa` / `@ts-ignore`) | **DENY** (v0.11 patch-style detector, see rule 09) |
| post-write (closing) | `Stop` layer (e) | `turn_count == last_edit_turn` but last assistant message lacks "systematic self-answer" markers (< 3 rule-02 keywords) | **BLOCK** (v0.11) |

## Must not (MUST NOT)

- ❌ **Edit on grep hits**: grep is a locator, not an understanding tool.
- ❌ **Edit from memory**: "I read this last session" ≠ "I have re-Read the current content in this session".
- ❌ **Edit without reading connected files**: changing `rules/0X-*.md` without Reading `prompts/` and `docs/RULES.md` immediately breaks the sync contract.
- ❌ **Submit Edit without recording "why"**: if chain-of-thought / final reply has no explicit root cause / impact / solution, you violate think-before-write.
- ❌ **Bypass read_guard's DENY then call register_read with a hash you didn't actually read**: defeats the hash gate.

## Relationships

| Relationship | Note |
|---|---|
| 08 vs 04 | 04 specifies "read fully" semantically; 08 is its **pre-action physical-enforcement** entry point (read-before-edit hook). |
| 08 vs 02 | 02 is the full "seven questions"; 08 is its **minimum required subset** (six questions) plus a "must record explicitly" hard requirement. |
| 08 vs 09 | 08 governs "did you complete pre-edit discipline?"; 09 governs "is the content itself patch-style?". Pre-action vs content; complementary. |
| 08 vs 06 | 06 is post-edit convergence; 08 is pre-edit preparation. `before → during → after` are now fully covered. |
| 08 vs 07 | 07 verifies "did you deliver everything the user asked for?" at closing; 08 verifies "did you prepare sufficiently before editing?" up front. |

## Self-check triggers

- About to `Edit` a file you have not Read **completely** in this session.
- About to `Edit` without Grep'ing the blast radius / Reading call sites.
- About to submit `Edit` without having recorded root cause + impact + solution in chain-of-thought.
- Editing `rules/*.md` without Reading `prompts/session-start.md` and `prompts/user-prompt.md`.
- Editing a hook script without Reading `hooks/hooks.json`, `docs/ARCHITECTURE.md` §8, and the corresponding `tests/test_*.py`.
- About to do a "quick fix" of < 5 lines (easy to skip pre-action discipline).

## Termination condition

`Edit` / `Write` is allowed only when **all** of the following hold:

1. The target file has been Read in this session (read_guard does not DENY).
2. All call sites / connected files have been Read (manual self-check + Stop layer (e) backstop).
3. At least 3 of the six items (root cause / architecture / solution / impact / risk / alternatives) are explicitly recorded in chain-of-thought or final reply.
4. `new_string` contains no patch-style markers (see rule 09 physical interception).

Otherwise → **read-before-edit / think-before-write not met**, return to Read / Grep / verify.
