---
id: "05"
title: "Citations must be traceable"
severity: must
---

# Rule 05 — Citations must be traceable

## Principle

Every claim must be **verifiable on the spot** by the reader. Vague
references, memory-based citations, and unsourced "common practice"
are unacceptable.

## Citation formats

| Scenario | Recommended format | Example |
|----------|--------------------|---------|
| Single line | `path/to/file.ext:LINE` | `src/auth.py:142` |
| Range | `path/to/file.ext:START-END` | `src/auth.py:142-156` |
| In a VS Code extension (clickable) | `[file.ext:LINE](path/to/file.ext#LLINE)` | `[auth.py:142](src/auth.py#L142)` |
| Command output | Triple-backtick code block, command first | ` ``` $ pytest tests/test_auth.py::test_lock ... ``` ` |
| Paper / doc | `<title or DOI> §<section> p.<page>` | `Smith 2024 §3.2 p.7` |
| Git | Full commit hash (≥ 7 chars) | `commit abc1234` |

## Must do

- Every claim about the repository → attach `file:line`.
- Every claim about an external resource → attach URL / DOI / chapter.
- Every claim about runtime behaviour → attach the actual command + output.
- PR descriptions, commit messages, replies to the user: every factual
  statement must satisfy the rules above.

## Must not

- ❌ "Somewhere in the auth module" → give the specific `auth.py:142` or `auth/login.py:88`.
- ❌ "I remember the docs said …" → find the doc, give the link + section.
- ❌ "I fixed a similar bug before" → find the commit, give the hash.
- ❌ Pasting a number into a paper without being able to point at the script / CSV / reference it came from.

## When citation may be omitted

Only the following exceptions:

- General CS knowledge (e.g. "linked-list insertion is O(1)");
- Facts the user just supplied in this conversation (and that have not crossed a context-compaction boundary);
- The agent's own change just made, mentioned in the same sentence ("I added a lock at `src/auth.py:142`").

## Self-check triggers

- About to make a code-location statement without a `file:line`;
- About to paraphrase a doc / paper / issue without giving the link;
- About to paraphrase command output without actually running the command this turn;
- About to paste numbers / dates / coefficients into a paper / report without re-reading the source this turn (see rule 01's "paper writing" clause).
