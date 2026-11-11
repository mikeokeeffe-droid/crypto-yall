"""Review-only snapshot query plans for future Hyperliquid testnet /info.

No network client, SDK, signer, secrets, account discovery, database or
production invocation. Constructing a query is NOT permission to perform it
or a statement that data belongs to the operator.

The order-status and fill-history CI protocol already lives in
offline_readonly_collector_contract.py; don't invent a second implementation.
This module fills the missing account/market snapshot QUERY coverage only.
"""
from dataclasses import dataclass
import json
import re

_ACCOUNT = re.compile(r"0x[0-9a-f]{40}\Z", re.ASCII)
_ENDPOINT = "https://api.hyperliquid-testnet.xyz/info"
_ALLOW = frozenset((
    "clearinghouseState",
    "openOrders",
    "allMids",
    "meta",
    "spotClearinghouseState",
))
_USER = frozenset(("clearinghouseState", "openOrders", "spotClearinghouseState"))
_DEX = frozenset(("clearinghouseState", "openOrders", "allMids", "meta"))


@dataclass(frozen=True)
class OfflineSnapshotInfoRequest:
    state: str = "hold"
    reason: str = "unapproved request"
    endpoint: str | None = None
    request_type: str | None = None
    request_json: str | None = None
    network_authorized: bool = False
    origin_authenticated: bool = False
    history_complete: bool = False
    ownership_verified: bool = False
    submit_authorized: bool = False


def build_offline_testnet_snapshot_request(*, pinned_account, request_type,
                                           pinned_environment="testnet",
                                           pinned_dex=""):
    """Create one strict Hyperliquid /info POST body, NEVER send it.

    The account and environment must be pinned by an *independent* operator
    configuration in a future service, not a bot's wire request. Only the
    first perp DEX is in scope. Defaults reject mainnet/HIP-3 and all order
    actions; no user-controlled host, URL, method or arbitrary payload.
    """
    def hold(reason):
        return OfflineSnapshotInfoRequest(reason=reason)

    if (type(pinned_environment) is not str
            or pinned_environment != "testnet"
            or type(pinned_dex) is not str or pinned_dex != ""
            or type(pinned_account) is not str
            or _ACCOUNT.fullmatch(pinned_account) is None
            or type(request_type) is not str
            or request_type not in _ALLOW):
        return hold("testnet-only pinned scope and allowlisted /info type required")

    body = {"type": request_type}
    if request_type in _USER:
        body["user"] = pinned_account
    if request_type in _DEX:
        body["dex"] = pinned_dex

    return OfflineSnapshotInfoRequest(
        state="query_only",
        reason="read-only /info query prepared; no HTTP or trusted provenance",
        endpoint=_ENDPOINT,
        request_type=request_type,
        request_json=json.dumps(body,sort_keys=True,separators=(",",":")),
    )
