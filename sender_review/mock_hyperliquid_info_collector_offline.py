"""NO NETWORK: simulated Hyperliquid /info response collector.

Consuming ONLY immutable scripted response bytes, this models a future
read-only process without running HTTP, importing Hyperliquid/executors,
opening sockets, reading keys or accessing databases. Its preview ALWAYS
returns HOLD, with no authenticated exchange or ownership evidence.

Payload shapes model documented Hyperliquid /info response examples, but
cannot establish real provider data completeness or a flat historical
baseline. Unknown/missing fields or ambiguous records HOLD conservatively.
"""
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
import json
import re

from sender_review.hyperliquid_readonly_collection_plan_offline import (
    ReadOnlyCollectorPlan,
    plan_offline_readonly_testnet_collection,
)

_COIN = re.compile(r"[A-Z][A-Z0-9]{0,23}\Z", re.ASCII)
_AMOUNT = re.compile(r"-?(?:0|[1-9][0-9]*)(?:\.[0-9]{1,12})?\Z", re.ASCII)
_CLOID = re.compile(r"0x[0-9a-f]{32}\Z", re.ASCII)
_EXPECTED = ("clearinghouseState", "openOrders", "historicalOrders",
             "userFillsByTime", "clearinghouseState")
_MAX_RESPONSE_BYTES = 262144
_MAX_HISTORY = 2000
_MAX_ITEMS = 2000


@dataclass(frozen=True)
class MockInfoReply:
    request_body_json: str
    status_code: int
    body: bytes


@dataclass(frozen=True)
class ScriptedMockInfoTransport:
    """Inert data container, NOT an injectable network transport."""
    replies: tuple[MockInfoReply, ...]
    network_enabled: bool = False
    exchange_calls: int = 0


@dataclass(frozen=True)
class MockCollectorReview:
    state: str = "HOLD"
    reason: str = "mock-only data; no authenticated provider or execution"
    fixture_consistent: bool = False
    fixture_counts: tuple[tuple[str, int], ...] = ()
    history_complete: bool = False
    provider_authenticated: bool = False
    account_ownership_verified: bool = False
    runtime_identity_authenticated: bool = False
    network_request_performed: bool = False
    exchange_order_permitted: bool = False
    close_authorized: bool = False
    retry_authorized: bool = False
    signing_enabled: bool = False


def _pairs_unique(pairs):
    output = {}
    for k, v in pairs:
        if k in output:
            raise ValueError("duplicate JSON key")
        output[k] = v
    return output


def _bad_constant(_):
    raise ValueError("NaN or infinity")


def _amount(value, *, signed=False):
    if type(value) is not str or len(value) > 40 or not _AMOUNT.fullmatch(value):
        return None
    try:
        n = Decimal(value)
    except (ValueError, InvalidOperation):
        return None
    if not n.is_finite() or abs(n) > 1000000000:
        return None
    if not signed and n <= 0:
        return None
    return n


def _oid(value):
    return type(value) is int and 0 < value <= 2**64 - 1


def _coin(value):
    return type(value) is str and _COIN.fullmatch(value) is not None


def _timestamp(value):
    return type(value) is int and 0 <= value <= 9007199254740991


def _parse_positions(doc):
    if type(doc) is not dict or type(doc.get("assetPositions")) is not list:
        raise ValueError("malformed clearinghouseState")
    if "time" in doc and not _timestamp(doc["time"]):
        raise ValueError("invalid position snapshot time")
    positions = {}
    for entry in doc["assetPositions"]:
        if type(entry) is not dict or type(entry.get("position")) is not dict:
            raise ValueError("invalid assetPosition")
        pos = entry["position"]
        coin, size = pos.get("coin"), _amount(pos.get("szi"), signed=True)
        if not _coin(coin) or size is None or coin in positions:
            raise ValueError("duplicate/bad signed position")
        positions[coin] = size
    return positions


