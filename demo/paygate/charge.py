"""A deliberately buggy module, used by the before/after demo.

The bug is a LATENT one: `charge()` assumes the gateway always answers with
an id. When the gateway answers with an error envelope instead, the lookup
raises `KeyError: 'id'` — loud, immediate, and easy to trace.

That loudness is the point. The demo shows what happens to it under an
agent that patches reactively: the crash does not get fixed, it gets
*quieted*, and the failure reappears later as a `None` nobody checked.
"""
from __future__ import annotations


class GatewayError(Exception):
    """The payment gateway rejected the charge."""


def charge(gateway, order: dict) -> str:
    """Charge an order and return the gateway's transaction id.

    Raises KeyError when the gateway returns an error envelope — that is
    the bug the demo's task asks an agent to fix.
    """
    response = gateway.post("/charge", order)
    return response["id"]


def settle(gateway, orders: list[dict]) -> list[str]:
    """Charge every order, returning the transaction ids."""
    return [charge(gateway, order) for order in orders]
