"""Strict, offline-only characterization of a single Hyperliquid order response.

No SDK, exchange access, credentials, database writes, or live integration.
Even an accepted structural fill is untrusted and NEVER grants entry/release.
"""
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

@dataclass(frozen=True)
class StrictFillReview:
    status: str
    reason: str
    oid: int = 0
    size: str = ""
    price: str = ""

def _positive_decimal(raw):
    if type(raw) not in (str, int):
        return None
    if type(raw) is str and (not raw or raw.strip() != raw):
        return None
    try:
        number = Decimal(raw)
    except (InvalidOperation, ValueError):
        return None
    return number if number.is_finite() and number > 0 else None

def inspect_market_order_response_offline(*, response, expected_oid=None,
                                          requested_size=None):
    """Parse only one positive fill; otherwise HOLD, including resting orders.

    The caller must independently establish the account, environment, order
    identity, and authentic provenance. This function cannot establish them.
    """
    def hold(reason):
        return StrictFillReview("hold", reason)
    if type(response) is not dict or response.get("status") != "ok":
        return hold("missing or unsuccessful exchange response")
    wrapper = response.get("response")
    if type(wrapper) is not dict or wrapper.get("type") != "order":
        return hold("unexpected exchange response type")
    data = wrapper.get("data")
    if type(data) is not dict or type(data.get("statuses")) is not list:
        return hold("missing order status array")
    statuses = data["statuses"]
    if len(statuses) != 1 or type(statuses[0]) is not dict:
        return hold("ambiguous or multiple order statuses")
    fill = statuses[0].get("filled")
    if type(fill) is not dict or len(statuses[0]) != 1:
        return hold("not a single confirmed structural fill")
    oid = fill.get("oid")
    size = _positive_decimal(fill.get("totalSz"))
    price = _positive_decimal(fill.get("avgPx"))
    if type(oid) is not int or oid <= 0 or size is None or price is None:
        return hold("invalid order id, fill size, or price")
    if expected_oid is not None and (type(expected_oid) is not int or expected_oid != oid):
        return hold("order id mismatch")
    if requested_size is not None:
        requested = _positive_decimal(requested_size)
        if requested is None or size > requested:
            return hold("invalid requested size or overfill")
    return StrictFillReview("parsed_untrusted",
                            "structural fill only; provenance and ownership unverified",
                            oid, str(size), str(price))
