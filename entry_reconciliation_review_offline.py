"""Pure, offline review policy for unresolved exchange entry intents.

This is NOT a live reconciler and cannot release a database claim or submit
an exchange order. Evidence must already be authenticated, independently
fetched, complete, and fresh by a separately reviewed trusted component.
A 'review_candidate' is NOT permission to unlock or re-enter.

An unknown, partially-filled, missing-ID, stale, or contradictory exchange
outcome remains HOLD. Conservative by design.
"""
from dataclasses import dataclass
from math import isfinite


@dataclass(frozen=True)
class ReviewDecision:
    status: str
    reason: str


def review_final_no_fill(*, coin, order_id, submitted_at_ms,
                         order, first, second):
    """Return only 'hold' or 'review_candidate'; NEVER unlocks an intent."""
    hold = lambda why: ReviewDecision("hold", why)
    if (type(coin) is not str or not coin or not coin.isascii()
            or not coin.isalnum() or coin != coin.upper()
            or type(order_id) is not str or not order_id.strip()
            or type(submitted_at_ms) is not int or submitted_at_ms < 0):
        return hold("missing durable order identity")
    if (type(order) is not dict or order.get("coin") != coin
            or order.get("order_id") != order_id
            or order.get("final") is not True
            or order.get("status") != "rejected"
            or order.get("complete") is not True):
        return hold("final authoritative rejection not confirmed")
    if type(order.get("filled_size")) not in (int, float):
        return hold("missing definitive zero fill")
    if not isfinite(order["filled_size"]) or order["filled_size"] != 0:
        return hold("order may have filled")
    if type(first) is not dict or type(second) is not dict:
        return hold("missing independent snapshots")

    previous_time = submitted_at_ms
    for observation in (first, second):
        if (observation.get("coin") != coin
                or observation.get("fresh") is not True
                or observation.get("complete") is not True
                or observation.get("fills_complete") is not True
                or type(observation.get("observed_at_ms")) is not int
                or observation["observed_at_ms"] <= previous_time):
            return hold("snapshot is stale, incomplete or not independently ordered")
        previous_time = observation["observed_at_ms"]
        size = observation.get("position_size")
        if type(size) not in (float, int) or not isfinite(size) or size != 0:
            return hold("flat position not established")
        if type(observation.get("open_orders")) is not list:
            return hold("open-order evidence missing")
        if any(type(item) is not dict or item.get("coin") == coin
               or not item.get("coin") for item in observation["open_orders"]):
            return hold("open order or ambiguous order evidence")
        if type(observation.get("fills")) is not list:
            return hold("fill evidence missing")
        if any(type(fill) is not dict or fill.get("coin") == coin
               and str(fill.get("order_id")) == order_id
               or not fill.get("coin") or not fill.get("order_id")
               for fill in observation["fills"]):
            return hold("matching or ambiguous fill evidence")

    return ReviewDecision(
        "review_candidate",
        "two fresh complete snapshots and final no-fill rejection; "
        "trusted reconciler review and authorized DB transition still required",
    )


def review_persisted_entry_no_fill(*, intent, expected_bot, expected_coin,
                                   expected_token, order, first, second):
    """Read-only review of evidence bound to one persisted unresolved intent.

    The caller must independently authenticate the intent's origin and exchange
    snapshots. Matching caller-supplied fields is NOT authentication. Even a
    successful result is only a manual-review candidate, NEVER unlock approval.
    """
    hold = lambda why: ReviewDecision("hold", why)
    if (type(intent) is not dict
            or expected_bot not in ("aggressive", "intraday", "daily")
            or type(expected_coin) is not str
            or type(expected_token) is not str or not expected_token):
        return hold("missing trusted intent context")
    if (intent.get("bot") != expected_bot
            or intent.get("coin") != expected_coin
            or intent.get("token") != expected_token):
        return hold("persisted intent identity does not match")
    if intent.get("status") not in ("submitted", "uncertain"):
        return hold("unresolved submitted intent required")
    order_id = intent.get("exchange_order_id")
    timestamp = intent.get("submitted_at_ms")
    size = intent.get("requested_size")
    if (type(order_id) is not str or not order_id.strip()
            or type(timestamp) is not int or timestamp < 0
            or type(size) not in (int, float)
            or not isfinite(size) or size <= 0):
        return hold("durable order details incomplete")
    return review_final_no_fill(
        coin=expected_coin, order_id=order_id, submitted_at_ms=timestamp,
        order=order, first=first, second=second,
    )