def _parse_order(doc, *, nested):
    if nested:
        if type(doc) is not dict or type(doc.get("order")) is not dict:
            raise ValueError("missing order envelope")
        if doc.get("status") not in ("filled", "open", "canceled"):
            raise ValueError("unsettled/unknown order status")
        obj = doc["order"]
    else:
        obj = doc
    if type(obj) is not dict:
        raise ValueError("invalid order")
    oid, coin, side = obj.get("oid"), obj.get("coin"), obj.get("side")
    if not _oid(oid) or not _coin(coin) or side not in ("A", "B"):
        raise ValueError("invalid order id/side")
    if not _timestamp(obj.get("timestamp")):
        raise ValueError("invalid order timestamp")
    cloid = obj.get("cloid")
    if cloid is not None and (type(cloid) is not str
                              or not _CLOID.fullmatch(cloid)):
        raise ValueError("invalid CLOID")
    size = _amount(obj.get("origSz") if nested else obj.get("sz"))
    if size is None:
        raise ValueError("invalid order quantity")
    return (oid, coin, side, size, cloid)


def _parse_fills(doc, *, start_ms, end_ms):
    if type(doc) is not list or len(doc) > _MAX_HISTORY:
        raise ValueError("invalid/capped fills")
    fills, tids = {}, set()
    for fill in doc:
        if type(fill) is not dict:
            raise ValueError("invalid fill")
        oid, tid = fill.get("oid"), fill.get("tid")
        coin, side, time = fill.get("coin"), fill.get("side"), fill.get("time")
        size = _amount(fill.get("sz"))
        if (not _oid(oid) or not _oid(tid) or tid in tids
                or not _coin(coin) or side not in ("A", "B")
                or not _timestamp(time) or not start_ms <= time <= end_ms
                or size is None):
            raise ValueError("duplicate/malformed/out-of-range fill")
        tids.add(tid)
        fills.setdefault(oid, []).append((coin, side, size))
    return fills


def _safe_decompress_none(reply):
    if (type(reply) is not MockInfoReply
            or type(reply.status_code) is not int or reply.status_code != 200
            or type(reply.body) is not bytes
            or not 0 < len(reply.body) <= _MAX_RESPONSE_BYTES):
        raise ValueError("HTTP error, empty, oversized or non-byte response")
    return json.loads(
        reply.body.decode("utf-8"),
        object_pairs_hook=_pairs_unique,
        parse_constant=_bad_constant,
    )


