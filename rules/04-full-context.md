---
id: "04"
title: "Read fully — keyword search is location, not understanding"
severity: must
---

# Rule 04 — Read fully; reject keyword-only edits

## Principle

Before editing or writing new content, the agent **must genuinely
explore the relevant architecture and fully read all related files**.

- Keyword search (`Grep`) is for **locating**, not for **understanding**.
- Once you have a hit, you must `Read` its surrounding context — otherwise you are blind-editing.
- Memory is a **snapshot of a past moment**; current file state is authoritative.

## Must do

Before modifying any file:

1. `Read` the **entire file** (if > 2000 lines, read all relevant functions / sections in chunks).
2. `Grep` for every reference to the file (imports, calls, string matches).
3. `Read` the surrounding context (≥ 20 lines either side) at every call site.
4. For configuration / manifest files, read the **entire JSON/YAML** and understand each key.
5. When introducing a name (variable / function / class) that already exists in the new file's neighbourhood, grep the whole repo first to confirm naming conventions.

## Must not

- ❌ Start editing from the diff context alone (diff context ≠ full file).
- ❌ Take action on the first grep hit (the second hit may be the function definition; the third may be a counter-example).
- ❌ Justify "I read it last session" as a reason not to re-read (current state may have changed).
- ❌ Read only the README / comments and skip the source itself (comments rot).

## Example: grep + full read

**Bad — grep only**
```
> grep "session_token" src/
src/auth.py:42:    session_token = generate_token()
> Add a lock at src/auth.py:42
```
This is wrong: you don't know how `session_token` is used elsewhere
in the file, and you don't know whether `tests/test_auth.py` depends
on the current behaviour.

**Good — grep → full Read → impact analysis**
```
> grep -rn "session_token" .
src/auth.py:42:    session_token = generate_token()
src/auth.py:88:    return session_token
src/session.py:14:    def store(self, session_token): ...
tests/test_auth.py:55:    assert session_token in cache
> Read src/auth.py in full
> Read src/session.py in full
> Read the session_token-related block in tests/test_auth.py
> Decide based on synthesising all 4 usages
```

## Self-check triggers

- About to `Edit` a file not yet `Read` in this session;
- About to reference a symbol not yet `Grep`-ed in this session;
- About to make changes based on "memory from last session" without re-reading;
- Skimmed grep results by filename / line number only, without reading context.
