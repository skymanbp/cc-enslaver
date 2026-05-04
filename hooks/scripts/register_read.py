#!/usr/bin/env python3
"""cc-enslaver — user-facing entry for the Read-cache escape hatch.

When Claude Code's harness short-circuits a `Read` tool call to its
result cache, neither `PreToolUse(Read)` nor `PostToolUse(Read)` fires,
so the file never enters session state. A subsequent `Edit` is then
denied by `read_guard.py` even though the agent legitimately read the
file. See `docs/ARCHITECTURE.md` §2 for the full failure mode.

This script is the *user-facing* part of the escape hatch. The actual
state mutation is performed by `bash_guard.py` in the
`PreToolUse(Bash)` hook because only the hook payload exposes the
session_id needed to key the state file. This script's job is to:

  1. Be discoverable on the command line (a clean documented invocation
     point that does not look like a `: '#magic-comment'` hack).
  2. Compute and print the SHA-256 of `--file` so the agent can sanity-
     check that the file it intends to register is the file on disk.
  3. Exit 0. The bash_guard hook has already handled the registration
     by the time this script runs.

Usage from an agent's Bash tool call:

    # 1. Compute current hash of the file:
    sha=$(python -c "import hashlib,sys; print(hashlib.sha256(open(sys.argv[1],'rb').read()).hexdigest())" PATH)

    # 2. Register:
    python "${CLAUDE_PLUGIN_ROOT}/hooks/scripts/register_read.py" \\
        --file PATH --hash "$sha"

If `bash_guard.py` rejected the call (hash mismatch, file missing,
malformed args), the deny fires before this script runs and the agent
sees the deny reason instead.
"""

from __future__ import annotations

import argparse
import hashlib
import sys
from pathlib import Path


def _compute_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Register a file as 'read' in cc-enslaver session state.",
    )
    parser.add_argument(
        "--file",
        required=True,
        help="Absolute path to the file the agent has already read.",
    )
    parser.add_argument(
        "--hash",
        required=True,
        help="SHA-256 hex digest (lowercase, 64 chars) of the file's current bytes.",
    )
    args = parser.parse_args()

    fpath = Path(args.file)
    if not fpath.is_absolute():
        sys.stderr.write(
            f"register_read: --file must be absolute (got {args.file!r})\n"
        )
        return 1

    if not fpath.is_file():
        sys.stderr.write(f"register_read: file not found: {fpath}\n")
        return 2

    actual = _compute_sha256(fpath)
    if actual != args.hash.lower():
        sys.stderr.write(
            "register_read: hash mismatch\n"
            f"  --hash:    {args.hash}\n"
            f"  on-disk:   {actual}\n"
            "Either the file changed between your read and now, or the\n"
            "supplied hash was not computed from the current file content.\n"
        )
        return 3

    # If we got here, the bash_guard hook would have already added the
    # file to session state during PreToolUse. We just print confirmation.
    print(
        f"register_read: ok  file={fpath}  hash={actual}\n"
        "(state mutation is performed by the PreToolUse(Bash) hook;\n"
        " this script only verifies your hash against on-disk content)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
