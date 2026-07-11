---
id: "06"
title: "Verify-and-converge (post-fix)"
severity: must
---

# Rule 06 — Verify-and-converge (post-fix verify-and-converge)

## Principle

**Done editing ≠ problem solved.** After any fix, update, or patch,
the agent **must** actively verify that the change actually rooted out
the problem. If verification reveals an unresolved part (symptom
still reproduces / boundary still broken / new regression introduced),
**you are forbidden from claiming "done"** — return to rule 02's seven
questions, re-analyse the root cause, re-fix, re-verify, **until
convergence**.

> "Looks right" / "should be fine" / "tests pass" / "works on my
> machine" — none of these are convergence.
>
> Convergence means: **traceable evidence that the original symptom no
> longer occurs + boundary cases still behave + no new regressions.**

## Must do

After modifications, run **every** check below in order:

### Check 1 — Re-trigger the original symptom

- Re-run the **exact command / input** the user originally reported failing.
- Paste the new output. Show explicitly that "the original error / behaviour is gone".
- Running only the related tests is **not** a substitute — test inputs may not match the user's input.

### Check 2 — Boundaries and counter-examples

- **Beyond the happy path**: error paths, empty inputs, exception types, concurrency, resource exhaustion, file-not-found, permission-denied, cross-platform paths, CJK / Unicode / NUL bytes, etc.
- Run at least **one negative case** (a scenario that should still fail does still fail).
- Compare **before vs after**: when measurable, give numbers (latency, count, size, hash) — don't just say "looks faster".

### Check 3 — Connected non-breakage

- Run the existing test suite / lint / type-check; attach output.
- Inspect the downstream callers of changed files: do they still hold?
- If the change touched a public contract (function signature, return type, config schema), **list every call site**.

### Check 4 — Mandatory four-question self-quiz

After steps 1–3, the agent must explicitly answer (in the chain of thought or final reply):

1. **Did I really solve the problem?** What concrete evidence do I have? How does that evidence rule out "coincidence / cache / environment difference"?
2. **Is there a better way?** Compared on *simplicity / performance / maintainability / fit to existing architecture* — does my approach lose to an alternative? If yes, why am I not picking the alternative?
3. **Have my changes been verified?** Which line of code / which connected concern was **not** touched by checks 1–3? Why doesn't it need to be?
4. **Is the verification meaningful?** Do the tests / commands / comparison cases I ran actually exercise the failure mechanism? Do they cover the root-cause causal chain (rule 03)?

If any answer is "I don't know" / "should be fine" / "more or less" → **not converged**, return to rule 02.

### Check 5 — Quantitative beats qualitative

- "Faster" → benchmark with numbers.
- "Correct" → specific input → expected output → actual output.
- "Stable" → re-run N times (N ≥ 10 for race-related fixes), list failure count.
- "Compatible" → list the specific environments tested (OS, version, config combinations).

## Must not

- ❌ "No errors after the change → problem solved" — running ≠ correct.
- ❌ "Tests pass → done" — coverage < 100% is the norm; tests may miss the very scenario you are fixing.
- ❌ "Works on my machine → ship it" — other environments, CI, the user's machine are different distributions.
- ❌ "Looks right" — claiming without evidence is a double rule violation (01 + 06).
- ❌ "I fixed a similar one before, should be similar" — memory-dependence + verification skip (rule 04 + 06).
- ❌ "No time / user is waiting / good enough for now" — half-finished delivery; you will return to refix this.
- ❌ Have the agent self-review its own diff alone as "verification" — your bias is the source of non-convergence.

## Form of evidence (extending rule 05)

Every required check produces evidence that must be traceable:

- Command + relevant output:
  ```
  $ pytest tests/test_auth.py -v
  ===== 21 passed in 1.12s =====
  ```
- `file:line` references + before/after snippets;
- Links to commit / PR / CI run.

A claim of "verified" without evidence is equivalent to a rule-01 violation.

## Relationships with other rules

| Relationship | Note |
|---|---|
| 06 vs 02 question 7 ("globally, is the problem solved?") | 02 is *pre-action* global thinking; 06 is *post-action* global verification. Complementary. |
| 06 vs 03 (root causes) | 03 decides **what to change** to touch the root cause; 06 verifies **after the change** that the root cause has actually been removed. |
| 06 vs 01 (verify, don't guess) | 01 constrains input-side claims; 06 constrains output-side claims. Both share the "no claim without evidence" principle. |
| 06 vs 05 (traceable citations) | The evidence produced by verification is itself subject to 05's citation norms. |

## Self-check triggers

- About to write "solved" / "done" / "should be fine" / "fixed";
- About to move on to the next task / close the conversation;
- Tests passed but you did not manually re-trigger the user's original symptom;
- About to propose a fix without first answering "how will I verify it actually fixes this?";
- One of checks 1–3 was skipped / "not necessary" without **why**;
- Any of the four self-questions was answered with a vague hedge.

> When triggered, the right move is: **stop**, fill in the evidence; if
> the evidence shows the problem is unresolved, **acknowledge it** and
> return to rule 02 to restart.

## Convergence = termination condition

The agent may claim "done" only when **all** of the following hold:

1. Check 1 (re-trigger original symptom) ran; output shows symptom gone.
2. Check 2 (boundary / counter-examples) covered ≥ 1 boundary + 1 negative.
3. Check 3 (connected) ran with no new failures.
4. Check 4's four self-questions all have traceable evidence.
5. Check 5 — for performance / race / compatibility scenarios, quantitative comparisons are present.

Otherwise → **not converged**, keep working.
