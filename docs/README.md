# Documentation index

Four documents, four distinct audiences. Read the one that matches the
question you actually have — they deliberately do not repeat each other, so
the answer lives in exactly one of them.

| Document | Audience | Answers |
|---|---|---|
| [`ARCHITECTURE.md`](ARCHITECTURE.md) | Developers extending or auditing the plugin | How the five layers fit together, every hook's input/output contract, the Stop decision tree layer by layer, the detector inventory, and §8's **connected-files map** — the table you must consult before editing anything here. |
| [`RULES.md`](RULES.md) | Anyone looking a rule up | The catalog of all 12 rules: id, title, severity, full-text link, and which situations each one governs. An index, not the rules themselves. |
| [`EDICTS.md`](EDICTS.md) | Users writing their own hard rules | The Imperial Edicts (圣旨) system: the TOML schema, `must` vs `should`, project vs global scope, how a regex becomes a `PreToolUse` DENY, and how to debug one that is not firing. |
| [`I18N.md`](I18N.md) | Translators and CI | The skeleton↔translation contract. English at the root is the source of truth; what `i18n_check.py` compares, what it deliberately does not, and what to do when it goes red. |

## Where everything else lives

| You want… | Go to |
|---|---|
| The rules themselves | [`../rules/`](../rules/) (English skeleton) · [`../rules/zh/`](../rules/zh/) (中文) |
| What the agent is actually told each turn | [`../prompts/`](../prompts/) |
| Install steps, the 30-second pitch, the enforcement tables | [`../README.md`](../README.md) · [`../README.zh.md`](../README.zh.md) |
| Project-level development rules (this repo governs itself) | [`../CLAUDE.md`](../CLAUDE.md) |
| Release history — the only copy of it | [`../CHANGELOG.md`](../CHANGELOG.md) |
| The test suite, file by file | [`../tests/README.md`](../tests/README.md) |

## A note on scope

These four documents describe **what the plugin does and why**. They are not
the enforcement itself: the rules are Markdown in `../rules/`, the hooks are
Python in `../hooks/scripts/`, and the guarantee that this documentation still
matches them is [`../tests/test_doc_sync.py`](../tests/test_doc_sync.py) — a
CI gate that derives every pinned number and inventory from the code at test
time. Since v0.35.1 it also derives three *behavioural* claim classes —
advertised hedge triggers, printed coverage bars, and backticked identifiers —
because a sentence naming a pattern, an arithmetic result, or an identifier
turned out to be checkable even though "prose" as a whole is not. A green gate
still says nothing about judgement prose: whether an explanation is right, or
a rationale sound. That limit is stated here for the same reason it is stated
in the gate's own docstring.
