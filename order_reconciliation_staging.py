"""Offline order-outcome decision policy for staging; no live integration.

An unknown outcome must remain fenced until an independent exchange check
confirms both order status and position status.
"""
from enum import Enum


class OrderOutcome(Enum):
    FILLED = "filled"
    REJECTED = "rejected"
    UNKNOWN = "unknown"


def can_resolve_entry_intent(outcome: OrderOutcome, *, order_final: bool, position_flat: bool) -> bool:
    """Only remove an entry fence after a definitive no-fill reconciliation.

    A filled order requires ownership handoff first and must not simply be
    released because its request completed. Unknown/timeout outcomes never
    release a fence automatically.
    """
    return outcome is OrderOutcome.REJECTED and order_final and position_flat


def may_submit_new_entry(*, has_reservation: bool, has_durable_intent: bool,
                         exchange_position_flat: bool, exchange_orders_clear: bool) -> bool:
    return all((has_reservation, has_durable_intent, exchange_position_flat, exchange_orders_clear))
