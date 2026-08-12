---
id: "03"
title: "Fix root causes, not symptoms"
severity: must
---

# Rule 03 — Fix root causes, not symptoms

## Principle

When errors, failures, or exceptions appear: **find the cause, don't
mask it**. Bypassing checks, silencing errors, or papering over a race
with `sleep` is **technical debt**, not a fix.

## Upstream tracing (v0.28) — the first cause you find is rarely the root

Causes come in chains, and every failure has three kinds of location:

| Level | What it is | Fixing here is |
|---|---|---|
| **Symptom site** | where the failure surfaces — the raised exception, the wrong output, the red test | a patch |
| **Propagation path** | the code the bad state flowed through on its way to the surface | still a patch |
| **Origin** | the mechanism / design decision / missing invariant that *generates* the bad state | the fix |

The levels can coincide: when the origin *is* the symptom site, fixing
there *is* fixing the origin. What is banned is stopping at the surface
without having asked the question.

When a problem appears, point-to-point patching at the symptom site is
forbidden. The mandatory order is **trace upstream → diagnose → fix**:

1. **Climb the chain.** Starting from the failure, keep asking "what
   produced *this*?" until the answer is a mechanism, a design
   decision, or a missing invariant — not yet another symptom. Record
   each hop with `file:line` evidence (rule 05).
2. **Stop climbing only for a stated reason.** The true origin may sit
   out of reach — a vendor bug, a platform contract, another repo.
   Fixing at a lower node is then legitimate, but only explicitly:
   name the actual origin and say why the fix lands downstream of it.
   An unstated stop is a patch with better paperwork.
3. **Confirm the diagnosis before treating.** Demonstrate first-party
   — probe, reproduction, failing test — that the suspected origin
   actually produces the observed symptom(s) (rule 01). A diagnosis
   that has not been demonstrated is a guess wearing a lab coat. An
   emergency mitigation may precede full diagnosis only when it is
   explicitly labeled as mitigation — recorded debt (rule 07), never
   reported as the fix.
4. **Fix once, at the diagnosed origin** — one unified change covering
   every instance the origin generates (rule 09 "one root cause, one
   unified fix").

Measured on this repo itself: v0.25.1 correctly *named* a root cause —
detectors that described a *string* instead of the *concept* — and
then fixed the instances it had seen. The mechanism survived, and the
next audit (v0.26) found a fresh crop of the same class, including one
regression. Fixing instances of a mechanism defect is symptom-patching
one level up.

## Forbidden anti-pattern catalogue

| Anti-pattern | Why it's lazy | What you should do |
|---|---|---|
| `try: ... except: pass` | Silences errors, loses diagnostic info | Let the exception propagate, OR record + handle correctly |
| `--no-verify` to skip git hooks | Hooks are there to stop bad commits; bypassing = shipping bad code | Fix the actual hook failure |
| `time.sleep()` to "fix" a race | Behaves differently on fast/slow machines; treats symptom not cause | Fix the synchronisation primitive (lock, condvar, await) |
| `// @ts-ignore` / `# type: ignore` | The type system is warning for a reason | Fix the type, OR comment **why** the ignore is principled |
| `if (false)` to disable a test | Silently removes coverage | Fix the test OR delete it with rationale |
| `pip install --force-reinstall` | Doesn't resolve the dependency graph | Resolve the graph; use a lock file |
| `chmod 777` | Creates a security hole | Identify the actual owner / process and grant precisely |
| `rm -rf node_modules && reinstall` as a panacea | You don't know what you actually fixed | Find which dependency broke and why |
| 10× the timeout | Turns a latency bug into a slower latency bug | Find why it's slow |
| Loosen the test assertion | The test loses its meaning | Fix product code OR update the expectation explicitly |

## Must do

- Inside any `except` block: either **log + re-raise**, or have a **specific recoverable handling path** with a one-line comment explaining why.
- Any `--no-verify` use: must have explicit user authorisation (otherwise it is a rule violation).
- Any `sleep` / `wait`: must wait for a specific event, not "long enough".
- Any type/lint ignore comment: must explain **why** this ignore is justified.
- Any fix: state the causal chain first — symptom site → propagation → origin — and where on it the edit lands; stopping short of the origin requires the stated reason from "Upstream tracing" above.

## Self-check triggers

- About to write `except: pass` / `except Exception: pass`;
- About to write `time.sleep(N)` in tests or sync code;
- About to add `--no-verify` / `--force` / `--skip-*`;
- About to add `@ts-ignore` / `type: ignore` / `# noqa`;
- About to comment out a failing test;
- About to "redeploy" or "restart the service" as the fix;
- The failure has the same shape as one already fixed before — a class is announcing itself; climb the chain instead of patching the new sighting;
- About to fix at the line that throws, without asking what produced the bad state that reached it.

> When triggered, the right move is: **stop**, walk through rule 02's seven
> questions, understand the mechanism first.
