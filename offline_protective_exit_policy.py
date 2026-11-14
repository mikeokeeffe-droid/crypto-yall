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


def review_pinned_close_identity_offline(*, intended, observed):
    """Check synthetic close identity against a pinned bot/account/coin/side.

    An exact match is review-only: neither caller-provided record is
    authenticated. Never grants permission to send an exchange order.
    """
    def hold(reason):
        return ExitReview("hold", reason)
    keys = {"bot", "account", "coin", "side"}
    if type(intended) is not dict or type(observed) is not dict:
        return hold("missing pinned close identity")
    if set(intended) != keys or set(observed) != keys:
        return hold("missing or extra close identity fields")
    for key in keys:
        a, b = intended[key], observed[key]
        if type(a) is not str or type(b) is not str or not a or not b:
            return hold("invalid close identity")
        if a != b:
            return hold("close identity mismatch")
    if intended["bot"] not in ("daily", "intraday", "aggressive"):
        return hold("unknown bot")
    if intended["side"] not in ("long", "short"):
        return hold("unknown position side")
    if (not intended["coin"].isascii()
            or not intended["coin"].isalnum()
            or intended["coin"] != intended["coin"].upper()):
        return hold("invalid coin")
    return ExitReview("review_only",
                      "synthetic identities match; ownership not authenticated")
