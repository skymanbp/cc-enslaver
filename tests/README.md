# Tests

Black-box tests for the three hook scripts in
[`../hooks/scripts/`](../hooks/scripts/). Each test invokes the target
script as a real subprocess with a synthetic JSON stdin payload — the
same way Claude Code itself does at runtime.

## Run

```bash
# From the repo root, using only Python stdlib (no pytest needed):
python -m unittest discover tests
```

Pytest is also supported (it runs unittest classes natively):

```bash
pytest tests/
```

## Layout

| File | Covers |
|---|---|
| [`_helpers.py`](_helpers.py) | `run_hook(...)` — invokes a script as subprocess, returns `(returncode, parsed_stdout, stderr)` |
| [`test_inject_context.py`](test_inject_context.py) | Soft-layer hook: SessionStart and UserPromptSubmit injection, including UTF-8 / CJK survival |
| [`test_read_guard.py`](test_read_guard.py) | Hard-layer guard: record on Read/Write, allow/deny matrix on Edit/Write, path normalization, fail-open |
| [`test_bash_guard.py`](test_bash_guard.py) | Hard-layer guard: bypass-pattern catalog, event gating, fail-open |

## Adding a new test case

When extending a hook's behavior:

1. Add the **positive case** (the new pattern the guard should catch) to the
   relevant `test_*.py` matrix.
2. Add a **nearby negative case** that is similar but should NOT trigger,
   so future contributors can see the boundary.
3. Update [`../docs/RULES.md`](../docs/RULES.md) and / or
   [`../docs/ARCHITECTURE.md`](../docs/ARCHITECTURE.md) per the
   connected-files matrix in [`../CLAUDE.md`](../CLAUDE.md) §4.

## What is intentionally NOT tested here

- **End-to-end install** — `/plugin marketplace add` is a Claude Code IDE
  slash command, not a CLI surface. Verifying that the plugin loads is
  done manually after install.
- **Live tool denial in Claude Code** — same reason. The unit tests prove
  the script emits the documented JSON when the documented stdin shape
  arrives; whether Claude Code honours the deny is its own contract.
