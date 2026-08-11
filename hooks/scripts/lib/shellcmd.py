#!/usr/bin/env python3
"""cc-enslaver — a small model of what a shell command actually invokes.

Root cause this module exists to kill (v0.26.0 audit, root cause a):
`bash_guard` asked two structural questions and answered both by looking
for characters in a string.

  "does this command force-push?"
      -> do `git`, `push` and a force-ish token co-occur in this slice of
         text?  That denied an `echo` of a force-push string (prose) and
         `git config alias.deploy "push --mirror"` (a different
         subcommand), while MISSING `git push origin +main` (a force
         refspec contains no force flag at all) and any real force push
         whose global options pushed `push` past an arbitrary 120-char
         lookahead.

  "is this token the script being executed?"
      -> walk backwards over anything starting with `-`.  That accepted
         `python -c register_read.py ...` (the operand of `-c` is CODE,
         not a script, so the sanctioned script never runs -- yet the
         hook registered the file as read), and rejected
         `python -X utf8 register_read.py ...`, a spelling its own
         docstring advertised as supported, plus every versioned
         interpreter such as `python3.13`.

Both are answered properly by tokenising once, splitting into segments,
and reading each segment as `argv`.

Public API
----------
``tokenize(command)``        shell tokens, or None if unparseable
``segments(command)``        list of argv lists, split on shell separators
``command_name(argv)``       lowercased basename of argv[0]
``git_subcommand(argv)``     (subcommand, remaining_args) for a git argv
``python_script_arg(argv)``  the script path a python argv executes, else None
"""

from __future__ import annotations

import os
import re
import shlex

# Tokens that end one command and begin the next.
#
# Grouping and command-substitution delimiters count: the words inside
# `$( … )`, `( … )` and backticks are a command in their own right. The
# text heuristic this model replaced caught those by accident (it scanned
# raw text), so omitting them would have been a REGRESSION — `$(git push
# --force)` executes a force push and must still be denied.
SEPARATORS = {"&&", "||", ";", "|", "&", "\n", "(", ")", "`", "$"}

# Interpreters whose `-c` operand is another command line to scan.
_SHELL_NAMES = {"sh", "bash", "zsh", "dash", "ksh", "ash",
                "sh.exe", "bash.exe", "zsh.exe"}
_MAX_NESTED_SHELL_DEPTH = 3


def tokenize(command: str, windows: bool | None = None) -> list[str] | None:
    """Tokenise a shell command; None when it cannot be parsed.

    Windows paths are why this is not plain `shlex.split`. In posix mode a
    backslash is an escape, so an unquoted drive-letter path came back
    with every separator eaten, and the register escape hatch denied it as
    "file does not exist" -- i.e. the documented recovery path from a
    false rule-04 DENY was itself broken, on this plugin's main platform.
    `shlex.shlex(escape="")` keeps posix QUOTING (so a quoted path with
    spaces still groups) while making backslash literal.

    `commenters` is cleared unconditionally: shlex treats `#` as a comment
    introducer by default, which silently truncated a perfectly legal
    filename containing `#` and produced a wrong, shorter path.
    """
    if windows is None:
        windows = os.name == "nt"
    try:
        # The backtick is added to shlex's default punctuation set so a
        # legacy `` `git push -f` `` substitution tokenises as its own
        # command rather than gluing the delimiter onto the first word.
        lex = shlex.shlex(command, posix=True, punctuation_chars="();<>|&`")
        lex.whitespace_split = True
        lex.commenters = ""
        if windows:
            lex.escape = ""
        return list(lex)
    except ValueError:
        # Unbalanced quotes: the caller must not guess. Returning None
        # keeps every consumer failing-open rather than acting on a
        # half-parsed command.
        return None


