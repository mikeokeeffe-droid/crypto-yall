"""Offline-only order-intent binding for synthetic fill receipts.

Never authenticates the exchange, confirms ownership, or releases a fence.
No network, database, SDK, or live executor imports.
"""
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from offline_hyperliquid_strict_order_parser import inspect_market_order_response_offline

@dataclass(frozen=True)
class IntentBoundFillReview:
    status: str
    reason: str

def inspect_intent_bound_fill_offline(*, response, intent):
    def hold(reason):
        return IntentBoundFillReview("hold", reason)
    if type(intent) is not dict or set(intent) != {"oid", "requested_size", "coin", "direction"}:
        return hold("missing or unexpected order intent fields")
    oid, size = intent["oid"], intent["requested_size"]
    coin, direction = intent["coin"], intent["direction"]
    if (type(oid) is not int or oid <= 0
            or type(size) is not str or not size or size.strip() != size
            or type(coin) is not str or not coin.isascii()
            or not coin.isalnum() or coin != coin.upper()
            or direction not in ("long", "short")):
        return hold("invalid pinned intent")
    try:
        quantity = Decimal(size)
    except (InvalidOperation, ValueError):
        return hold("invalid requested quantity")
    if not quantity.is_finite() or quantity <= 0:
        return hold("nonpositive requested quantity")
    parsed = inspect_market_order_response_offline(
        response=response, expected_oid=oid, requested_size=size)
    if parsed.status != "parsed_untrusted":
        return hold("fill does not match pinned order id and size")
    # Market-order submit receipts do not independently bind coin/side/account.
    # Keep even matching synthetic receipts on HOLD until independent evidence.
    return IntentBoundFillReview(
        "hold", "order id and size structurally match, but coin, side, "
                "account and exchange provenance are unverified")
