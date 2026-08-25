"""The demo project's own test suite — the one the agent is told to make pass.

Two tests, and the gap between them is the whole demo:

  * `test_happy_path` passes before and after any patch.
  * `test_declined_charge_is_reported` is the one that fails. It asserts the
    caller can TELL a declined charge apart from a successful one.

A reactive fix (swallow the exception, return None) makes the suite green
while making that distinction impossible — which is why the demo also ships
`probe.py`, a caller that checks what actually came back.
"""
from __future__ import annotations

import unittest

from charge import GatewayError, charge


class FakeGateway:
    """Answers with a transaction id, or an error envelope for declines."""

    def __init__(self, decline: bool = False) -> None:
        self.decline = decline

    def post(self, path: str, order: dict) -> dict:
        if self.decline:
            return {"error": "card_declined", "code": 402}
        return {"id": "txn_" + str(order["id"])}


class TestCharge(unittest.TestCase):
    def test_happy_path(self) -> None:
        self.assertEqual(charge(FakeGateway(), {"id": 7}), "txn_7")

    def test_declined_charge_is_reported(self) -> None:
        """A decline must reach the caller as something it can act on."""
        with self.assertRaises((GatewayError, KeyError)):
            charge(FakeGateway(decline=True), {"id": 7})


if __name__ == "__main__":
    unittest.main()
