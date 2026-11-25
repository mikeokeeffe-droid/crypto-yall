"""SOL TESTNET one-shot protected-order *plan*, strictly offline.

This defines the Python SDK normalTpsl parent + attached TP/SL structure,
but deliberately provides NO exchange call, signing, key, network or workflow.
The plan is a REVIEW FIXTURE, NOT an executable order or authorization.
Fail-closed admission is reused from testnet_daily_admission_gate.
Official SDK example: hyperliquid-python-sdk/examples/basic_tpsl.py.
"""
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, ROUND_DOWN, ROUND_UP
import re

from testnet_paper_review.testnet_daily_admission_gate import (
    assess, EXPECTED_ACCOUNT, EXPECTED_NETWORK, MIN_NOTIONAL, MAX_NOTIONAL
)

GROUPING = "normalTpsl"
TEST_COIN = "SOL"
MAX_LEVERAGE = 1
REFERENCE_MIN = Decimal("1")
REFERENCE_MAX = Decimal("10000")
MIN_SL_PCT = Decimal("0.01")
TP_PCT = Decimal("0.02")
SL_PCT = Decimal("0.01")
AGGRESSIVE_ENTRY_PCT = Decimal("0.005")


class BracketHold(ValueError):
    pass


@dataclass(frozen=True)
class OfflineBracketPlan:
    grouping: str
    symbol: str
    account: str
    direction: str
    orders: tuple[dict, dict, dict]
    effective_notional: str
    reference_price: str
    status: str = "HOLD_OFFLINE_REVIEW_ONLY"

    @property
    def permits_submission(self):
        return False


def _decimal(text, label):
    if type(text) is not str or not re.fullmatch(r"(?:0|[1-9][0-9]*)(?:\.[0-9]{1,8})?", text):
        raise BracketHold(f"HOLD: invalid {label}")
    try:
        value = Decimal(text)
    except InvalidOperation as exc:
        raise BracketHold(f"HOLD: invalid {label}") from exc
    if not value.is_finite() or value <= 0:
        raise BracketHold(f"HOLD: nonpositive or nonfinite {label}")
    return value


def _price(value, *, decimals, round_up):
    # Hyperliquid perp prices require at most 5 significant figures AND
    # at most (6 - szDecimals) decimal places. Retaining extra figures in a
    # protective stop can make the whole grouped submission invalid.
    # A price above 1 may require FEWER decimals than metadata alone permits.
    allowable_decimals = min(decimals, 4 - value.adjusted())
    q = Decimal(1).scaleb(-allowable_decimals)
    out = value.quantize(q, rounding=ROUND_UP if round_up else ROUND_DOWN)
    if not out.is_finite() or out <= 0:
        raise BracketHold("HOLD: invalid rounded price")
    # Hyperliquid price serialization has additional restrictions. We only
    # emit review fixtures here; an actual adapter must verify asset metadata.
    return format(out, "f")


