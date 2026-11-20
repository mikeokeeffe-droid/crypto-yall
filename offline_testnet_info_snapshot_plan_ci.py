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

from offline_hyperliquid_http_envelope import inspect_http_envelope_offline
from offline_readonly_collector_runner import OfflineFixtureTransportResult
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


@dataclass(frozen=True)
class OfflineSnapshotCaptureReview:
    """A synthetic HTTP observation, never trusted exchange provenance."""
    state: str = "hold"
    reason: str = "read-only capture requires review"
    request_sha256: str | None = None
    response_sha256: str | None = None
    request_type: str | None = None
    response_shape: str | None = None
    origin_authenticated: bool = False
    history_complete: bool = False
    ownership_verified: bool = False
    submit_authorized: bool = False


def _unique_json_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate response field")
        result[key] = value
    return result


def _reject_json_constant(value):
    raise ValueError("nonfinite JSON constant")


def review_offline_testnet_snapshot_capture(
    *, plan, expected_account, expected_request_type, fixture_result,
    captured_at_ms, now_ms,
):
    """Inspect one exact planned request against a supplied synthetic response.

    NO HTTP occurs here; the sealed fixture_result is not an exchange-origin
    record. Even a matching body/claimed TLS status cannot prove account
    control, source authenticity, complete fills or close authorization.
    """
    def hold(reason):
        return OfflineSnapshotCaptureReview(reason=reason)

    preflight = preflight_testnet_info_transport_offline(
        plan=plan, expected_account=expected_account,
        expected_request_type=expected_request_type,
    )
    if (preflight.state != "dry_run_only"
            or type(fixture_result) is not OfflineFixtureTransportResult
            or fixture_result.network_authorized
            or fixture_result.proxy_used is not False
            or type(fixture_result.body) is not bytes
            or type(captured_at_ms) is not int
            or type(now_ms) is not int
            or not 0 < captured_at_ms <= now_ms
            or now_ms - captured_at_ms > 30000):
        return hold("untrusted plan, transport, clock or stale synthetic evidence")

    envelope = inspect_http_envelope_offline(
        status_code=fixture_result.status_code,
        elapsed_ms=fixture_result.elapsed_ms,
        body_bytes=len(fixture_result.body),
        redirect_count=fixture_result.redirect_count,
        tls_verified=fixture_result.tls_verified,
        expected_url=preflight.endpoint,
        final_url=fixture_result.final_url,
        network_error=fixture_result.network_error,
        content_type=fixture_result.content_type,
    )
    if (envelope.status != "review_only"
            or fixture_result.elapsed_ms > preflight.timeout_ms
            or len(fixture_result.body) > preflight.max_response_bytes):
        return hold("HTTP fixture envelope rejected: " + envelope.reason)

    try:
        payload = json.loads(
            fixture_result.body.decode("utf-8"),
            object_pairs_hook=_unique_json_pairs,
            parse_constant=_reject_json_constant,
        )
    except (UnicodeError, ValueError, TypeError):
        return hold("malformed, duplicate-key or nonfinite fixture JSON")

    # Narrow structural checks; never treat an empty list as evidence of no
    # orders, nor a snapshot as proof of order/fill history completeness.
    kind = plan.request_type
    if kind == "clearinghouseState":
        valid = (type(payload) is dict
                 and type(payload.get("marginSummary")) is dict
                 and type(payload.get("assetPositions")) is list)
        shape = "perp_account_snapshot"
    elif kind == "spotClearinghouseState":
        valid = type(payload) is dict and type(payload.get("balances")) is list
        shape = "spot_account_snapshot"
    elif kind == "openOrders":
        valid = (type(payload) is list and len(payload) <= 1000
                 and all(type(order) is dict for order in payload))
        shape = "open_orders_snapshot"
    elif kind == "allMids":
        valid = (type(payload) is dict and len(payload) <= 10000
                 and all(type(key) is str for key in payload))
        shape = "market_mids_snapshot"
    elif kind == "meta":
        valid = type(payload) is dict and type(payload.get("universe")) is list
        shape = "perp_meta_snapshot"
    else:
        return hold("unsupported snapshot kind")
    if not valid:
        return hold("synthetic snapshot shape rejected")

    return OfflineSnapshotCaptureReview(
        state="fixture_only",
        reason="synthetic snapshot shape and request bytes consistent; "
               "actual TLS/origin, history and ownership unverified",
        request_sha256=preflight.canonical_request_sha256,
        response_sha256=hashlib.sha256(fixture_result.body).hexdigest(),
        request_type=kind,
        response_shape=shape,
    )
