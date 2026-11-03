"""Fail-closed account-level ambiguity review for synthetic Hyperliquid fills.

An individual order's matching fills do NOT establish the account's net
position or the absence of concurrent orders. This is pure offline review:
no SDK, network, wallet, database, orders, or trading authorization.
"""
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

@dataclass(frozen=True)
class AccountImpactReview:
    status: str
    reason: str

def _positive(raw):
    if type(raw) is not str:
        return None
    try:
        value = Decimal(raw)
    except (InvalidOperation, ValueError):
        return None
    return value if value.is_finite() and value > 0 else None

def inspect_account_order_impact_offline(*, target_oid, target_coin,
                                         order_status, requested_size,
                                         fills, open_orders_known_empty,
                                         position_snapshot_verified):
    def hold(reason):
        return AccountImpactReview("hold", reason)
    if (type(target_oid) is not int or target_oid <= 0
            or type(target_coin) is not str or not target_coin
            or _positive(requested_size) is None
            or type(fills) is not tuple):
        return hold("invalid target order or fill evidence")
    if order_status not in ("filled", "rejected", "canceled", "cancelled"):
        return hold("nonterminal or unknown order status")
    if (open_orders_known_empty is not True
            or position_snapshot_verified is not True):
        return hold("account-level open orders or position state unverified")
    observed = Decimal(0)
    tids = set()
    for fill in fills:
        if type(fill) is not tuple or len(fill) != 7:
            return hold("invalid account fill record")
        coin, oid, tid, timestamp, side, direction, raw_size = fill
        if (type(coin) is not str or type(oid) is not int
                or type(tid) is not int or tid <= 0 or tid in tids
                or type(timestamp) is not int or timestamp <= 0
                or side not in ("A", "B") or type(direction) is not str
                or _positive(raw_size) is None):
            return hold("malformed or duplicated account fill")
        tids.add(tid)
        if coin == target_coin and oid != target_oid:
            return hold("other order affects target coin; account position ambiguous")
        if oid == target_oid:
            if coin != target_coin:
                return hold("target order fill has conflicting coin")
            observed += _positive(raw_size)
            if observed > _positive(requested_size):
                return hold("target order fills exceed original size")
    if order_status in ("rejected", "canceled", "cancelled"):
        return hold("terminal cancellation or rejection cannot establish safe re-entry")
    if observed != _positive(requested_size):
        return hold("missing or partial target fills")
    return AccountImpactReview(
        "review_only",
        "synthetic account impact appears consistent; provenance and account state unverified",
    )
