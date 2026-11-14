"""INERT candidate HTTPS transport for future Hyperliquid TESTNET /info reads.

HARD-DISABLED: this module contains a candidate TLS/HTTP implementation for
independent review, but _NETWORK_IMPLEMENTATION_APPROVED is fixed False and
cannot be overridden by a caller, environment variable, or CI flag. NO network
requests can be made by invoking the public function in this version.

This is not an authenticated or deployed collector. Production-grade egress,
audit provenance, operator-selected account and testnet permission require
independent review BEFORE any future edit to enable execution. Never import
this from original executors or run it with live credentials.
"""
from dataclasses import dataclass

from offline_testnet_info_snapshot_plan_ci import (
    OfflineSnapshotInfoRequest,
    preflight_testnet_info_transport_offline,
)

_NETWORK_IMPLEMENTATION_APPROVED = False  # requires reviewed code change
_PINNED_HOST = "api.hyperliquid-testnet.xyz"
_PINNED_PATH = "/info"


@dataclass(frozen=True)
class OfflineHTTPSCandidateResult:
    state: str = "hold"
    reason: str = "network-disabled implementation candidate"
    request_sha256: str | None = None
    response_sha256: str | None = None
    http_status: int | None = None
    response_bytes: int | None = None
    elapsed_ms: int | None = None
    origin_authenticated: bool = False
    history_complete: bool = False
    ownership_verified: bool = False
    submit_authorized: bool = False


def review_candidate_http_response_offline(*, status, content_type,
                                           content_encoding, response_bytes,
                                           expected_response_limit):
    """Validate a caller-supplied response envelope, not its authenticity."""
    if (type(status) is not int or status != 200
            or type(content_type) is not str
            or content_type.lower() != "application/json"
            or content_encoding not in ("", "identity", None)
            or type(response_bytes) is not bytes
            or type(expected_response_limit) is not int
            or expected_response_limit != 262144
            or not 0 < len(response_bytes) <= expected_response_limit):
        return False
    return True


def collect_testnet_info_candidate_offline(*, plan, expected_account,
                                           expected_request_type):
    """Dry-run only. Cannot open a connection while compiled gate is False.

    A future approved source patch would need to review transport mechanics,
    OS egress restrictions and immutable provenance before changing the gate.
    The code below deliberately never grants ownership or submission rights.
    """
    hold = OfflineHTTPSCandidateResult
    if type(plan) is not OfflineSnapshotInfoRequest:
        return hold(reason="unrecognized read-only request plan")
    preflight = preflight_testnet_info_transport_offline(
        plan=plan,
        expected_account=expected_account,
        expected_request_type=expected_request_type,
    )
    if preflight.state != "dry_run_only":
        return hold(reason="non-canonical or unapproved /info plan")
    if _NETWORK_IMPLEMENTATION_APPROVED is not False:
        # This review build explicitly rejects even a monkeypatched True.
        # A separate approved transport must replace this module, not flip
        # an environment variable or call an internal helper.
        return hold(reason="unexpected collector execution configuration")
    return hold(
        reason="request validated; real HTTPS disabled pending independent "
               "testnet security and operator approval",
        request_sha256=preflight.canonical_request_sha256,
    )


# No network-capable transport is provided here. A future real connector is
# a separate reviewed change, not a switch on this candidate module.