def inspect_scripted_info_collection_offline(*, plan, transport):
    """Inspect fake response bytes, NEVER contact or authorize anything."""
    def hold(reason):
        return MockCollectorReview(reason=reason)

    if (type(plan) is not ReadOnlyCollectorPlan
            or type(transport) is not ScriptedMockInfoTransport
            or transport.network_enabled is not False
            or type(transport.exchange_calls) is not int
            or transport.exchange_calls != 0
            or type(transport.replies) is not tuple
            or plan.state != "HOLD" or not plan.queries):
        return hold("invalid mock plan or attempted transport activation")
    try:
        # A typed dataclass is not trusted input. Rebuild the entire query
        # plan from the pinned test account and validate every exact byte of
        # the canonical request envelopes, not merely their "type" fields.
        types = [json.loads(q.body_json)["type"] for q in plan.queries]
        if types not in (list(_EXPECTED),
                         list(_EXPECTED[:4]) + ["orderStatus", _EXPECTED[4]]):
            return hold("unexpected query sequence")
        if any(type(q.body_json) is not str for q in plan.queries):
            return hold("non-string request envelope")
        fills_selector = json.loads(plan.queries[3].body_json)
        if type(fills_selector) is not dict:
            return hold("invalid fills query")
        selected_oid = None
        if "orderStatus" in types:
            lookup = json.loads(plan.queries[4].body_json)
            if type(lookup) is not dict:
                return hold("invalid status query")
            selected_oid = lookup.get("oid")
        expected_plan = plan_offline_readonly_testnet_collection(
            account="0x" + "1" * 40,
            start_time_ms=fills_selector.get("startTime"),
            end_time_ms=fills_selector.get("endTime"),
            optional_order_lookup=selected_oid,
        )
        if not expected_plan.queries or plan.queries != expected_plan.queries:
            return hold("noncanonical account, request fields or query scope")
        if len(transport.replies) != len(types):
            return hold("missing/extra mock responses")
        docs = {}
        for q, reply, kind in zip(plan.queries, transport.replies, types):
            if (q.scheme != "https" or q.host != "api.hyperliquid-testnet.xyz"
                    or q.path != "/info" or q.method != "POST"
                    or q.content_type != "application/json"
                    or q.network_request_performed or q.contains_trading_key
                    or q.authorizes_order
                    or type(reply) is not MockInfoReply
                    or reply.request_body_json != q.body_json):
                return hold("request/response mismatch or unsafe request")
            doc = _safe_decompress_none(reply)
            docs.setdefault(kind, []).append(doc)
        positions_before = _parse_positions(docs["clearinghouseState"][0])
        positions_after = _parse_positions(docs["clearinghouseState"][1])
        if positions_before != positions_after:
            return hold("position snapshot changed during mock read")
        open_orders = docs["openOrders"][0]
        historical = docs["historicalOrders"][0]
        if (type(open_orders) is not list or len(open_orders) > _MAX_ITEMS
                or type(historical) is not list
                or len(historical) >= _MAX_HISTORY):
            return hold("invalid, capped or possibly truncated order history")
        if open_orders:
            # Even open orders outside the synthetic close target could
            # change account-wide exposure before a real decision.
            for obj in open_orders:
                _parse_order(obj, nested=False)
            return hold("outstanding orders require independent reconciliation")
        orders, cloids = {}, set()
        for item in historical:
            oid, coin, side, size, cloid = _parse_order(item, nested=True)
            if oid in orders or (cloid is not None and cloid in cloids):
                return hold("duplicate order ID or CLOID")
            if item["status"] != "filled":
                return hold("non-final historical order")
            orders[oid] = (coin, side, size, cloid)
            if cloid is not None:
                cloids.add(cloid)
        request = json.loads(plan.queries[3].body_json)
        fills = _parse_fills(
            docs["userFillsByTime"][0],
            start_ms=request["startTime"],
            end_ms=request["endTime"],
        )
        if len(docs["userFillsByTime"][0]) >= _MAX_HISTORY:
            return hold("fill result at provider cap; possible truncation")
        net, quantities = {}, {}
        for oid, entries in fills.items():
            if oid not in orders:
                return hold("fill references unknown/old/manual order")
            coin, side, limit_size, _ = orders[oid]
            for fcoin, fside, amount in entries:
                if fcoin != coin or fside != side:
                    return hold("order/fill coin or side conflict")
                quantities[oid] = quantities.get(oid, Decimal("0")) + amount
                net[coin] = net.get(coin, Decimal("0")) + (
                    amount if side == "B" else -amount
                )
            if quantities[oid] > limit_size:
                return hold("overfill inconsistent with order quantity")
        for oid, (_, _, size, _) in orders.items():
            if quantities.get(oid, Decimal("0")) != size:
                return hold("filled order missing fill records")
        for coin, amount in positions_after.items():
            if net.get(coin, Decimal("0")) != amount:
                return hold("position/fill net mismatch or absent baseline")
        if any(coin not in positions_after and amount != 0
               for coin, amount in net.items()):
            return hold("fill for unknown position")
        if "orderStatus" in docs:
            status_doc = docs["orderStatus"][0]
            if (type(status_doc) is not dict
                    or status_doc.get("status") != "order"
                    or type(status_doc.get("order")) is not dict
                    or status_doc["order"].get("status") != "filled"):
                return hold("missing/ambiguous individual order status")
            oid, coin, side, size, cloid = _parse_order(
                status_doc["order"], nested=True
            )
            selector = json.loads(plan.queries[4].body_json)["oid"]
            if (oid not in orders or orders[oid] != (coin, side, size, cloid)
                    or cloid != selector):
                return hold("order status/CLOID/historical mismatch")
        return MockCollectorReview(
            reason="synthetic JSON internally matches, but history and "
                   "exchange origin are NOT authenticated",
            fixture_consistent=True,
            fixture_counts=(("positions", len(positions_after)),
                            ("historicalOrders", len(historical)),
                            ("userFillsByTime", len(docs["userFillsByTime"][0]))),
        )
    except (KeyError, TypeError, ValueError, UnicodeError, OverflowError,
            InvalidOperation, IndexError):
        return hold("malformed, ambiguous or inconsistent simulated API response")
