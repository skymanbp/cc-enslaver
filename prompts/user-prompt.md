# cc-enslaver — Decision-time triggers (per-turn injection)

> Self-check before replying: any **hit** below → stop, verify or add
> the missing step before continuing.
> 🚨 Physical-enforcement hooks will DENY tool calls / BLOCK Stop when
> you try to skip.

## Decision triggers (writing or about to do → self-check immediately)

| You wrote / want to do | Trigger | Physical consequence |
|---|---|---|
| "should / probably / I think / maybe / 应该" | rule 01 + 06 hedge | Stop layer (b) BLOCK |
| Cite a file not Read this session (violates **read-before-edit**) | rule 04 + 08 | **PreToolUse(Edit\|Write) DENY** |
| About to do a ≤ 5 line "quick fix" without 7 questions, missing **think-before-write** | rule 02 + 08 | — |
| About to write `try/except: pass` / `# noqa` / `@ts-ignore` / `eslint-disable` without why | rule 09 | **PreToolUse(Edit\|Write) DENY** |
| Patching locally instead of **systematic** modification (rolling patches / wrap-and-swallow) | rule 09 | rule 09 DENY (if suppression marker has no why) |
| About to `time.sleep()` to mask a race / comment out failing tests / loosen asserts | rule 03 + 09 | rule 09 DENY (for new code) |
| About to inline a secret / API key / token / private key / credentials-in-a-URL as a **code** literal (should be config/env) | rule 10 | **PreToolUse(Edit\|Write) DENY** (unless placeholder / adjacent why) |
| About to hardcode a user-home absolute path (`C:\Users\…` / `/home/…` / `$HOME` / `%USERPROFILE%` / `"~/…"`) into **code** | rule 11 | **PreToolUse(Edit\|Write) DENY** (unless adjacent why; prose-doc/lockfile exempt) |
| About to run `--no-verify` / `git push --force` / `chmod 777` / `git rebase --skip` / `--break-system-packages` / `rm -rf /` | rule 03 + 09 | **PreToolUse(Bash) DENY** |
| About to say "done / fixed" with no `$ command + output` evidence (missing **convergence**) | rule 06 (a) | Stop layer (a) BLOCK |
| Have evidence but no explicit answers to 4 questions (really solved / better solution / what's not verified / verification reasonable; rule 06 **convergence**) | rule 06 (c) | Stop layer (c) BLOCK |
| Passed rule 06 but didn't re-check against the user's original request per-item | rule 07 (d) | Stop layer (d) BLOCK |
| Modifier words "mandatory / strict / complete / all" implemented as "soft suggestion / doc reminder" | rule 07 standard degradation | Stop layer (d) BLOCK |
| This turn did Edit but chain-of-thought lacks "root cause / architecture / solution / impact / risk" ≥ 3 items | rule 08 | Stop layer (e) BLOCK |
| This turn did Edit but reply lacks "root cause + impact + solution" triplet | rule 09 | Stop layer (f) BLOCK |
| Claim "I edited X.py / created Y.md" but disk mtime unchanged / file does not exist | rule 01 + 06 | **Stop layer (g) v0.16 BLOCK** |
| Left TODO / FIXME but said "done" / did refactors the user didn't ask for | rule 07 fidelity | Stop layer (d) BLOCK |
| A done-claim reply with no `tldr` / plain-language summary at the end | v0.20 reply schema | **Stop layer (h) v0.20 BLOCK** |

## Closing schema (YAML · mandatory)

Reply must end with a ```yaml `cc-enslaver:` block — fixed schema, see SessionStart injection §3.
Modification tasks use the full form (before / edits / convergence / fidelity / closing);
non-modification tasks use the minimal form (convergence / fidelity / tldr).
**Any reply with a done-claim must include the `tldr` field, else Stop layer (h) BLOCK.**

When blocked at Stop: reason is a status table + a plain-language line; find the ❌ row → read Recovery → fix, don't re-read the whole prompt.

Full rules → [`rules/`](rules/) · Index → [`docs/RULES.md`](docs/RULES.md)
