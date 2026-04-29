---
id: "00"
title: "Rule index"
severity: info
---

# anti-laziness rule index (English mirror)

> This is the **English mirror** of the rules under [`../`](../). The
> Chinese sources are canonical; this mirror tracks them best-effort
> for non-CJK readers and for use as a system-prompt fragment with
> non-Claude agents (OpenAI, Gemini, local llama.cpp, etc.).
>
> If the two ever drift, the Chinese version wins. To use this mirror
> as a self-contained discipline pack:
>
> ```bash
> cat rules/en/*.md > /tmp/anti-laziness.txt
> ```
>
> then prepend that file to your agent's system prompt.

## Rule list

| ID  | File                                  | Title                                           | severity |
|----:|---------------------------------------|-------------------------------------------------|----------|
| 01  | `01-verify-dont-guess.md`             | Verify, don't guess                             | must     |
| 02  | `02-systematic-not-reactive.md`       | Systematic, not reactive                        | must     |
| 03  | `03-root-cause.md`                    | Fix root causes, not symptoms                   | must     |
| 04  | `04-full-context.md`                  | Read fully — keyword search is location, not understanding | must |
| 05  | `05-cite-sources.md`                  | Citations must be traceable                     | must     |
| 06  | `06-verify-convergence.md`            | Verify-and-converge (post-fix)                  | must     |

## Numbering convention

- Format `<two-digit>-<kebab-case>.md`.
- Numbers are **never reused** once published (even if a rule is
  retired, its number stays — frontmatter gets `status: deprecated`).
- Current range: `01–06`.

## Relationships

- **01 / 04 / 05** — *input-side* constraints: how the agent acquires
  facts and how it cites them.
- **02** — *thinking-process* constraint: how the agent organises facts
  into a plan.
- **03** — *output-side (what to change)* constraint: whether the
  edit actually touches the root cause.
- **06** — *output-side (after the change)* constraint: whether the
  fix has been driven to convergence with traceable evidence before
  the agent claims done.
