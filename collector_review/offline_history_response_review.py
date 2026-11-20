"""Validate untrusted, caller-supplied Hyperliquid history RESPONSE bytes.

This is a PURE OFFLINE companion to offline_history_query_plan.py. It never
calls HTTPS, sockets, signer, SQL or the original bot modules, and never
authenticates an exchange origin. A valid response is a FIXTURE ONLY:
  * orderStatus can be missing, non-final, or lack independently bound OID.
  * userFillsByTime is capped at 2000 and retains only recent 10000 fills.
  * funding windows can paginate and cannot prove the prior opening baseline.
A positive shape check cannot establish empty history, exclusive ownership,
reduce-only close rights, order authorization or permission to retry.

Docs: https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/info-endpoint
and /info-endpoint/perpetuals (reviewed 2026-11-14).
"""
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
import hashlib
import json
import re

from collector_review.offline_history_query_plan import (
    OfflineHistoryQueryPlan, OfflineHistoryQueryScope,
    plan_testnet_history_query_offline,
)

_SHA256_BYTES_LIMIT = 262144
_TX_HASH = re.compile(r"0x[0-9a-f]{64}\Z", re.ASCII)
_CLOID = re.compile(r"0x[0-9a-f]{32}\Z", re.ASCII)
_COIN = re.compile(r"[A-Z][A-Z0-9]{0,23}\Z", re.ASCII)
_DECIMAL = re.compile(r"-?(?:0|[1-9]\d*)(?:\.\d+)?\Z", re.ASCII)
_FUNDING_PAGE_CAP = 500
_FILLS_PAGE_CAP = 2000
_ORDER_STATUSES = frozenset((
    "open", "filled", "canceled", "triggered", "rejected",
    "marginCanceled", "reduceOnlyCanceled", "selfTradeCanceled",
    "minTradeNtlRejected", "perpMarginRejected",
    "marketOrderNoLiquidityRejected", "liquidatedCanceled",
    "scheduledCancel", "tickRejected",
))


@dataclass(frozen=True)
class OfflineHistoryResponseReview:
    state: str = "hold"
    reason: str = "history capture unverified"
    request_sha256: str | None = None
    response_sha256: str | None = None
    record_count: int | None = None
    origin_authenticated: bool = False
    history_complete: bool = False
    ownership_verified: bool = False
    close_authorized: bool = False
    submit_authorized: bool = False


def _unique_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _reject_constant(_):
    raise ValueError("non-finite JSON")


def _number(value, *, positive=False):
    if type(value) is not str or _DECIMAL.fullmatch(value) is None:
        return False
    try:
        d = Decimal(value)
    except (InvalidOperation, ValueError):
        return False
    return d.is_finite() and (not positive or d > 0)


def _uid(value):
    return type(value) is int and 0 < value <= (2**64 - 1)


def _timestamp(value):
    return type(value) is int and value > 0


def _order_status(payload, oid):
    if (type(payload) is not dict or payload.get("status") != "order"
            or type(payload.get("order")) is not dict):
        return False
    record = payload["order"]
    order = record.get("order")
    if (type(order) is not dict
            or record.get("status") not in _ORDER_STATUSES
            or not _timestamp(record.get("statusTimestamp"))
            or not _uid(order.get("oid"))
            or type(order.get("coin")) is not str
            or _COIN.fullmatch(order["coin"]) is None
            or order.get("side") not in ("A", "B")
            or not _timestamp(order.get("timestamp"))
            or not _number(order.get("origSz"), positive=True)
            or not _number(order.get("sz"))
            or not _number(order.get("limitPx"), positive=True)
            or type(order.get("reduceOnly")) is not bool):
        return False
    # "sz" is remaining order quantity, not a signed position delta.
    # A stale/malformed response must never show more unfilled than
    # originally requested, nor a status predating its own order.
    original = Decimal(order["origSz"])
    remaining = Decimal(order["sz"])
    if (remaining < 0 or remaining > original
            or record["statusTimestamp"] < order["timestamp"]
            or (record["status"] == "filled" and remaining != 0)):
        return False
    cloid = order.get("cloid")
    if cloid is not None and (
            type(cloid) is not str or _CLOID.fullmatch(cloid) is None):
        return False
    # A queried CLOID must be present in the result, never inferred from a
    # returned OID or unrelated stored local-intent identifier.
    if type(oid) is str:
        return cloid == oid
    return order["oid"] == oid


