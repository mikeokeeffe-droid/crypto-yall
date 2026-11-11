"""Review-only snapshot query plans for future Hyperliquid testnet /info.

No network client, SDK, signer, secrets, account discovery, database or
production invocation. Constructing a query is NOT permission to perform it
or a statement that data belongs to the operator.

The order-status and fill-history CI protocol already lives in
offline_readonly_collector_contract.py; don't invent a second implementation.
This module fills the missing account/market snapshot QUERY coverage only.
"""
from dataclasses import dataclass
import hashlib
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


# A dry-run security contract, not an HTTP implementation. A later,
# independently reviewed collector would need to enforce these limits at its
# effective OS/network boundary; these values cannot certify TLS or egress.
_INFO_WEIGHTS = {
    "clearinghouseState": 2,
    "openOrders": 20,
    "allMids": 2,
    "meta": 20,
    "spotClearinghouseState": 2,
}


@dataclass(frozen=True)
class OfflineTestnetTransportPreflight:
    state: str = "hold"
    reason: str = "network-disabled testnet preflight not accepted"
    method: str | None = None
    endpoint: str | None = None
    canonical_request_sha256: str | None = None
    request_bytes: int | None = None
    estimated_ip_weight: int | None = None
    timeout_ms: int | None = None
    max_response_bytes: int | None = None
    redirects_allowed: bool = False
    inherited_proxies_allowed: bool = False
    automatic_retries_allowed: bool = False
    network_authorized: bool = False
    origin_authenticated: bool = False
    history_complete: bool = False
    ownership_verified: bool = False
    submit_authorized: bool = False


def preflight_testnet_info_transport_offline(*, plan, expected_account,
                                            expected_request_type,
                                            allow_network=False):
    """Reject changed request plans and emit no networking capability.

    The caller must have independently pinned the account/type. No arbitrary
    URL, host, headers, bearer token, signing key, transport callback, request
    operation, retry settings, or network-enabling switch is accepted. This
    deliberately cannot perform a real testnet read.
    """
    def hold(reason):
        return OfflineTestnetTransportPreflight(reason=reason)

    if (type(plan) is not OfflineSnapshotInfoRequest
            or type(expected_account) is not str
            or type(expected_request_type) is not str
            or allow_network is not False):
        return hold("invalid plan or attempt to enable the network")

    expected = build_offline_testnet_snapshot_request(
        pinned_account=expected_account,
        request_type=expected_request_type,
    )
    if (expected.state != "query_only"
            or plan != expected
            or plan.network_authorized
            or plan.submit_authorized
            or plan.origin_authenticated
            or plan.history_complete
            or plan.ownership_verified):
        return hold("plan changed, account not pinned, or authority spoofed")

    encoded = expected.request_json.encode("utf-8")
    if not 0 < len(encoded) <= 256:
        return hold("invalid or oversized canonical request")

    return OfflineTestnetTransportPreflight(
        state="dry_run_only",
        reason="canonical /info request identified; network and provenance "
               "are deliberately unavailable",
        method="POST",
        endpoint=_ENDPOINT,
        canonical_request_sha256=hashlib.sha256(encoded).hexdigest(),
        request_bytes=len(encoded),
        estimated_ip_weight=_INFO_WEIGHTS[expected_request_type],
        timeout_ms=4000,
        max_response_bytes=262144,
    )
