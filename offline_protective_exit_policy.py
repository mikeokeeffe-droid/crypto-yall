"""Offline policy for protective close eligibility when entries are disabled.

Review-only. A positive result NEVER places an order or overrides a kill switch.
The live exchange adapter must independently enforce reduce-only semantics,
account ownership, position size and a fresh authenticated snapshot.
"""
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

@dataclass(frozen=True)
class ExitReview:
    status: str
    reason: str
    submit_authorized: bool = False

def _positive_decimal(value):
    if type(value) is not str:
        return None
    try:
        number = Decimal(value)
    except (InvalidOperation, ValueError):
        return None
    return number if number.is_finite() and number > 0 else None

def review_protective_exit_offline(*, action, reduce_only, account_verified,
                                   position_owned, position_side,
                                   position_size, close_size, snapshot_fresh,
                                   entries_disabled):
    def hold(reason):
        return ExitReview("hold", reason)
    if action != "close" or reduce_only is not True:
        return hold("not an explicitly reduce-only close")
    if any(type(flag) is not bool for flag in (
            account_verified, position_owned, snapshot_fresh, entries_disabled)):
        return hold("invalid verification flag")
    if not entries_disabled:
        return hold("this review applies only to disabled-entry mode")
    if not account_verified or not position_owned or not snapshot_fresh:
        return hold("account, position ownership or snapshot unverified")
    if position_side not in ("long", "short"):
        return hold("position side missing")
    size = _positive_decimal(position_size)
    closing = _positive_decimal(close_size)
    if size is None or closing is None or closing > size:
        return hold("invalid or oversized close")
    return ExitReview(
        "review_only",
        "synthetic close meets preliminary checks; live enforcement unverified",
    )
