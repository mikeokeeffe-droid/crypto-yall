"""Offline-only close quantity attribution for shared-account bots.

Synthetic records are untrusted. Even exact matches never authorize an order.
No exchange, executor, database, or network dependencies.
"""
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

@dataclass(frozen=True)
class QuantityReview:
    status: str
    reason: str
    submit_authorized: bool = False

def _qty(value):
    if type(value) is not str:
        return None
    try:
        v = Decimal(value)
    except (InvalidOperation, ValueError):
        return None
    return v if v.is_finite() and v >= 0 else None

def review_close_quantity_offline(*, bot, account, coin, side, close_size,
                                  exchange_size, fills, provenance_verified=False):
    def hold(reason):
        return QuantityReview("hold", reason)
    if bot not in ("daily", "intraday", "aggressive") or type(account) is not str or not account:
        return hold("invalid bot or account")
    if type(coin) is not str or not coin.isascii() or not coin.isalnum() or coin != coin.upper():
        return hold("invalid coin")
    if side not in ("long", "short") or type(fills) is not list:
        return hold("invalid side or fill evidence")
    close, exchange = _qty(close_size), _qty(exchange_size)
    if close is None or exchange is None or close == 0 or close > exchange:
        return hold("invalid or oversized close")
    if provenance_verified is not True:
        return hold("independent fill provenance unverified")
    # Opposite-side fills can net a shared account position. Without an
    # independently reconciled per-order ledger, never attribute such flows.
    if any(type(f) is dict and f.get("side") != side for f in fills):
        return hold("opposite-direction fill may net shared position")
    seen = set()
    owned = Decimal(0)
    for fill in fills:
        if type(fill) is not dict or set(fill) != {"id", "bot", "account", "coin", "side", "kind", "size"}:
            return hold("incomplete or unexpected fill record")
        fid = fill["id"]
        qty = _qty(fill["size"])
        if type(fid) is not str or not fid or fid in seen or qty is None or qty == 0:
            return hold("duplicate or invalid fill")
        seen.add(fid)
        if fill["account"] != account or fill["coin"] != coin or fill["side"] != side:
            return hold("foreign account, coin or direction")
        if fill["bot"] not in ("daily", "intraday", "aggressive") or fill["kind"] not in ("entry", "close"):
            return hold("invalid fill identity or kind")
        if fill["bot"] == bot:
            owned += qty if fill["kind"] == "entry" else -qty
            if owned < 0:
                return hold("close exceeds prior attributed entries")
    if owned > exchange:
        return hold("attributed quantity exceeds shared exchange position")
    if close > owned:
        return hold("close exceeds bot-attributed remaining quantity")
    return QuantityReview("review_only", "synthetic attribution fits; independent reconciliation and live enforcement absent")
