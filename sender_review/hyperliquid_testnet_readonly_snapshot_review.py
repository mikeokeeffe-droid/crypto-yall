"""Opt-in, testnet-only /info snapshot reader; never an exchange sender.

Prepares a real HTTPS-only public-data route for later *independent* host
attestation and operator approval. It has no wallet, private key, signer,
Hyperliquid SDK, /exchange endpoint, DB write, retry or order operation.
Disabled by default; no existing workflow or server invokes this module.

Observed state can never prove position ownership, history completeness,
that no intervening fill occurred, or permission to close, retry or trade.
Even consistent snapshots always return HOLD.
"""
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
import hashlib
import json
import re
import ssl
import urllib.request

_URL = "https://api.hyperliquid-testnet.xyz/info"
_ACCOUNT = re.compile(r"0x[0-9a-f]{40}\Z", re.ASCII)
_COIN = re.compile(r"[A-Z][A-Z0-9]{0,23}\Z", re.ASCII)
_SIZE = re.compile(r"-?(?:0|[1-9][0-9]*)(?:\.[0-9]{1,12})?\Z", re.ASCII)
_LIMIT = 1048576


@dataclass(frozen=True)
class ReadOnlyTestnetSnapshot:
    state: str = "HOLD"
    reason: str = "read-only testnet network access not approved"
    snapshot_consistent: bool = False
    positions_digest: str | None = None
    position_count: int = 0
    open_order_count: int = 0
    # No source of operational authority exists here.
    account_ownership_verified: bool = False
    historical_completeness_verified: bool = False
    fills_reconciled: bool = False
    position_ownership_verified: bool = False
    runtime_identity_authenticated: bool = False
    replay_consumed: bool = False
    journal_recorded: bool = False
    submit_authorized: bool = False
    close_authorized: bool = False
    signing_enabled: bool = False


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        return None


def _no_duplicates(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON property")
        result[key] = value
    return result


def _no_constants(_):
    raise ValueError("nonfinite JSON constant")


def _info_query(opener, *, account, kind):
    if kind not in ("clearinghouseState", "openOrders"):
        raise ValueError("only two read-only info types supported")
    body = json.dumps(
        {"type": kind, "user": account, "dex": ""},
        sort_keys=True, separators=(",", ":"),
    ).encode("ascii")
    req = urllib.request.Request(
        _URL, data=body, method="POST",
        headers={"Content-Type": "application/json",
                 "Accept": "application/json"},
    )
    with opener.open(req, timeout=5) as response:
        if (response.status != 200 or response.geturl() != _URL
                or response.headers.get("Content-Type", "").split(";")[0]
                .strip().lower() != "application/json"):
            raise ValueError("unexpected response")
        raw = response.read(_LIMIT + 1)
    if not 0 < len(raw) <= _LIMIT:
        raise ValueError("invalid response length")
    return json.loads(raw.decode("utf-8"), object_pairs_hook=_no_duplicates,
                      parse_constant=_no_constants)


def _positions(document):
    if (type(document) is not dict
            or type(document.get("assetPositions")) is not list
            or len(document["assetPositions"]) > 500):
        raise ValueError("invalid position document")
    positions = {}
    for record in document["assetPositions"]:
        if type(record) is not dict or type(record.get("position")) is not dict:
            raise ValueError("invalid position record")
        pos = record["position"]
        coin, size = pos.get("coin"), pos.get("szi")
        if (type(coin) is not str or _COIN.fullmatch(coin) is None
                or coin in positions or type(size) is not str
                or _SIZE.fullmatch(size) is None):
            raise ValueError("duplicate/invalid asset")
        try:
            amount = Decimal(size)
        except InvalidOperation:
            raise ValueError("invalid position amount") from None
        if not amount.is_finite() or amount == 0 or abs(amount) > 1000000000:
            raise ValueError("invalid position amount")
        positions[coin] = format(amount.normalize(), "f")
    return positions


def _orders(document):
    if type(document) is not list or len(document) > 5000:
        raise ValueError("invalid open orders document")
    seen = set()
    for order in document:
        if type(order) is not dict:
            raise ValueError("invalid order record")
        oid, coin, side, size = (
            order.get("oid"), order.get("coin"),
            order.get("side"), order.get("sz"),
        )
        if (type(oid) is not int or oid <= 0 or oid in seen
                or type(coin) is not str or _COIN.fullmatch(coin) is None
                or side not in ("A", "B")
                or type(size) is not str or _SIZE.fullmatch(size) is None
                or Decimal(size) <= 0):
            raise ValueError("invalid/duplicate order")
        seen.add(oid)
    return len(document)


def inspect_testnet_info_readonly_snapshot(
    *, configured_public_account, enabled_readonly_testnet_network=False,
):
    """Make exactly three public /info requests only after an explicit opt-in.

    The account is an *untrusted input*, expected to be pinned separately
    by a future verified host. It cannot determine real trading ownership.
    No token, wallet key, account secret, URL or action is accepted.
    """
    hold = ReadOnlyTestnetSnapshot()
    if (enabled_readonly_testnet_network is not True
            or type(configured_public_account) is not str
            or _ACCOUNT.fullmatch(configured_public_account) is None):
        return hold
    try:
        opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({}), _NoRedirect(),
            urllib.request.HTTPSHandler(context=ssl.create_default_context()),
        )
        before = _positions(_info_query(
            opener, account=configured_public_account, kind="clearinghouseState"
        ))
        open_orders = _orders(_info_query(
            opener, account=configured_public_account, kind="openOrders"
        ))
        after = _positions(_info_query(
            opener, account=configured_public_account, kind="clearinghouseState"
        ))
        if before != after:
            return ReadOnlyTestnetSnapshot(
                reason="position quantities changed between observations"
            )
        digest = hashlib.sha256(json.dumps(
            before, sort_keys=True, separators=(",", ":")
        ).encode("ascii")).hexdigest()
        return ReadOnlyTestnetSnapshot(
            state="OBSERVED_TESTNET_READONLY_HOLD",
            reason="testnet /info response shapes consistent; no historical "
                   "or trade/close/retry authority and no host attestation",
            snapshot_consistent=True,
            positions_digest=digest,
            position_count=len(after),
            open_order_count=open_orders,
        )
    except (ValueError, TypeError, UnicodeError, OSError, OverflowError):
        return hold
