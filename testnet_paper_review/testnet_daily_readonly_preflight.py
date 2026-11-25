"""Read-only Hyperliquid TESTNET account preflight for the Daily trial.

Strictly GETS PUBLIC INFO via POST /info. No exchange/signer/client SDK, secrets,
database writes or order submission. The script's final answer is always HOLD
or READY_FOR_REVIEW, and neither grants authority to trade.
This code must not be run or deployed without separate approval.
"""
import argparse
import http.client
import json
import ssl
import sys
import time

from testnet_paper_review.testnet_daily_admission_gate import (
    EXPECTED_ACCOUNT, EXPECTED_NETWORK, assess
)

HOST = "api.hyperliquid-testnet.xyz"
PATH = "/info"
MAX_BYTES = 512 * 1024
TIMEOUT_SECONDS = 8


class ReadOnlyError(RuntimeError):
    pass


def query_body(kind):
    if kind not in ("clearinghouseState", "openOrders", "frontendOpenOrders"):
        raise ReadOnlyError("HOLD: unapproved Testnet public /info request")
    return json.dumps(
        {"type": kind, "user": EXPECTED_ACCOUNT, "dex": ""},
        separators=(",", ":"), ensure_ascii=True
    ).encode("ascii")


def fetch_public_info(kind, *, connection_factory=None):
    """Exactly one bounded Testnet HTTPS request. No retries or redirects."""
    payload = query_body(kind)
    if connection_factory is None:
        connection_factory = lambda: http.client.HTTPSConnection(
            HOST, 443, context=ssl.create_default_context(), timeout=TIMEOUT_SECONDS
        )
    connection = connection_factory()
    try:
        connection.request(
            "POST", PATH, body=payload,
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json",
                "Connection": "close"
            },
        )
        response = connection.getresponse()
        if response.status != 200:
            raise ReadOnlyError("HOLD: Testnet /info HTTP error")
        length = response.getheader("Content-Length")
        if length is not None:
            if not length.isascii() or not length.isdecimal() or int(length) > MAX_BYTES:
                raise ReadOnlyError("HOLD: invalid Testnet response length")
        raw = response.read(MAX_BYTES + 1)
        if len(raw) > MAX_BYTES:
            raise ReadOnlyError("HOLD: oversized Testnet /info response")
        try:
            value = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, ValueError) as e:
            raise ReadOnlyError("HOLD: invalid Testnet JSON response") from e
        if kind == "clearinghouseState":
            if (type(value) is not dict
                    or type(value.get("assetPositions")) is not list
                    or len(value["assetPositions"]) > 1000
                    or type(value.get("marginSummary")) is not dict):
                raise ReadOnlyError("HOLD: malformed account state")
        else:
            if type(value) is not list or len(value) > 5000:
                raise ReadOnlyError("HOLD: malformed open-orders state")
        return value
    except (OSError, ssl.SSLError, http.client.HTTPException) as exc:
        raise ReadOnlyError("HOLD: Testnet public /info network failure") from exc
    finally:
        connection.close()


def _oid_index(rows, source):
    """Fail closed if an account order view is incomplete or ambiguous."""
    if type(rows) is not list:
        raise ReadOnlyError(f"HOLD: missing {source} view")
    indexed = {}
    for order in rows:
        if type(order) is not dict:
            raise ReadOnlyError(f"HOLD: malformed {source} order")
        oid = order.get("oid")
        if type(oid) is not int or oid <= 0 or oid in indexed:
            raise ReadOnlyError(f"HOLD: invalid or duplicated {source} order id")
        indexed[oid] = order
    return indexed


def verify_consistent_order_views(basic, detailed):
    """Compare account-wide /info order views; never authorize a trade."""
    a, b = _oid_index(basic, "openOrders"), _oid_index(detailed, "frontendOpenOrders")
    if set(a) != set(b):
        raise ReadOnlyError("HOLD: basic and detailed Testnet order views disagree")
    for oid in a:
        x, y = a[oid], b[oid]
        if (x.get("coin") != y.get("coin")
                or x.get("side") != y.get("side")
                or x.get("sz") != y.get("sz")):
            raise ReadOnlyError("HOLD: order coin/side/size views disagree")
        if (type(y.get("reduceOnly")) is not bool
                or type(y.get("isTrigger")) is not bool
                or type(y.get("orderType")) is not str
                or not y["orderType"]
                or type(y.get("triggerPx")) is not str):
            raise ReadOnlyError("HOLD: incomplete order protection metadata")
    return len(a)


def review_once(*, fetcher=fetch_public_info, clock=None):
    """Read three public snapshots then always require separate Daily signal approval."""
    if clock is None:
        clock = lambda: int(time.time())
    # Three bounded public /info reads; no signing or order submission.
    # An interrupted read is HOLD: never assume zero orders or positions.
    start = clock()
    state = fetcher("clearinghouseState")
    orders = fetcher("openOrders")
    detailed = fetcher("frontendOpenOrders")
    end = clock()
    if type(start) is not int or type(end) is not int or end - start > 15 or end < start:
        raise ReadOnlyError("HOLD: inconsistent/stale Testnet snapshot")
    verified_order_count = verify_consistent_order_views(orders, detailed)
    decision = assess(
        account=EXPECTED_ACCOUNT,
        network=EXPECTED_NETWORK,
        state=state,
        open_orders=orders,
        signal=None,  # deliberately no trading signal or authorization
        now_s=end,
        snapshot_at_s=start,
        notional_usdc="20",
        leverage=1,
    )
    return {
        "decision": decision,
        "positions": len(state["assetPositions"]),
        "open_orders": verified_order_count,
        "reduce_only_orders": sum(1 for item in detailed if item["reduceOnly"]),
        "stop_market_orders": sum(1 for item in detailed if item["orderType"] == "Stop Market" and item["reduceOnly"]),
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description="Public Testnet Daily account review (NO ORDERS)")
    parser.add_argument("--read-only-review", action="store_true")
    args = parser.parse_args(argv)
    if not args.read_only_review:
        print("HOLD: explicit read-only review required", file=sys.stderr)
        return 2
    try:
        result = review_once()
    except (ReadOnlyError, ValueError, KeyError, TypeError) as exc:
        print("HOLD: Testnet preflight failed closed", file=sys.stderr)
        return 2
    decision = result["decision"]
    print(f"TESTNET READ ONLY: positions={result['positions']}, "
          f"open_orders={result['open_orders']}, "
          f"reduce_only_orders={result['reduce_only_orders']}, "
          f"stop_market_orders={result['stop_market_orders']}; "
          f"{decision.status}; no trade authority")
    return 0 if decision.status in ("HOLD", "READY_FOR_REVIEW") else 2


if __name__ == "__main__":
    raise SystemExit(main())
