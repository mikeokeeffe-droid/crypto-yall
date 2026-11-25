"""Read-only TESTNET public SOL metadata and midpoint probe.

NO signers, trading SDK, keys, order endpoints, Mainnet fallback or trading
authority. This diagnostic fetches exactly two public /info methods:
meta (perpetual lot precision) and allMids (SOL market reference price).
It does NOT establish executable order permissions or price freshness for
automatic trading, and may not be relied upon for an order without a separate
post-lock live snapshot and independent security approval.
"""
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
import http.client
import json
import re
import ssl
import time

HOST = "api.hyperliquid-testnet.xyz"
PATH = "/info"
COIN = "SOL"
MAX_BYTES = 512 * 1024
TIMEOUT_SECONDS = 8
MAX_SPAN_SECONDS = 10


class MarketReadHold(ValueError):
    pass


@dataclass(frozen=True)
class SolTestnetMarketReview:
    symbol: str
    mid_price: str
    size_decimals: int
    max_price_decimals: int
    observed_at_s: int
    status: str = "READ_ONLY_REVIEW_HOLD"

    @property
    def allows_trading(self):
        return False


def query_body(kind):
    if kind not in ("meta", "allMids"):
        raise MarketReadHold("HOLD: only TESTNET meta/allMids public reads allowed")
    return json.dumps({"type": kind, "dex": ""},
                      separators=(",", ":"), ensure_ascii=True).encode("ascii")


def fetch_public_market(kind, *, connection_factory=None):
    payload = query_body(kind)
    if connection_factory is None:
        connection_factory = lambda: http.client.HTTPSConnection(
            HOST, 443, context=ssl.create_default_context(),
            timeout=TIMEOUT_SECONDS,
        )
    conn = connection_factory()
    try:
        conn.request("POST", PATH, body=payload, headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Connection": "close",
        })
        response = conn.getresponse()
        if response.status != 200:
            raise MarketReadHold("HOLD: Testnet market /info rejected")
        header = response.getheader("Content-Length")
        if header is not None:
            if not re.fullmatch(r"[0-9]+", header) or int(header) > MAX_BYTES:
                raise MarketReadHold("HOLD: oversized or malformed market response length")
        payload = response.read(MAX_BYTES + 1)
        if len(payload) > MAX_BYTES:
            raise MarketReadHold("HOLD: oversized Testnet market response")
        try:
            result = json.loads(payload.decode("utf-8"))
        except (ValueError, UnicodeDecodeError) as exc:
            raise MarketReadHold("HOLD: malformed Testnet market JSON") from exc
        if type(result) is not dict:
            raise MarketReadHold("HOLD: unexpected Testnet market response type")
        return result
    except (OSError, ssl.SSLError, http.client.HTTPException) as exc:
        raise MarketReadHold("HOLD: Testnet-only market read failed") from exc
    finally:
        conn.close()


def _positive_decimal(value, label):
    if type(value) is not str or not re.fullmatch(
            r"(?:0|[1-9]\d*)(?:\.\d{1,8})?", value):
        raise MarketReadHold(f"HOLD: malformed {label}")
    try:
        d = Decimal(value)
    except InvalidOperation as exc:
        raise MarketReadHold(f"HOLD: invalid {label}") from exc
    if not d.is_finite() or d <= 0:
        raise MarketReadHold(f"HOLD: invalid nonpositive {label}")
    return d


def inspect_sol_market(*, meta, mids, start_s, finish_s):
    if type(start_s) is not int or type(finish_s) is not int \
            or not 0 <= finish_s - start_s <= MAX_SPAN_SECONDS:
        raise MarketReadHold("HOLD: time interval unknown or too long")
    if type(meta) is not dict or type(mids) is not dict:
        raise MarketReadHold("HOLD: missing exchange metadata or market data")
    universe = meta.get("universe")
    if type(universe) is not list or len(universe) > 2000:
        raise MarketReadHold("HOLD: invalid perp metadata universe")
    matches = [x for x in universe if type(x) is dict and x.get("name") == COIN]
    if len(matches) != 1:
        raise MarketReadHold("HOLD: missing or duplicate SOL metadata")
    item = matches[0]
    if item.get("isDelisted") is True or item.get("onlyIsolated") is True:
        raise MarketReadHold("HOLD: market disabled or unexpected margin rules")
    size_decimals = item.get("szDecimals")
    leverage = item.get("maxLeverage")
    if type(size_decimals) is not int or not 0 <= size_decimals <= 5:
        raise MarketReadHold("HOLD: unknown SOL size precision")
    if type(leverage) is not int or leverage < 1:
        raise MarketReadHold("HOLD: unverified SOL leverage metadata")
    max_price_decimals = 6 - size_decimals
    if COIN not in mids:
        raise MarketReadHold("HOLD: SOL quote missing from Testnet mids")
    mid = _positive_decimal(mids[COIN], "SOL midpoint")
    if not Decimal("1") <= mid <= Decimal("10000"):
        raise MarketReadHold("HOLD: SOL quote outside reviewed range")
    return SolTestnetMarketReview(
        symbol=COIN, mid_price=str(mid),
        size_decimals=size_decimals,
        max_price_decimals=max_price_decimals,
        observed_at_s=finish_s,
    )


def read_sol_market_once(*, fetcher=fetch_public_market, clock=None):
    if clock is None:
        clock = lambda: int(time.time())
    begin = clock()
    meta = fetcher("meta")
    mids = fetcher("allMids")
    end = clock()
    return inspect_sol_market(meta=meta, mids=mids, start_s=begin, finish_s=end)
