"""Standalone Hyperliquid testnet /info HTTPS collector (REVIEW ONLY).

The real HTTP implementation is present but deliberately unreachable from the
public entrypoint until an independently reviewed code change is approved.
No environment variable, CLI option or caller argument can enable networking.

Never run this inside the existing trading executors. For a future approved
deployment the process must be isolated without trading keys, with externally
enforced egress/identity permissions and independently pinned testnet account.
"""
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
import hashlib
import http.client
import json
import re
import ssl
import time

HOST = "api.hyperliquid-testnet.xyz"
PATH = "/info"
ENDPOINT = "https://" + HOST + PATH
MAX_BYTES = 262144
TIMEOUT_SECONDS = 4
# Fixed in source; enabling requires a separate reviewed code change and
# explicit approval for a specific public testnet account and request type.
NETWORK_ENABLED = False
ACCOUNT_PATTERN = re.compile(r"0x[0-9a-f]{40}\Z", re.ASCII)

ACCOUNT_TYPES = frozenset(("clearinghouseState", "openOrders", "spotClearinghouseState"))
MARKET_TYPES = frozenset(("allMids", "meta"))
APPROVED_TYPES = ACCOUNT_TYPES | MARKET_TYPES
PERP_DEX_TYPES = frozenset(("clearinghouseState", "openOrders", "allMids", "meta"))


@dataclass(frozen=True)
class ReadReview:
    state: str
    reason: str
    request_sha256: str | None = None
    response_sha256: str | None = None
    status_code: int | None = None
    body_length: int | None = None
    elapsed_ms: int | None = None
    origin_authenticated: bool = False
    history_complete: bool = False
    ownership_verified: bool = False
    submit_authorized: bool = False


