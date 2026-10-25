"""Read-only Hyperliquid evidence acquisition for an isolated reconciler.

No wallet keys, database writes, or trading calls. Client is injected by caller.
This is not a deployed trusted service and must not authorize live orders.
"""
from dataclasses import dataclass
import time
import re

@dataclass(frozen=True)
class ExchangeSnapshot:
    user_state: dict
    open_orders: list
    fills: list
    fetched_at: float

def fetch_exchange_snapshot(info, account_address: str, *, clock=time.time):
    if not isinstance(account_address, str) or not re.fullmatch(r"0x[0-9a-fA-F]{40}", account_address):
        raise ValueError("valid public account address required")
    # SDK Info methods are read-only; fail closed if any request fails.
    started_at = clock()
    user_state = info.user_state(account_address)
    open_orders = info.open_orders(account_address)
    fills = info.user_fills(account_address)
    if not isinstance(user_state, dict) or not isinstance(open_orders, list) or not isinstance(fills, list):
        raise ValueError("incomplete exchange snapshot")
    # Timestamp at request start, not after slow sequential requests.
    return ExchangeSnapshot(user_state, open_orders, fills, started_at)

def is_fresh(snapshot: ExchangeSnapshot, *, now=None, max_age_seconds=15):
    if now is None:
        now = time.time()
    age = now - snapshot.fetched_at
    return 0 <= age <= max_age_seconds
