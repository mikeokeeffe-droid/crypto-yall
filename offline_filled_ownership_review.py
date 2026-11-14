"""Offline, read-only review of a possible filled-entry ownership handoff.

This module accepts *supplied* evidence only; it does not authenticate a
Hyperliquid response, read a database, submit an order, change bot ownership,
or grant a shared lock. A 'handoff_candidate' MUST NOT be fed directly into
owned_coins or any executable trading path. Only an independent authenticated
reconciler with approved atomic DB fencing could eventually perform handoff.

Conservative scope: fresh flat-before evidence and a fully filled new entry.
Partial fills, pyramids, netting against another bot, ambiguous fill history,
missing order IDs or stale captures ALWAYS hold for manual investigation.
"""
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation


@dataclass(frozen=True)
class OwnershipReview:
    status: str
    reason: str


def _amount(value):
    if type(value) not in (int, float, str, Decimal):
        return None
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    return result if result.is_finite() else None


def review_filled_entry_ownership(*, intent, expected_bot, expected_coin,
                                  expected_token, expected_account, order,
                                  before, first, second, now_ms,
                                  freshness_ms=60_000):
    """Returns only 'hold' or 'handoff_candidate'; never changes ownership."""
    def hold(message):
        return OwnershipReview("hold", message)

    if (type(intent) is not dict
            or expected_bot not in ("daily", "intraday", "aggressive")
            or type(expected_coin) is not str or not expected_coin.isascii()
            or not expected_coin.isalnum() or expected_coin != expected_coin.upper()
            or type(expected_token) is not str or not expected_token
            or type(expected_account) is not str or not expected_account
            or type(now_ms) is not int or now_ms <= 0
            or type(freshness_ms) is not int or not 0 < freshness_ms <= 300_000):
        return hold("invalid review context")
    if (intent.get("bot") != expected_bot
            or intent.get("coin") != expected_coin
            or intent.get("token") != expected_token
            or intent.get("status") not in ("submitted", "uncertain")
            or intent.get("action") not in ("open_long", "open_short")):
        return hold("unresolved new-entry intent identity missing or mismatched")
    order_id = intent.get("exchange_order_id")
    submitted = intent.get("submitted_at_ms")
    requested = _amount(intent.get("requested_size"))
    if (type(order_id) is not str or not order_id.strip()
            or type(submitted) is not int or submitted <= 0
            or requested is None or requested <= 0):
        return hold("durable order identity or size missing")

    side = "long" if intent["action"] == "open_long" else "short"
    direction = Decimal(1) if side == "long" else Decimal(-1)
    if (type(order) is not dict or order.get("account") != expected_account
            or order.get("coin") != expected_coin
            or order.get("order_id") != order_id
            or order.get("side") != side
            or order.get("status") != "filled"
            or order.get("final") is not True
            or order.get("complete") is not True
            or _amount(order.get("filled_size")) != requested):
        return hold("final, fully filled matching order not established")

    if type(before) is not dict or type(first) is not dict or type(second) is not dict:
        return hold("missing complete independent captures")
    snapshots = (before, first, second)
    ids = []
    for index, capture in enumerate(snapshots):
        stamp = capture.get("observed_at_ms")
        if (capture.get("account") != expected_account
                or capture.get("coin") != expected_coin
                or capture.get("fresh") is not True
                or capture.get("complete") is not True
                or type(stamp) is not int
                or type(capture.get("capture_id")) is not str
                or not capture["capture_id"].strip()):
            return hold("snapshot missing required account or provenance")
        ids.append(capture["capture_id"])
        if type(capture.get("open_orders")) is not list:
            return hold("open orders not completely observed")
        if any(type(item) is not dict or not item.get("coin")
               or item.get("coin") == expected_coin
               for item in capture["open_orders"]):
            return hold("outstanding or ambiguous order on the coin")
        current_size = _amount(capture.get("position_size"))
        expected_size = Decimal(0) if index == 0 else direction * requested
        if current_size != expected_size:
            return hold("position does not establish isolated order ownership")
        if index == 0:
            if not (submitted - 30_000 <= stamp <= submitted):
                return hold("flat-before capture is not near submission")
        else:
            previous = snapshots[index - 1]["observed_at_ms"]
            if not (previous < stamp <= now_ms
                    and stamp >= submitted
                    and now_ms - stamp <= freshness_ms):
                return hold("post-fill capture stale, future or unordered")
    if len(set(ids)) != 3:
        return hold("repeated capture identifier")

    # Independently complete fill histories should agree and contain no
    # competing same-coin order, duplicate ID, partial fill, or malformed fill.
    histories = []
    for capture in (first, second):
        if capture.get("fills_complete") is not True or type(capture.get("fills")) is not list:
            return hold("fill history incomplete")
        fills = {}
        for fill in capture["fills"]:
            if type(fill) is not dict or not fill.get("coin"):
                return hold("malformed exchange fill")
            if fill["coin"] != expected_coin:
                continue
            if (fill.get("account") != expected_account
                    or fill.get("order_id") != order_id
                    or fill.get("side") != side
                    or type(fill.get("fill_id")) is not str
                    or not fill["fill_id"].strip()
                    or type(fill.get("time_ms")) is not int
                    or not submitted <= fill["time_ms"] <= capture["observed_at_ms"]):
                return hold("foreign or ambiguous fill on shared coin")
            qty = _amount(fill.get("size"))
            if qty is None or qty <= 0 or fill["fill_id"] in fills:
                return hold("invalid or duplicate matching fill")
            fills[fill["fill_id"]] = (qty, fill["time_ms"])
        if not fills or sum((v[0] for v in fills.values()), Decimal(0)) != requested:
            return hold("missing, partial or oversized order fills")
        histories.append(fills)
    if histories[0] != histories[1]:
        return hold("exchange fill history changed across captures")
    return OwnershipReview(
        "handoff_candidate",
        "synthetic structural evidence matches; independent authentication, "
        "shared ownership fencing and audited DB handoff still required",
    )
