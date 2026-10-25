"""Read-only Hyperliquid evidence acquisition for an isolated reconciler.

No wallet keys, database writes, or trading calls. Client is injected by caller.
This is not a deployed trusted service and must not authorize live orders.
"""
from dataclasses import dataclass
import time

@dataclass(frozen=True)
class ExchangeSnapshot:
    user_state: dict
    open_orders: list
    fills: list
    fetched_at: float

def fetch_exchange_snapshot(info, account_address: str, *, clock=time.time):
    if not isinstance(account_address, str) or not account_address.startswith("0x") or len(account_address) != 42:
        raise ValueError("valid public account address required")
    # SDK Info methods are read-only; fail closed if any request fails.
    user_state = info.user_state(account_address)
    open_orders = info.open_orders(account_address)
    fills = info.user_fills(account_address)
    if not isinstance(user_state, dict) or not isinstance(open_orders, list) or not isinstance(fills, list):
        raise ValueError("incomplete exchange snapshot")
    return ExchangeSnapshot(user_state, open_orders, fills, clock())

def is_fresh(snapshot: ExchangeSnapshot, *, now=None, max_age_seconds=15):
    if now is None:
        now = time.time()
    age = now - snapshot.fetched_at
    return 0 <= age <= max_age_seconds
