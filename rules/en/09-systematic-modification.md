---
id: "09"
title: "Systematic modification, no patch-style"
severity: must
---

# Rule 09 — Systematic modification · no patch-style

## Principle

> **Modifications must be systematic and complete, not local patches.**

Typical patch-style modifications:

- Treating the symptom ("add an `if` to swallow the exception") instead of the root cause;
- Local `try / except: pass` / `# noqa` / `@ts-ignore` / `// eslint-disable` silencers without justification;
- Repeated small `Edit`s on the same file in the same session (rolling patches), each touching 1–3 lines;
- Wrapping a try at the call site to "fix" the symptom while the real bug is in the callee;
- Increasing the timeout / loosening assertions / making tests more permissive;
- Commenting out failing tests instead of fixing the code;
- Stuffing TODO / "for now" / "later" into new code.

These are not "fixes" — they **defer** problems. Rule 09 elevates them to a hard prohibition and installs **physical interception** at the hook layer.

## Must do (MUST)

### Before modification

1. **Find the actual root cause** (rule 03) — not "where it throws", but "why it throws".
2. **Verify root-cause evidence** (rule 01 verification) — confirm the root-cause hypothesis *on the spot* via Read / Grep / command output.
3. **Map the impact** (rule 02 Q5) — list every upstream / downstream tied to the root cause.
4. **Compare ≥ 2 fix strategies** (rule 08 item 6) — across simplicity / performance / fit with existing architecture / future maintainability.

### During modification

5. **Fix the cause, not the symptom** (rule 03) — the edit point must sit at the source of the causal chain, not at the manifestation.
6. **Cover the full impact** — fix every connected point of the same root cause; never "fix one now and patch the rest later".
7. **Do not introduce patch markers** — see "Physical interception" below.
8. **Record new invariants** — if the change establishes a new invariant ("X is never None" / "must acquire the lock first"), declare it explicitly in code or docs.

### After modification

9. Run rule 06 convergence; run rule 07 task fidelity.

## Physical interception (hooks)

| Layer | Hook | Trigger | Action |
|---|---|---|---|
| **Edit/Write content** | `PreToolUse(Edit\|Write)` | `new_string` contains an unjustified patch marker | **DENY** |
| **Edit/Write frequency** (v0.13) | `PreToolUse(Edit\|Write)` | same file, 4th "small edit" (≤ 10 lines AND < 200 chars) in one session without a systematic rewrite (≥ 50 lines / ≥ 1500 chars) in between | **DENY** |
| **Bash command** | `PreToolUse(Bash)` | `--no-verify` / `--no-gpg-sign` / `git push --force` / `chmod 777` | **DENY** (v0.3 bash_guard) |
| **Closing** | `Stop` layer (f) | this turn did Edit but the final reply lacks "root cause + impact + solution" markers | **BLOCK** |

### Edit/Write frequency layer — rolling-patch counter (v0.13)

The guard maintains a per-file small-edit counter at
`state.edits_per_file[path]`:

| Classification | Bounds | Counter action |
|---|---|---|
| **small** | max(\|old\|, \|new\|) < 200 chars **and** max line count ≤ 10 | +1 (if predicted to reach 4 → DENY, **no increment**) |
| **systematic** | max chars ≥ 1500 **or** max line count ≥ 50 | reset to 0 |
| **medium** | between the two | no change |

A predicted reach of the threshold (4) triggers DENY and the counter is **not** incremented. Subsequent small edits to the same file therefore also DENY until a systematic rewrite resets the counter — which is exactly what rule 09 wants: **re-engage with the whole file structure, don't keep patching**.

Recovery paths offered in the DENY message:
1. Combine the pending small fixes into a single systematic Edit (new_string ≥ 50 lines);
2. Use `Write` to replace the file wholesale (content ≥ 50 lines);
3. Stop and surface to the user that the file needs a refactor.

### Edit/Write content layer — patch-marker catalog

The following patterns, when present in `new_string` **without an accompanying "why" comment** justifying them, are intercepted:

| Pattern | Reason |
|---|---|
| `try:\s*\n[^\n]*\n\s*except[^:]*:\s*\n\s*pass` | Silent exception-swallowing (rule 03) |
| `^\s*#\s*noqa\b` (without immediately adjacent rationale comment) | Lint suppression (rule 03) |
| `^\s*#\s*type:\s*ignore\b` (without rationale) | Type-checker suppression (rule 03) |
| `//\s*@ts-ignore\b` (without rationale) | TS suppression (rule 03) |
| `//\s*eslint-disable(?:-next-line)?\b` (without rationale) | Lint suppression (rule 03) |
| `time\.sleep\([^)]*\)\s*#\s*(wait\|race\|workaround)` | Sleep masking a race (rule 03) |

**Acceptable form**: every suppression marker must carry a rationale on the same line, or on an immediately adjacent line, containing "because" / "原因" / "why" / a concrete justification, e.g.:

```python
# noqa: E501  -- URL string exceeds 100 chars; splitting hurts readability
LONG_URL = "https://..."
```

```typescript
// @ts-ignore: third-party lib has incomplete type, see issue #1234
const result = legacy.foo();
```

A bare marker without justification = laziness, intercepted.

## Must not (MUST NOT)

- ❌ **Symptom patching**: wrap the call site with try/except to make the exception vanish without changing the root cause.
- ❌ **Silent suppression**: `# noqa` / `@ts-ignore` / `// eslint-disable` without a why comment.
- ❌ **Race-via-sleep**: adding `time.sleep(0.5)` to stabilize a test ≠ fixing the race.
- ❌ **Loosening tests**: original asserts `X == 5`, you change to `X > 0` to make it pass.
- ❌ **Extending timeouts**: original `timeout=5s`, you push to `60s` to mask a performance issue.
- ❌ **Commenting out failing tests**: deleting / commenting / `@skip` to declare "done".
- ❌ **Rolling patches**: ≥ 4 small Edits on the same file this session without a single systematic rewrite — reactive accumulation. As of v0.13 this is physically intercepted by the `PreToolUse(Edit|Write)` frequency layer, not just soft discipline.
- ❌ **Fix one and leave three TODOs**: "I'll patch the rest later" is not allowed; one pass must cover the full root-cause impact.

## Relationships

| Relationship | Note |
|---|---|
| 09 vs 03 | 03 lists specific lazy anti-patterns; 09 **structures them into a general modification discipline** with physical interception. |
| 09 vs 02 | 02 is the thinking discipline before modification; 09 is the execution discipline during. They chain. |
| 09 vs 08 | 08 verifies "did you complete pre-action prep?"; 09 verifies "is the content systematic, not patch-style?". Pre vs content. |
| 09 vs 06 | 06 verifies "did the fix converge?"; 09 verifies "was the fix done systematically?". Process vs result. |
| 09 vs 07 | 07 verifies "did you deliver everything the user asked for?"; 09 verifies "was the way of delivering it patch-style?". Coverage vs implementation. |

## Self-check triggers

- About to make a ≤ 5-line "quick fix".
- About to write `try / except: pass` or `try / except: ...` with vague handling.
- About to write `# noqa` / `@ts-ignore` / `eslint-disable` **without** a rationale.
- About to add `time.sleep` to stabilize a test.
- About to loosen a test assertion / extend a timeout.
- Commenting out / `@skip`-ing any failing test.
- Already made ≥ 3 small Edits on the same file this session and still patching, not rewriting.
- Chain-of-thought lacks the "root cause + impact + alternatives" triplet.

## Termination condition

"Modification complete" is allowed only when **all** of the following hold:

1. Root cause has been found and verified (rule 03 + rule 01).
2. All connected points of the root cause have been covered (rule 02 Q5).
3. `new_string` contains no unjustified patch markers (read_guard patch-style check passes).
4. Chain-of-thought or final reply explicitly records the "root cause / impact / alternatives" triplet (Stop layer (f) passes).
5. Rule 06 convergence + rule 07 fidelity self-quizzes done.

Otherwise → **not systematic**, return to rule 02 + rule 03 + rule 08.