def _fills(payload, start, end):
    if type(payload) is not list or len(payload) >= _FILLS_PAGE_CAP:
        # A saturated page may have unseen same-millisecond fills.
        return False
    seen_tid = set()
    for item in payload:
        if (type(item) is not dict
                or type(item.get("coin")) is not str
                or _COIN.fullmatch(item["coin"]) is None
                or not _uid(item.get("oid"))
                or not _uid(item.get("tid"))
                or item["tid"] in seen_tid
                or not _timestamp(item.get("time"))
                or not start <= item["time"] <= end
                or item.get("side") not in ("A", "B")
                or type(item.get("dir")) is not str
                or not 0 < len(item["dir"]) <= 64
                or type(item.get("crossed")) is not bool
                or not _number(item.get("sz"), positive=True)
                or not _number(item.get("px"), positive=True)
                or not _number(item.get("startPosition"))
                or not _number(item.get("closedPnl"))
                or not _number(item.get("fee"))
                or type(item.get("feeToken")) is not str
                or not 0 < len(item["feeToken"]) <= 32
                or type(item.get("hash")) is not str
                or _TX_HASH.fullmatch(item["hash"]) is None):
            return False
        if ("cloid" in item
                and (type(item["cloid"]) is not str
                     or _CLOID.fullmatch(item["cloid"]) is None)):
            return False
        seen_tid.add(item["tid"])
    return True


def _funding(payload, start, end):
    if type(payload) is not list or len(payload) >= _FUNDING_PAGE_CAP:
        return False
    seen = set()
    for item in payload:
        if (type(item) is not dict
                or not _timestamp(item.get("time"))
                or not start <= item["time"] <= end
                or type(item.get("hash")) is not str
                or _TX_HASH.fullmatch(item["hash"]) is None
                or type(item.get("delta")) is not dict):
            return False
        delta = item["delta"]
        if (delta.get("type") != "funding"
                or type(delta.get("coin")) is not str
                or _COIN.fullmatch(delta["coin"]) is None
                or not _number(delta.get("usdc"))
                or not _number(delta.get("szi"))
                or not _number(delta.get("fundingRate"))
                or ("nSamples" in delta
                    and delta["nSamples"] is not None
                    and (type(delta["nSamples"]) is not int
                         or delta["nSamples"] < 0))):
            return False
        # Repeated same-coin funding update for one exact chain transaction
        # may be legitimate in unusual cases; hold rather than guessing.
        identity = (item["hash"], item["time"], delta["coin"])
        if identity in seen:
            return False
        seen.add(identity)
    return True


def inspect_history_fixture_response_offline(
    *, plan, pinned_scope, pinned_request_type,
    pinned_oid=None, pinned_start_ms=None, pinned_end_ms=None,
    raw_body, status_code, content_type, content_encoding=None,
):
    """Check fixture bytes against INDEPENDENTLY pinned request criteria.

    The caller must supply the expected scope, operation, order identifier or
    exact time bounds from a separately reviewed configuration; they cannot
    be inferred from the untrusted response or the received plan itself.
    This pure offline test cannot verify that the caller actually obtained
    those pins independently. Neither a match nor a digest authenticates the
    exchange, completes account history, or grants any trading authority.
    """
    held = OfflineHistoryResponseReview()
    if (type(pinned_scope) is not OfflineHistoryQueryScope
            or type(pinned_request_type) is not str):
        return held
    expected = plan_testnet_history_query_offline(
        scope=pinned_scope, request_type=pinned_request_type,
        oid=pinned_oid, start_ms=pinned_start_ms,
        end_ms=pinned_end_ms,
    )
    if (expected.state != "plan_only" or plan != expected):
        return held
    if (type(plan) is not OfflineHistoryQueryPlan
            or plan.state != "plan_only"
            or plan.network_authorized or plan.transport_verified
            or plan.origin_authenticated
            or type(plan.request_body) is not bytes
            or type(plan.request_type) is not str
            or type(status_code) is not int or status_code != 200
            or type(content_type) is not str
            or content_type.split(";", 1)[0].strip().lower() != "application/json"
            or content_encoding not in (None, "", "identity")
            or type(raw_body) is not bytes
            or not 0 < len(raw_body) <= _SHA256_BYTES_LIMIT):
        return held
    try:
        req = json.loads(plan.request_body, object_pairs_hook=_unique_pairs)
        if (req.get("user") != pinned_scope.account
                or req.get("type") != pinned_request_type
                or plan.request_body != expected.request_body):
            return held
        payload = json.loads(
            raw_body.decode("utf-8"), object_pairs_hook=_unique_pairs,
            parse_constant=_reject_constant,
        )
        if plan.request_type == "orderStatus":
            valid = _order_status(payload, req["oid"])
            count = 1
        elif plan.request_type == "userFillsByTime":
            valid = _fills(payload, req["startTime"], req["endTime"])
            count = len(payload) if type(payload) is list else None
        elif plan.request_type == "userFunding":
            valid = _funding(payload, req["startTime"], req["endTime"])
            count = len(payload) if type(payload) is list else None
        else:
            return held
    except (UnicodeError, ValueError, TypeError, KeyError, AttributeError):
        return held
    if not valid:
        return held
    return OfflineHistoryResponseReview(
        state="fixture_only",
        reason="synthetic response shape consistent; actual TLS origin, "
               "coverage, history completeness and ownership UNVERIFIED",
        request_sha256=hashlib.sha256(plan.request_body).hexdigest(),
        response_sha256=hashlib.sha256(raw_body).hexdigest(),
        record_count=count,
    )
