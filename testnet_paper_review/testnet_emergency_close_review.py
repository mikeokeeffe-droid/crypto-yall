"""Offline-only emergency close plan for a missing SOL Testnet stop.

Produces ONE reduce-only SOL IOC limit close order; cannot submit it.
Conservative fixed 3% slippage bound, full remaining position, independent
account/order snapshots, 1x isolated, exact original reviewed plan. A limit
IOC might not fill; it cannot guarantee a stop, recovery or maximum loss.
Unexpected orders/positions => HOLD for human intervention.
"""
from dataclasses import dataclass
from decimal import Decimal
import hashlib
import re

from testnet_paper_review.offline_daily_bracket_plan import (
    OfflineBracketPlan, _price
)
from testnet_paper_review.testnet_daily_admission_gate import (
    EXPECTED_ACCOUNT, EXPECTED_NETWORK
)
from testnet_paper_review.testnet_daily_readonly_preflight import (
    verify_consistent_order_views, ReadOnlyError
)

SIZE = re.compile(r"(?:0|[1-9]\d*)(?:\.\d{1,8})?\Z")
SIGNED_SIZE = re.compile(r"-?(?:0|[1-9]\d*)(?:\.\d{1,8})?\Z")
REQ = re.compile(r"[a-z0-9][a-z0-9-]{7,63}\Z")
SLIPPAGE = Decimal("0.03")


class EmergencyHold(ValueError):
    pass


@dataclass(frozen=True)
class EmergencyCloseReview:
    account: str
    network: str
    request_id: str
    close_order: dict
    observed_position_size: str
    missing_stop: bool
    status: str = "REVIEW_ONLY_UNPROTECTED_TESTNET_SOL_HOLD"

    @property
    def may_send(self):
        return False


def review_missing_stop_close(*, plan, request_id, state, open_orders,
                              frontend_open_orders, mid_price,
                              size_decimals, px_decimals, account,
                              network, snapshot_at_s, now_s):
    """Reject mixed ownership and propose only a bounded reduce-only close."""
    if type(plan) is not OfflineBracketPlan or plan.permits_submission \
            or plan.symbol != "SOL" or plan.grouping != "normalTpsl":
        raise EmergencyHold("HOLD: invalid one-shot Testnet bracket")
    if (type(account) is not str or account.lower() != EXPECTED_ACCOUNT.lower()
            or network != EXPECTED_NETWORK
            or plan.account.lower() != EXPECTED_ACCOUNT.lower()):
        raise EmergencyHold("HOLD: emergency plan must be on pinned TESTNET owner")
    if type(request_id) is not str or not REQ.fullmatch(request_id):
        raise EmergencyHold("HOLD: invalid original request identity")
    if (type(now_s) is not int or type(snapshot_at_s) is not int
            or not 0 <= now_s-snapshot_at_s <= 5):
        raise EmergencyHold("HOLD: stale live exposure evidence")
    if (type(size_decimals) is not int or not 0 <= size_decimals <= 5
            or type(px_decimals) is not int
            or not 0 <= px_decimals <= 6-size_decimals):
        raise EmergencyHold("HOLD: unknown SOL Testnet size/price precision")
    if type(state) is not dict or type(state.get("assetPositions")) is not list \
            or len(state["assetPositions"]) != 1:
        raise EmergencyHold("HOLD: missing/foreign or multiple positions")
    pos = state["assetPositions"][0]
    if type(pos) is not dict or type(pos.get("position")) is not dict:
        raise EmergencyHold("HOLD: malformed SOL position")
    p = pos["position"]
    if p.get("coin") != "SOL" or type(p.get("szi")) is not str \
            or not SIGNED_SIZE.fullmatch(p["szi"]):
        raise EmergencyHold("HOLD: unexpected SOL position")
    size = Decimal(p["szi"])
    if size == 0 or (size > 0) != (plan.direction == "long") \
            or plan.direction not in ("long","short"):
        raise EmergencyHold("HOLD: position flipped or flat")
    lev = p.get("leverage")
    if type(lev) is not dict or lev.get("type") != "isolated" \
            or type(lev.get("value")) is not int or lev["value"] != 1:
        raise EmergencyHold("HOLD: unknown 1x isolated risk state")
    entry_qty = Decimal(plan.orders[0]["sz"])
    if abs(size) > entry_qty or size.as_tuple().exponent < -size_decimals:
        raise EmergencyHold("HOLD: increased size or invalid SOL lot")
    if type(mid_price) is not str or not SIZE.fullmatch(mid_price):
        raise EmergencyHold("HOLD: invalid midpoint quote")
    mid = Decimal(mid_price)
    if not Decimal("1") <= mid <= Decimal("10000"):
        raise EmergencyHold("HOLD: unknown SOL market quote")
    try:
        verify_consistent_order_views(open_orders, frontend_open_orders)
    except (ReadOnlyError, ValueError, TypeError) as exc:
        raise EmergencyHold("HOLD: inconsistent Testnet order views") from exc
    if len(frontend_open_orders) > 1:
        raise EmergencyHold("HOLD: unexpected multiple outstanding orders")
    reverse = "A" if size > 0 else "B"
    # Do not parse arbitrary exchange fields with Decimal directly: invalid,
    # non-string or non-finite values must HOLD with no constructed close.
    expected_price = plan.orders[1]["order_type"]["trigger"]["triggerPx"]
    if type(expected_price) is not str or not SIZE.fullmatch(expected_price):
        raise EmergencyHold("HOLD: invalid original take-profit trigger")
    expected_tp = Decimal(expected_price)
    if expected_tp <= 0:
        raise EmergencyHold("HOLD: invalid original take-profit price")
    for row in frontend_open_orders:
        if type(row) is not dict:
            raise EmergencyHold("HOLD: malformed outstanding order")
        seen_price = row.get("triggerPx")
        if (row.get("coin") != "SOL" or row.get("side") != reverse
                or row.get("reduceOnly") is not True
                or row.get("isTrigger") is not True
                or row.get("orderType") != "Take Profit Market"
                or type(seen_price) is not str
                or not SIZE.fullmatch(seen_price)
                or Decimal(seen_price) != expected_tp
                or Decimal(seen_price) <= 0):
            raise EmergencyHold("HOLD: unknown order or stop still present")
    # No matching stop seen in either consistent account-wide public view.
    # Never cancel protective orders before verifying the position is flat.
    is_buy = size < 0
    price = _price(mid * (1+SLIPPAGE if is_buy else 1-SLIPPAGE),
                   decimals=px_decimals, round_up=is_buy)
    # 3% is a LIMIT bound, not a promised fill or maximum loss.
    cloid = "0x"+hashlib.sha256(
        f"testnet-emergency:{account.lower()}:{request_id}:{plan.orders[0]['sz']}"
        .encode("ascii")).hexdigest()[:32]
    close = {
        "coin":"SOL",
        "is_buy":is_buy,
        "sz":format(abs(size),"f"),
        "limit_px":price,
        "order_type":{"limit":{"tif":"Ioc"}},
        "reduce_only":True,
        "cloid":cloid,
    }
    return EmergencyCloseReview(
        account=EXPECTED_ACCOUNT,network=EXPECTED_NETWORK,
        request_id=request_id,close_order=close,
        observed_position_size=format(size,"f"),missing_stop=True,
    )