def segments(command: str, windows: bool | None = None,
             _depth: int = 0) -> list[list[str]]:
    """Split a command line into per-invocation argv lists.

    A `sh -c "…"` / `bash -c "…"` operand is a command line, not an opaque
    string, so it is tokenised recursively and its invocations appear in
    the result too. Without this, wrapping anything in `bash -c` would hide
    it from every consumer — and the text heuristic this model replaced did
    see through it, so skipping it would be a regression rather than a
    known limitation. Depth-bounded so a self-referential command cannot
    spin.
    """
    tokens = tokenize(command, windows)
    if tokens is None:
        return []
    out: list[list[str]] = []
    current: list[str] = []
    for tok in tokens:
        if tok in SEPARATORS:
            if current:
                out.append(current)
            current = []
            continue
        current.append(tok)
    if current:
        out.append(current)

    if _depth >= _MAX_NESTED_SHELL_DEPTH:
        return out
    expanded: list[list[str]] = []
    for argv in out:
        expanded.append(argv)
        if command_name(argv) not in _SHELL_NAMES:
            continue
        for i in range(1, len(argv) - 1):
            if argv[i] == "-c":
                expanded.extend(segments(argv[i + 1], windows, _depth + 1))
                break
    return expanded


def command_name(argv: list[str]) -> str:
    """Lowercased basename of the executable an argv invokes."""
    if not argv:
        return ""
    return os.path.basename(argv[0].replace("\\", "/")).lower()


# git global options that consume a SEPARATE following value. The
# `--opt=value` spellings need no entry: the value rides in the same token.
_GIT_VALUE_OPTS = {
    "-C", "-c", "--git-dir", "--work-tree", "--namespace",
    "--exec-path", "--config-env", "--super-prefix",
}


def git_subcommand(argv: list[str]) -> tuple[str | None, list[str]]:
    """Return (subcommand, args_after_it) for a git argv.

    Global options -- including the value-taking ones -- are skipped, so
    `git -C /repo push ...` and `git --git-dir=... push ...` both resolve
    to `push` no matter how long the option values are.
    """
    i = 1
    n = len(argv)
    while i < n:
        tok = argv[i]
        if not tok.startswith("-"):
            return tok, argv[i + 1:]
        if tok in _GIT_VALUE_OPTS:
            i += 2
            continue
        i += 1
    return None, []


# `python`, `python3`, `python3.13`, `pythonw`, `py`, with or without .exe.
_PY_NAME = re.compile(r"^(?:python|py)[0-9._]*w?(?:\.exe)?$")

# Interpreter options that consume a separate operand.
_PY_VALUE_OPTS = {"-W", "-X", "--check-hash-based-pycs"}
# Interpreter options after which NO script file follows: the operand is
# inline code (-c) or a module name (-m).
_PY_NO_SCRIPT_OPTS = {"-c", "-m"}
# v0.26.0 audit — the same options with an ATTACHED value. Python accepts
# `-cpass` exactly as it accepts `-c pass`, so `python -cpass foo.py`
# runs the inline code and passes `foo.py` as a mere argument. Matching
# only the separated spelling meant that argv registered `foo.py` as
# "read" while the script never executed.
_PY_NO_SCRIPT_PREFIXES = ("-c", "-m")
# Options that make the interpreter print and exit: no script runs.
_PY_TERMINAL_OPTS = {"-V", "--version", "-h", "--help", "-VV"}


def python_script_arg(argv: list[str]) -> str | None:
    """Return the script path a python argv executes, else None.

    None means "this argv runs no script file" -- either it is not a
    Python interpreter at all, or it uses `-c` / `-m`, whose operand is
    code or a module name rather than a script. Treating that operand as a
    script is what let an inline-code invocation masquerade as a
    sanctioned registration while never executing it.
    """
    if not argv or not _PY_NAME.match(command_name(argv)):
        return None
    i = 1
    n = len(argv)
    while i < n:
        tok = argv[i]
        if tok in _PY_NO_SCRIPT_OPTS or tok in _PY_TERMINAL_OPTS:
            return None
        # Attached inline-code / module spellings: `-cpass`, `-mvenv`.
        if any(tok.startswith(p) and len(tok) > len(p)
               for p in _PY_NO_SCRIPT_PREFIXES):
            return None
        if tok in _PY_VALUE_OPTS:
            i += 2
            continue
        if tok.startswith("-") and tok != "-":
            i += 1
            continue
        return tok
    return None
