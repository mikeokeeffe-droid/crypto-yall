"""Independent, *offline*, exact bracket evidence checks for a future TESTNET Daily sender.

Inputs are TEST FIXTURES shaped like Hyperliquid /info clearinghouseState,
openOrders and frontendOpenOrders (which includes reduceOnly/isTrigger/orderType).
This does NOT fetch /info, sign, submit, cancel, close, mutate a durable claim, or
authorize trading. A matching snapshot means 'review-only', never 'safe to trade'.
Unknown, partial, stale, mismatched or missing evidence always raises HOLD.
"""
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
import re

from testnet_paper_review.offline_daily_bracket_plan import (
    OfflineBracketPlan, BracketHold
)
from testnet_paper_review.testnet_daily_admission_gate import (
    EXPECTED_ACCOUNT, EXPECTED_NETWORK
)

MAX_OBSERVATION_AGE_S = 10


@dataclass(frozen=True)
class ProtectionObservation:
    status: str
    reason: str
    entry_oid: int
    take_profit_oid: int
    stop_loss_oid: int

    @property
    def allows_trading(self):
        return False


def _decimal(value, name):
    if type(value) is not str or not re.fullmatch(
            r"(?:0|[1-9][0-9]*)(?:\.[0-9]{1,8})?", value):
        raise BracketHold(f"HOLD: invalid {name}")
    try:
        result = Decimal(value)
    except InvalidOperation as exc:
        raise BracketHold(f"HOLD: invalid {name}") from exc
    if not result.is_finite() or result <= 0:
        raise BracketHold(f"HOLD: nonpositive {name}")
    return result


def _oid(status, key):
    if type(status) is not dict or set(status) != {key}:
        raise BracketHold(f"HOLD: ambiguous {key} acknowledgment")
    data = status[key]
    if type(data) is not dict:
        raise BracketHold(f"HOLD: invalid {key} acknowledgment")
    value = data.get("oid")
    if type(value) is not int or value <= 0:
        raise BracketHold(f"HOLD: missing exchange order identifier in {key}")
    return value


def _matching_oid_records(records, label):
    if type(records) is not list:
        raise BracketHold(f"HOLD: absent {label} evidence")
    seen = {}
    for row in records:
        if type(row) is not dict:
            raise BracketHold(f"HOLD: non-object {label} record")
        oid = row.get("oid")
        if type(oid) is not int or oid <= 0 or oid in seen:
            raise BracketHold(f"HOLD: missing or duplicate {label} oid")
        seen[oid] = row
    return seen


