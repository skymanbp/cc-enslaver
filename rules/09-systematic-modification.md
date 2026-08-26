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
- Stuffing TODO / "for now" / "later" into new code;
- Fixing N symptoms of one root cause one at a time (point-to-point), instead of one unified fix at the diagnosed origin (v0.28 — enforced at the text/injection level; its same-file form is what the v0.13 frequency layer catches).

These are not "fixes" — they **defer** problems. Rule 09 elevates them to a hard prohibition and installs **physical interception** at the hook layer.

## Must do (MUST)

### Before modification

1. **Find the actual root cause** (rule 03) — not "where it throws", but "why it throws".
2. **Verify root-cause evidence** (rule 01 verification) — confirm the root-cause hypothesis *on the spot* via Read / Grep / command output.
3. **Map the impact** (rule 02 Q5) — list every upstream / downstream tied to the root cause.
4. **Compare ≥ 2 fix strategies** (rule 08 item 6) — across simplicity / performance / fit with existing architecture / future maintainability.

### One root cause, one unified fix (v0.28)

Point-to-point patching — treating each observed failure as its own
little fix — is forbidden. When a problem appears, the only accepted
shape is **trace upstream → diagnose → one unified fix**:

5. **Trace to the most-upstream cause** (rule 03 upstream ladder):
   climb the causal chain until the answer is a mechanism / design
   decision / missing invariant, and state explicitly why you stopped
   where you stopped.
6. **Diagnose before treating**: the root-cause hypothesis must be
   demonstrated by a first-party probe / reproduction / failing test
   (rule 01) *before* the first line of the fix is written.
7. **Enumerate the class, not the instance.** A diagnosed root cause
   defines a *class* of defects; the instance you observed is merely
   the one that happened to surface. Sweep the repo for every sibling
   of the class (Grep to locate, Read to confirm — rule 04; report the
   sweep — rule 12). Scope note: the sweep is part of fixing the
   reported problem, not scope creep — rule 07 bans *unrequested*
   changes. When the enumerated class materially expands the visible
   scope of the user's request, surface the enumeration and get the
   user's call before the one-pass fix.
8. **Fix the mechanism once.** One systematic change that removes the
   generating mechanism and covers every enumerated instance in the
   same pass. N symptoms sharing one root cause = **one** fix — never
   N patches, and never "fix the reported ones, leave the rest of the
   class". The unit of "one" is the mechanism, not the diff size:
   minimum effective change still applies.
9. **Prove the class is closed** (rule 06): re-trigger not only the
   observed instance but at least one *other* enumerated instance of
   the class. When the sweep shows the class has exactly one member,
   say so explicitly — the sweep report is then the closure evidence.

The instance-fix trap, measured on this repo: v0.25.1 named a root
cause and fixed only the instances it had seen; the mechanism survived
and regenerated a fresh crop of the same class by v0.26 — including
one regression. v0.26 then replaced the mechanism (33 findings → three
root causes → four shared models), which is exactly the shape this
section prescribes. A second failure with the same shape is the class
announcing itself — an obligation to test whether the origins are
truly shared, never a coincidence to ignore.

### During modification

10. **Fix the cause, not the symptom** (rule 03) — the edit point must sit at the source of the causal chain, not at the manifestation.
11. **Cover the full impact** — fix every connected point of the same root cause; never "fix one now and patch the rest later".
12. **Do not introduce patch markers** — see "Physical interception" below.
13. **Record new invariants** — if the change establishes a new invariant ("X is never None" / "must acquire the lock first"), declare it explicitly in code or docs.

### Bulk mechanical edits (rename / codemod / sed)

A regex that matches your intent also matches its homographs, and a bulk
rewrite is the one edit shape where a single bad rule corrupts hundreds
of files at once. Before running one:

1. **Survey first, write the rule second.** Enumerate what actually
   surrounds every occurrence of the target token and *read that list*.
   Homographs found this way in one real directory rename: an API
   version inside a URL (`…/v3/me`), a DB table version
   (`agent_subtypes v3/613`), a schema range (`Mesh v3/v4`), a **math
   variable** (`v3 = v2 * v1 + …`), a function parameter, and a report
   id (`DIV-V3`). A blind sed would have corrupted all six.
2. **Rewrite only allowlisted forms.** Never "replace everything that
   matches" — replace what the survey proved is the thing you mean.
