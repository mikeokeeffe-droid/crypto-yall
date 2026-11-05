"""Cross-check synthetic order status and raw fills; never authorize trading.

Pure offline inspection of already parsed untrusted tuples. The caller must
supply an independently pinned intent and both parser results. Neither source
authenticity nor historical completeness is established by this check.
"""
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

@dataclass(frozen=True)
class ConflictReview:
    status: str
    reason: str

def _amount(raw):
    if type(raw) is not str:
        return None
    try:
        value = Decimal(raw)
    except (InvalidOperation, ValueError):
        return None
    return value if value.is_finite() and value > 0 else None

def inspect_order_fill_consistency_offline(*, order_review, fills_review,
                                           oid, coin, direction, size,
                                           submitted_at_ms, start_ms, end_ms):
    def hold(reason):
        return ConflictReview("hold", reason)
    if (getattr(order_review, "status", None) != "parsed_untrusted"
            or getattr(fills_review, "status", None) != "parsed_untrusted"):
        return hold("missing or untrusted order/fill parser result")
    expected_size = _amount(size)
    if (type(oid) is not int or oid <= 0 or type(coin) is not str
            or not coin or direction not in ("long", "short")
            or expected_size is None or type(submitted_at_ms) is not int
            or type(start_ms) is not int or type(end_ms) is not int
            or submitted_at_ms <= 0 or start_ms > submitted_at_ms
            or end_ms < submitted_at_ms):
        return hold("invalid intent or missing fill coverage")
    orders = getattr(order_review, "records", None)
    fills = getattr(fills_review, "records", None)
    if (type(orders) is not tuple or len(orders) != 1
            or type(fills) is not tuple):
        return hold("missing parsed evidence")
    order = orders[0]
    if (type(order) is not tuple or len(order) != 4
            or type(order[0]) is not int or order[0] != oid
            or order[1] not in ("filled", "rejected")
            or type(order[2]) is not int or type(order[3]) is not int
            or order[2] < submitted_at_ms or order[3] < order[2]
            or end_ms < order[3]):
        return hold("order status conflicts with pinned intent or window")
    total = Decimal("0")
    tids = set()
    for fill in fills:
        if type(fill) is not tuple or len(fill) != 7:
            return hold("invalid fill tuple")
        fcoin, foid, tid, timestamp, side, _dir, raw_size = fill
        if type(tid) is not int or tid <= 0 or tid in tids:
            return hold("duplicate or invalid trade id")
        tids.add(tid)
        if type(timestamp) is not int or not start_ms <= timestamp <= end_ms:
            return hold("fill outside requested window")
        if foid != oid:
            if fcoin == coin:
                return hold("other same-coin order may have changed the shared account position")
            continue  # Different-coin activity does not establish this coin's ownership.
        if (fcoin != coin or side != ("B" if direction == "long" else "A")
                or timestamp < submitted_at_ms or timestamp > order[3]):
            return hold("fill conflicts with order identity, side or time")
        amount = _amount(raw_size)
        if amount is None:
            return hold("invalid fill size")
        total += amount
        if total > expected_size:
            return hold("fills exceed original order size")
    if order[1] == "rejected":
        if total:
            return hold("rejected order has matching fills")
        return hold("rejection and empty fills cannot prove no fill")
    if total != expected_size:
        return hold("filled status and observed fill sizes disagree or incomplete")
    return ConflictReview(
        "review_only",
        "synthetic order and fills agree; origin and history still unverified",
    )
