"""Staging-only dry-run bridge: exercise entry gate without placing an order.

Not imported by any live bot. The injected order callback is deliberately
NEVER called; the return value is always a denial for actual execution.
"""
from dataclasses import dataclass
from typing import Any, Callable
from entry_gate_staging import acquire_entry_permit
from entry_lifecycle_staging import EntryLifecycle


@dataclass(frozen=True)
class DryRunResult:
    simulated_allowed: bool
    live_order_submitted: bool = False


def simulate_executor_entry(
    store: Any, *, coin: str, bot: str, exchange_position_flat: bool,
    exchange_orders_clear: bool, order_sender: Callable[..., Any] | None = None,
) -> DryRunResult:
    # Caller MUST supply fake/staging store. This function is deliberately
    # incapable of submitting a live order even if given an order_sender.
    permit = acquire_entry_permit(store, coin, bot)
    if permit is None:
        return DryRunResult(False)
    lifecycle = EntryLifecycle()
    simulated = lifecycle.acquire(
        reserved=True, claimed=True,
        exchange_flat=exchange_position_flat,
        no_open_orders=exchange_orders_clear,
    )
    return DryRunResult(simulated_allowed=simulated)
