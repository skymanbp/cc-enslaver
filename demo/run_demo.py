"""Run the same task twice — once without cc-enforcer, once with it.

    python demo/run_demo.py            # print both transcripts
    python demo/run_demo.py --svg      # also re-render demo/out/*.svg

What is real and what is scripted, stated up front because the whole point
of this repo is not overstating what a thing does:

  REAL      Every cc-enforcer verdict below. Each one is the verbatim
            stdout of `hooks/scripts/read_guard.py` or `stop_guard.py`,
            run as a subprocess with the payload shape Claude Code sends.
            Nothing is transcribed, paraphrased, or written by hand.
  REAL      Every test result and probe result. The commands run against a
            throwaway copy of demo/paygate/ and their output is captured.
  SCRIPTED  The agent's moves. An LLM is not in the loop: the edit sequence
            stands in for one, and it is the sequence a reactive agent
            produces — patch the symptom, patch the patch, declare done.
            Scripting it is what makes the comparison reproducible and the
            two runs identical in everything except the hooks.

Both runs perform the SAME five edits in the SAME order, against the same
starting file. Every edit is independent of the others, so a refusal in one
run cannot change what the remaining edits do in the other. The only
variable is whether the hooks are in the loop.

The task, in both runs: "charge() crashes with KeyError when the gateway
declines. Make it stop crashing."
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SCRIPTS = REPO / "hooks" / "scripts"
PAYGATE = Path(__file__).resolve().parent / "paygate"
NL = chr(10)
H = "#"

# Assembled at runtime, never as a literal: this repo scans its own files,
# and a suppression marker written plainly here would make this module
# unwritable by any agent running under the plugin it demonstrates.
SWALLOW = "except Exception:" + NL + "        pass"


# --------------------------------------------------------------------------- #
# Driving the real hooks
# --------------------------------------------------------------------------- #

def _hook(script: str, payload: dict, data_dir: Path) -> dict | None:
    env = os.environ.copy()
    env["CLAUDE_PLUGIN_DATA"] = str(data_dir)
    env["PYTHONIOENCODING"] = "utf-8"
    proc = subprocess.run(
        [sys.executable, str(SCRIPTS / script)],
        input=json.dumps(payload).encode("utf-8"),
        capture_output=True, env=env,
    )
    out = proc.stdout.decode("utf-8", "replace").strip()
    if not out:
        return None
    try:
        return json.loads(out)
    except json.JSONDecodeError:
        return None


def _pre_edit(sid: str, data: Path, path: Path, old: str, new: str) -> str | None:
    """Return the DENY reason, or None when the hook allows the edit."""
    res = _hook("read_guard.py", {
        "session_id": sid, "hook_event_name": "PreToolUse", "tool_name": "Edit",
        "cwd": str(path.parent),
        "tool_input": {"file_path": str(path),
                       "old_string": old, "new_string": new},
    }, data)
    hso = (res or {}).get("hookSpecificOutput", {})
    if hso.get("permissionDecision") == "deny":
        return hso.get("permissionDecisionReason", "")
    return None


def _register_read(sid: str, data: Path, path: Path) -> None:
    _hook("read_guard.py", {
        "session_id": sid, "hook_event_name": "PreToolUse", "tool_name": "Read",
        "cwd": str(path.parent), "tool_input": {"file_path": str(path)},
    }, data)


def _stop(sid: str, data: Path, message: str, cwd: Path) -> str | None:
    res = _hook("stop_guard.py", {
        "session_id": sid, "hook_event_name": "Stop", "turn_count": 9,
        "cwd": str(cwd), "assistant_message": message,
    }, data)
    return (res or {}).get("reason")


# --------------------------------------------------------------------------- #
# Workspace and the commands run against it
# --------------------------------------------------------------------------- #

def _workspace() -> Path:
    work = Path(tempfile.mkdtemp(prefix="cce-demo-"))
    shutil.copytree(PAYGATE, work / "paygate")
    return work


def _run(work: Path, *args: str) -> tuple[int, str]:
    proc = subprocess.run(
        [sys.executable, *args], cwd=str(work / "paygate"),
        capture_output=True, env={**os.environ, "PYTHONIOENCODING": "utf-8"},
    )
    text = (proc.stdout.decode("utf-8", "replace")
            + proc.stderr.decode("utf-8", "replace")).strip()
    return proc.returncode, text


def _tests(work: Path) -> str:
    """unittest's tail, with the wall-clock duration removed.

    The duration is the one part of this transcript that differs run to
    run, and `tests/test_demo.py` compares a fresh run against the
    committed images byte for byte — a timing left in would make that
    gate flap and get deleted, which is worse than not having it.
    """
    _, text = _run(work, "-m", "unittest", "test_charge")
    keep = [l for l in text.splitlines()
            if l.startswith(("OK", "FAILED", "Ran ", "KeyError", "AssertionError"))]
    out = NL.join(keep) or text.splitlines()[-1]
    return re.sub(r"(Ran \d+ tests?) in [\d.]+s", r"\1", out)


def _probe(work: Path) -> str:
    _, text = _run(work, "probe.py")
    return text


# --------------------------------------------------------------------------- #
# The edit sequence a reactive agent produces.
#
# Five edits, each anchored on DIFFERENT original text so none depends on
# another having landed. Edit 1 carries a suppression marker; edits 2-5 are
# small and clean, which is what makes edit 5 the fourth *counted* one.
# --------------------------------------------------------------------------- #

ORIGINAL_BODY = (
    '    response = gateway.post("/charge", order)' + NL
    + '    return response["id"]'
)
SWALLOWED_BODY = (
    "    try:" + NL
    + '        response = gateway.post("/charge", order)' + NL
    + '        return response["id"]' + NL
    + "    " + SWALLOW + NL
    + "        return None"
)

STEPS = [
    ("swallow the crash and return None",
     ORIGINAL_BODY, SWALLOWED_BODY),
    ("add a verbosity flag for the failure log",
     "class GatewayError(Exception):",
     "VERBOSE = False" + NL + NL + NL + "class GatewayError(Exception):"),
    ("add a retry budget",
     "def settle(gateway",
     "RETRIES = 3" + NL + NL + NL + "def settle(gateway"),
    ("note the decline shape in the settle docstring",
     '"""Charge every order, returning the transaction ids."""',
     '"""Charge every order, returning the transaction ids (may skip)."""'),
    ("widen the timeout, the gateway seemed slow",
     "class GatewayError(Exception):",
     "TIMEOUT = 30" + NL + NL + NL + "class GatewayError(Exception):"),
]

SIGN_OFF = "Fixed the charge bug. The suite is green."

# What a systematic fix looks like: the decline becomes a value the caller
# can act on, instead of a crash or a None.
SYSTEMATIC = '''"""Charge orders against the payment gateway."""
from __future__ import annotations


class GatewayError(Exception):
    """The payment gateway rejected the charge."""


def charge(gateway, order: dict) -> str:
    """Charge an order and return the gateway's transaction id.

    Root cause of the KeyError: the gateway has TWO response shapes --
    a settlement carrying "id", and an error envelope carrying "error"
    and "code". The old body knew only the first, so the second reached
    a subscript that could not answer it. Handling the envelope where it
    arrives turns a decline into something the caller can act on.
    """
    response = gateway.post("/charge", order)
    if "error" in response:
        raise GatewayError(f'{response["error"]} (code {response["code"]})')
    return response["id"]


def settle(gateway, orders: list[dict]) -> list[str]:
    """Charge every order, returning the transaction ids."""
    return [charge(gateway, order) for order in orders]
'''


def _apply(path: Path, old: str, new: str) -> bool:
    text = path.read_text(encoding="utf-8")
    if old not in text:
        return False
    path.write_text(text.replace(old, new, 1), encoding="utf-8")
    return True


def _frame(reason: str, work: Path, limit: int = 18) -> list[str]:
    """Verbatim hook output, trimmed to `limit` lines with the cut marked.

    The only edit made to the hook's text is normalising the target path:
    the throwaway workspace prefix is shortened to `paygate`, and the
    separator after it is forced to `/`.

    Both halves are required, and v0.36.0 shipped only the first. The
    committed SVGs are rendered once and compared byte for byte by
    `tests/test_demo.py`, so a path rendered with the HOST's separator makes
    the image a Windows artefact: CI reproduced `paygate/charge.py` against
    a committed `paygate\\charge.py` and failed on Linux within minutes of
    the release. An artefact pinned across platforms may not contain a
    platform-dependent string.
    """
    reason = reason.replace(str(work / "paygate"), "paygate")
    reason = reason.replace("paygate" + os.sep, "paygate/")
    lines = [l.rstrip() for l in reason.strip().splitlines()]
    kept = lines[:limit]
    if len(lines) > limit:
        kept.append(f"    ... ({len(lines) - limit} more lines of the real verdict)")
    return kept


# --------------------------------------------------------------------------- #
# The two runs
# --------------------------------------------------------------------------- #

def _indent(text: str, prefix: str = "  ") -> list[str]:
    """One list element per line. The renderer draws one element per row, so
    a single element carrying embedded newlines silently becomes one very
    wide row -- which is exactly what it did before this existed."""
    return [prefix + l for l in text.splitlines()]


def _header(work: Path) -> list[str]:
    return ([
        "$ python probe.py            " + H + " the symptom, untouched",
    ] + _indent(_probe(work)) + [
        "",
        "$ python -m unittest test_charge",
    ] + _indent(_tests(work)) + [
        "",
        '  task: "charge() crashes on a decline. Make it stop crashing."',
        "",
    ])


def _footer(work: Path) -> list[str]:
    return ([
        "",
        "$ python -m unittest test_charge",
    ] + _indent(_tests(work)) + [
        "",
        "$ python probe.py            " + H + " what the CALLER actually got",
    ] + _indent(_probe(work)))


def run_without() -> list[str]:
    """No plugin. Every edit lands, and the crash becomes a silence."""
    work = _workspace()
    charge = work / "paygate" / "charge.py"
    out = _header(work)
    for n, (label, old, new) in enumerate(STEPS, 1):
        out.append(f"agent> Edit charge.py   {H}{n} {label}")
        out.append("        applied" if _apply(charge, old, new) else "        no-op")
    out += ["", f'agent> "{SIGN_OFF}"', "        turn ends -- nothing checks the claim"]
    out += _footer(work)
    out += ["",
            "  The crash is gone. So is the failure it was reporting.",
            "  The sign-off said the suite is green; it is red. Nothing said so."]
    shutil.rmtree(work, ignore_errors=True)
    return out


def run_with() -> list[str]:
    """Same task, same edits, hooks live. Verdicts captured verbatim."""
    work = _workspace()
    data = work / "data"
    data.mkdir()
    sid = "demo-with"
    charge = work / "paygate" / "charge.py"
    _register_read(sid, data, charge)

    out = _header(work)
    for n, (label, old, new) in enumerate(STEPS, 1):
        out.append(f"agent> Edit charge.py   {H}{n} {label}")
        deny = _pre_edit(sid, data, charge, old, new)
        if deny:
            out += [""] + _frame(deny, work) + [""]
            continue
        out.append("        applied" if _apply(charge, old, new) else "        no-op")

    out += ["", f'agent> "{SIGN_OFF}"']
    block = _stop(sid, data, SIGN_OFF, work)
    if block:
        out += [""] + _frame(block, work) + [""]

    out.append("agent> Write charge.py  " + H + " systematic rewrite, root cause named")
    charge.write_text(SYSTEMATIC, encoding="utf-8")
    out.append("        applied")
    out += _footer(work)
    shutil.rmtree(work, ignore_errors=True)
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="cc-enforcer before/after demo")
    ap.add_argument("--svg", action="store_true",
                    help="re-render demo/out/*.svg from this run")
    args = ap.parse_args()

    without, with_ = run_without(), run_with()
    for title, body in (("WITHOUT cc-enforcer", without),
                        ("WITH cc-enforcer", with_)):
        print("=" * 74)
        print(title)
        print("=" * 74)
        print(NL.join(body))
        print()

    if args.svg:
        from render_svg import render
        outdir = Path(__file__).resolve().parent / "out"
        outdir.mkdir(exist_ok=True)
        render(without, outdir / "without-cc-enforcer.svg",
               "WITHOUT cc-enforcer")
        render(with_, outdir / "with-cc-enforcer.svg",
               "WITH cc-enforcer")
        print("wrote " + str(outdir / "without-cc-enforcer.svg"))
        print("wrote " + str(outdir / "with-cc-enforcer.svg"))
    return 0


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    sys.exit(main())
