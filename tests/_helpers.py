"""Shared helpers for cc-enslaver hook tests.

Each test file invokes its hook script as a real subprocess with a
synthetic JSON stdin payload, mirroring exactly what Claude Code does
at runtime. This keeps the test surface a black box — we never import
the script's module, only execute it as Claude Code would.

Why subprocess and not direct module import:
  - Hooks run in fresh subprocesses in production. Module-level state,
    sys.stdin, sys.stdout.buffer, and exit codes all behave differently
    when the script is *called* vs *imported*. Subprocess testing is
    the only way to catch regressions in those areas.
  - Independence: a bug in one test file cannot leak module state into
    another. Each invocation is hermetically clean.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = REPO_ROOT / "hooks" / "scripts"


def run_hook(
    script_args: list[str],
    stdin_payload: dict,
    env_overrides: dict | None = None,
) -> tuple[int, dict | None, str]:
    """Run a hook subprocess. Returns (returncode, parsed_stdout, stderr).

    Parameters
    ----------
    script_args
        Command-line tail. Typically `[str(SCRIPTS_DIR / "<script>.py")]`,
        plus any extra flags like `["--event", "SessionStart"]`.
    stdin_payload
        The JSON object Claude Code would send on stdin. Serialized as
        UTF-8 before being piped to the subprocess.
    env_overrides
        Extra environment variables (e.g., `CLAUDE_PLUGIN_DATA`).
        Inherits the current environment as a base.

    Returns
    -------
    returncode : int
    parsed_stdout : dict | None
        The script's stdout parsed as JSON, or None if stdout was empty
        or not valid JSON. (None is the documented "allow" signal for
        PreToolUse hooks.)
    stderr : str
        Decoded as UTF-8 with replacement on error; useful for asserting
        on the failing-open log path.
    """
    env = os.environ.copy()
    if env_overrides:
        env.update(env_overrides)

    proc = subprocess.run(
        [sys.executable, *script_args],
        input=json.dumps(stdin_payload).encode("utf-8"),
        capture_output=True,
        env=env,
    )

    parsed: dict | None = None
    if proc.stdout.strip():
        try:
            parsed = json.loads(proc.stdout.decode("utf-8"))
        except json.JSONDecodeError:
            parsed = None

    return proc.returncode, parsed, proc.stderr.decode("utf-8", errors="replace")
