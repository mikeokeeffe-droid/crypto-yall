"""Non-trading Intraday entry observer; never grants a live order permit.

The observer intentionally reports missing independent exchange evidence.
It never imports the reservation store or uses credentials.
"""


def observe_intraday_entry(*, trade: dict, position_snapshot=None) -> dict:
    coin = str(trade.get("hl_coin", ""))
    action = str(trade.get("action", ""))
    valid = bool(coin and action in ("open_long", "open_short", "pyramid_long", "pyramid_short"))
    return {
        "coin": coin,
        "action": action,
        "candidate_valid": valid,
        "position_evidence_available": isinstance(position_snapshot, dict),
        "reservation_verified": False,
        "decision": "blocked_no_trusted_reservation_or_exchange_reconciliation",
        "order_submitted": False,
    }