3. **Emit a refusal report.** Every occurrence the allowlist declined is
   printed for a human to read. A silent skip is indistinguishable from
   a site you missed.
4. **Reconcile the arithmetic.** total occurrences = rewritten + skipped
   + refused. If it does not add up, the rule is wrong, not the count.
5. **Expect shapes the pattern is structurally blind to.** The token
   inside a regex alternation (`^(?:v3|docs)/` — followed by `|`, not by
   the separator you keyed on); the token as a standalone argument
   (`join(root, "v3", "assets")`); and the *symbol* named after it
   (`V3_DIR`). Each needs its own survey pass.
6. **Never rewrite a path that addresses history.**
   `git show <fixed-rev>:<path>` resolves against an old tree in which
   the old layout is still the correct one. Worktree paths move;
   history-addressing paths must not.

### After modification

14. Run rule 06 convergence — including Check 2b, since a bulk edit is
    exactly the case where totals stay equal while composition shifts;
    run rule 07 task fidelity.

## Physical interception (hooks)

| Layer | Hook | Trigger | Action |
|---|---|---|---|
| **Edit/Write content** | `PreToolUse(Edit\|Write)` | `new_string` contains an unjustified patch marker | **DENY** |
| **Edit/Write frequency** (v0.13) | `PreToolUse(Edit\|Write)` | same file, 4th "small edit" (≤ 10 lines AND < 200 chars) in one session without a systematic rewrite (≥ 50 lines / ≥ 1500 chars / **≥ 30% of the file**) in between. **Never counted** (v0.35): a net reduction, or a bookkeeping edit | **DENY** |
| **Bash command** | `PreToolUse(Bash)` | `--no-verify` / `--no-gpg-sign` / `chmod 777` / `git rebase --skip` / `--break-system-packages` / `rm -rf` on a root path / `git push --force` (not `--force-with-lease`) | **DENY** (v0.3 bash_guard, extended v0.14; matched against parsed argv since v0.26) |
| **Closing** | `Stop` layer (f) | this turn did Edit but the final reply lacks "root cause + impact + solution" markers | **BLOCK** |

### Edit/Write frequency layer — rolling-patch counter (v0.13)

The guard maintains a per-file small-edit counter at
`state.edits_per_file[path]`:

| Classification | Bounds | Counter action |
|---|---|---|
| **small** | max(\|old\|, \|new\|) < 200 chars **and** max line count ≤ 10 | +1 (if predicted to reach 4 → DENY, **no increment**) |
| **systematic** | max chars ≥ 1500 **or** max line count ≥ 50 **or** the change spans ≥ 30% of the target file, on either axis (v0.35) | reset to 0 |
| **medium** | between the two | no change |

A predicted reach of the threshold (4) triggers DENY and the counter is **not** incremented. Subsequent small edits to the same file therefore also DENY until a systematic rewrite resets the counter — which is exactly what rule 09 wants: **re-engage with the whole file structure, don't keep patching**.

#### Thresholds are relative to the file (v0.35)

The absolute floors alone made the counter **unrecoverable on small files**.
A file under 1500 characters and 50 lines admits no edit that can reach
"systematic" — a full `Write` of a 30-line module classifies as *medium*,
which neither counts nor resets — so three small edits locked that file for
the rest of the session, and the only legal move left was to pad it past
1500 characters. A gate against reactive patching, demanding the file be
made bigger.

The coverage route is therefore an **additional** way to qualify, never a
replacement: every change that was systematic before still is. Re-scaling
both ends instead (`max(1500, 30% of file)`) was rejected because it raises
the floor for large files and recreates the identical lock-in there.

Consequence, stated rather than hidden, with the measured number: this layer
goes inert only on files of about **five lines or fewer**, where a two-line
edit already spans a third of the file. From six lines up the absolute
small-edit definition still binds — a 30-line file still denies its fourth
two-line patch, because its coverage bar is 10 lines. That is intended —
*"you have not re-engaged with the file's overall structure"* is not a claim
anyone can make about a five-line file.

#### Two shapes are never counted (v0.35)

| Exempt shape | Test | Why it cannot be a rolling patch |
|---|---|---|
| **Net reduction** | `len(new) < len(old)` | A rolling patch is an *accretion* of small additions. An edit that leaves the file shorter than it found it is the opposite of the behaviour this layer exists to stop. |
| **Bookkeeping** | Both sides are byte-identical once numeric runs are elided, and every numeric position that moved holds the **same bookkeeping shape** on both sides — version (`1.2.3`) or ISO date (`2026-08-25`); in prose documents, bare integers too | Bumping a version number or a date is not a symptom fix. |

