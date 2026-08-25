#!/usr/bin/env python3
"""cc-enforcer — measure what the guards cost per tool call.

Every hook here is a separate OS process that Claude Code spawns and
waits for, so the plugin's latency sits directly in the critical path of
the agent's Read / Edit / Write / Bash / Stop. That makes "how slow is
it?" a real question about the product, and one the README should not
answer from memory.

What it reports and why the baseline row matters
------------------------------------------------
Each hook's wall-clock is measured end to end: spawn, interpret, read
stdin, decide, write stdout, exit. On Windows most of that is the Python
interpreter starting up, not any detector running — so a bare
``python -c pass`` is measured in the same loop and printed alongside.
Without that row a reader would attribute the whole figure to the
guards, and the interesting number (what cc-enforcer itself adds) would
be invisible.

Numbers are machine-specific by nature; nothing in CI pins them. This
script is the reproduction the README cites, so a reader can get their
own figures instead of trusting the author's.

Usage
-----
    python hooks/scripts/bench_hooks.py [--runs N] [--json]

``--json`` emits one object per scenario for scripted comparison.
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent

# Warm-up runs discarded before measurement: the first spawn of a script
# pays for the OS file cache and the .pyc write, which is a one-off the
# steady-state figure should not carry.
WARMUP_RUNS = 3
DEFAULT_RUNS = 25


def _percentile(values: list[float], pct: float) -> float:
    """The `pct` percentile by nearest-rank, on a copy sorted ascending.

    Nearest-rank rather than interpolation: at n=25 an interpolated p95
    invents a value between two samples, and every number printed here
    should be one that was actually observed.
    """
    ordered = sorted(values)
    rank = max(1, min(len(ordered), round(pct / 100.0 * len(ordered))))
    return ordered[rank - 1]


def _time_one(argv: list[str], payload: str | None, env: dict) -> float:
    start = time.perf_counter()
    subprocess.run(
        argv,
        input=payload.encode("utf-8") if payload is not None else b"",
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
    )
    return (time.perf_counter() - start) * 1000.0


def _measure(argv: list[str], payload: str | None, env: dict, runs: int) -> dict:
    for _ in range(WARMUP_RUNS):
        _time_one(argv, payload, env)
    samples = [_time_one(argv, payload, env) for _ in range(runs)]
    return {
        "p50_ms": round(statistics.median(samples), 1),
        "p95_ms": round(_percentile(samples, 95), 1),
        "max_ms": round(max(samples), 1),
    }


def _dumps(payload: dict) -> str:
    """Serialise a benchmark payload the way Claude Code sends one.

    `ensure_ascii=False` matters here (v0.37): the Stop scenario below is
    written in Chinese, and the `json.dumps` default would escape it to
    `\\uXXXX` before it reached the wire. That is a shorter payload AND a
    different code path — the layers would find no CJK markers to match —
    so the number printed would not be the number production pays.
    """
    return json.dumps(payload, ensure_ascii=False)


def _scenarios(target: str, session: str) -> list[tuple[str, str | None, str]]:
    """(label, hook script or None for the baseline, stdin payload)."""
    done = (
        "已修复并验证。\n$ python -m unittest → Ran 617 tests, OK\n"
        "重触发原症状: 已通过。\nrule 07: 无降级、无遗漏。\n"
        "根因/影响/方案均已说明。\ntldr: 修好了，测试全绿。"
    )
    return [
        ("PreToolUse(Read)", "read_guard.py", _dumps({
            "session_id": session, "hook_event_name": "PreToolUse",
            "tool_name": "Read", "tool_input": {"file_path": target},
        })),
        ("PreToolUse(Edit)", "read_guard.py", _dumps({
            "session_id": session, "hook_event_name": "PreToolUse",
            "tool_name": "Edit", "tool_input": {
                "file_path": target,
                "old_string": "# line 005\n", "new_string": "# line 005b\n",
            },
        })),
        ("PreToolUse(Bash)", "bash_guard.py", _dumps({
            "session_id": session, "hook_event_name": "PreToolUse",
            "tool_name": "Bash", "tool_input": {"command": "git status --short"},
        })),
        ("Stop (9 layers)", "stop_guard.py", _dumps({
            "session_id": session, "hook_event_name": "Stop",
            "assistant_message": done,
        })),
        ("baseline: python -c pass", None, ""),
    ]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--runs", type=int, default=DEFAULT_RUNS,
                    help=f"measured runs per scenario (default {DEFAULT_RUNS})")
    ap.add_argument("--json", action="store_true",
                    help="emit JSON instead of a table")
    args = ap.parse_args()

    with tempfile.TemporaryDirectory(prefix="ccenf-bench-") as tmp:
        env = dict(os.environ)
        env["CLAUDE_PLUGIN_DATA"] = tmp
        # A 300-line target: big enough that the v0.35 scale measurement
        # actually reads a file, which is the cost this benchmark exists
        # to keep honest about.
        target = os.path.join(tmp, "target.py")
        with open(target, "w", encoding="utf-8") as fh:
            fh.write("".join(f"# line {i:03d}\n" for i in range(300)))

        results = []
        for label, script, payload in _scenarios(target, "bench-session"):
            if script is None:
                argv = [sys.executable, "-c", "pass"]
                stdin = None
            else:
                argv = [sys.executable, str(SCRIPTS / script)]
                stdin = payload
            stats = _measure(argv, stdin, env, args.runs)
            results.append({"scenario": label, **stats})

    if args.json:
        print(json.dumps(results, indent=2))
        return 0

    baseline = next(
        (r["p50_ms"] for r in results if r["scenario"].startswith("baseline")),
        0.0,
    )
    # Output is deliberately ASCII-only. Windows consoles default to a
    # legacy codepage (cp936 here), which renders an em dash as mojibake
    # and can raise UnicodeEncodeError outright on a redirected stream --
    # a benchmark that crashes while reporting is worse than a plain one.
    print(f"cc-enforcer hook latency - {args.runs} runs each, "
          f"{WARMUP_RUNS} discarded warm-ups")
    print(f"python {sys.version.split()[0]} on {sys.platform}\n")
    print(f"{'scenario':<26} {'p50':>10} {'p95':>10} {'max':>10}"
          f"   {'own share':>10}")
    print("-" * 72)
    for r in results:
        own = r["p50_ms"] - baseline
        is_base = r["scenario"].startswith("baseline")
        share = "-" if is_base else f"{own:+.1f} ms"
        print(f"{r['scenario']:<26} {r['p50_ms']:>7.1f} ms {r['p95_ms']:>7.1f} ms "
              f"{r['max_ms']:>7.1f} ms   {share:>10}")
    print("\n'own share' = p50 minus the bare-interpreter baseline: the part "
          "that\nis cc-enforcer's work rather than process startup.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
