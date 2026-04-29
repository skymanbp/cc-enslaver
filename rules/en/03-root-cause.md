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

## Self-check triggers

- About to write `except: pass` / `except Exception: pass`;
- About to write `time.sleep(N)` in tests or sync code;
- About to add `--no-verify` / `--force` / `--skip-*`;
- About to add `@ts-ignore` / `type: ignore` / `# noqa`;
- About to comment out a failing test;
- About to "redeploy" or "restart the service" as the fix.

> When triggered, the right move is: **stop**, walk through rule 02's seven
> questions, understand the mechanism first.
