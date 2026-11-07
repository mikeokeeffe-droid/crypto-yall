"""Staging-only wrapper for all three executors. NEVER submits an order.

This is an inspection adapter, not a live trading gate. No production
executor imports it. The real entry path must not use this until reviewed.
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Any

from executor_entry_dry_run_staging import simulate_executor_entry

BOTS = frozenset(("aggressive", "intraday", "daily"))


@dataclass(frozen=True)
class GateDecision:
    bot: str
    coin: str
    action: str
    simulated_allowed: bool
    live_order_submitted: bool = False


def inspect_entry(
    store: Any, *, bot: str, trade: dict,
    exchange_position_flat: bool, exchange_orders_clear: bool,
) -> GateDecision:
    if bot not in BOTS:
        raise ValueError("Unknown bot")
    coin = str(trade.get("hl_coin", ""))
    action = str(trade.get("action", ""))
    if not coin or not action:
        raise ValueError("Missing trade fields")
    if action == "close":
        # Exit paths must remain independent of entry reservation outages.
        # This wrapper makes NO exchange calls, including close calls.
        return GateDecision(bot, coin, action, simulated_allowed=False)
    if action not in ("open_long", "open_short", "pyramid_long", "pyramid_short"):
        return GateDecision(bot, coin, action, simulated_allowed=False)
    result = simulate_executor_entry(
        store, coin=coin, bot=bot,
        exchange_position_flat=exchange_position_flat,
        exchange_orders_clear=exchange_orders_clear,
    )
    return GateDecision(
        bot, coin, action, simulated_allowed=result.simulated_allowed,
    )