def compose_mock_bracket(*, account, network, state, open_orders, signal,
                         now_s, snapshot_at_s, mid_price, notional_usdc="20",
                         leverage=1, size_decimals=2, px_decimals=2):
    """Compose exactly 3 synthetic orders ONLY after pure admission review."""
    result = assess(
        account=account, network=network, state=state, open_orders=open_orders,
        signal=signal, now_s=now_s, snapshot_at_s=snapshot_at_s,
        notional_usdc=notional_usdc, leverage=leverage
    )
    if result.status != "READY_FOR_REVIEW":
        raise BracketHold(f"HOLD: Daily account admission failed: {result.reason}")
    if result.allows_order:
        raise BracketHold("HOLD: admission review cannot confer order authority")
    if type(size_decimals) is not int or not 0 <= size_decimals <= 5:
        raise BracketHold("HOLD: size precision not independently reviewed")
    if type(px_decimals) is not int or not 0 <= px_decimals <= (6 - size_decimals):
        raise BracketHold("HOLD: price precision not independently reviewed")
    reference = _decimal(mid_price, "market reference price")
    amount = _decimal(notional_usdc, "notional")
    if not REFERENCE_MIN <= reference <= REFERENCE_MAX:
        raise BracketHold("HOLD: reference price outside simulation range")
    if not MIN_NOTIONAL <= amount <= MAX_NOTIONAL:
        raise BracketHold("HOLD: order notional outside $12-$25 bounds")
    if type(leverage) is not int or leverage != 1:
        raise BracketHold("HOLD: leverage not exactly 1x")
    action = signal.get("action")
    is_buy = action == "buy"
    if action not in ("buy", "enter_short"):
        raise BracketHold("HOLD: no entry signal")
    qty_quantum = Decimal(1).scaleb(-size_decimals)
    # Compute the aggressive IOC limit before sizing the order. Capping only
    # at mid-quote can exceed the user's approved amount for a long entry.
    entry_px = _price(
        reference * (1 + AGGRESSIVE_ENTRY_PCT if is_buy else 1 - AGGRESSIVE_ENTRY_PCT),
        decimals=px_decimals, round_up=is_buy,
    )
    entry_limit = Decimal(entry_px)
    qty = (amount / entry_limit).quantize(qty_quantum, rounding=ROUND_DOWN)
    if qty <= 0:
        raise BracketHold("HOLD: rounded size is zero")
    effective = entry_limit * qty
    if not MIN_NOTIONAL <= effective <= MAX_NOTIONAL:
        raise BracketHold("HOLD: rounded worst-case entry exceeds notional bounds")
    tp_px = _price(
        reference * (1 + TP_PCT if is_buy else 1 - TP_PCT),
        decimals=px_decimals, round_up=is_buy
    )
    sl_px = _price(
        reference * (1 - SL_PCT if is_buy else 1 + SL_PCT),
        decimals=px_decimals, round_up=not is_buy
    )
    tp = Decimal(tp_px)
    sl = Decimal(sl_px)
    if not (sl < reference < tp if is_buy else tp < reference < sl):
        raise BracketHold("HOLD: protective price orientation is invalid")
    # Each child is an opposite-side REDUCE-ONLY market trigger. The grouping
    # is critical: do not send an entry without attached exits.
    def order(*, side, px, order_type, reduce):
        return {
            "coin": TEST_COIN, "is_buy": side,
            "sz": format(qty, "f"), "limit_px": px,
            "order_type": order_type, "reduce_only": reduce,
        }
    entry = order(
        side=is_buy, px=entry_px,
        order_type={"limit": {"tif": "Ioc"}}, reduce=False
    )
    take = order(
        side=not is_buy, px=tp_px,
        order_type={"trigger": {
            "triggerPx": tp_px, "isMarket": True, "tpsl": "tp"
        }}, reduce=True
    )
    stop = order(
        side=not is_buy, px=sl_px,
        order_type={"trigger": {
            "triggerPx": sl_px, "isMarket": True, "tpsl": "sl"
        }}, reduce=True
    )
    return OfflineBracketPlan(
        grouping=GROUPING, symbol=TEST_COIN, account=EXPECTED_ACCOUNT,
        direction="long" if is_buy else "short",
        orders=(entry, take, stop),
        effective_notional=format(effective, "f"),
        reference_price=format(reference, "f"),
    )


def review_exchange_reply(*, response, actual_positions, actual_open_orders,
                          plan: OfflineBracketPlan):
    """Reject any unverified parent/TP/SL response; NEVER clears HOLD.

    Even a syntactically valid response is not enough: read-only reconciled
    fills and BOTH reduce-only stop orders are required in a future sender.
    This function intentionally has no result that authorizes another order.
    """
    if type(plan) is not OfflineBracketPlan or plan.permits_submission:
        raise BracketHold("HOLD: invalid offline plan")
    if type(response) is not dict or response.get("status") != "ok":
        raise BracketHold("HOLD: unknown/rejected grouped exchange response")
    payload = response.get("response")
    if type(payload) is not dict:
        raise BracketHold("HOLD: missing grouped response payload")
    data = payload.get("data")
    if type(data) is not dict:
        raise BracketHold("HOLD: missing grouped response data")
    statuses = data.get("statuses")
    if type(statuses) is not list or len(statuses) != 3:
        raise BracketHold("HOLD: incomplete grouped order acknowledgments")
    if any(type(status) is not dict or not ({"filled", "resting"} & status.keys())
           or "error" in status for status in statuses):
        raise BracketHold("HOLD: unexpected fill/trigger status")
    if type(actual_positions) is not list or type(actual_open_orders) is not list:
        raise BracketHold("HOLD: unknown independent position/order observations")
    # A working sender needs exact oid/cloid/size/price/reduceOnly reconciliation.
    # Deliberately do not make that determination from this mock function.
    return "HOLD: bracket response shaped plausibly; independent exchange reconciliation and manual approval still required"
