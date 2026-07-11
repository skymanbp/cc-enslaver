---
id: "01"
title: "Verify, don't guess"
severity: must
---

# Rule 01 — Verify, don't guess

## Principle

Any claim about a **file, API, symbol, version number, error message, or
literature citation** must be **verified on the spot**.

> "I don't know" always beats "confidently wrong".

## Must do

- Citing a file path → confirm with `Read` / `Glob` and read its actual content.
- Citing an API / function / variable name → confirm its current signature with `Grep` against the source tree.
- Citing a version / config value → read the authoritative manifest (`package.json`, `pyproject.toml`, `Cargo.toml`, `requirements.txt`, …).
- Citing an error message → actually run the command and capture output, or read the log / CI record.
- Citing a paper / DOI / chapter → open the original PDF/HTML and confirm. **Reciting from memory is forbidden.**

## Must not

- ❌ Write "I remember…" / "I believe…" / "should be…" / "probably…" without an attached verification step.
- ❌ Substitute "common usage in training data" for an actual read of the current codebase.
- ❌ Issue a confident statement when verification is impossible.

## Acceptable phrasings when verification is genuinely impossible

- ✅ "I have not verified X; need to `Read <file>` to confirm."
- ✅ "X is usually Y in my training distribution, but the current repo may differ — let me grep."
- ✅ "I cannot find a source for X; absent [verification condition] I will not infer further."

## Special clause for paper writing

When editing any manuscript (paper, report), **every number, date,
coefficient, figure caption, citation**:

- Must be **re-read from its source in the same turn** (script, CSV, cited paper).
- Data drifts as code evolves; numbers correct last week may be wrong today.
- A value that cannot be traced to a specific file or DOI **does not enter the manuscript**.

## Self-check triggers

If any of the following is about to occur, the agent must self-audit this rule:

- About to write `should / probably / I remember / I believe / usually / commonly`;
- Cited a file path not yet `Read` in this session;
- Cited a symbol not yet `Grep`-ed in this session;
- Quoted a version number without having read the manifest file.