def prepare_testnet_info_body(*, account, kind):
    """Create exact allowable JSON or return None, never infer account scope."""
    if (type(account) is not str or not ACCOUNT_PATTERN.fullmatch(account)
            or type(kind) is not str or kind not in APPROVED_TYPES):
        return None
    body = {"type": kind}
    if kind in ACCOUNT_TYPES:
        body["user"] = account
    if kind in PERP_DEX_TYPES:
        body["dex"] = ""
    return json.dumps(body, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _no_duplicate_keys(pairs):
    out = {}
    for key, value in pairs:
        if key in out:
            raise ValueError("duplicate JSON field")
        out[key] = value
    return out


def _reject_constant(value):
    raise ValueError("non-finite JSON")


def _valid_number(value, *, allow_negative=False, positive=False):
    if type(value) is not str or not value or value.strip() != value:
        return False
    try:
        n = Decimal(value)
    except (InvalidOperation, ValueError):
        return False
    return n.is_finite() and (allow_negative or n >= 0) and (not positive or n > 0)


def _valid_coin(value):
    return (type(value) is str and 0 < len(value) <= 64
            and re.fullmatch(r"[A-Za-z0-9@._:/-]+", value, re.ASCII) is not None)


def _valid_account_snapshot(payload):
    if (type(payload) is not dict
            or type(payload.get("marginSummary")) is not dict
            or type(payload.get("assetPositions")) is not list
            or not _valid_number(payload["marginSummary"].get("accountValue"),
                                 allow_negative=True)):
        return False
    coins = set()
    for record in payload["assetPositions"]:
        if type(record) is not dict or type(record.get("position")) is not dict:
            return False
        pos = record["position"]
        coin = pos.get("coin")
        if (not _valid_coin(coin) or coin in coins
                or not _valid_number(pos.get("szi"), allow_negative=True)):
            return False
        coins.add(coin)
    return True


def _valid_spot_snapshot(payload):
    if type(payload) is not dict or type(payload.get("balances")) is not list:
        return False
    coins = set()
    for item in payload["balances"]:
        if type(item) is not dict:
            return False
        coin = item.get("coin")
        if (not _valid_coin(coin) or coin in coins
                or not _valid_number(item.get("total"))
                or not _valid_number(item.get("hold"))):
            return False
        if Decimal(item["hold"]) > Decimal(item["total"]):
            return False
        coins.add(coin)
    return True


def _valid_open_orders(payload):
    if type(payload) is not list or len(payload) > 1000:
        return False
    oids = set()
    for order in payload:
        if type(order) is not dict:
            return False
        oid = order.get("oid")
        if (type(oid) is not int or oid <= 0 or oid in oids
                or type(order.get("timestamp")) is not int
                or order["timestamp"] <= 0
                or not _valid_coin(order.get("coin"))
                or order.get("side") not in ("A", "B")
                or not _valid_number(order.get("sz"))
                or not _valid_number(order.get("limitPx"), positive=True)):
            return False
        oids.add(oid)
    return True


def _valid_market_mids(payload):
    return (type(payload) is dict and 0 < len(payload) <= 10000
            and all(_valid_coin(coin) and _valid_number(price, positive=True)
                    for coin, price in payload.items()))


def _valid_meta(payload):
    if type(payload) is not dict or type(payload.get("universe")) is not list:
        return False
    coins = set()
    for item in payload["universe"]:
        if type(item) is not dict:
            return False
        coin, decimals = item.get("name"), item.get("szDecimals")
        if (not _valid_coin(coin) or coin in coins
                or type(decimals) is not int or not 0 <= decimals <= 8):
            return False
        coins.add(coin)
    return True


def review_untrusted_http_capture(*, account, kind, sent_body, raw_body,
                                  status_code, content_type, content_encoding,
                                  elapsed_ms):
    """Review a supplied HTTP capture, not independently verify its origin.

    These values are untrusted caller inputs until collected inside a
    separately authenticated and audited transport service.
    """
    prepared = prepare_testnet_info_body(account=account, kind=kind)
    if prepared is None or type(sent_body) is not bytes or sent_body != prepared:
        return ReadReview("hold", "request body or pinned scope mismatch")
    req_hash = hashlib.sha256(prepared).hexdigest()
    if (type(status_code) is not int or status_code != 200
            or type(content_type) is not str
            or content_type.split(";", 1)[0].strip().lower() != "application/json"
            or content_encoding not in (None, "", "identity")
            or type(elapsed_ms) is not int or not 0 <= elapsed_ms <= 4000
            or type(raw_body) is not bytes
            or not 0 < len(raw_body) <= MAX_BYTES):
        return ReadReview("hold", "invalid HTTP status, timeout or response framing",
                          request_sha256=req_hash)
    try:
        payload = json.loads(raw_body.decode("utf-8"),
                             object_pairs_hook=_no_duplicate_keys,
                             parse_constant=_reject_constant)
    except (UnicodeError, ValueError, TypeError):
        return ReadReview("hold", "malformed or ambiguous JSON",
                          request_sha256=req_hash)
    validators = {
        "clearinghouseState": _valid_account_snapshot,
        "spotClearinghouseState": _valid_spot_snapshot,
        "openOrders": _valid_open_orders,
        "allMids": _valid_market_mids,
        "meta": _valid_meta,
    }
    valid = validators[kind](payload)
    if not valid:
        return ReadReview("hold", "unexpected /info response shape",
                          request_sha256=req_hash)
    return ReadReview(
        "fixture_only", "structure consistent; origin, history and ownership unverified",
        request_sha256=req_hash,
        response_sha256=hashlib.sha256(raw_body).hexdigest(),
        status_code=status_code,
        body_length=len(raw_body),
        elapsed_ms=elapsed_ms,
    )


def _https_post_restricted_review_only(body):
    """Transport mechanics for later independent audit; NOT publicly invoked.

    Uses Python's verified TLS context and direct HTTPSConnection (no
    environment proxy, redirect follow, or automatic retry). No generic URL
    is accepted. The caller MUST impose network-level egress limits separately.
    """
    if NETWORK_ENABLED is not False:
        raise PermissionError("unreviewed network activation")
    raise PermissionError("network transport has not been approved")
    # Inaccessible candidate for independent code review only:
    context = ssl.create_default_context()
    context.check_hostname = True
    context.verify_mode = ssl.CERT_REQUIRED
    conn = http.client.HTTPSConnection(HOST, 443,
                                        timeout=TIMEOUT_SECONDS,
                                        context=context)
    start = time.monotonic()
    try:
        conn.request("POST", PATH, body=body, headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Accept-Encoding": "identity",
            "Connection": "close",
        })
        response = conn.getresponse()
        # Read at most one byte beyond the cap to detect truncation.
        raw = response.read(MAX_BYTES + 1)
        return {
            "raw_body": raw,
            "status_code": response.status,
            "content_type": response.getheader("Content-Type", ""),
            "content_encoding": response.getheader("Content-Encoding"),
            "elapsed_ms": int((time.monotonic() - start) * 1000),
        }
    finally:
        conn.close()


def collect_testnet_readonly_review(*, account, kind):
    """Public fail-closed entrypoint. No network call on this branch."""
    body = prepare_testnet_info_body(account=account, kind=kind)
    if body is None:
        return ReadReview("hold", "invalid operator-pinned testnet request")
    if NETWORK_ENABLED is not False:
        # Unexpected tampering must not enable the network.
        return ReadReview("hold", "unreviewed network configuration")
    return ReadReview(
        "hold", "network disabled pending isolated runtime review and "
                "explicit one-shot testnet approval",
        request_sha256=hashlib.sha256(body).hexdigest(),
    )