def assess_observed_bracket(*, plan, account, network, response,
                            positions, open_orders, frontend_open_orders,
                            observation_started_s, observation_finished_s,
                            now_s):
    """Compare exchange-shaped ACK, position and both independent order views.

    An apparently passing observation is only evidence for a human/security
    reviewer. It is not an emergency stop, not durable ownership, not a full
    fill-proof or indication that a stop will execute during volatility.
    """
    if type(plan) is not OfflineBracketPlan or plan.permits_submission:
        raise BracketHold("HOLD: no review-only protected plan")
    if type(account) is not str or account.lower() != EXPECTED_ACCOUNT.lower():
        raise BracketHold("HOLD: incorrect account identity")
    if network != EXPECTED_NETWORK or plan.account.lower() != EXPECTED_ACCOUNT.lower():
        raise BracketHold("HOLD: wrong network or plan account")
    if any(type(x) is not int for x in
           (observation_started_s, observation_finished_s, now_s)):
        raise BracketHold("HOLD: invalid independent observation times")
    if not (0 <= now_s - observation_started_s <= MAX_OBSERVATION_AGE_S
            and observation_started_s <= observation_finished_s <= now_s):
        raise BracketHold("HOLD: stale, reversed or future exchange evidence")
    if type(response) is not dict or response.get("status") != "ok":
        raise BracketHold("HOLD: grouped order ACK missing or unknown")
    envelope = response.get("response")
    if type(envelope) is not dict or type(envelope.get("data")) is not dict:
        raise BracketHold("HOLD: malformed grouped order ACK")
    statuses = envelope["data"].get("statuses")
    if type(statuses) is not list or len(statuses) != 3:
        raise BracketHold("HOLD: grouped ACK does not confirm 3 orders")
    entry_ack, take_ack, stop_ack = statuses
    entry_oid = _oid(entry_ack, "filled")
    tp_oid = _oid(take_ack, "resting")
    sl_oid = _oid(stop_ack, "resting")
    if len({entry_oid, tp_oid, sl_oid}) != 3:
        raise BracketHold("HOLD: duplicated exchange order ID")
    expected_size = _decimal(plan.orders[0]["sz"], "planned entry size")
    fill_info = entry_ack["filled"]
    # Without exact full fill acknowledgement, a partial IOC fill remains HOLD.
    filled_sz = _decimal(fill_info.get("totalSz"), "acknowledged entry size")
    if filled_sz != expected_size:
        raise BracketHold("HOLD: unknown or partial parent fill")
    # Restrict to exactly the expected 1x isolated perp position, and nothing else.
    if type(positions) is not list or len(positions) != 1:
        raise BracketHold("HOLD: missing or unexpected exchange position")
    container = positions[0]
    if type(container) is not dict or type(container.get("position")) is not dict:
        raise BracketHold("HOLD: malformed exchange position")
    p = container["position"]
    expected_signed = expected_size if plan.direction == "long" else -expected_size
    if p.get("coin") != plan.symbol:
        raise BracketHold("HOLD: unrelated open position")
    szi = p.get("szi")
    if type(szi) is not str or not re.fullmatch(r"-?(?:0|[1-9]\d*)(?:\.\d{1,8})?", szi):
        raise BracketHold("HOLD: invalid signed position size")
    if Decimal(szi) != expected_signed:
        raise BracketHold("HOLD: partial, flipped or unexpected position exposure")
    leverage = p.get("leverage")
    if type(leverage) is not dict or leverage.get("type") != "isolated" \
            or type(leverage.get("value")) is not int or leverage["value"] != 1:
        raise BracketHold("HOLD: position is not independently verified 1x isolated")
    _decimal(p.get("entryPx"), "exchange entry price")
    basic = _matching_oid_records(open_orders, "basic openOrders")
    rich = _matching_oid_records(frontend_open_orders, "frontendOpenOrders")
    if set(basic) != {tp_oid, sl_oid} or set(rich) != {tp_oid, sl_oid}:
        raise BracketHold("HOLD: missing, canceled, duplicate or additional open orders")
    reverse_side = "A" if plan.direction == "long" else "B"
    for oid, expected, kind in (
        (tp_oid, plan.orders[1], "Take Profit Market"),
        (sl_oid, plan.orders[2], "Stop Market")
    ):
        a, b = basic[oid], rich[oid]
        if (a.get("coin") != plan.symbol or b.get("coin") != plan.symbol
                or a.get("side") != reverse_side
                or b.get("side") != reverse_side):
            raise BracketHold("HOLD: wrong coin or protective order side")
        if (_decimal(a.get("sz"), "basic remaining protective size") != expected_size
                or _decimal(b.get("sz"), "frontend remaining protective size") != expected_size):
            raise BracketHold("HOLD: protective order is smaller, larger or partially filled")
        if (b.get("reduceOnly") is not True or b.get("isTrigger") is not True
                or b.get("orderType") != kind):
            raise BracketHold("HOLD: expected active reduce-only market trigger not observed")
        trigger_px = expected["order_type"]["trigger"]["triggerPx"]
        if _decimal(b.get("triggerPx"), "observed trigger") != _decimal(
                trigger_px, "expected trigger"):
            raise BracketHold("HOLD: stop or take-profit trigger mismatch")
        if b.get("origSz") is not None and _decimal(
                b["origSz"], "original protective size") != expected_size:
            raise BracketHold("HOLD: original protective size mismatch")
    return ProtectionObservation(
        status="MATCHED_OFFLINE_EVIDENCE_REVIEW_ONLY",
        reason=("Exact mock position and both TP/SL orders observed; still HOLD "
                "for durable fill reconciliation, signer security and operator approval"),
        entry_oid=entry_oid, take_profit_oid=tp_oid, stop_loss_oid=sl_oid,
    )
