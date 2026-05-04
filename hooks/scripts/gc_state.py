#!/usr/bin/env python3
"""cc-enslaver — session-state garbage collection (v0.6.1).

Each Claude Code session creates one JSON state file in
`${CLAUDE_PLUGIN_DATA}/sessions/<sid>.json`. Sessions are not
auto-cleaned. Over months, files accumulate. This script prunes old
state files based on file mtime.

# Why mtime, not "session ended"

There is no "session ended" signal. `state_lib.add_read` writes the
file every time the session records a read/write, so mtime tracks
the most recent activity in the session. A file with mtime 30+ days
old is almost certainly a long-dead session (the IDE has been
restarted many times since).

# Why not auto-run

In v0.6.1, GC is *manual only* (`python gc_state.py` from a Bash
tool call, or via the `/cc-enslaver:gc` slash command). Auto-on-
SessionStart was considered but deferred:
  - Adds latency to every session start.
  - Adds a code path that runs on the critical hook timeline.
  - Hard to debug if the GC logic ever has a bug.
  - State files are KB-sized; even thousands accumulated is < 10 MB.
A future version may add an `auto_gc_on_session_start` config flag.

# Output

Always prints a summary:
    state_dir: <path>
    scanned: N
    threshold: M days
    [DRY RUN] would delete: K   |   deleted: K
    bytes freed: B

# Safety

  * `--dry-run` (default off) shows what would be deleted without
    touching anything. The slash command `/cc-enslaver:gc` invokes
    `--dry-run` by default; the user must explicitly request
    `--apply` to actually delete.
  * `--older-than DAYS` defaults to 30 (configurable). Files newer
    than the threshold are never touched.
  * Files outside `${CLAUDE_PLUGIN_DATA}/sessions/` are never touched
    (we resolve `state_lib.state_dir()` and refuse to delete anything
    elsewhere).
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib import state as state_lib  # noqa: E402


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Prune cc-enslaver session state files older than a threshold.",
    )
    parser.add_argument(
        "--older-than",
        type=int,
        default=30,
        metavar="DAYS",
        help="Prune files whose mtime is older than DAYS days. Default: 30.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what would be deleted without touching anything.",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Actually delete (counterpart to --dry-run; one or the other "
        "must be passed explicitly).",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)

    if args.dry_run == args.apply:
        # XOR: exactly one must be set. Refuse to act if ambiguous so the
        # operator never deletes by accident with no flag.
        sys.stderr.write(
            "gc_state: pass exactly one of --dry-run or --apply\n"
        )
        return 1

    if args.older_than < 1:
        sys.stderr.write("gc_state: --older-than must be >= 1\n")
        return 1

    sessions_dir = state_lib.state_dir()
    threshold_seconds = args.older_than * 86400
    cutoff = time.time() - threshold_seconds

    scanned = 0
    eligible = []  # (path, age_days, size)
    for f in sessions_dir.glob("*.json"):
        scanned += 1
        try:
            mtime = f.stat().st_mtime
            size = f.stat().st_size
        except OSError:
            continue
        if mtime < cutoff:
            age_days = (time.time() - mtime) / 86400
            eligible.append((f, age_days, size))

    print(f"state_dir: {sessions_dir}")
    print(f"scanned:   {scanned}")
    print(f"threshold: {args.older_than} days")
    print(f"eligible:  {len(eligible)}")

    if not eligible:
        print("nothing to do")
        return 0

    deleted = 0
    bytes_freed = 0
    for path, age_days, size in eligible:
        verb = "[dry-run] would delete" if args.dry_run else "deleted"
        print(f"  {verb}: {path.name}  ({age_days:.1f}d old, {size}B)")
        if args.apply:
            try:
                path.unlink()
                deleted += 1
                bytes_freed += size
            except OSError as exc:
                sys.stderr.write(f"  failed: {exc}\n")

    if args.apply:
        print(f"deleted:    {deleted}")
        print(f"bytes_freed: {bytes_freed}")
    else:
        print(f"would delete: {len(eligible)}")
        print(f"would free:   {sum(s for _, _, s in eligible)}B")
    return 0


if __name__ == "__main__":
    sys.exit(main())
