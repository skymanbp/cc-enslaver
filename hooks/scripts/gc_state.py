#!/usr/bin/env python3
"""cc-enslaver — session-state garbage collection (v0.6.1 + v0.18 auto).

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

# Two entry points (v0.6.1 manual + v0.18 auto)

  - Manual:    `python gc_state.py --dry-run` or `--apply`. Used by
               the `/cc-enslaver:gc` slash command. Prints a verbose
               summary to stdout.
  - Auto:      `prune_old_sessions(threshold_days, dry_run=False,
               exclude_session=None) -> dict`. Imported by
               `inject_context.py` SessionStart hook when the user has
               opted in via `CC_ENSLAVER_AUTO_GC_DAYS=N`. Returns a
               summary dict; logs nothing on its own (the caller
               decides where to surface results — stderr in the
               injection path so stdout stays reserved for the JSON
               hook payload).

The manual CLI is a thin argparse wrapper around `prune_old_sessions`
so both paths share identical deletion semantics.

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


# Filenames in state_dir that are NOT per-session state files. These
# must never be GC'd no matter how old. Keep this list narrow.
_GC_INTERNAL_FILES = {
    "_auto_gc.json",  # auto-GC rate-limit marker (v0.18)
}


def prune_old_sessions(
    threshold_days: int,
    *,
    dry_run: bool = False,
    exclude_session: str | None = None,
) -> dict:
    """Prune session-state JSON files older than `threshold_days`.

    The single shared deletion routine used by both the manual CLI and
    the auto-GC hook entry point. Operates only on `*.json` files
    inside `state_lib.state_dir()`; never touches anything else.

    Parameters
    ----------
    threshold_days
        Files whose mtime is older than this many days are eligible.
        Must be >= 1 (`ValueError` otherwise; callers handle).
    dry_run
        If True, identify eligible files but do not delete.
    exclude_session
        Optional session id to spare even if its file is old (used by
        auto-GC at SessionStart to avoid deleting the live session's
        own state — defensively, since the file may not exist yet).

    Returns
    -------
    dict with keys:
        scanned       int   — number of *.json files inspected
        eligible      int   — number that crossed the threshold
        deleted       int   — number actually deleted (0 in dry-run)
        bytes_freed   int   — total bytes deleted
        failures      list[str] — per-file failure messages
        items         list[(path, age_days, size)] — eligible files
    """
    if threshold_days < 1:
        raise ValueError("threshold_days must be >= 1")

    sessions_dir = state_lib.state_dir()
    cutoff = time.time() - (threshold_days * 86400)
    excluded_filename = (
        f"{exclude_session}.json" if exclude_session else None
    )

    scanned = 0
    items: list[tuple[Path, float, int]] = []
    for f in sessions_dir.glob("*.json"):
        if f.name in _GC_INTERNAL_FILES:
            continue
        if excluded_filename and f.name == excluded_filename:
            continue
        scanned += 1
        try:
            mtime = f.stat().st_mtime
            size = f.stat().st_size
        except OSError:
            continue
        if mtime < cutoff:
            age_days = (time.time() - mtime) / 86400
            items.append((f, age_days, size))

    deleted = 0
    bytes_freed = 0
    failures: list[str] = []
    if not dry_run:
        for path, _, size in items:
            try:
                path.unlink()
                deleted += 1
                bytes_freed += size
            except OSError as exc:
                failures.append(f"{path.name}: {exc}")

    return {
        "scanned": scanned,
        "eligible": len(items),
        "deleted": deleted,
        "bytes_freed": bytes_freed,
        "failures": failures,
        "items": items,
    }


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
    summary = prune_old_sessions(
        threshold_days=args.older_than,
        dry_run=args.dry_run,
    )

    print(f"state_dir: {sessions_dir}")
    print(f"scanned:   {summary['scanned']}")
    print(f"threshold: {args.older_than} days")
    print(f"eligible:  {summary['eligible']}")

    if summary["eligible"] == 0:
        print("nothing to do")
        return 0

    for path, age_days, size in summary["items"]:
        verb = "[dry-run] would delete" if args.dry_run else "deleted"
        print(f"  {verb}: {path.name}  ({age_days:.1f}d old, {size}B)")
    for failure_msg in summary["failures"]:
        sys.stderr.write(f"  failed: {failure_msg}\n")

    if args.apply:
        print(f"deleted:    {summary['deleted']}")
        print(f"bytes_freed: {summary['bytes_freed']}")
    else:
        print(f"would delete: {summary['eligible']}")
        print(
            f"would free:   "
            f"{sum(s for _, _, s in summary['items'])}B"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
