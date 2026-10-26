"""Offline-only guarded executor adapter for the three real execute_trade functions.

Not imported by production executors. Caller injects fake exchange and store.
A real deployment must use a reviewed atomic store, durable intent lifecycle,
exchange reconciliation and authenticated DB roles.
"""
from __future__ import annotations
from typing import Callable, Any
from entry_gate_staging import acquire_entry_permit

OPEN_ACTIONS = frozenset(("open_long", "open_short", "pyramid_long", "pyramid_short"))
BOTS = frozenset(("aggressive", "intraday", "daily"))

def execute_with_staging_fence(
    execute_trade: Callable[..., dict], info: Any, exchange: Any,
    trade: dict, capital: float, leverage: float, *,
    bot: str, store: Any, exchange_position_flat: bool,
    exchange_orders_clear: bool,
) -> dict:
    """Invoke the real function only when a simulated permit is valid.

    The adapter is intentionally offline-only and rejects non-fake exchanges.
    Do not use this as a live entry integration.
    """
    if bot not in BOTS:
        raise ValueError("unknown bot")
    if not isinstance(trade, dict):
        raise ValueError("invalid trade")
    action = trade.get("action")
    coin = trade.get("hl_coin")
    if not isinstance(coin, str) or not coin:
        raise ValueError("invalid coin")
    if action == "close":
        return execute_trade(info, exchange, trade, capital, leverage)
    if action not in OPEN_ACTIONS:
        return {**trade, "status": "skipped", "reason": "unknown entry action"}
    if not getattr(exchange, "is_offline_fake", False):
        return {**trade, "status": "skipped", "reason": "staging adapter requires offline fake exchange"}
    permit = acquire_entry_permit(store, coin, bot)
    if permit is None:
        return {**trade, "status": "skipped", "reason": "entry reservation denied"}
    if not exchange_position_flat or not exchange_orders_clear:
        return {**trade, "status": "skipped", "reason": "exchange entry preflight denied"}
    return execute_trade(info, exchange, trade, capital, leverage)
