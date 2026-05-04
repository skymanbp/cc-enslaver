---
id: "07"
title: "Task fidelity"
severity: must
---

# Rule 07 — Task fidelity (request coverage / no-degrade)

## Principle

**Fixed it ≠ done.** Rule 06 checks "did the part I edited technically converge?". Rule 07 checks "did I do **everything the user asked for**, at the **standard they asked for**?".

Before claiming completion, the agent **must** explicitly answer:

1. What sub-tasks does the user's original request break into?
2. Did I do **every one** of them? (no omission)
3. Did I meet the **exact standard** the user demanded? (no degrade, no concept-swap, no relaxation)
4. Did I introduce changes the user **didn't ask for**? (no scope creep)

> Common laziness modes that rule 06 cannot catch:
> - User asks for A, B, C — agent does A, B and quietly skips C.
> - User asks "fix and add tests" — agent fixes only.
> - User asks "refactor the whole module" — agent only touches the entry function.
> - User asks for X — agent decides Y is "better" and ships Y without asking.
> - User asks for "comprehensive validation" — agent runs one happy path and declares done.
> - Agent leaves `TODO` / "for now" / "later" but writes "done" at the end.
>
> The fixed part technically converged (rule 06 satisfied), but the user got short-changed. Rule 07 nails this side at the wrap-up.

## Must do

### Check 1 — Decompose the original request

Go back to the user's *original* message (not your in-flight rewrites). Break it into **independently checkable sub-items**:

- Explicit verb commands ("add X / fix Y / delete Z / verify W").
- Stated standards ("strict / comprehensive / mandatory / hard-enforced / all").
- Implicit dependencies (asking for "a new rule" usually implies: rule file + index update + prompt injection + tests, per project conventions).

### Check 2 — Mark every sub-item

For each:

- ✅ **Done** — attach `file:line` or command evidence.
- ⚠️ **Degraded / partial** — say which corner was cut, why, and whether the user agreed.
- ❌ **Not done** — tell the user explicitly, with the reason (blocked / out of scope / conflicts with other constraints).

"Mostly covered" / "should be there" / "main parts done" are **not** acceptable.

### Check 3 — Standard adherence

For every modifier the user used, prove the standard was met:

| User's word | Evidence required (cannot be glossed) |
|---|---|
| "mandatory / hard / strict / forced" | Implementation lands as a **hook block / test assertion** — not just a doc line. |
| "comprehensive / complete / thorough" | Enumerated list + boundary coverage. |
| "rigorous" | Explicit non-allowed cases + verification that they're rejected. |
| "all / every" | Enumeration + count. |
| "immediate / on-the-spot" | Show the activation path. |

If the user said "mandatory" but you shipped "soft suggestion", that's a degrade — fix it or actively tell the user.

### Check 4 — No scope creep

- Did you do refactors / renames / abstractions the user did not ask for? Without asking? That violates "minimum effective change" — and it's rule 07's territory.
- Did you touch files unrelated to this task? List them; they should be a separate PR / commit, or at minimum disclosed in the wrap-up.

### Check 5 — Surface every half-finished piece

- Any `TODO` / `FIXME` / "for now" / "do later" / commented-out tests **must be listed in the final reply** — not buried in code while the message says "done".
- If the user did not approve such a half-finish, the conversation should end on "I did A, B; C is not done because…; want me to continue / change approach / accept as-is?" — not on a completion claim.

## Mandatory three-question self-quiz (in final reply or chain of thought)

After checks 1–5, the agent must explicitly answer:

1. **Coverage** — How many sub-items did the user's original request decompose into? Which did I do? Which did I not do, and why?
2. **Standard** — Which modifiers did the user use (mandatory / complete / strict / all / immediate / comprehensive)? Did I land each one as a verifiable hard action, or did some end up as soft documentation?
3. **Fidelity** — Did I concept-swap (user asked for A, I did a subset of A / an approximation of A / something related to A but not A)? Did I add changes the user didn't request?

If any answer is "I don't know" / "should be" / "roughly" / "main parts" → **not faithful**, return to check 1.

## Must not

- ❌ **Silent degrade** — "I made it a soft suggestion" when the user asked for hard enforcement. Any degrade must be **disclosed** and approval requested.
- ❌ **Silent trim** — user listed 5 items, reply covers 3, the rest pretend not to exist.
- ❌ **Concept swap** — user said "on every X add Y", agent adds Y on "main X" and treats "main" as "every".
- ❌ **Tests-pass-equals-done** — rule 06 covers "is the edited part correct?", rule 07 covers "is everything the user asked for actually edited?". A test suite cannot answer the latter (tests cover code that exists; they don't know about the code you forgot to write).
- ❌ **Half-finished as done** — `TODO` left in the code while the reply says "completed"; empty stub while the reply says "implemented".
- ❌ **Out-of-scope changes as a "freebie"** — drive-by refactors / renames / abstractions are not in scope; they pollute the commit and add review burden.
- ❌ **Substituting rule 06 evidence for rule 07** — different axes; both must be answered separately.

## Relationships

| Relationship | Note |
|---|---|
| 07 vs 06 | 06 verifies the part you edited; 07 verifies the totality the user asked for. The two solve different axes — symptom-vs-rootcause for 06, request-vs-delivery for 07. |
| 07 vs 02 question 5 ("connected impact") | 02 is pre-edit ("what will my change affect?"); 07 is post-edit ("did I do everything the user asked for?"). |
| 07 vs 03 (root cause vs symptom) | 03 prevents bypassing the root cause; 07 prevents bypassing the user's request. Two faces of the same laziness. |
| 07 vs 05 (citations) | Rule 07's per-item evidence must follow rule 05 (`file:line` / command output). |
| 07 vs "minimum effective change" | The minimum-effective-change principle forbids scope creep; rule 07 check 4 is its enforcement entry point. |

## Self-check triggers

- About to write "done / fixed / completed / resolved" without re-reading the user's original message.
- About to move on to the next topic.
- The user's message contains "mandatory / strict / comprehensive / all / every / immediate / forced / hard-enforced", but your implementation is "soft suggestion / documentation reminder / partial".
- You did refactors / abstractions / renames the user did not request.
- You left any `TODO` / `FIXME` / commented-out code / half-finished piece.
- The user listed N items; your reply covers fewer than N without explanation.
- The user's request contains "double-check / second-pass / wrap-up verification", and you've only done rule 06.

## Termination condition

The agent may claim "done" only when **all** of the following hold:

1. Check 1 — original request was explicitly decomposed.
2. Check 2 — every sub-item is marked ✅ / ⚠️ / ❌ with evidence.
3. Check 3 — every modifier word has a corresponding hard-evidence anchor.
4. Check 4 — no scope creep (or it's been disclosed).
5. Check 5 — every half-finish has been surfaced (if any).
6. The three-question self-quiz has traceable answers.

Otherwise → **not faithful**, keep working or stop and align with the user.