The bookkeeping allowlist is **shaped, not "any digit"**, precisely because
`timeout = 30 → 300` and `if n > 3 → n > 4` are also small numeric edits —
and this rule names lengthening a timeout and loosening an assertion as
forbidden. Bare integers are exempt only where neither exists: prose
documents, the same non-scannable set rules 10 and 11 exempt.

Both exemptions apply to **this frequency layer only**. The content
detectors run first and are untouched: an edit that deletes fifty lines and
plants one unjustified `# noqa` is still denied, because suppression has
nothing to do with which direction the file grew.

Recovery paths offered in the DENY message:
1. Combine the pending small fixes into a single systematic Edit (new_string ≥ 50 lines, ≥ 1500 chars, or ≥ 30% of the file);
2. Use `Write` to replace the file wholesale;
3. Stop and surface to the user that the file needs a refactor.

### Edit/Write content layer — patch-marker catalog

The following patterns, when present in `new_string` **without an accompanying "why" comment** justifying them, are intercepted:

| Pattern | Reason |
|---|---|
| `try:` … `except …:` … `pass` (all clauses, nested blocks, one-liners) | Silent exception-swallowing (rule 03) |
| `#\s*noqa\b` (without rationale) | Lint suppression (rule 03) |
| `#\s*type:\s*ignore\b` (without rationale) | Type-checker suppression (rule 03) |
| `//\s*@ts-ignore\b` / `//\s*@ts-expect-error\b` (without rationale) | TS suppression (rule 03) |
| `//\s*eslint-disable(?:-next-line)?\b` (without rationale) | Lint suppression (rule 03) |
| `time\.sleep(…)\s*#\s*(wait\|race\|workaround)` (nested calls included) | Sleep masking a race (rule 03) |

**Marker spelling is not the pattern (v0.25.1).** The five single-line markers no
longer require end-of-line:

- **CRLF no longer defeats them.** The old `[ \t]*(?:\n|$)` anchor cannot match
  `\r\n`, so on Windows every one of these detectors was silently off.
- **Trailing text no longer makes a marker invisible.** `// @ts-ignore: TODO`
  used to match *nothing at all* — it was allowed without the rationale check
  ever running, while the bare form was denied. Trailing text is now evaluated:
  an explanation justifies the marker, a bare deferral keyword (TODO / FIXME /
  HACK / WIP / later) does not.
- **Prose docs** (`.md` / `.rst` / `.txt` / `.adoc`) keep matching only the bare
  form, because there the markers are being discussed, not executed.

**Swallow-line scanning (v0.25, extended v0.25.1).** The `try/except: pass`
detector compares the **code** on the swallow line, not the raw text:

- A trailing comment no longer defeats it — `pass  # TODO later` is intercepted.
  Requiring an exactly-bare `pass` had made the why-comment escape hatch below
  *unreachable for this marker*: a rationale comment silenced the detector by
  changing the string, so the rationale was never actually read.
- A **comment line between the handler header and the swallow** no longer masks
  it either. That was the same defect one spelling over: a rationale written on
  its own line above `pass` — the most natural way to write it — moved the
  `pass` out of the scanner's sight, so the hatch stayed unreachable and the
  v0.25 regression test that claimed to pin it passed for the wrong reason.
- `except Exception: pass` **one-liners** are detected, **nested** `try` blocks
  are tracked (a stack, not a single pending indent), and **every** hit in an
  edit is inspected — a justified swallow no longer hides an unjustified one.
- Every `except` clause of a `try` statement is inspected, not just the first,
  so the canonical shape — a narrow handler followed by a catch-all that
  swallows everything (`except ValueError: log()` then `except Exception: pass`)
  — is no longer invisible.

**The rationale must be a comment (v0.25.1).** The hatch used to search the raw
±1-line window, so a token anywhere in executable code satisfied it —
`reason = compute()` next to a bare marker was enough. Only comment text counts
now, which is what the deny message always claimed.

**What counts as a comment is decided lexically (v0.26.0).** "Find the first `#`
or `//`" is not the same question as "where does a comment start": it found the
`#` inside `"http://host/#frag"` and the `//` inside *any* URL, so one
neighbouring line such as `API = "https://api.example.com"` silenced the
detector — and, via the shared hatch, the rule-10 secret detector with it.
Comment extraction now goes through a real lexer
([`lib/srclex.py`](../hooks/scripts/lib/srclex.py)), which also means:

