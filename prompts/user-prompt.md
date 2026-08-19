# cc-enforcer — Decision-time triggers (per-turn injection)

> Self-check before replying: any **hit** below → stop, verify or add
> the missing step before continuing.
> 🚨 Physical-enforcement hooks will DENY tool calls / BLOCK Stop when
> you try to skip.

## Decision triggers (writing or about to do → self-check immediately)

| You wrote / want to do | Trigger | Physical consequence |
|---|---|---|
| "应该是 / 大概 / 我觉得 / I think / maybe / probably" within 50 chars of a done-claim (bare "should" / "应该" are deliberately NOT detected — only first-person uncertainty is) | rule 01 + 06 hedge | Stop layer (b) BLOCK |
| Cite a file not Read this session (violates **read-before-edit**) | rule 04 + 08 | **PreToolUse(Edit\|Write) DENY** |
| About to do a ≤ 5 line "quick fix" without 7 questions, missing **think-before-write** | rule 02 + 08 | — |
| About to write `try/except: pass` / `# noqa` / `# type: ignore` / `@ts-ignore` / `@ts-expect-error` / `eslint-disable` without why | rule 09 | **PreToolUse(Edit\|Write) DENY** |
| Patching locally instead of **systematic** modification (rolling patches / wrap-and-swallow) | rule 09 | rule 09 DENY (if suppression marker has no why) |
| About to patch at the symptom site without climbing the causal chain to the most-upstream origin, stating why you stop there, and demonstrating the diagnosis first-party | rule 03 upstream ladder (v0.28) | Stop layer (f) BLOCK when the edit turn lacks the root-cause triplet (ladder position itself is text-level) |
| Fixing the *second* failure of the same shape one-by-one instead of diagnosing the shared root cause and sweeping its class in one unified fix | rule 03 + 09 unified fix (v0.28) | same-file pile-up → **PreToolUse(Edit\|Write) DENY** (v0.13); the cross-file form is text-level |
| About to `time.sleep()` to mask a race / comment out failing tests / loosen asserts | rule 03 + 09 | rule 09 DENY (for new code) |
| About to inline a secret / API key / provider token (`ghp_…` `xox…` `AIza…`) / private key / credentials-in-a-URL as a **code** literal (should be config/env) | rule 10 | **PreToolUse(Edit\|Write) DENY** (unless placeholder / adjacent why) |
| About to hardcode a user-home absolute path (`C:\Users\…` / `/home/…` / `$HOME` / `%USERPROFILE%` / `"~/…"`) into **code** | rule 11 | **PreToolUse(Edit\|Write) DENY** (unless adjacent why; prose-doc/lockfile exempt) |
| About to run `--no-verify` / `--no-gpg-sign` / `git push --force` / `chmod 777` / `git rebase --skip` / `--break-system-packages` / `rm -rf /` | rule 03 + 09 | **PreToolUse(Bash) DENY** |
| About to say "done / fixed" with no `$ command + output` evidence (missing **convergence**) | rule 06 (a) | Stop layer (a) BLOCK |
| About to claim "unchanged / neutral / no regression" from a matching **total** (issue count, pass count, size) instead of a per-item **set diff** | rule 06 Check 2b | Stop layer (c) BLOCK |
| A gate went green and you are generalizing that to the parts it does **not** check (scope of evidence ≠ scope of claim) | rule 06 Check 2b | Stop layer (c) BLOCK |
| About to run a bulk rename / codemod / sed without a survey of the token's real neighbourhoods, an allowlist, and a refusal report | rule 09 bulk edits | — |
| Have evidence but no explicit answers to 4 questions (really solved / better solution / what's not verified / verification reasonable; rule 06 **convergence**) | rule 06 (c) | Stop layer (c) BLOCK |
| Passed rule 06 but didn't re-check against the user's original request per-item | rule 07 (d) | Stop layer (d) BLOCK |
| Modifier words "mandatory / strict / complete / all" implemented as "soft suggestion / doc reminder" | rule 07 standard degradation | Stop layer (d) BLOCK |
| This turn did Edit but **your final reply** lacks "root cause / architecture / solution / impact / risk" ≥ 3 items (the hook reads the reply, not hidden reasoning — so write them where the user can see them) | rule 08 | Stop layer (e) BLOCK |
| This turn did Edit but reply lacks "root cause + impact + solution" triplet | rule 09 | Stop layer (f) BLOCK |
| Claim "I edited X.py / created Y.md" but disk mtime unchanged / file does not exist | rule 01 + 06 | **Stop layer (g) v0.16 BLOCK** |
| Left TODO / FIXME but said "done" / did refactors the user didn't ask for | rule 07 fidelity | Stop layer (d) BLOCK |
| A done-claim reply with no `tldr` / plain-language summary at the end | v0.20 reply schema | **Stop layer (h) v0.20 BLOCK** |
| A `tldr` item longer than one sentence / 160 chars (a paragraph is not a TL;DR; several things → one short line each) | v0.23 tldr length contract | **Stop layer (h) v0.23 BLOCK** |
| Closing an edit without a repo-wide reference sweep (docs / downstream / tests / translations), when a sync-gate `when` group matched but no `require` file was edited and no `同步核对` / `sync-check` line is present | rule 12 repo-wide sync | **Stop layer (i) v0.23 BLOCK** (projects with `.claude/cc-enforcer/sync-gate.toml`) |

## Closing schema (YAML · mandatory)

Reply must end with a ```yaml `cc-enforcer:` block. Field names ARE the Stop-hook
detection markers — don't rename them. Modification tasks use the full form,
non-modification tasks (Q&A, lookup) the minimal form (convergence / fidelity / tldr):

```yaml
cc-enforcer:
  before: {architecture: ..., root cause: ..., solution: ...}   # rule 02
  edits: [{file: "path:line", what: "..."}]                     # rule 09
  convergence:                                                  # rule 06
    re-trigger: "$ <cmd> → <output with counts>"
    boundary case: ...
    existing tests: ...
    self-quiz: {really solved: ..., better solution: ..., unverified: ..., verification reasonable: ...}
  fidelity: {request coverage: [...], standard: ..., no degradation: ...}   # rule 07
  closing: {root cause: ..., impact: ..., solution: ...}        # rule 08+09
  sync-check: <co-files updated, or why none needed>            # rule 12, edit turns
  tldr: "<one plain sentence>"
```

**Any reply with a done-claim must include the `tldr` field, else Stop layer (h) BLOCK.**
**`sync-check` settles only groups a previous block NAMED — a first violation still
BLOCKS at layer (i) and names the group. A placeholder value (`n/a` / `无` / `-`)
is treated as ABSENT and still BLOCKS (v0.32), as is one you merely quoted.**
**`tldr` length (v0.23): one sentence per item — cause, action, outcome — ≤ 160 chars;
several things → one item per line, each within the cap, else Stop layer (h) BLOCK.**

When blocked at Stop: reason is a status table + a plain-language line; find the ❌ row → read Recovery → fix, don't re-read the whole prompt.

Full rules → [`rules/`](rules/) · Index → [`docs/RULES.md`](docs/RULES.md)
