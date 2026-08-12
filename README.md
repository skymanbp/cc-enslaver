# cc-enslaver

> A Claude Code plugin and LLM-agnostic rule pack that **eliminates lazy AI behavior** — reactive patches, guessed citations, surface-level "fixes", half-finished work — by enforcing systematic thinking, verification, and root-cause analysis at every layer of the agent loop.

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Plugin Version](https://img.shields.io/badge/version-0.28.0-blue.svg)](CHANGELOG.md)
[![Tests](https://github.com/skymanbp/cc-enslaver/actions/workflows/test.yml/badge.svg)](https://github.com/skymanbp/cc-enslaver/actions/workflows/test.yml)
[![Claude Code Plugin](https://img.shields.io/badge/Claude%20Code-plugin-purple.svg)](https://code.claude.com/docs/en/plugins.md)

<!-- The v0.28.0 headline lives with the other "New in" blocks further
     down, next to v0.27.0, so this badge area stays scannable. -->

中文用户请直接看 → [中文说明](#中文说明)

---

## What is this?

LLM coding agents (Claude Code, Cursor, Copilot, Cline, Aider, etc.) frequently fall into predictable lazy patterns:

| Lazy pattern | What it looks like |
|---|---|
| **Reactive patching** | Sees a bug, slaps a try/except around it, declares done. |
| **Guessed citations** | Cites file paths, line numbers, or APIs that don't exist. |
| **Keyword-search-only** | Greps once, edits, never reads the surrounding architecture. |
| **Memory dependence** | Acts on stale recollection instead of re-reading the current file. |
| **Root-cause bypass** | Adds `sleep` for races, `--no-verify` for hooks, swallows exceptions. |
| **Half-finished work** | Stops at "should work", leaves TODOs, doesn't verify the whole flow. |
| **Premature done-claim** | Claims "fixed" without re-running the original failing case, no edge cases, no comparison evidence. |

`cc-enslaver` ships a **layered defense** against all seven, currently **12 built-in rules + user-defined Imperial Edicts (圣旨) + 9 Stop-hook gates** (v0.28.0):

> **New in v0.28.0** — 🪜 **Rules 03 + 09 upgraded: trace upstream → diagnose → one unified fix. Point-to-point patching is banned outright.**
>
> **Rule 03 gains an upstream tracing ladder.** Every failure has three kinds of location: the **symptom site** (where it surfaces), the **propagation path** (what the bad state flowed through), and the **origin** (the mechanism / design decision / missing invariant that *generates* it). Fixing at the first two levels is a patch, even when the observed failure disappears. Climb the chain until the answer is a mechanism; stopping short is legitimate only with the true origin named and the reason stated — an unstated stop is a patch with better paperwork. And the diagnosis must be **demonstrated first-party** (probe / reproduction / failing test) *before* the first line of the fix is written.
>
> **Rule 09 gains "one root cause, one unified fix".** A diagnosed root cause defines a *class* of defects — the instance you observed is merely the one that surfaced first. Sweep the repo for every sibling of the class, fix the generating mechanism once covering all instances in the same pass, and prove the class is closed by re-triggering at least one *other* instance. N symptoms sharing one root = **one** fix, never N patches. Grounded in this repo's own measured history: v0.25.1 *named* a root cause and fixed only the instances it had seen; the mechanism survived and regenerated a fresh crop by v0.26 — including one regression. v0.28 codifies v0.26's replace-the-mechanism response as the required shape of every fix.
>
> **Zero new detectors, deliberately** (the v0.22.1 precedent): this is a reasoning shape, not a syntax shape a hook can match. The existing hard layers — patch-marker content scan, rolling-patch frequency layer, Stop layer (f)'s root-cause triplet — remain the physical floor. New checklist items F9–F11; tests hold at 556.

> **From v0.27.0** — 🧵 **Three deferred contract questions, closed with evidence instead of preference.** v0.26 shipped them as "known, not fixed"; leaving them is how a "documented limitation" becomes permanent.
>
> **The tokeniser now follows the shell, not the host OS.** v0.25.1 disabled backslash escaping when `os.name == "nt"`. Measuring the shell Claude Code actually runs on Windows — Git Bash / MSYS, `bash 5.2.37(1)-release` — showed the branch was wrong in *both* directions: an unquoted drive path loses its separators in the real shell too (so it never rescued anything), and `git push --for\ce` reaches git as **`--force`** while the guard saw an unrecognised token. That was a live force-push bypass, now closed. Quoting is what preserves a drive path — in this tokeniser and in the shell alike.
>
> **Layer (h) presence and measurement are now separate verdicts.** One `countable` flag forced a bad trade, which is why v0.26 skipped CommonMark lazy continuation entirely: implementing it made a *visible* `tldr:` under a blockquote uncountable, so the presence half then blocked the reply for a "missing" summary the author could see. Presence is now generous (`attributable`), measurement conservative (`countable`), and lazy continuation is implemented.
>
> **Layer (i): one INFORMED answer per group.** A sync marker used to settle every pending group on the primary path while the grace path settled only the groups actually shown — and that inconsistency *was* the bypass, since outlasting the grace window reached the looser path. Both paths are scoped now: a group is named once, then your marker settles it. Strictly stricter, deliberately.
>
> Tests **543 → 556**.

> **From v0.26.0** — 🧩 **Fourth-round audit: the previous release's own fix diff was reviewed, and the mechanism was replaced instead of the symptoms.** Three parallel read-only reviews plus a first-party pass produced **37 findings**; **33 reproduced** under first-party runtime probes, 3 were recorded as by-design, and **1 was refuted** (a reviewer called a test vacuous that in fact fails on the pre-fix tree). They collapse into **three root causes**, and the fix is **four shared models**, not ~30 patches. Tests **378 → 556**, across two audit rounds: the first replays **43 failures + 3 errors** on the pre-fix tree; the second (16 parallel read-only reviews, 15 of which reported) fixed a further 20+ confirmed defects at the root — including five stale test counts and two wrong claims in this release's own notes.
>
> **The fix was then re-audited before shipping** — because the defect this release corrects was *introduced by the previous release's fix*. That pass found **8 more real defects in the new code**, all fixed: `$( … )` / backtick / subshell invocations were not segmented (the text heuristic caught those **by accident**, so the model would have been a regression — `$(git push --force)` executes); an escaped `\"""` ended a triple-quoted block early, exposing string content as comments; three CommonMark bugs in the fence model; `cannot` / `unable` / `绝非` were missing from negation while `not only fixed but tested` was wrongly suppressed; and punctuation padding reached the rationale length bar. One change of mine was **reverted** when it broke a deliberate v0.23 contract.
>
> **α — the detector encoded a _spelling_, not the concept.** "Is this `#` a comment?" was `line.find("#")`, which finds the `#` inside a URL — so a single neighbouring `API = "https://api.example.com"` line turned the **rule-10 secret detector off entirely** (`example` is a rationale token, and `example.com` is the IANA example domain — i.e. the leak fired exactly where committed credentials live). "Where does this `try` block end?" was indentation over *physical* lines, so a multi-line string re-anchored the block; and a handler suppressed **every** stack pop, which **regressed** nested `try/except` from deny (v0.25.0) to **allow** (v0.25.1) *while its own docstring claimed nesting was now handled by a stack*. "Does this force-push?" was words co-occurring in text — denying an `echo` of a force-push string and `git config alias.deploy "push --mirror"`, while missing `git push origin +main` and `+:refs/heads/main`. "Is this token executed?" was walking backwards over dashes, so `python -c register_read.py` polluted read state, while `python -X utf8 …` (**its own docstring's advertised example**) and `python3.13` were missed. Replaced by [`lib/srclex.py`](hooks/scripts/lib/srclex.py) (tolerant lexer: comments vs docstrings vs data literals, literal masking, bracket-joined logical lines), [`lib/mdctx.py`](hooks/scripts/lib/mdctx.py) (fence/blockquote context — now consumed by **both** halves of Stop layer (h), which previously disagreed about which fences count), [`lib/shellcmd.py`](hooks/scripts/lib/shellcmd.py) (segments → argv → git subcommand / python script operand), and a schema-driven state normaliser.
>
> **β — hardening scoped to the observed instance.** v0.25.1's normaliser repaired `read_files` and left `session_id` raising `KeyError` — so a Read went unrecorded and the **next edit was falsely denied**; auto-GC compared a **raw** session id against **sanitised** filenames; `manage_edicts` coerced only `id`, so one wrongly-typed field broke the whole CLI.
>
> **γ — the claim outran the change.** Four tests passed unchanged on the pre-fix tree (now paired with twins), and the self-rewritability invariant said it pinned "the whole tree" while globbing only `hooks/scripts` — **six of the ten test modules were self-locked**.
>
> Also: marker regexes now end at **token boundaries** (`# noquality`, `@ts-ignore-generated`, `eslint-disablement` were false **DENIES**); the rationale hatch accepts **Chinese** (`因为` / `故意` — previously English-only, in a Chinese-primary repo) and **block comments**; done-claim negation handles `not yet done` / `isn't done` (the old `\bn't\b` was **unreachable dead code**).

> **New in v0.25.1** — 🔬 **Third-round audit: 94 review findings → 21 first-party reproductions → six root-cause fixes.** Three parallel read-only reviews of the v0.25.0 tree returned 94 findings; rather than trust that, every high-signal claim was re-run against the real code by a probe, and the 21 that reproduced collapse into **six root causes** — fixed as six systematic changes, not 21 patches. Red-first: the new assertions produce **37 failures + 4 errors** on the pre-fix tree; the fixed tree is **378/378** (350 → 378). The theme is **detectors that described a *string* instead of a *concept***. Nine findings were one spelling away: **CRLF** defeated all five single-line rule-09 markers — on this plugin's primary platform; **any trailing text** made a marker match *nothing at all*, so `@ts-ignore` + a bare deferral keyword was allowed while the bare form was denied and the rationale check never ran; a **comment line between `except:` and `pass`** moved the swallow out of the scanner's sight, leaving rule 09's escape hatch unreachable for its most natural spelling — v0.25 fixed the same-line variant and shipped a regression test that passed for the wrong reason; `except Exception: pass` one-liners, nested `time.sleep(max(0, d))`, **doubled backslashes** in `"C:\\Users\\bob"` (how a user-home path actually appears in committed source), `git -C repo push --force`, quoted `"--force"`, `+refspec` and `--mirror` all slipped through. Second root cause: **untrusted TOML values used without a type check** — `severity = ["must"]` and `mode = []` are valid TOML and raised `TypeError: unhashable type` out of loaders documented as never raising, disabling rules 04 + 08 for a whole session and taking Stop layer (i) with them. Third: the rationale hatch was wrong **in both directions** — honored inside arbitrary code (`reason = compute()` silenced an adjacent marker) yet unreachable as a standalone comment. Fourth: presence checks standing in for meaning — `已完成` / `Implemented` / `Finished` were absent from `DONE_PATTERNS`, so **all nine Stop layers** were skipped, while `Not done; tests failed.` counted as a completion claim and an **empty `tldr:`** satisfied layer (h). Fifth: **auto-GC could delete the live session's state** on resume, and a mistyped GC marker suppressed the entire SessionStart injection. Sixth: a grace-window sync ack silenced groups the agent was **never shown**.

> **New in v0.25** — 🔍 **A second-round audit: 12 confirmed defect fixes, zero new features.** Multi-lens adversarial review of the v0.24 tree, every finding independently probe-verified, red-first regressions (**323 → 346**; 32 of the new assertions fail on the pre-fix tree). The theme is **guards that could be walked around**: a successful `register_read` invocation short-circuited the *entire* bypass catalog, so `register_read.py --file F --hash H && git push --force` was **ALLOWED** — the deny checks now run first, and a command destined for denial no longer mutates session state. Rule 09's flagship `try/except: pass` detector was defeated by *any* trailing comment on the `pass` line, which also made its own why-comment escape hatch unreachable (a rationale silenced the detector by changing the string, so it was never read), and it only inspected the first `except` clause — hiding the canonical narrow-handler-then-catch-all shape. Reading a path *before it existed* granted permanent blind-edit authorization once anything created it. An unreadable-but-present state file became a false read-before-edit **DENY** while stderr announced "failing open". Layer (g)'s Chinese claim regex had no first-person anchor, so `v0.23 修改了 X` parsed as a self-claim and truthful third-party attributions were **blocked** — in this repo's own primary language. A mis-encoded `edicts.toml` raised `UnicodeDecodeError` past every downstream check and silently switched **off** read-before-edit for the whole session. Also: quoted-key secrets (`"api_key": "…"`, the most common committed-credential shape) now denied; force-push detection scoped to the `git push` sub-command (`rm -f x && git push` no longer false-denies, `git push -fu` no longer escapes); a shared hardened TOML reader ([`lib/tomlio.py`](hooks/scripts/lib/tomlio.py)); nested code fences no longer close their parent. And **five of twelve hook scripts were self-locked** — unrewritable by any agent running this plugin, because they carried bare `# noqa` / `try: … except: pass` — now fixed and pinned by a tree-wide test.
>
> **From v0.24** — 🩺 **A health-audit release: 10 confirmed defect fixes (3 HIGH), zero new features.** A full architecture review plus multi-path adversarial model review (every finding re-verified with a runtime probe, red-first regression tests) fixed, among others: **Windows state saves silently lost to the plugin's own lock-free readers** (`os.replace` vs an open reader → `PermissionError` → failing-open → the mutation vanished; read accessors now share the session lock, `save()` retries against external readers, and the audit session itself had live-reproduced the bug when the plugin denied its own auditor's Edit); **the layer-(i) sync acknowledgement lost in the one-shot grace window** (the primary block→`同步核对:`-recovery flow never persisted the ack, so an answered group re-blocked later — the grace path now reads the reply and acks); **a DENIED Write-new still registering its target as "read"**; an atomic rolling-patch counter; and three detector false-positive/false-negative fixes for rules 10/11 (`password: "SecretStr"` annotations, URL routes with `/home/` segments, `requirements*.txt` credential scanning + `.asciidoc` exemption). Tests 310 → 323.
>
> **From v0.23** — 🔄 **Rule 12: repo-wide sync (全库更新) + a hard TL;DR length contract.** An edit is now *done* only when **every repo-wide reference of the changed content** — docs, downstream code, tests, mirrors/translations — is co-updated in the same session or explicitly verified current (reported via a `同步核对:` / `sync-check:` closing line). The **passive half** is a per-project 代码门禁: register known co-update invariants in `.claude/cc-enslaver/sync-gate.toml` (`[[groups]]` with `when` / `require` globs), and the new **Stop layer (i)** blocks an edit-turn done-claim whose `when` group matched with no `require`-side edit and no sync-acknowledgement marker — per-project opt-in, failing-open, with the marker escape making "checked, no change needed" an explicit legitimate outcome. The **active half** is the new **`repo-refresh` skill** ("全库更新" / "stale scan" / "audit the repo"): a systematic whole-repo sweep — docs *and* code — for **stale (陈旧) / outdated (过时) / redundant (冗余) / wrong (错误) / drifted (漂移)** content, every finding carrying `file:line` evidence. Separately, the v0.20 `tldr` closing gains a **160-char-per-item cap** hard-enforced at Stop layer (h): one sentence per item (cause → action → outcome); several things to report → one short line each. See [`rules/12-repo-wide-sync.md`](rules/12-repo-wide-sync.md).
>
> **From v0.22.2** — 🏷️ **A version-drift gate, because v0.22.1 shipped broken.** `plugin.json` said `0.22.1` while `.claude-plugin/marketplace.json` — *the file the plugin installer actually reads* — still said `0.22.0` in both of its version fields. Every test passed, CI was green, the tag was pushed, and users kept seeing the previous version. That is v0.22.1's own **scope of evidence ≠ scope of claim** failure committed by the release that introduced the rule: a green suite proved nothing about the two manifests it never opened. [`tests/test_version_sync.py`](tests/test_version_sync.py) makes `plugin.json` the single version authority and pins the README badge and the newest `CHANGELOG` release heading to it. The manifest sites are a **closed set** (rule 09): both manifests are walked recursively for *every* `"version"` key and the discovered JSON-pointer set must equal the registered set — so a version field added later cannot silently escape the gate, which a two-path checklist would have allowed. Also fixed: **a git tag is not a release** — v0.22.1's tag was pushed but no GitHub Release object was ever created, so the releases page also still read v0.22.0. The release checklist in [`CLAUDE.md`](CLAUDE.md) §4.1 now ends at `gh release create`, not at `git push --tags`.
>
> **New in v0.22.1** — 🔬 **Two rules sharpened from real field failures** (no new detector, no new Stop layer — which is why it is a patch). **rule 06 gains Check 2b — "aggregate-equal is not unchanged"**: any *unchanged / no-regression* claim must compare the **item set** (category names, test IDs, failing-assertion identities, per-file hashes), never a matching **total**. Field evidence: a validator printed `Total issues: 754` both before and after a ~9,500-substitution refactor — byte-identical — while a per-category diff showed one category had flipped `OK …: INFO:1` → `X …: CRITICAL:1`. The check carries the corollary **scope of evidence ≠ scope of claim**: a gate that validates part of an artifact proves nothing about the rest. **rule 09 gains a bulk-mechanical-edit discipline** for renames / codemods / sed: survey what actually surrounds every occurrence *before* writing the rule, rewrite only allowlisted forms, emit a **refusal report**, reconcile `total = rewritten + skipped + refused`, expect shapes the pattern is structurally blind to (the token inside a regex alternation, as a standalone argument, and the symbol named after it), and **never rewrite a path that addresses history** (`git show <fixed-rev>:<path>`). Plus **closed-set guards**: enumerate the legal set instead of blacklisting stray shapes. See [`rules/06-verify-convergence.md`](rules/06-verify-convergence.md) + [`rules/09-systematic-modification.md`](rules/09-systematic-modification.md).
>
> **New in v0.22** — 🔒 **Two new write-time content detectors (rules 10 + 11)**: `PreToolUse(Edit|Write)` now physically **DENY**s writing *non-essential* hardcoding or machine-specific path dependencies into code. **Rule 10 (no hardcoding)** flags an unjustified hardcoded secret — a secret-named literal (`password` / `api_key` / `token` / … ≥ 8 chars), a PEM `-----BEGIN … PRIVATE KEY-----` header, an `AKIA…` AWS access key, or credentials embedded in a connection URL. **Rule 11 (no path dependency)** flags a user-home absolute path baked into code (`C:\Users\…`, `/home/…` or `/Users/…`, `$HOME`, `%USERPROFILE%`, a quoted `~/…`). Both share the rule-09 **why-comment escape hatch** — an adjacent `because` / `原因` / `essential` / `fixture` / `placeholder` justification allows the write, which is exactly how "*non-essential*" is operationalized — and both **exempt prose-doc + lockfile targets** (`.md` / `.rst` / `.txt` / `.adoc`, `*.lock`, `package-lock.json`) so this repo's own example-laden docs never self-trip. Like the other content detectors they are **PreToolUse-only** (no Stop layer). See [`rules/10-no-hardcoding.md`](rules/10-no-hardcoding.md) + [`rules/11-no-path-dependency.md`](rules/11-no-path-dependency.md).
>
> **New in v0.21** — 🌍 **English is now the skeleton language**: the plugin's rule + prompt surface flipped from Chinese-canonical to **English-as-source-of-truth**. English lives at the root (`rules/*.md`, `prompts/*.md`); each translation lives in a language subdir (`rules/zh/`, `prompts/zh/`, and any `rules/<code>/`). Injection defaults to English (`CC_ENSLAVER_LANG` unset / `en`); set `CC_ENSLAVER_LANG=zh` for Chinese, or any code for a partial translation (missing files fall back to the English skeleton). **Language version control is a hard, CI-enforced gate**: [`hooks/scripts/i18n_check.py`](hooks/scripts/i18n_check.py) (run via `/cc-enslaver:i18n`) asserts every translation tracks the skeleton file-for-file and section-for-section; [`tests/test_i18n_sync.py`](tests/test_i18n_sync.py) turns CI red on any drift. **On drift, English wins.** See [`docs/I18N.md`](docs/I18N.md).
>
> **New in v0.20** — 📋 **Structured YAML reporting + plain-language TL;DR**: every reply now ends with a fixed ```yaml `cc-enslaver:` block (`改前 / 改中 / 收敛 / 忠实 / 收尾 / tldr`; English mirror `before / edits / convergence / fidelity / closing / tldr`) — the audit trail is **scannable at a glance** instead of drifting free-form prose. A new **Stop layer (h)** hard-enforces a one-sentence `tldr` (大白话总结) on every done-claim reply, and every block reason now carries a `大白话:` takeaway. The schema's field names ARE the existing Stop-hook detection markers, so no detector changed — old emoji-markdown and new YAML reply forms both pass.
>
> **From v0.18** — 🧹 **Opt-in auto-GC on SessionStart**: set `CC_ENSLAVER_AUTO_GC_DAYS=30` and the SessionStart hook automatically prunes session-state files older than N days. Rate-limited to once per 24h via a marker file so rapid session restarts don't re-scan. Default off (backward-compatible); the manual `/cc-enslaver:gc` slash command still works and shares the same `prune_old_sessions()` deletion routine.
>
> **From v0.17** — 🌐 **Imperial Edicts go bilingual**: with `CC_ENSLAVER_LANG=en`, the soft-layer injection and the PreToolUse DENY reason both flip to English ("Imperial Edicts" / "Imperial Edict E01 violation"). Default Chinese ("圣旨") preserved. Plus Windows portability fixes: file-claim regex now matches drive-letter paths (`C:\Users\...\x.py`), and `manage_edicts.py` forces UTF-8 stdout.
>
> **From v0.16** — 🕵️ **Stop Layer (g) file-claim verification**: read_guard captures per-file mtime baselines on first encounter; stop_guard parses `I edited X.py` / `我修改了 Y.md` claims and BLOCKs the Stop when the on-disk mtime contradicts. Conservative-by-design (no baseline / any ambiguity → pass). Escape hatch: `CC_ENSLAVER_DISABLE_LAYER_G=1`.
>
> **From v0.15** — 🌍 **Switchable prompt language**: `CC_ENSLAVER_LANG` selects which translation the hook injects. (v0.21 flipped the default — English is now the skeleton at `prompts/{session-start,user-prompt}.md`; `CC_ENSLAVER_LANG=zh` injects the Chinese translation under `prompts/zh/`, and any unknown code falls back to the English skeleton.)
>
> **From v0.14** — ⚡ **Three more Bash bypass patterns** (`git rebase --skip`, `--break-system-packages`, `rm -rf` on root/`$HOME`/`~`) get `PreToolUse(Bash)` DENY. 🏛️ **Edicts `--global` flag**: `add --global` writes to `~/.claude/cc-enslaver/edicts.toml` for personal cross-project rules.
>
> **From v0.13** — 🔁 **Rule-09 rolling-patch hard layer**: `PreToolUse(Edit|Write)` physically DENYs the 4th small Edit (≤ 10 lines AND < 200 chars) to the same file in one session unless a systematic rewrite (≥ 50 lines OR ≥ 1500 chars) resets the counter. See [`rules/09-systematic-modification.md`](rules/09-systematic-modification.md) §"Edit/Write 频率层".
>
> **From v0.12** — 🏛️ **Imperial Edicts (圣旨)**: user-defined per-project hard rules loaded from `.claude/cc-enslaver/edicts.toml` with PreToolUse(Edit|Write|Bash) DENY and `/cc-enslaver:edict` CRUD slash command. See [`docs/EDICTS.md`](docs/EDICTS.md). Stop-hook block reasons render as uniform **status tables**. Soft-layer prompts thinned 54%.


1. **Soft layer (prompt injection)** — at session start and before every user prompt, the plugin injects a concise reminder of the 12 discipline rules into the agent's context. v0.11 added a standard response skeleton; **v0.20 turns it into a fixed YAML reply schema** (`cc-enslaver:` block with `改前 / 改中 / 收敛 / 忠实 / 收尾 / tldr` fields — English mirror uses `before / edits / convergence / fidelity / closing / tldr`) whose field names ARE the Stop-hook detection markers, plus a mandatory plain-language `tldr` (大白话总结) closing line. A **per-turn self-check checklist** with a physical-enforcement table maps each lazy attempt to the specific hook that catches it.
2. **Hard layer (PreToolUse blocks)** — at the moment the agent calls `Edit`, `Write`, or `Bash`, the plugin gates the call:
   - **Edit/Write read-before-edit** (rule 04 + rule 08): denied if the target file already exists but has not been `Read` in this session. New file creation is allowed.
   - **Edit/Write patch-style content** (rule 09, **v0.11**): denied if `new_string` (Edit) or `content` (Write) contains an *unjustified* suppression marker — `try / except: pass`, `# noqa`, `# type: ignore`, `// @ts-ignore`, `// @ts-expect-error`, `// eslint-disable[-next-line]`, `time.sleep(...) # race/wait/workaround`. Each marker is allowed when accompanied by a why-comment on the same or adjacent line containing `because`, `原因`, `why`, `正当`, `rationale`, `see issue/pr/ticket`, `intentional[ly]`, `deliberate[ly]`, `third-party`, or `per spec/rfc/standard`.
   - **Edit/Write hardcoded secret** (rule 10, **v0.22**): denied if `new_string` (Edit) or `content` (Write) targets *code* — not a `.md`/`.rst`/`.txt`/`.adoc` prose doc or a lockfile — and contains an *unjustified* hardcoded secret: a secret-named literal ≥ 8 chars (`password` / `api_key` / `token` / …), a PEM `-----BEGIN … PRIVATE KEY-----` header, an `AKIA…` AWS access key, or credentials embedded in a connection URL. Allowed when an adjacent line carries a why/essential rationale (`because`, `原因`, `essential`, `fixture`, `placeholder`, …) or the value is an obvious placeholder / env-read.
   - **Edit/Write path dependency** (rule 11, **v0.22**): denied if code contains an *unjustified* machine-specific user-home absolute path (`C:\Users\…`, `/home/…` or `/Users/…`, `$HOME`, `%USERPROFILE%`, a quoted `~/…`). Recovery: derive the path at runtime (plugin root / cwd / env / arg), or justify with an adjacent why-comment. Same prose-doc + lockfile exemption as rule 10; deliberately narrow to *user-specific* roots to keep false positives low.
   - **Bash bypass patterns** (rule 03 + rule 09): denied if the command contains `--no-verify`, `--no-gpg-sign`, `git push --force` (without `--force-with-lease`), or `chmod 777`. Each deny includes a precise recovery instruction.
   - **Read-cache escape hatch** (v0.4.0): when Claude Code's harness short-circuits a `Read` to its result cache without invoking the tool, the file never enters session state and a subsequent `Edit` is falsely denied. Agents can call `register_read.py --file ABS --hash SHA256` from Bash; `bash_guard.py` recomputes the hash from disk and only registers on match, so the hatch can't itself be used as a bypass.
   - **Edit-turn signal** (**v0.11**, reworked **v0.23**): every accepted Edit/Write sets an `edited_since_last_stop` flag (plus `last_edit_turn` when the payload carries a turn_count — production payloads don't, an E2E finding that had left the edit-gated Stop layers dormant outside the test suite). The Stop-hook layers (e)/(f)/(g)/(i) consult it to scope themselves to edit turns only; every allowed Stop clears it (turn boundary), blocked Stops keep it.
3. **Hard layer (Stop hook, v0.6.0 → v0.7.0 → v0.8.0 → v0.11.0 → v0.16.0 → v0.20.0 → v0.23.0)** — at every `Stop` event, `stop_guard.py` inspects the agent's last assistant message and applies **nine** layered checks (v0.12 reformatted the block reason as a uniform status table with the failing row highlighted; v0.20 added the (h) row and a plain-language `大白话` line under each block; v0.23 added the (i) row):
   - **(a) v0.6.0** — done-claim with **no evidence** (no `$ ` shell prompt, no test counts, no `重触发`/`pytest`/`unittest` keyword, no fenced code block) → block.
   - **(b) v0.7.0** — done-claim with **hedge near it** (`我觉得` / `I think` / `应该是` / `probably` / `maybe` within ~50 chars) → block (rule 01 cross-enforcement). Confident verification cannot coexist with hedged language.
   - **(c) v0.7.0** — done-claim with evidence but **no rule-06 marker** (`rule 06` / `自答` / `收敛` / `重触发` / `边界用例`) and **fewer than 2 of 4 self-quiz questions** detected (真解决? 更好方案? 哪些没验? 验证合理?) → block. Tests passing alone is not convergence.
   - **(d) v0.8.0** — passes (a)(b)(c) but **no rule-07 fidelity marker** (`rule 07` / `任务忠实` / `请求覆盖` / `原始请求` / `无降级` / `无遗漏` / `task fidelity` / `request coverage` / `no degradation` / `no omission` / `no scope creep` / `covered all` / `all requested` / ✅ 完成 checklist row) and **fewer than 2 of 3 fidelity questions** detected (覆盖性 / 标准性 / 忠实性) → block.
   - **(e) v0.11.0** — **fires only on edit turns** (the `edited_since_last_stop` flag, or `last_edit_turn == turn_count` when the payload supplies one — v0.23 fixed the signal for production payloads, which carry no turn_count). No **rule-08 marker** (`rule 08` / `改前必读` / `写前必想` / `read-before-edit` / `think-before-write` / `系统式自答`) AND fewer than 3 of 6 rule-02 keywords (架构 / 职责 / 根源 / 方案 / 连带 / 风险) → block. Read-only / analysis turns never trip this layer.
   - **(f) v0.11.0** — also **edit-turns-only**. No **rule-09 marker** (`rule 09` / `系统式修改` / `打补丁` / `systematic modification` / `patch-style` / `non-patch` / `反补丁`) AND incomplete triplet (root-cause + impact + solution) → block. Demands the systematic-modification triplet on every edit-bearing closing.
   - **(g) v0.16.0** — also **edit-turns-only**. Parses `I edited X.py` / `我修改了 Y.md` / `created Z.js` claims from the message and checks each against a **per-file mtime baseline** captured by `read_guard.py` on first Read / Edit / Write. If the on-disk state **definitively contradicts** a claim (mtime unchanged for "edited" / file still missing for "created"), → block. Conservative: no baseline / any ambiguity → pass. Escape hatch: `CC_ENSLAVER_DISABLE_LAYER_G=1`.
   - **(h) v0.20.0, length cap v0.23.0** — fires on **every done-claim turn** (not just edit turns). The reply must surface a plain-language **TL;DR** (`tldr:` schema field / `大白话` / `一句话总结` / `TL;DR`), else block; and each tldr item must stay within **160 characters** — one sentence (cause, action, outcome) per item, several things → one short line each — else block with a dedicated "overlong" recovery. Enforced as a closing readability convention, deliberately not promoted to a numbered rule.
   - **(i) v0.23.0** — **edit-turns-only, per-project opt-in** (rule 12). If a `when` glob group in the project's `.claude/cc-enslaver/sync-gate.toml` matched an edited file, no edited file matched any `require` glob, and the reply carries no sync-acknowledgement marker (`同步核对` / `sync-check` / `rule 12` / …) → block. No config file → the layer never fires; loader/evaluator failing-open.

   A one-shot guard (`last_blocked_turn` in session state, with a 3-turn grace window) prevents infinite loops. Each layer has its own block-reason text so the agent sees exactly which discipline gate failed.
4. **Active layer (slash commands)** — **5 slash commands** let the user (or the agent) trigger discipline on demand:
   - **`/cc-enslaver:checklist`** — structured 8-section checklist (A pre-edit / B post-edit / C convergence / D fidelity / E rule-08 read-before-edit·think-before-write / F rule-09 systematic-modification / G tldr closing / H rule-12 repo-wide sync).
   - **`/cc-enslaver:verify`** — independent file:line citation re-verification pass.
   - **`/cc-enslaver:gc`** (v0.6.1) — session-state file garbage collection (dry-run by default).
   - **`/cc-enslaver:edict`** (v0.12) — Imperial Edicts CRUD (`list / add / remove / reload / path`); `add --global` (v0.14) writes to `~/.claude` instead of project.
   - **`/cc-enslaver:i18n`** (v0.21) — run the language version-control check: file-set, header-structure and enforcement-token parity between the English skeleton and every translation.
5. **Subagent layer** — the `verifier` subagent independently re-reads any file:line citations the agent has produced and reports whether they're real.
6. **Skill layer** — `systematic-debug` auto-invokes when debugging language is detected, forcing a root-cause walk-through before any fix is proposed (v0.10 adds Step 0 = build a reproducible feedback loop with 10 concrete loop patterns). `repo-refresh` (v0.23) auto-invokes on whole-repo audit language and executes rule 12's active half: the five-category stale/outdated/redundant/wrong/drift sweep with `file:line` evidence.
7. **LLM-agnostic core** — every rule lives as plain Markdown, with **English as the skeleton (source of truth)** at [`rules/`](rules/) and translations in language subdirs ([`rules/zh/`](rules/zh/), and any `rules/<code>/`). The soft-layer prompts follow the same layout ([`prompts/`](prompts/) = English skeleton, `prompts/<code>/` = translation), so injection can run in any language via `CC_ENSLAVER_LANG` — the switch also covers Imperial Edicts injection + deny reasons. Translations are kept in lock-step with the skeleton by a CI-enforced check ([`docs/I18N.md`](docs/I18N.md)). The discipline pack works as a system-prompt fragment for ChatGPT, Gemini, local models, or anything else.

> **Future (roadmap):** Per-session ephemeral edicts (`/cc-enslaver:edict add --session ...`); Layer (g) content-hash escalation for same-second mtime edge cases. (Auto-GC on SessionStart — delivered in v0.18.)

---

## Repository structure

```
cc-enslaver/
├── .claude-plugin/
│   ├── plugin.json              # Plugin manifest
│   └── marketplace.json         # Single-plugin marketplace entry
├── CLAUDE.md                    # Project-level instructions (loaded by Claude Code)
├── README.md / CHANGELOG.md / LICENSE
├── docs/
│   ├── ARCHITECTURE.md          # How the layers fit together
│   ├── RULES.md                 # Catalog of every rule
│   ├── EDICTS.md                # Imperial Edicts (圣旨) user guide (v0.12)
│   └── I18N.md                  # Language version control — English is the skeleton (v0.21)
├── rules/                       # ★ LLM-agnostic source of truth (plain Markdown)
│   ├── 00-index.md ~ 12-repo-wide-sync.md  # English skeleton (source of truth)
│   └── zh/                      # 中文 translation (any rules/<code>/; v0.21)
├── prompts/                     # Distilled injection text (consumed by hooks)
│   ├── session-start.md         # SessionStart injection (English skeleton)
│   ├── user-prompt.md           # UserPromptSubmit injection (English skeleton)
│   └── zh/                      # 中文 translation (CC_ENSLAVER_LANG=zh; v0.21)
├── hooks/
│   ├── hooks.json               # Hook registration (4 events)
│   └── scripts/
│       ├── inject_context.py    # Soft-layer injection (English skeleton; any lang via CC_ENSLAVER_LANG)
│       ├── read_guard.py        # PreToolUse(Read|Edit|Write) — rule 04+08+09+10+11 + edicts + baseline
│       ├── bash_guard.py        # PreToolUse(Bash) — rule 03+09 + edicts
│       ├── stop_guard.py        # Stop — 9-layer status table
│       ├── register_read.py     # Read-cache escape hatch (v0.4)
│       ├── gc_state.py          # Manual session-state GC (v0.6.1)
│       ├── manage_edicts.py     # Imperial Edicts CRUD CLI (v0.12)
│       ├── i18n_check.py        # Language version-control sync check (v0.21)
│       └── lib/
│           ├── state.py         # Per-session JSON state (read_files / edits_per_file / baseline_mtimes / edited_files / ...)
│           ├── edicts.py        # Edicts loader / matcher / bilingual renderer (v0.12 + v0.17)
│           ├── sync_gate.py     # rule-12 sync-gate config loader / evaluator (v0.23)
│           ├── tomlio.py        # Hardened TOML reader (BOM + non-UTF-8) (v0.25)
│           ├── srclex.py        # Source lexer: comments / docstrings / data literals (v0.26)
│           ├── mdctx.py         # Markdown context: fences / blockquotes (v0.26)
│           └── shellcmd.py      # Shell command model: segments / argv / subcommands (v0.26)
├── commands/                    # /cc-enslaver:{checklist,verify,gc,edict,i18n}
├── agents/verifier.md           # Independent citation verifier subagent
├── skills/systematic-debug/     # Auto-invoked debug discipline skill
├── skills/repo-refresh/         # Auto-invoked whole-repo refresh skill (rule 12 active half; v0.23)
└── tests/                       # 556 black-box + unit tests (run with python -m unittest discover tests)
```

See [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) for a layer-by-layer walkthrough and [`docs/EDICTS.md`](docs/EDICTS.md) for the Imperial Edicts user guide.

---

## Installation

### As a Claude Code plugin (recommended)

The repo ships with `.claude-plugin/marketplace.json`, so it can be registered as a single-plugin marketplace and installed via Claude Code's `/plugin` UI.

```bash
# 1) Clone this repo somewhere — the path you choose becomes the marketplace root.
git clone https://github.com/skymanbp/cc-enslaver.git /path/to/cc-enslaver
```

Then in any Claude Code session (CLI or IDE):

```
/plugin marketplace add /path/to/cc-enslaver
/plugin install cc-enslaver@cc-enslaver
```

The plugin's internal name is `cc-enslaver` (declared in `plugin.json`), so slash commands surface as `/cc-enslaver:checklist`, `/cc-enslaver:verify`, and the auto-invoked `systematic-debug` skill is available as `systematic-debug`. The GitHub repo name `cc-enslaver` is the marketplace identifier.

To verify: `/plugin` → "Installed" tab should list `cc-enslaver@cc-enslaver`.

> **Requirements:** Python on PATH (tested with Python 3.13). The hook scripts use only the standard library — no third-party packages.

### As a rule pack for any other LLM

You don't need Claude Code at all. The actual rules live in [`rules/`](rules/) as plain Markdown. **English is the skeleton (source of truth)** at [`rules/`](rules/); the Chinese translation lives at [`rules/zh/`](rules/zh/) (any other language goes in `rules/<code>/`, kept in sync with the skeleton — see [`docs/I18N.md`](docs/I18N.md)).

```bash
# English (skeleton / default):
cat rules/*.md > /tmp/cc-enslaver.txt

# Chinese (translation):
cat rules/zh/*.md > /tmp/cc-enslaver.txt

# Then feed that to your agent of choice as system prompt / pre-context.
```

For specific integration patterns (OpenAI, Gemini, local llama.cpp, etc.) see the **LLM portability** section in [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).

---

## How it works

### Hooks (Claude Code only)

| Event | Matcher | Behavior | Implementation |
|---|---|---|---|
| `SessionStart` | — | Inject 12-rule discipline summary + standard response skeleton + Imperial Edicts block (English skeleton by default; any language via `CC_ENSLAVER_LANG`) | [`hooks/scripts/inject_context.py`](hooks/scripts/inject_context.py) |
| `UserPromptSubmit` | — | Re-inject per-turn decision triggers + Imperial Edicts (defends against context compaction) | [`hooks/scripts/inject_context.py`](hooks/scripts/inject_context.py) |
| `PreToolUse` | `Read\|Edit\|Write` | Record on Read/Write; capture mtime baseline (v0.16); deny Edit/Write of unread existing file (rule 04+08); deny patch-style `new_string` (rule 09 v0.11); deny hardcoded secret in code (rule 10 v0.22); deny user-home path dependency in code (rule 11 v0.22); deny 4th small Edit without systematic rewrite (rule 09 v0.13); deny on Imperial Edict `deny_edit` regex hit (v0.12); record the edit-turn signal (`edited_since_last_stop` + `last_edit_turn`, v0.23); record accepted edits into `edited_files` (rule 12 v0.23) | [`hooks/scripts/read_guard.py`](hooks/scripts/read_guard.py) |
| `PreToolUse` | `Bash` | Deny on bypass patterns (rule 03+09: `--no-verify` / `--no-gpg-sign` / `git push --force` / `chmod 777` / `git rebase --skip` / `--break-system-packages` / `rm -rf` root paths); process `register_read.py`; deny on Imperial Edict `deny_bash` regex hit | [`hooks/scripts/bash_guard.py`](hooks/scripts/bash_guard.py) |
| `Stop` | — | **Nine-layer decision** (v0.23): (a) no-evidence / (b) hedged-completion / (c) missing rule-06 quiz / (d) missing rule-07 fidelity / (e) missing rule-08 system-thinking / (f) missing rule-09 triplet / (g) file-claim contradicted by disk / (h) missing **or overlong (> 160 chars/item)** plain-language TL;DR / (i) rule-12 sync-gate group unmet (opt-in per project). Block reason renders as a uniform status table + a `大白话:` line. | [`hooks/scripts/stop_guard.py`](hooks/scripts/stop_guard.py) |

Hook scripts (8 total under [`hooks/scripts/`](hooks/scripts/)):

- **`inject_context.py`** — soft layer. Emits `hookSpecificOutput.additionalContext` from prompt files in [`prompts/`](prompts/) (the English skeleton) — or `prompts/<lang>/` when `CC_ENSLAVER_LANG=<lang>`, falling back to the skeleton for any file a translation is missing; appends Imperial Edicts block via `lib/edicts.render_injection()`. Always allows.
- **`read_guard.py`** — hard layer (file context). Read-before-edit (rule 04+08); patch-style content scan (rule 09 content axis); rolling-patch counter (rule 09 frequency axis, v0.13); Imperial Edicts content scan (v0.12); mtime baseline capture for Stop layer (g) (v0.16); edit-turn signal (`edited_since_last_stop` flag + optional `last_edit_turn`, v0.23). Failing-open.
- **`bash_guard.py`** — hard layer (command discipline). Static bypass-pattern catalog (rule 03+09); `register_read.py` interception; Imperial Edicts command scan (v0.12). Built-in patterns always run before Edicts so a project edict can't whitelist `--no-verify`. Failing-open.
- **`stop_guard.py`** — hard layer (rule 06+07+08+09+01+12 at turn boundary). 9-layer decision tree + uniform status-table block reason (v0.12) + file-claim verification (v0.16) + tldr length cap (v0.23) + sync gate (v0.23). One-shot guard via `last_blocked_turn` with 3-turn grace window. Layers (e)+(f)+(g)+(i) scoped to edit turns. Failing-open.
- **`register_read.py`** — user-facing CLI for the read-cache escape hatch (v0.4). State mutation lives in `bash_guard.py` after a SHA-256 hash match.
- **`gc_state.py`** — manual garbage collection of stale session state files (v0.6.1; dry-run by default).
- **`manage_edicts.py`** — Imperial Edicts CRUD CLI (v0.12; `--global` flag v0.14; UTF-8 stdout v0.17). Used by the `/cc-enslaver:edict` slash command and directly from the shell.
- **`lib/`** — the shared library the hooks are built on (7 modules): **`state.py`** (per-session state), **`edicts.py`** (Imperial Edicts loader / matcher / **multilingual renderer** — English default; `zh` or any code via `CC_ENSLAVER_LANG`, with English fallback for unknown codes; v0.17 + v0.21), **`sync_gate.py`** (rule-12 sync-gate config loader / evaluator, v0.23), **`tomlio.py`** (hardened TOML reader — BOM and non-UTF-8 tolerant, v0.25), and the three models added in v0.26 that the detectors now decide with rather than pattern-matching raw text: **`srclex.py`** (tolerant source lexer — comment vs docstring vs data literal, literal masking, bracket-joined logical lines), **`mdctx.py`** (markdown fence / blockquote context, shared by both halves of Stop layer (h)), **`shellcmd.py`** (tokenise → segments → argv → git sub-command / python script operand).

All scripts are covered by **556 tests** in [`tests/`](tests/) (black-box subprocess tests for the hooks + unit tests for `lib/sync_gate.py` and for the three v0.26 models in `tests/test_v026_models.py`, plus the version-drift and doc-drift gates) — run with `python -m unittest discover tests`. CI matrix: ubuntu-latest × windows-latest × Python 3.13. Session state is safe under parallel hook processes (v0.23, completed v0.24): every mutation holds a cross-process file lock and saves atomically, read accessors share the same lock (the v0.24 fix for Windows `os.replace`-vs-open-reader save loss), pinned by a 12-way concurrency regression test plus a reader-writer collision test. Production payload shapes (no `turn_count`, transcript-only Stop messages) are pinned by a dedicated E2E test class.

See [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) §2 for the full hook output contracts.

### User-invokable

| Surface | Purpose |
|---|---|
| `/cc-enslaver:checklist`   | Print the 8-section checklist (pre-action / pre-finish) on demand. |
| `/cc-enslaver:verify`      | Ask the agent to re-verify recent `file:line` citations and fact claims. |
| `/cc-enslaver:gc`          | List (or `--apply` to delete) session-state files older than N days. |
| `/cc-enslaver:edict`       | Manage Imperial Edicts: `list / add / remove / reload / path` (+ `--global`). |
| `verifier` subagent        | Independently re-reads cited locations and reports drift. |
| `systematic-debug` skill   | Auto-triggered on bug-fix language; forces root-cause walk before any fix. |
| `repo-refresh` skill       | Auto-triggered on "全库更新" / "stale scan" / "audit the repo"; five-category whole-repo sweep (rule 12 active half, v0.23). |

### Environment switches

| Variable | Effect |
|---|---|
| `CC_ENSLAVER_LANG=<code>` | Choose the injection language for SessionStart / UserPromptSubmit AND Imperial Edicts injection + deny reason. Default (unset / `en`) = **English skeleton**; `zh` = Chinese; any other code reads `<dir>/<code>/` and falls back to the English skeleton for missing files. |
| `CC_ENSLAVER_DISABLE_LAYER_G=1` | Disable Stop layer (g) file-claim verification (escape hatch for false positives in unusual workflows; the other 8 layers still apply). |
| `CC_ENSLAVER_AUTO_GC_DAYS=N` | **v0.18 opt-in.** Auto-prune session-state files older than N days on SessionStart. Rate-limited to once per 24h via a marker file. Unset / `0` / non-numeric → disabled. |
| `CLAUDE_PLUGIN_DATA` | Session-state base dir. Set by Claude Code; falls back to `${CLAUDE_PROJECT_DIR}/.claude/local/cc-enslaver/` then `~/.claude/local/cc-enslaver/`. |
| `CLAUDE_PROJECT_DIR` | Project root. Used to resolve project-level edicts at `.claude/cc-enslaver/edicts.toml`. |

---

## Contributing

The plugin enforces its own rules on its own development. Read [`CLAUDE.md`](CLAUDE.md)
section 4 ("修改本仓库时的强制流程") before opening a PR. In short:

1. Read every related file end-to-end before editing.
2. Trace downstream impact (e.g., editing a rule file → update the prompt, the
   docs, the checklist command, all in the same change).
3. Cite `file:line` in PR descriptions; never "I think" / "should be".
4. Address root causes, not symptoms. No `--no-verify`, no swallowed errors.

---

## License

MIT — see [`LICENSE`](LICENSE).

---

## 中文说明

`cc-enslaver` 是一个 **Claude Code 插件 + 任意 LLM 通用规则包**。它存在的唯一目的是：**杜绝 AI 编程助手的偷懒行为**。

### "偷懒"具体指什么？

| 偷懒模式 | 表现 |
|---|---|
| 反应式修补 | 看到 bug 就 try/except 包一下，宣告完成 |
| 猜测式引用 | 引用了不存在的 `file:line`、API 或版本号 |
| 关键词检索依赖 | grep 一下就改，从不读上下文 |
| 记忆依赖 | 凭印象答题，不重新读当前文件 |
| 根因绕过 | 用 `sleep` 掩盖竞态、用 `--no-verify` 跳过钩子 |
| 半成品 | 写到"应该能工作"就停手，留 TODO，不验证整条链路 |

### 防御分层（**v0.28.0**：12 内置规则 + 用户自定义圣旨 + Stop 钩子 9 层闸门）

> **v0.28.0 新增** — 🪜 **rule 03 + 09 语义升级：溯源 → 确诊 → 统一修复，点对点补丁明令禁止**。rule 03 新增**上游溯源阶梯**：每个失败有三种位置——**症状位**（浮出水面处）、**传播路径**（坏状态流经的代码）、**起源**（*产生*坏状态的机制 / 设计决策 / 缺失不变量）；修在前两级都算补丁，哪怕现象消失。沿链上爬直到答案是机制为止；停在中途必须点名真正起源 + 理由，且根因假设必须先经第一方探针 / 复现 / 红测试**确诊**再动手。rule 09 新增**"一个根因，一次统一修复"**：确诊的根因定义一个"类"——你看到的实例只是先冒头的那个；全库清扫同类、机制只修一次、同趟覆盖全部实例，并重触发类里**另一个**实例证明类已闭合。N 个症状共一个根因 = 一次修复，绝非 N 个补丁。动机是本仓库自己的实测史：v0.25.1 点名根因却只修实例，机制存活、v0.26 再生同类新缺陷（含一个倒退）——v0.28 把"换机制而非修症状"固化为每次修复的强制形态。**零新检测器**（v0.22.1 同一先例：推理形态而非钩子可匹配的语法形态）；既有硬层（补丁标记内容层 / rolling-patch 频率层 / Stop layer (f) 三件套）仍是物理地板。checklist 新增 F9–F11；测试保持 556。
>
> **v0.27.0 新增** — 🧵 **把 v0.26 记为"已知但不修"的三条契约悬案全部收口，方向由证据定、不由偏好定**。shell tokenizer 跟 **shell** 走、不跟宿主机走：实测 Claude Code 在 Windows 上真正用的 shell（Git Bash / MSYS）后发现 v0.25.1 那条 `os.name == "nt"` 分支两个方向都错——真实 shell 同样吃掉不加引号盘符路径的分隔符（所以它从没救回任何东西），而 `git push --for\ce` 到 git 手里就是 `--force`——一个活的 force-push 绕过，已闭合；盘符路径的受支持写法是**加引号**。layer (h) 把"存在"（宽，`attributable`）与"度量"（严，`countable`）拆成两个判定，CommonMark 懒延续随之实现。layer (i) 一组一次**知情**回答：标记只结清已被点名展示过的组（刻意的严格度上调，如实记录）。测试 **543 → 556**。
>
> **v0.26.0 新增** — 🧩 **第四轮审计：这次审的是上一版自己的修复 diff，而且换掉的是机制，不是症状**。三路并行只读审阅 + 我自己一路，共 **37 条 finding**；**33 条**用我自己的运行时探针复现，3 条记录为"属设计"，**1 条被驳回**（审阅说某测试空转，实际它在未修树上是红的）。它们归结为**三个根因**，修法是**四个统一件**，不是 ~30 个补丁。此后又跑了**第二轮 16 路并行只读复审**（15 路有效；sync-gate 那一路返回空、**未跑**，如实记录），按根因再修 20+ 处确认缺陷——其中包括本版发布说明自己写错的 **5 处测试数**与 **2 处错误声称**。测试 **378 → 556**；第一轮新断言在未修树上 replay 出 **43 failures + 3 errors**（第二轮无 pre-fix 树可回放，两轮均未提交）。
>
> **本轮的修复代码自己也过了一遍只读复审**（因为这一版要修的缺陷，正是上一版的修复引入的）。复审在**新代码里**又抓出 **8 个真缺陷**，已全部修掉：`$( … )` / 反引号 / 子 shell 的调用没被分段——而被替换掉的文本启发式**是靠巧合**抓住它们的，所以这个模型本来会是**倒退**（`$(git push --force)` 是真会执行的）；转义的 `\"""` 会提前结束三引号块，把字符串内容暴露成注释；围栏模型三处 CommonMark 缺陷；否定判断漏了 `cannot` / `unable` / `绝非`（**危险方向**：会把如实的"没做完"当成完成声明拦下），同时 `not only fixed but tested` 被误判为否定；标点填充能凑够理由长度门槛。另有**我自己的一处改动被回退**——它打破了 v0.23 刻意钉下的契约。
>
> **α — 检测器描述的是"拼写"，不是概念**。"这个 `#` 是注释吗"写成了 `line.find("#")`，于是它找到 URL 里的 `#`——相邻一行 `API = "https://api.example.com"` 就能把 **rule 10 密钥检测器整个关掉**（`example` 是理由 token，而 `example.com` 是 IANA 保留示例域名，也就是说泄漏恰好发生在凭证最常出现的地方）。"这个 `try` 块到哪结束"靠的是**物理行**缩进，于是多行字符串的正文能重新锚定块；而 handler 会抑制**所有**出栈，导致嵌套 `try/except` 从 v0.25.0 的拦截**倒退**成 v0.25.1 的放行——**而它自己的 docstring 正宣称"现在用栈处理嵌套了"**。"这条命令 force-push 吗"靠的是文本里的词共现——把 `echo` 一段 force-push 字符串和 `git config alias.deploy "push --mirror"` 误拦，却漏掉 `git push origin +main` 和 `+:refs/heads/main`。"这个 token 会被执行吗"靠的是往回跳过横杠，于是 `python -c register_read.py` 污染了 read 状态，而 `python -X utf8 …`（**它自己 docstring 里写明支持的例子**）和 `python3.13` 反而不认。改为 [`lib/srclex.py`](hooks/scripts/lib/srclex.py)（宽容词法器：注释 / docstring / 数据字面量的区分、字面量遮蔽、按括号合并逻辑行）、[`lib/mdctx.py`](hooks/scripts/lib/mdctx.py)（围栏 / 引用上下文，现由 Stop layer (h) **两个半区共用**——它们此前对"哪些围栏算数"意见不一致）、[`lib/shellcmd.py`](hooks/scripts/lib/shellcmd.py)（分段 → argv → git 子命令 / python 脚本操作数），以及一个 schema 驱动的状态归一器。
>
> **β — 加固只针对被观察到的那一处**。v0.25.1 的归一器修了 `read_files`，却留下 `session_id` 抛 `KeyError`——于是一次 Read 没被记录，**下一次编辑被误判未读而拒绝**；auto-GC 拿**原始** session id 去比**净化过的**文件名；`manage_edicts` 只对 `id` 做了 `str()`，一个类型写错的字段就能让整个 CLI 崩掉。
>
> **γ — 结论跑在改动前面**。四个测试在未修树上原样通过（现已补孪生断言）；自改性不变量的 docstring 说它钉的是"全树"，glob 却只覆盖 `hooks/scripts`——**十个测试模块里有六个是自锁的**（用 pre-fix 检测器重放 `83e5487` 上每个 `tests/*.py` 的 pre-fix 内容实测得到，不是估的）。这条根因在第二轮复审里又被抓到一次，而且抓的是本版发布说明自己：原稿写"七个模块全部自锁"，两个半句都不成立。
>
> 另外：标记正则现在在**词边界**收尾（`# noquality` / `@ts-ignore-generated` / `eslint-disablement` 此前都是误拦）；理由逃生口现在认**中文**（`因为` / `故意`——此前只认英文，而这是个以中文为主语言的仓库）和**块注释**；完成声明的否定判断现在能处理 `not yet done` / `isn't done`（旧的 `\bn't\b` 是**永远匹配不到的死代码**）。

> **v0.25.1 新增** — 🔬 **第三轮审计：94 条审阅 finding → 21 条自证复现 → 六处根因修复**。三路并行只读审阅对 v0.25.0 树返回 94 条；我没有照单全收，而是把每条高信号 claim 拿真实代码用探针重跑，复现的 21 条**归结为六个根因**——按 rule 09 自己的"系统式 ≫ 打补丁"，做成六处系统性修改而不是 21 个补丁。红先：新断言在未修树上产生 **37 failures + 4 errors**，修后 **378/378**（350 → 378）。主题是**检测器描述的是"字符串"而不是"概念"**。九条只差一个拼写：**CRLF** 击穿全部五个单行 rule-09 标记——就在本插件的主平台上；**任意尾随文本**让标记**根本不匹配**，于是 `@ts-ignore` 后跟一个光秃秃的延期词反而放行、裸形态反被拦、理由检查从未运行；**`except:` 与 `pass` 之间的注释行**把吞错行挪出扫描器视野，让 rule 09 的逃生口对最自然的写法依旧不可达——v0.25 只修了同行写法，还配了一条因错误原因而通过的回归测试；`except Exception: pass` 单行形、嵌套的 `time.sleep(max(0, d))`、源码里**成对**反斜杠的 `"C:\\Users\\bob"`（user-home 路径在被提交代码里的实际样子）、`git -C repo push --force`、引号形 `"--force"`、`+refspec`、`--mirror` 全部在外面。第二个根因：**配置值未验类型**——`severity = ["must"]` 和 `mode = []` 都是合法 TOML，`TypeError: unhashable type` 从两个自称"never raises"的 loader 里逃出来，让 rule 04 + 08 整场失效，并把 Stop layer (i) 一起带走。第三：理由逃生口**两个方向都错**——普通代码里的 token 就能让标记沉默（`reason = compute()`），而写成独立注释行反倒不可达。第四：拿"有没有这个词"冒充"有没有这个意思"——`已完成` / `Implemented` / `Finished` 不在 `DONE_PATTERNS` 里，于是 **Stop 九层全跳过**；`Not done; tests failed.` 反倒算完成声明；**空的 `tldr:`** 满足 layer (h)。第五：**auto-GC 会删掉被恢复会话的活状态**，而一个写错类型的 GC 标记文件会让整个 SessionStart 注入静默消失。第六：宽限期的同步 ack 会静音掉**从未向 agent 展示过**的组。

> **v0.25 新增** — 🔍 **第二轮审计：12 个确认缺陷修复，零新功能**。对 v0.24 树做多路对抗式审阅，每条 finding 独立探针复证，回归先红后绿（**323 → 346**，其中 32 条断言在修复前的树上是红的）。主题是**能被绕过的守卫**：一次成功的 `register_read` 调用会短路**整个**绕过模式目录——`register_read.py --file F --hash H && git push --force` 是**放行**的；现在 deny 检查先跑，且注定被拒的命令不再改动会话状态。规则 09 的旗舰检测器 `try/except: pass` 被 `pass` 行**任意行尾注释**击穿，这同时让它自己的 why 注释逃生口**不可达**（加理由是靠改变字符串让检测器沉默，理由从没被读过）；而且一个 `try` 只看第一个 `except`，放过了"窄 handler + 兜底吞掉"这个最典型形态。**在文件存在之前**读它，一旦有别的东西创建了它，就永久获得了盲改授权。状态文件"存在但读不出"会变成**误 DENY**（read-before-edit），而 stderr 同时在喊"failing open"。layer (g) 的中文声明正则没有第一人称锚点，于是 `v0.23 修改了 X` 被当成自我声明、如实的第三方归因反而被**拦下**——发生在本仓库自己的主语言上。一个编码错误的 `edicts.toml` 会让 `UnicodeDecodeError` 穿过所有下游检查，把 read-before-edit **整场关掉**。另外：带引号键的密钥（`"api_key": "…"`，最常见的凭证提交形态）现在拦得住；force-push 检测收敛到 `git push` 子命令（`rm -f x && git push` 不再误拒，`git push -fu` 不再漏网）；两个 TOML 配置共用加固读取器（[`lib/tomlio.py`](hooks/scripts/lib/tomlio.py)）；嵌套代码围栏不再关掉父围栏。以及：**12 个 hook 脚本里有 5 个是自锁的**——任何运行本插件的 agent 都改不动它们，因为它们自己带着裸 `# noqa` / `try: … except: pass`——现已修复并由一条全树测试钉住。
>
> **v0.24 起** — 🩺 **体检式发布：10 个确认缺陷修复（3 个 HIGH），零新功能**。一轮完整架构审查 + 多路对抗式模型审阅（每条 finding 先用运行时探针独立复证、回归测试先红后绿）修掉了：**Windows 上 state 保存被插件自己的无锁读者悄悄丢弃**（`os.replace` 撞上打开中的读者 → `PermissionError` → failing-open → 记录消失；读访问器现与写共享会话锁，`save()` 对外部读者加重试——这个 bug 在体检会话里当场活体复现：插件把自己审计者的 Edit 误拒了）；**layer (i) 同步确认在 one-shot 宽限窗口内丢失**（被拦→带 `同步核对:` 恢复的主流程从不落盘 ack，已答过的组过后再拦；宽限路径现在会读回复并记 ack）；**被 DENY 的新文件 Write 仍把目标注册为"已读"**；rolling-patch 计数器原子化；以及规则 10/11 的三处误报/漏报修正（`password: "SecretStr"` 注解、URL 路由里的 `/home/` 段、`requirements*.txt` 凭证扫描 + `.asciidoc` 豁免）。测试 310 → 323。
>
> **v0.23 起** — 🔄 **规则 12：全库同步（全库更新）+ tldr 长度硬约定**。修改的完成标准升级为：所改内容在**仓库任何角落的引用**——文档、下游代码、测试、镜像翻译——同会话连带更新，或显式核对确认无需改（收尾用一行 `同步核对:` / `sync-check:` 汇报）。**被动半区**是项目级代码门禁：把已知连带不变量登记进 `.claude/cc-enslaver/sync-gate.toml`（`[[groups]]` 的 `when` / `require` glob），新增 **Stop layer (i)** 在"`when` 命中而 `require` 侧无编辑、回复又无同步标记"时拦下 done-claim——按项目 opt-in、failing-open，标记逃生口让"核对过、无需改"成为显式合法结论。**主动半区**是新的 **`repo-refresh` skill**（"全库更新" / "扫陈旧" / "audit the repo" 自动唤起）：对全库（文档 + 代码）按**陈旧 / 过时 / 冗余 / 错误 / 漂移**五类做系统式扫描，每条 finding 带 `file:line` 证据。另外，v0.20 的 `tldr` 收尾加上 **单条 160 字符上限**（Stop layer (h) 硬强制）：每条一句话（前因 → 动作 → 结果），多条内容逐条一行。详见 [`rules/zh/12-repo-wide-sync.md`](rules/zh/12-repo-wide-sync.md)。
>
> **v0.22.2 起** — 🏷️ **版本漂移门——因为 v0.22.1 自己发歪了**。`plugin.json` 写着 `0.22.1`，而 `.claude-plugin/marketplace.json`——*插件安装器真正读的那个文件*——两个版本字段都还停在 `0.22.0`。测试全过、CI 全绿、tag 已推，用户看到的却仍是上一个版本。这正是 v0.22.1 自己刚立的**证据覆盖面 ≠ 结论覆盖面**，被引入该规则的那次发布本身犯了：绿色套件对它从没打开过的两个清单文件什么也没证明。[`tests/test_version_sync.py`](tests/test_version_sync.py) 把 `plugin.json` 立为唯一版本权威，并把 README 徽章与 `CHANGELOG` 最新发布标题钉死到它。清单里的版本位点是**封闭集**（规则 09）：递归遍历两个清单的*每一个* `"version"` 键，发现的 JSON 指针集合必须等于登记集合——所以以后新加的版本字段无法悄悄逃过这道门，而"检查这两条路径"式的清单会放它过去。同批修正：**git tag 不等于 release**——v0.22.1 的 tag 推了，却从未创建 GitHub Release 对象，所以 releases 页面同样还停在 v0.22.0。[`CLAUDE.md`](CLAUDE.md) §4.1 的发布清单现在终点是 `gh release create`，而不是 `git push --tags`。
>
> **v0.22.1 新增** — 🔬 **两条规则按真实翻车现场加厚**（零新检测器、零新 Stop 层，故为补丁级）。**规则 06 加「验证 2b：总量相等 ≠ 没变」**：任何"没变 / 无回归"的声称必须比**集合**（类别名、测试 ID、失败断言身份、逐文件哈希），绝不凭一个相同的**总数**。实证：某校验器在约 9,500 处替换前后都打印 `Total issues: 754`（逐字节相同），而逐类别比对显示一类从 `OK …: INFO:1` 翻成 `X …: CRITICAL:1`。附带推论**证据覆盖面 ≠ 结论覆盖面**：门只对它检查的那部分变绿，其余什么也没证明。**规则 09 加批量机械替换纪律**（改名 / codemod / sed）：先勘察 token 真实上下文再写规则、只改白名单形态、出**拒绝报告**、算术自洽（总数 = 改写 + 跳过 + 拒绝）、预期三种正则天生看不见的形态（藏在正则选择分支里 / 作独立参数 / 以它命名的符号）、**绝不改写寻址历史的路径**（`git show <固定 rev>:<path>`）。另加**封闭集守卫**：不变量若是"只有名单内合法"，就枚举合法集而不是拉黑见过的散件形态。详见 [`rules/zh/06-verify-convergence.md`](rules/zh/06-verify-convergence.md) + [`rules/zh/09-systematic-modification.md`](rules/zh/09-systematic-modification.md)。
>
> **v0.22 新增** — 🔒 **两个写时内容检测器（规则 10 + 11）**：`PreToolUse(Edit|Write)` 现在物理 **DENY** 把*非必须*的硬编码或机器相关路径依赖写进代码。**规则 10（禁止硬编码）** 拦截未经证明的硬编码密钥——secret 命名的字面量（`password` / `api_key` / `token` / … ≥ 8 字符）、PEM `-----BEGIN … PRIVATE KEY-----` 头、`AKIA…` AWS key、或连接串里内嵌的凭证。**规则 11（禁止路径依赖）** 拦截写死进代码的 user-home 绝对路径（`C:\Users\…`、`/home/…` 或 `/Users/…`、`$HOME`、`%USERPROFILE%`、带引号的 `~/…`）。两者共用 rule-09 的 **why 注释逃生口**——相邻一行有 `because` / `原因` / `essential` / `fixture` / `placeholder` 说明即放行，这正是"*非必须*"的落地方式——且都**豁免散文档 + lockfile**（`.md` / `.rst` / `.txt` / `.adoc`、`*.lock`、`package-lock.json`），所以本仓库自己满是示例路径的文档不会自触发。跟其它内容检测器一样是 **PreToolUse-only**（无 Stop 层）。详见 [`rules/10-no-hardcoding.md`](rules/10-no-hardcoding.md) + [`rules/11-no-path-dependency.md`](rules/11-no-path-dependency.md)。
>
> **v0.21 新增** — 🌍 **英文成为骨架语言**：插件的规则 + 注入文案从"中文 canonical"翻转为**英文 = source of truth**。英文放在根层（`rules/*.md`、`prompts/*.md`），每种翻译放语言子目录（`rules/zh/`、`prompts/zh/`、任意 `rules/<code>/`）。注入**默认英文**（`CC_ENSLAVER_LANG` 未设 / `en`）；设 `CC_ENSLAVER_LANG=zh` 用中文，或任意语言码用部分翻译（缺失文件自动回退英文骨架）。**语言版本控制是硬性、CI 强制的闸门**：[`hooks/scripts/i18n_check.py`](hooks/scripts/i18n_check.py)（`/cc-enslaver:i18n` 调用）断言每种翻译逐文件、逐章节跟随骨架；[`tests/test_i18n_sync.py`](tests/test_i18n_sync.py) 一旦漂移就让 CI 变红。**漂移时以英文为准。** 详见 [`docs/I18N.md`](docs/I18N.md)。
>
> **v0.20 新增** — 📋 **结构化 YAML 汇报 + 大白话总结**：每次回复末尾输出固定的 ```yaml `cc-enslaver:` 块（`改前 / 改中 / 收敛 / 忠实 / 收尾 / tldr`），把审计轨迹从飘忽的自由文本变成**一眼可扫的固定 schema**。新增 **Stop layer (h)** 硬强制每条 done-claim 回复必含一句 `tldr`（大白话总结），每条拦截理由也附一行 `大白话:`。schema 的字段名**本身就是**现有 Stop 检测 marker，所以检测层一行未改——新旧两种回复格式都通过。

1. **软提醒层**：会话启动 + 每轮用户提问前，把纪律规则 + 圣旨注入 agent 上下文。**v0.21 起**默认英文骨架（`CC_ENSLAVER_LANG` 未设 / `en`）；设 `CC_ENSLAVER_LANG=zh` 切到中文，或任意语言码用部分翻译、缺失文件回退英文（注入主体 + 圣旨 deny reason 同步切换）。**v0.20** 把"标准回复骨架"改为上面的 YAML schema。
2. **硬拦截层**：agent 调用 `Edit` / `Write` / `Bash` 或 Stop 时，插件在工具/回合边界做拦截：
   - **Edit/Write 改前必读**（v0.2 + v0.11 rule 08）：目标文件已存在但本会话未 `Read` 过 → DENY。新文件创建放行。
   - **Edit/Write 反补丁内容**（**v0.11 rule 09**）：new_string 含未带 why 注释的 `try/except: pass` / `# noqa` / `# type: ignore` / `@ts-ignore` / `@ts-expect-error` / `// eslint-disable` / `time.sleep(...) # race` → DENY。why 注释必须落在**注释**里，且"是不是注释"由词法器判定（v0.26：URL 里的 `#` 不算，`/* … */` 与独立成行 docstring 算）。
   - **Edit/Write rolling-patch 频率**（**v0.13 rule 09**）：同一文件本会话第 4 次小幅 Edit（≤ 10 行 且 < 200 字符）且**无**系统式重写（≥ 50 行 / ≥ 1500 字符）介入 → DENY；不增计数器，需一次系统式 Edit/Write 才能重置。
   - **Edit/Write 禁止非必须硬编码**（**v0.22 rule 10**）：写入*代码*（非 `.md` / `.markdown` / `.rst` / `.txt` / `.adoc` / `.asciidoc` 散文档、非 lockfile）的 new_string 含未经证明的硬编码密钥（secret 命名字面量 ≥ 8 字符、含带引号键形态 / PEM 私钥头 / `AKIA…` / 服务商 token `ghp_…` `xox…` `AIza…` / 连接串内嵌凭证）→ DENY。相邻 why 注释（`because` / `原因` / `因为` / `essential` / `fixture` / `placeholder`）或占位符放行。**注意 `.txt` 有一个 v0.24 反向豁免**：`requirements*.txt` / `constraints*.txt` 是依赖清单不是散文，仍然会被扫描。
   - **Edit/Write 禁止非必须路径依赖**（**v0.22 rule 11**）：写入代码的 user-home 绝对路径（`C:\Users\…` / `/home/…` 或 `/Users/…` / `$HOME` / `%USERPROFILE%` / 带引号 `~/…`）→ DENY。改为运行时派生，或加相邻 why 注释。与 rule 10 同样豁免散文档 + lockfile。
   - **Edit/Write 圣旨**（**v0.12**）：new_string 命中项目 `edicts.toml` 中 `must` 圣旨的 `deny_edit` 正则 → DENY。
   - **Bash 内置绕过**（v0.3 + **v0.14 扩**）：`--no-verify` / `--no-gpg-sign` / `git push --force` / `chmod 777` / `git rebase --skip` / `--break-system-packages` / `rm -rf` 根路径 → DENY。
   - **Bash 圣旨**（v0.12）：命令命中 `must` 圣旨的 `deny_bash` 正则 → DENY。内置先跑、圣旨后跑（圣旨不能 whitelist `--no-verify`）。
   - **Read 缓存逃生口**（v0.4）：`register_read.py` + bash_guard 重算 SHA-256 闸门。
   - **基线 + Edit-turn 信号**（v0.11 + v0.16 + **v0.23 重做**）：每次成功 Read/Edit/Write 捕获 mtime 基线（v0.16），并置 `edited_since_last_stop` 旗标（production 载荷不带 turn_count——E2E 实弹发现，v0.23 前 edit 门控层在真实运行中从未触发；旗标在每次放行的 Stop 清除、被拦的 Stop 保留），给 Stop 各层提供判定依据。
   - **Stop 钩子**（v0.6 → v0.7 → v0.8 → v0.11 → v0.16 → v0.20 → **v0.23**）：每次 Stop **九层**决策，输出**统一状态表**（✅ Pass / ❌ FAIL / ⏸ pending / — n/a）+ 一行 `大白话:`：(a) done 但无 evidence；(b) done 附近 50 字内含 hedge（rule 01 投影）；(c) 有 evidence 但缺 rule-06 收敛标记 + 4 题命中 < 2；(d) 通过 (a-c) 但缺 rule-07 忠实标记 + 3 题命中 < 2；(e) 本轮做了 Edit 但缺 rule-08 标记 + rule-02 关键词命中 < 3；(f) 本轮做了 Edit 但缺 rule-09 "根因+影响+方案" 三件套；**(g) v0.16** —— 本轮做了 Edit 且解析出 `I edited X.py` / `我修改了 Y.md` 类声明，但磁盘 mtime 与基线一致（claim 被证伪）→ 拒；**(h) v0.20（v0.23 加长度上限）** —— 含 done-claim 的回复缺 `tldr` / `大白话` / `TL;DR`，或 tldr **单条超 160 字符** → 拒（在**所有 done-claim 轮**触发，非 edit-only）；**(i) v0.23** —— 本轮做了 Edit 且项目 `sync-gate.toml` 某组 `when` 命中而无 `require` 编辑、回复又无同步标记 → 拒（rule 12；无配置项目永不触发）。一次性守卫 + 3-turn 宽限窗口避免死循环。`CC_ENSLAVER_DISABLE_LAYER_G=1` 可禁用 (g)。
3. **主动调用层**：**5 个 slash 命令** —— `/cc-enslaver:checklist`、`/cc-enslaver:verify`、`/cc-enslaver:gc`（v0.6.1）、`/cc-enslaver:edict`（**v0.12** CRUD；**v0.14** 加 `--global` 写到 `~/.claude`）、`/cc-enslaver:i18n`（**v0.21** 语言版本控制检查）。
4. **子代理验证层**：`verifier` 独立重读 agent 给出的 `file:line` 引用，检查是否真实。
5. **技能层**：`systematic-debug` 在 debug 语境下自动唤起，强制走根因分析流程（v0.10 加 Step 0 = build feedback loop）；`repo-refresh`（v0.23）在"全库更新 / 扫陈旧"语境自动唤起，执行规则 12 主动半区的五类全库扫描。
6. **LLM-agnostic 核心**：所有规则以纯 Markdown 形式存放，**英文为骨架（source of truth）**放在 [`rules/`](rules/) 根层，翻译放语言子目录 [`rules/zh/`](rules/zh/) / 任意 `rules/<code>/`；注入文案同布局（[`prompts/`](prompts/) = 英文骨架，`prompts/<code>/` = 翻译）。翻译由 CI 硬门锁定跟随骨架（见 [`docs/I18N.md`](docs/I18N.md)）。整包可作为任意 LLM 的 system prompt 片段使用。

> **当前路线图**：会话级临时圣旨（`--session`）、Layer (g) 的 content-hash 同秒精度升级。（SessionStart 自动 GC 已在 v0.18 交付。）

### 安装

#### 作为 Claude Code 插件

```bash
git clone https://github.com/skymanbp/cc-enslaver.git /path/to/cc-enslaver
```

在 Claude Code 会话内：

```
/plugin marketplace add /path/to/cc-enslaver
/plugin install cc-enslaver@cc-enslaver
```

验证：`/plugin` 命令的 "Installed" 列表中应出现 `cc-enslaver@cc-enslaver`。
钩子脚本要求 `python` 在 PATH 上（在 Python 3.13 上测试过；只用标准库）。

#### 作为通用 LLM 规则包

```bash
# 英文骨架（默认 / source of truth）：
cat rules/*.md > cc-enslaver-rules-en.txt
# 或中文翻译：
cat rules/zh/*.md > cc-enslaver-rules-zh.txt
```

把这段文本作为 system prompt 喂给任何 LLM 即可。

### 详细文档

- 设计原则与项目级指令 → [`CLAUDE.md`](CLAUDE.md)
- 架构说明 → [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md)
- 完整规则目录 → [`docs/RULES.md`](docs/RULES.md)
- 圣旨（Imperial Edicts）使用指南 → [`docs/EDICTS.md`](docs/EDICTS.md)
- 变更日志与路线图 → [`CHANGELOG.md`](CHANGELOG.md)

### 环境变量

| 变量 | 作用 |
|---|---|
| `CC_ENSLAVER_LANG=<code>` | 选择 SessionStart / UserPromptSubmit 注入 + 圣旨注入 + DENY reason 的语言。默认（未设 / `en`）= **英文骨架（source of truth）**；`zh` = 中文翻译；其它语言码读 `<dir>/<code>/`，缺失文件自动回退英文骨架。语言版本控制契约见 [`docs/I18N.md`](docs/I18N.md)。 |
| `CC_ENSLAVER_DISABLE_LAYER_G=1` | 禁用 Stop layer (g) 文件声明验证（false-positive 时的 escape hatch；其余 8 层仍有效） |
| `CC_ENSLAVER_AUTO_GC_DAYS=N` | **v0.18 opt-in**：SessionStart 时自动清理 ≥ N 天未触碰的 state 文件。24h 速率限制。未设置 / `0` / 非数字 → 关闭。 |
