---
id: "11"
title: "No non-essential path dependency"
severity: must
---

# Rule 11 — No non-essential path dependency

## Principle

> **A filesystem path that is specific to one machine, one user, or one
> checkout must not be baked into code as an absolute literal.** Derive
> paths from a base the runtime already knows — the plugin root, the
> current working directory, an environment variable, or a passed-in
> argument.

A machine-specific absolute path is a portability landmine: it works on
the author's box and breaks on every other machine, CI runner, and
container. This repo lived that failure — **v0.21.1** was a hotfix for a
Windows path-portability bug in its *own* hook (a `~`-containing runner
`$TEMP` the path regex could not parse). Rule 11 makes "don't hardcode a
user-home path" a write-time, root-cause discipline (rule 03).

## What is hard-enforced (and what is not)

Faithful to the conservative-detector philosophy ("宁可漏报不误报"), only
paths anchored at a **user-specific root** are hard-enforced — the class
that is almost never legitimately portable:

| Class | Hard-enforced? |
|---|---|
| Windows user-home absolute path (`C:\Users\name\…`) | ✅ yes |
| POSIX user-home absolute path (`/home/name/…`, `/Users/name/…`) | ✅ yes |
| Shell home variable in a literal (`$HOME`, `%USERPROFILE%`) | ✅ yes |
| User-home tilde path in a string literal (`"~/…"`) | ✅ yes |
| System paths (`/etc/…`, `/usr/…`, bare `C:\`) | ❌ soft guidance only |
| Relative paths (`./data`, `../lib`) | ❌ allowed (already portable) |

System roots and bare drive letters are deliberately *not* flagged: they
are often legitimately fixed, and a hard detector for them would fire on
correct code. Relative paths are the desired outcome, not a violation.

## Physical interception (hooks)

| Layer | Hook | Trigger | Action |
|---|---|---|---|
| **Edit/Write content** | `PreToolUse(Edit\|Write)` | `new_string` / `content` contains an unjustified user-specific absolute path | **DENY** |

Prose docs (`.md` / `.markdown` / `.rst` / `.txt` / `.adoc` /
`.asciidoc`) and lockfiles are **exempt** — this repo's own docs are
full of illustrative `C:\Users\skyma\…` paths, and lockfiles
legitimately record absolute resolved paths. The detector targets
freshly authored *code*. (The `requirements*.txt` / `constraints*.txt`
carve-out from rule 10 applies here too — the exemption logic is
shared.)

### Detector catalog

The following, when present in the incoming content **without an adjacent
"why" rationale**, are intercepted:

| Pattern | Example (illustrative) |
|---|---|
| Windows user-home path (raw **or** escaped separators) | `C:\Users\skyma\data.csv` |
| POSIX user-home path | `/home/alice/proj/` |
| shell home variable literal | `$HOME`, `%USERPROFILE%` |
| tilde path in a quote | `"~/proj/data"` |

**Escaped separators count (v0.25.1).** The Windows pattern used a
single-character separator class, so it only ever matched a raw spelling.
In real Python / JSON / JavaScript source the separator is **doubled** —
that is how a user-home path actually appears in committed code — and the
detector caught the rare form while waving through the normal one, on the
platform this rule pack is most often run on.

The portable alternatives the detector wants you to reach for:
`Path(__file__).resolve().parent…`, `os.environ["CC_PLUGIN_DATA"]`,
`Path.home()` computed at runtime (not a literal), a CLI argument, or a
path relative to the repo root.

A `/home/<x>/` segment glued to a hostname is NOT flagged (v0.24): in
`https://host.test/home/alice/dashboard` it is a URL route, not a
filesystem path (the POSIX pattern rejects matches preceded by a
word / dot / dash character). A `file:///home/…` URI still matches —
that IS a machine path.

### Escape hatch — operationalizing "non-essential"

The user's scope is *non-essential* path dependency. An essential,
genuinely-fixed path (a documented example, a test fixture pinned to a
known layout, a platform path that truly cannot move) is allowed through
when the offending line, or an immediately adjacent line (±1), carries a
rationale token **inside a comment**: `because` / `原因` / `因为` /
`之所以` / `理由` / `故意` / `刻意` / `essential` / `必须` / `必需` /
`example` / `fixture` / `placeholder` / `占位` / `sample` / `test data`,
plus the shared leads (`see issue` / `tracking` / `intentional` /
`third-party` / `per spec` …). A bare user-home path with no rationale =
the non-essential case = **DENY**.

The hatch is shared with rules 09 and 10, and the same two corrections
apply — see [rule 10's escape hatch](10-no-hardcoding.md) for the detail:
the token must be **comment text** (v0.25.1, so `reason = compute()` no
longer silences a detector), and **"comment" is decided lexically**
(v0.26.0, so a `#` inside a URL is not one, while `/* … */` blocks and
own-line docstrings are). The Chinese forms were added in v0.26.0 as well.

## Must do (MUST)

1. **Derive, don't hardcode** — compute paths from the plugin root, cwd,
   an env var, or an argument, so the same code runs on any machine.
2. **Prefer relative paths** — anchor data/config relative to the repo or
   module, not to `/home/<you>` or `C:\Users\<you>`.
3. **Mark genuine fixtures** — if a path really must be a fixed literal,
   add an adjacent rationale so the check can tell intent from laziness.

## Must not (MUST NOT)

- ❌ Bake `C:\Users\<name>\…` or `/home/<name>/…` into shipped code.
- ❌ Hardcode `$HOME` / `%USERPROFILE%` / `~/…` as a string literal.
- ❌ Assume the author's directory layout on every other machine.
- ❌ Suppress the detector with a false rationale on a real dependency.

## Relationships

| Relationship | Note |
|---|---|
| 11 vs 03 | 03 says fix the root cause; 11 makes "derive the path, don't hardcode the machine" a hard, write-time portability fix. |
| 11 vs 09 | Same mechanism (PreToolUse content detector with a why-comment escape hatch); 09 targets suppression markers, 11 targets machine-specific paths. |
| 11 vs 10 | Sibling detectors added together (v0.22); 10 is *what* is inlined (secrets), 11 is *where* it points (machine-specific paths). |

## Self-check triggers

- About to paste an absolute path that starts with `C:\Users\` or
  `/home/` or `/Users/`.
- Writing `$HOME` / `%USERPROFILE%` / `"~/…"` as a literal in code.
- "It works on my machine" is the only reason the path is correct.
- Copying a path from your own shell straight into shipped source.

## Termination condition

Writing an absolute filesystem path is allowed only when **one** of:

1. It is derived at runtime from a known base (plugin root / cwd / env /
   argument), not a machine-specific literal; or
2. It is an obvious example / fixture (marked as such); or
3. An adjacent rationale explicitly justifies it as essential.

Otherwise → **non-essential path dependency**, return to rule 03 and
derive it.
