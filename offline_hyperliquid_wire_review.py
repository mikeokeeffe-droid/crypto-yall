"""Offline parsing checks for documented Hyperliquid /info response shapes.

NO network, SDK, credentials, order placement, DB writes, or authenticated
exchange access. Supplied response objects and request dictionaries are FAKE.
A 'parsed_untrusted' result is NOT proof of origin, complete history, no-fill,
ownership, or authorization to release a claim. Every ambiguity holds.

Source: official Hyperliquid docs, /for-developers/api/info-endpoint.
"""
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
import re


_ADDRESS = re.compile(r"0x[0-9a-fA-F]{40}\Z")
_TX_HASH = re.compile(r"0x[0-9a-fA-F]{64}\Z")


@dataclass(frozen=True)
class WireReview:
    status: str
    reason: str
    records: tuple = ()


def _hold(reason):
    return WireReview("hold", reason)


def _positive_amount(raw):
    if type(raw) is not str or not raw or raw.strip() != raw:
        return None
    try:
        value = Decimal(raw)
    except (InvalidOperation, ValueError):
        return None
    return value if value.is_finite() and value > 0 else None


def _valid_account(value):
    return type(value) is str and _ADDRESS.fullmatch(value) is not None


def _requested_for_account(request, *, kind, account):
    return (
        type(request) is dict
        and request.get("type") == kind
        and _valid_account(account)
        and request.get("user") == account
    )


def parse_order_status_offline(*, request, response, account, coin, oid,
                               direction, requested_size, submitted_at_ms):
    """Inspect one documented orderStatus response; never certify fills.

    The official 'sz' field is remaining size, NOT an independently verified
    filled-size receipt. In particular, status 'rejected' cannot by itself
    prove no fills or a globally flat account.
    """
    if (not _requested_for_account(request, kind="orderStatus", account=account)
            or type(oid) is not int or oid <= 0
            or request.get("oid") != oid or type(request.get("oid")) is not int
            or type(coin) is not str or not coin.isascii()
            or not coin.isalnum() or coin != coin.upper()
            or direction not in ("long", "short")
            or type(submitted_at_ms) is not int or submitted_at_ms <= 0
            or _positive_amount(requested_size) is None):
        return _hold("order query not bound to expected intent and account")
    if (type(response) is not dict
            or response.get("status") != "order"
            or type(response.get("order")) is not dict):
        return _hold("unknown or missing order status")
    wrapper = response["order"]
    raw = wrapper.get("order")
    if (type(raw) is not dict
            or wrapper.get("status") not in ("filled", "rejected")
            or type(raw.get("oid")) is not int or raw["oid"] != oid
            or raw.get("coin") != coin
            or raw.get("side") != ("B" if direction == "long" else "A")
            or raw.get("reduceOnly") is not False
            or type(raw.get("timestamp")) is not int
            or raw["timestamp"] < submitted_at_ms
            or type(wrapper.get("statusTimestamp")) is not int
            or wrapper["statusTimestamp"] < raw["timestamp"]
            or _positive_amount(raw.get("origSz")) !=
            _positive_amount(requested_size)
            or _positive_amount(raw.get("limitPx")) is None):
        return _hold("order identity, side, size or final status mismatched")
    # Never manufacture a 'final', 'complete', or 'filled_size' field.
    return WireReview(
        "parsed_untrusted", "structural orderStatus match; fills unverified",
        ((oid, wrapper["status"], raw["timestamp"],
          wrapper["statusTimestamp"]),),
    )


def parse_fills_by_time_offline(*, request, response, account,
                                start_ms, end_ms, cap=2000):
    """Inspect one userFillsByTime response, not its historical completeness.

    The docs specify inclusive startTime/endTime, max 2000 results/response,
    and last 10000 fills retained. Even a short or empty page is NOT proof
    that all earlier history was available. This function NEVER says complete.
    """
    if (not _requested_for_account(
                request, kind="userFillsByTime", account=account)
            or type(start_ms) is not int or type(end_ms) is not int
            or start_ms <= 0 or end_ms < start_ms
            or type(request.get("startTime")) is not int
            or type(request.get("endTime")) is not int
            or request.get("startTime") != start_ms
            or request.get("endTime") != end_ms
            or request.get("aggregateByTime") is not False
            or type(cap) is not int or not 1 <= cap <= 2000):
        return _hold("fill query scope is not pinned")
    if type(response) is not list or len(response) >= cap:
        return _hold("invalid or saturated fill page; history may be truncated")

    result = []
    seen = set()
    for fill in response:
        if type(fill) is not dict:
            return _hold("malformed fill")
        coin = fill.get("coin")
        oid = fill.get("oid")
        tid = fill.get("tid")
        time = fill.get("time")
        side = fill.get("side")
        # Perp-only subset. An unrecognised/spot fill requires manual review.
        if (type(coin) is not str or not coin.isascii()
                or not coin.isalnum() or coin != coin.upper()
                or type(oid) is not int or oid <= 0
                or type(tid) is not int or tid <= 0
                or type(time) is not int or not start_ms <= time <= end_ms
                or side not in ("A", "B")
                or type(fill.get("dir")) is not str or not fill["dir"]
                or type(fill.get("hash")) is not str
                or not _TX_HASH.fullmatch(fill["hash"])
                or _positive_amount(fill.get("sz")) is None
                or _positive_amount(fill.get("px")) is None):
            return _hold("fill identity, type or requested time mismatched")
        if tid in seen:
            return _hold("repeated exchange trade id")
        seen.add(tid)
        result.append((coin, oid, tid, time, side, fill["dir"],
                       str(_positive_amount(fill["sz"]))))
    # Other coins and orders are kept, not silently filtered out.
    # Two different tids on the SAME millisecond are valid distinct fills.
    return WireReview(
        "parsed_untrusted",
        "one raw fill window parsed; history completeness and source unverified",
        tuple(result),
    )
