---
id: "02"
title: "Systematic, not reactive"
severity: must
---

# Rule 02 — Systematic, not reactive

## Principle

Code (or any) modifications must be **systematic** — **zero reactive** patches.

- **Reactive** = see symptom → patch the symptom → if no visible failure, stop.
- **Systematic** = see symptom → understand the architecture → find the
  root cause → assess connected impact → fix the root → verify globally.

## The seven questions (must self-answer before modifying)

Before editing any file, the agent must **ask and explicitly answer** all seven:

1. **Architectural location** — what is the full architecture; where in it is the part I want to change?
2. **Responsibility** — what is the current responsibility of this code? Who are its upstream callers and downstream consumers?
3. **Root cause** — what is the **root cause** of the problem / requirement? What is the mechanism?
4. **Does the fix bottom out?** — does my change actually solve the problem at the root, or merely mask the symptom?
5. **Connected impact** — what does this change ripple to? Which downstreams need to change in lockstep?
6. **Risk** — what existing invariants, contracts, or tests might break?
7. **Global validity** — after the fix, does the problem actually go away from a global perspective?

> If any answer is "I don't know" or "from memory", **go verify first** (rules 01 and 04), then return to this rule.

## Forbidden anti-patterns (chains of thought that are a hard no)

- ❌ "Bug looks like this → change this line → symptom gone → done"
- ❌ "Test failed → make the test pass → done" (without asking *why* it failed and whether the fix touches the cause)
- ❌ "Type error → cast to `any` → done" (defeats the type system's intent)
- ❌ "Exception → wrap in `try/except` → done" (see rule 03)

## Recommended chain of thought

> "I notice `auth.py:142` flakes 500s under concurrent requests.
>
> **Architectural location**: `auth.py` is step 3 of the login chain; upstream is `session.py:create_session`, downstream is `routes/login.py:88`.
>
> **Root cause**: `auth.py:142` writes `session.pending` without acquiring the lock, racing the cleanup coroutine in `session.py:expire_pending`.
>
> **Plan**: Acquire `session._pending_lock` at `auth.py:140-145`. This lock already exists for exactly this purpose, so the fix is architecture-aligned.
>
> **Connected**: `routes/login.py:88` does not need changes; the test `tests/test_auth_concurrent.py` already covers this scenario but is currently `skip`ped — remove the skip.
>
> **Risk**: lock is on the hot path, but the critical section is 3 lines — no measurable latency impact.
>
> **Global**: after the fix, the entire login chain has full lock coverage under concurrency; this is exactly what `session._pending_lock` was designed for."

## Self-check triggers

- About to make a change of fewer than 5 lines without going through the seven questions;
- The file being modified has not been **fully `Read`** this session;
- Have not read the call sites / dependents of this change;
- The change is "to make the test pass" or "to make the error go away" rather than "to make the logic correct".
