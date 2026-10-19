"""Shared, sampled position-level USD loss threshold for live protection wrappers.

The threshold compares exchange-reported *unrealized* P&L, not net realized P&L.
Execution can happen beyond the threshold due to polling, latency and slippage.
"""

import math


def loss_cap_breached(unrealized_pnl: float, cap_usd: float) -> bool:
    """True when a valid, positive USD cap is breached by unrealized P&L.

    Bad or missing exchange values never independently authorize an order.
    """
    try:
        pnl = float(unrealized_pnl)
        cap = float(cap_usd)
    except (TypeError, ValueError, OverflowError):
        return False
    return math.isfinite(pnl) and math.isfinite(cap) and cap > 0 and pnl <= -cap
