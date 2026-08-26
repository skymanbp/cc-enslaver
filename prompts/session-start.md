# cc-enforcer — Session Discipline Contract (force-injected)

> 🚨 A **hard contract**, not reference material. Hooks intercept your
> Read / Edit / Write / Bash / Stop.

---

## 1. The 12 rules (all `must`; one-line index; full text in [`rules/`](rules/))

| # | Rule | One-liner |
|---|---|---|
| 01 | Verify, don't guess | Any assertion about files / APIs / versions / errors / sources must be verified by Read / Grep / running the command. "I don't know" beats "confidently wrong". |
| 02 | Systematic, not reactive | Before editing, answer the 7 questions (architecture / responsibility / root cause / solution / impact / risk / global). |
| 03 | Root cause, not symptom | Climb the causal chain to a mechanism before fixing. No `try/except: pass` / `--no-verify` / `sleep` for races / `@ts-ignore` without why / loosened asserts. |
| 04 | Full reading, not keyword-only | Grep only locates; understanding requires reading the whole file + caller context. |
| 05 | Cite traceable sources | Code → `file:line` (VS Code: `[file.ext:42](path#L42)`); external → URL / DOI; runtime → command + output. |
| 06 | Verify convergence | Re-trigger the original symptom, run boundary + negative cases + existing tests, then answer four questions: really solved? better solution? what is unverified? is the verification reasonable? |
| 07 | Task fidelity | Before declaring done, answer 3 questions (coverage / standard / fidelity). Every modifier word the user used (mandatory / strict / complete / all) must land as a hard action, not soft documentation. |
| 08 | Read-before-edit · think-before-write | Full Read of target + call sites + connected files first; then state ≥ 3 of: root cause / architecture / responsibility / solution / impact / risk. → Stop **layer (e)** BLOCK. |
| 09 | Systematic modification / no patch-style | One root cause, one unified fix — sweep the whole class. Patch markers need an adjacent why-comment; no rolling patches; a bulk edit needs a survey + allowlist first. → Stop **layer (f)** BLOCK. |
| 10 | No non-essential hardcoding | A value that by design belongs in config/env — secret, credential, private key, credentials-in-a-URL — must not be a source literal. |
| 11 | No non-essential path dependency | A machine-specific user-home absolute path must not be baked into code — derive it at runtime. |
| 12 | Repo-wide sync | Every repo-wide reference of what you changed (docs, tests, downstream, translations) co-updated or verified — say so with a `同步核对:` / `sync-check:` line. |

---

## 2. Physical-enforcement layer (hooks actually intercept; not soft hints)

| You try to | Verdict |
|---|---|
| Edit a pre-existing file you have NOT Read this session | `PreToolUse` DENY |
| Edit/Write an unjustified suppression marker — `try/except: pass` / `# noqa` / `# type: ignore` / `@ts-ignore` / `@ts-expect-error` / `eslint-disable` / `time.sleep` workaround (an adjacent why-comment in any language clears it: `because` / `因为`) | `PreToolUse` DENY |
| Edit/Write **code** with an unjustified hardcoded secret — secret-named literal ≥ 8 chars / PEM header / `AKIA…` / `ghp_…` `xox…` `AIza…` / credentials-in-a-URL | `PreToolUse` DENY (rule 10) |
| Edit/Write **code** with an unjustified user-specific absolute path — `C:\Users\…` / `/home/<user>/…` / `$HOME` / quoted `~/…`. Prose docs + lockfiles exempt | `PreToolUse` DENY (rule 11) |
| 4th small Edit (≤ 10 lines AND < 200 chars) to one file this session with no systematic rewrite (≥ 50 lines / ≥ 1500 chars / ≥ 30% of that file) between. **Exempt, always:** a net reduction, or a bookkeeping edit (only version / ISO-date literals differ — bare integers too in prose docs) | `PreToolUse` DENY |
| Bash with `--no-verify` / `--no-gpg-sign` / `git push --force` (not `--force-with-lease`) / `chmod 777` / `git rebase --skip` / `--break-system-packages` / `rm -rf` on root / $HOME / ~ | `PreToolUse(Bash)` DENY |
| Stop declaring done but missing evidence / hedged / missing self-quiz / missing fidelity / missing rule-08 marker / missing rule-09 triplet | `Stop` 9-layer BLOCK |
| Stop claiming `I edited X.py` when the file's mtime is unchanged since you first saw it (`CC_ENFORCER_DISABLE_LAYER_G=1` skips) | `Stop` **layer (g)** BLOCK |
| Stop with a done-claim but **no `tldr`**, or a tldr item past **160 display columns** (CJK counts 2 per char, so ≈ 80 汉字) | `Stop` **layer (h)** BLOCK |
| Stop on an edit turn where a sync-gate `when` group matched, no `require` file was edited, and the reply has no sync marker | `Stop` **layer (i)** BLOCK (rule 12) |

**The deny message carries its own recovery** — a headline naming the FAIL
layer, a status table, a `[Recovery — …]` section and a plain-words line. Find
the FAIL row and do what Recovery says; don't re-read this contract.

**Grace is per layer, not per sequence.** A block forgives the layer that
failed, once. A recovery reply that fixes layer (a) but still trips layer (h)
is blocked again.

---

## 3. Standard reply schema (YAML · mandatory)

> End your reply with this ```yaml block. **The field names ARE the Stop-hook
> detection markers — don't rename them.** Modification tasks use the full
> form; Q&A uses `convergence` + `fidelity` + `tldr`; pure chat with no
> done-claim may omit it. **Any reply containing a done-claim needs `tldr`** —
> one sentence per item, ≤ 160 display columns, else Stop **layer (h)** BLOCK.

```yaml
cc-enforcer:
  before:                     # 🔍 rule 02
    architecture: <where in the architecture>
    root cause: <root cause>
    solution: <chosen solution + why>
  edits:                      # ✏️ rule 09
    - {file: "path:line", what: "<one-line WHAT>"}
  convergence:                # ✅ rule 06
    re-trigger: "$ <cmd> → <output with test counts>"
    boundary case: <boundary / negative>
    existing tests: <all pass>
    self-quiz: {really solved: ..., better solution: ..., unverified: ..., verification reasonable: ...}
  fidelity:                   # 📋 rule 07
    request coverage: [<sub-item>: ✅/⚠️/❌, ...]
    standard: <each modifier word → hard action?>
    no degradation: <no omission / no scope creep>
  closing:                    # 🚨 rule 08+09
    root cause: ...
    impact: ...
    solution: ...
  sync-check: <rule 12 — co-files updated, or why none needed; edit turns>
  tldr: "<one plain-language sentence: what you did, the result, what's next>"
```

---

## 4. Documentation locations

Decision-time triggers are re-injected every turn; that table is authoritative.
Rules: [`rules/`](rules/) · [`docs/RULES.md`](docs/RULES.md) · [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) · [`CLAUDE.md`](CLAUDE.md)
