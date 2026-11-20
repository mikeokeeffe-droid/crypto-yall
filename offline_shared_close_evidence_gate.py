"""Fail-closed structural review of synthetic shared-account close evidence.

All records are caller supplied. This does not authenticate Hyperliquid, prove
who submitted an order, establish complete account history, acquire a shared
lock, or authorize ANY trade. Even a coherent case returns status='hold'.
No network, exchange SDK, executor, secrets, or database imports.
"""
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

BOTS = frozenset(("daily", "intraday", "aggressive"))
ORDER_KEYS = frozenset((
    "order_id", "bot", "account", "coin", "side", "kind", "requested_size",
    "submitted_at_ms", "status", "final",
))
FILL_KEYS = frozenset((
    "fill_id", "order_id", "account", "coin", "exchange_side", "size", "time_ms",
))
REQUEST_KEYS = frozenset(("bot", "account", "coin", "side", "close_size"))
SNAPSHOT_KEYS = frozenset((
    "capture_id", "account", "coin", "side", "position_size",
    "captured_at_ms", "fills_complete", "open_orders_empty",
))


@dataclass(frozen=True)
class SharedCloseEvidenceReview:
    status: str
    reason: str
    structurally_consistent: bool = False
    submit_authorized: bool = False


def _positive(raw):
    if type(raw) is not str or not raw or raw.strip() != raw:
        return None
    try:
        value = Decimal(raw)
    except (InvalidOperation, ValueError):
        return None
    return value if value.is_finite() and value > 0 else None


def _strict_keys(value, keys):
    return type(value) is dict and set(value) == keys


def review_shared_close_evidence_offline(
    *, request, order_claims, exchange_fills, snapshot, now_ms,
    max_snapshot_age_ms=30_000,
):
    """Compare claimed intent, fills and snapshot; NEVER unlocks a close."""
    def hold(reason, coherent=False):
        return SharedCloseEvidenceReview("hold", reason, coherent)

    if not _strict_keys(request, REQUEST_KEYS):
        return hold("missing or unexpected close request fields")
    bot, account, coin, side = (
        request["bot"], request["account"], request["coin"], request["side"]
    )
    close_size = _positive(request["close_size"])
    if (type(bot) is not str or bot not in BOTS
            or type(account) is not str or not account or account.strip() != account
            or type(coin) is not str or not coin.isascii()
            or not coin.isalnum() or coin != coin.upper()
            or side not in ("long", "short") or close_size is None):
        return hold("invalid pinned bot, account, coin, direction or close size")
    if (type(now_ms) is not int or now_ms <= 0
            or type(max_snapshot_age_ms) is not int
            or not 0 < max_snapshot_age_ms <= 60_000):
        return hold("invalid review clock or freshness policy")
    if not _strict_keys(snapshot, SNAPSHOT_KEYS):
        return hold("incomplete or unexpected position snapshot fields")
    captured = snapshot["captured_at_ms"]
    position_size = _positive(snapshot["position_size"])
    if (snapshot["account"] != account or snapshot["coin"] != coin
            or snapshot["side"] != side
            or type(snapshot["capture_id"]) is not str
            or not snapshot["capture_id"].strip()
            or type(captured) is not int
            or not 0 < captured <= now_ms
            or now_ms - captured > max_snapshot_age_ms
            or snapshot["fills_complete"] is not True
            or snapshot["open_orders_empty"] is not True
            or position_size is None or close_size > position_size):
        return hold("snapshot, completeness, freshness or size unverified")

    if (type(order_claims) is not list or not order_claims
            or type(exchange_fills) is not list or not exchange_fills):
        return hold("missing order claims or exchange fills")
    orders = {}
    for claim in order_claims:
        if not _strict_keys(claim, ORDER_KEYS):
            return hold("malformed or unexpected durable order claim")
        oid = claim["order_id"]
        submitted = claim["submitted_at_ms"]
        size = _positive(claim["requested_size"])
        if (type(oid) is not int or oid <= 0 or oid in orders
                or type(submitted) is not int or not 0 < submitted <= captured
                or claim["account"] != account or claim["coin"] != coin
                or claim["side"] != side or claim["bot"] not in BOTS
                or claim["kind"] not in ("entry", "close")
                or claim["status"] != "filled" or claim["final"] is not True
                or size is None):
            return hold("unmatched, duplicate, unfilled or ambiguous order claim")
        if claim["bot"] != bot:
            return hold("another bot claims an order on this shared coin")
        orders[oid] = (claim, size)

    grouped = {oid: Decimal(0) for oid in orders}
    trade_ids = set()
    for fill in exchange_fills:
        if not _strict_keys(fill, FILL_KEYS):
            return hold("malformed or unexpected fill receipt")
        oid, fid, when = fill["order_id"], fill["fill_id"], fill["time_ms"]
        qty = _positive(fill["size"])
        if (type(oid) is not int or oid not in orders
                or type(fid) is not str or not fid.strip() or fid in trade_ids
                or type(when) is not int or when < orders[oid][0]["submitted_at_ms"]
                or when > captured or qty is None
                or fill["account"] != account or fill["coin"] != coin):
            return hold("orphaned, duplicate, stale or mismatched fill")
        trade_ids.add(fid)
        claim = orders[oid][0]
        expected_side = (
            "buy" if (side == "long") == (claim["kind"] == "entry") else "sell"
        )
        if fill["exchange_side"] != expected_side:
            return hold("opposing execution side may net shared-account position")
        grouped[oid] += qty
        if grouped[oid] > orders[oid][1]:
            return hold("fills exceed claimed order quantity")

    remaining = Decimal(0)
    for oid, (claim, size) in sorted(
        orders.items(), key=lambda item: (item[1][0]["submitted_at_ms"], item[0])
    ):
        if grouped[oid] != size:
            return hold("incomplete or disputed full-fill coverage")
        if claim["kind"] == "entry":
            remaining += size
        else:
            remaining -= size
            if remaining < 0:
                return hold("historical close exceeds attributed entry quantity")
    if remaining != position_size or close_size > remaining:
        return hold("order ledger cannot reconcile to fresh exchange position")

    # An exact synthetic match still cannot establish authenticity, source
    # completeness, bot-to-order submission, or atomic ownership fencing.
    return hold(
        "synthetic evidence consistent; independent provenance and atomic "
        "shared-account fencing remain unverified",
        coherent=True,
    )
