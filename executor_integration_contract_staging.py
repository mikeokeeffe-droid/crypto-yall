"""Offline executor entry-path adapter. Never calls exchange APIs.

Each of the three real executors can be represented with the same action
mapping. This module is NOT imported by live executors. Fake/staging stores
only: inspect_entry reserves and claims a durable intent.
"""
from dataclasses import dataclass
from shared_entry_gate_staging import inspect_entry


@dataclass(frozen=True)
class SimulatedExecution:
    bot: str
    coin: str
    action: str
    decision: str
    order_submitted: bool = False


def evaluate_executor_trade(store, *, bot: str, trade: dict,
                            position_flat: bool, no_open_orders: bool):
    """Inspect entry safety without sending orders or executing exits.

    A close is handed back to the original exit pathway, not blocked by
    a database failure. Callers must not mistake this for an executed exit.
    """
    action = str(trade.get("action", ""))
    coin = str(trade.get("hl_coin", ""))
    if action == "close":
        return SimulatedExecution(bot, coin, action, "defer_to_existing_exit")
    try:
        result = inspect_entry(
            store, bot=bot, trade=trade,
            exchange_position_flat=position_flat,
            exchange_orders_clear=no_open_orders,
        )
    except Exception:
        return SimulatedExecution(bot, coin, action, "deny")
    return SimulatedExecution(
        bot, coin, action, "eligible_for_future_review" if result.simulated_allowed
        else "deny",
    )
