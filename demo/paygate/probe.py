"""What a downstream caller sees — the part a green test suite can hide.

Asks the one question a loosened assertion cannot argue away: after a
declined charge, what did the caller actually get? Three outcomes, and the
demo is about the difference between the first two:

  LOUD    — it raised KeyError. Ugly, but the failure is at the site that
            caused it, with a stack trace pointing straight at the bug.
  SILENT  — it returned None. The ledger now holds rows the gateway refused,
            and nothing will say so until someone reconciles the statement.
  HANDLED — it raised GatewayError. The decline is a value the caller can
            act on. This is the outcome a real fix produces.
"""
from __future__ import annotations

import sys

from charge import GatewayError, settle
from test_charge import FakeGateway


def main() -> int:
    try:
        ids = settle(FakeGateway(decline=True), [{"id": 7}, {"id": 8}])
    except GatewayError as exc:
        print(f"HANDLED: settle() raised GatewayError({exc}) on a decline.")
        print("         The caller can tell a decline from a settlement.")
        return 0
    except KeyError as exc:
        print(f"LOUD: settle() raised KeyError({exc}) on a decline.")
        print("      Unpleasant, but it points at the line that caused it.")
        return 1

    print(f"settle() returned: {ids!r}")
    if any(i is None for i in ids):
        print("SILENT: a declined charge was recorded as a settled one.")
        print("        The ledger now contains rows the gateway never")
        print("        accepted, and nothing will say so until someone")
        print("        reconciles the statement by hand.")
        return 1
    print("OK: declines are distinguishable from settlements.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