- `/* … */` **block comments are honoured** (they were invisible before, so a
  legitimate adjacent JavaScript/TypeScript rationale was rejected);
- a why-note in a **docstring counts** — it is documentation, not data — while
  a token inside an ordinary string literal does not;
- the window is judged against the **whole text's** lexical state, not by
  re-lexing three lines in isolation (a slice inside a docstring carries no
  delimiter of its own and, judged alone, looked like bare code).

**The hatch is not English-only (v0.26.0).** Only the noun `原因` was listed, so
the most natural Chinese "because" (`因为`) was DENIED while English `because`
passed. `因为` / `之所以` / `理由` / `故意` / `刻意` / `有意` / `特意` are now
rationale tokens. Relatedly, the "reads like an actual explanation" heuristic
required an ASCII space, which no Chinese sentence has — it now measures CJK
length instead, so the same justification is accepted in either language.

**Markers end at a token boundary (v0.26.0).** Dropping the end-of-line anchors
in v0.25.1 left the markers as bare substrings, so `# noquality`,
`@ts-ignore-generated` and `eslint-disablement` were each read as the
suppression they merely start with, and DENIED.

**Acceptable form**: every suppression marker must carry a rationale on the same line, or on an immediately adjacent line, containing `because` / `原因` / `因为` / `why` / a concrete justification, e.g.:

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
- ❌ **Rolling patches**: ≥ 4 small Edits on the same file this session without a single systematic rewrite — reactive accumulation. As of v0.13 this is physically intercepted by the `PreToolUse(Edit|Write)` frequency layer, not just soft discipline. Net reductions and bookkeeping edits are exempt (v0.35) — neither accretes.
- ❌ **Fix one and leave three TODOs**: "I'll patch the rest later" is not allowed; one pass must cover the full root-cause impact.
- ❌ **Blind bulk replace**: running a rename / codemod / sed without first surveying the token's real neighbourhoods, without an allowlist, or without a refusal report of what it declined.
- ❌ **Rewriting history-addressing paths** during a move: a path handed to a fixed git rev must keep the layout that rev actually has.
- ❌ **Pattern blacklists where the invariant is a closed set**: if only a known list of names is legal, enumerate that list and reject everything else. Blacklisting the stray shapes you happen to have seen lets the next shape walk straight through — including on the gate's own first live run.
- ❌ **Point-to-point patching** (v0.28): fixing symptom sites one at a time — each observed failure gets its own little fix — when they share a root cause. Includes "fix what was reported, leave the unreported siblings".
- ❌ **Instance hardening** (v0.28): repairing the observed instance of a mechanism defect while leaving the mechanism in place to regenerate the class — hardening scoped to the sighting, never sweeping the class.

## Relationships

| Relationship | Note |
|---|---|
| 09 vs 03 | 03 lists specific lazy anti-patterns and owns the **upstream-tracing ladder** (v0.28); 09 **structures them into a general modification discipline** — including the unified-fix requirement — with physical interception. |
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
- About to run a rename / codemod / sed across many files without a survey, an allowlist and a refusal report.
- About to write a guard that enumerates *bad* shapes for an invariant whose specification is a *closed set of good ones*.
- About to fix the *second* failure with the same shape as one already fixed — the class is announcing itself; diagnose the shared origin instead of patching the sighting.
- About to write a fix without having stated where the causal chain stops and why.
- Chain-of-thought lacks the "root cause + impact + alternatives" triplet.

## Termination condition

"Modification complete" is allowed only when **all** of the following hold:

1. The **most-upstream** root cause has been diagnosed — causal chain stated, diagnosis demonstrated first-party (rule 03 upstream ladder + rule 01).
2. All connected points of the root cause have been covered (rule 02 Q5).
3. Every sibling instance of the diagnosed class has been enumerated and covered in the same pass — no point-to-point residue (v0.28 unified fix).
4. `new_string` contains no unjustified patch markers (read_guard patch-style check passes).
5. The **final reply** explicitly records the "root cause / impact / alternatives" triplet (Stop layer (f) passes). Layer (f) reads the final reply text only — a triplet that stayed in the chain of thought does not count.
6. Rule 06 convergence + rule 07 fidelity self-quizzes done.

Otherwise → **not systematic**, return to rule 02 + rule 03 + rule 08.
