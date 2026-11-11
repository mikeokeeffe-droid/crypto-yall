"""Offline collector *handoff runner* with a sealed fixture transport.

This is intentionally not an HTTP implementation: it has no socket, URL
fetch, runtime secrets, exchange SDK, database, signer, or trading capability.
The only accepted transport is a frozen synthetic data object; adding any
real transport requires a separate security review and explicit approval.
"""
from dataclasses import dataclass

from offline_hyperliquid_http_envelope import inspect_http_envelope_offline
from offline_readonly_collector_contract import (
    OfflineInfoPlan,
    build_offline_info_plan,
    record_fixture_response_offline,
    inspect_fixture_response_offline,
    review_cloid_order_capture_offline,
)


@dataclass(frozen=True)
class OfflineFixtureTransportResult:
    """Untrusted synthetic HTTP observations, NEVER verified live transport."""
    status_code: int
    final_url: str
    elapsed_ms: int
    content_type: str
    body: bytes
    redirect_count: int = 0
    tls_verified: bool = True
    network_error: str | None = None
    proxy_used: bool = False
    network_authorized: bool = False


@dataclass(frozen=True)
class OfflineCollectionResult:
    state: str
    reason: str
    response_sha256: str | None = None
    structurally_consistent: bool = False
    observed_oid: int | None = None
    origin_authenticated: bool = False
    history_complete: bool = False
    ownership_verified: bool = False
    submit_authorized: bool = False


def run_offline_info_capture(*, plan, fixture_result, captured_at_ms,
                             now_ms, pinned_intent=None):
    """Evaluate one supplied fake response against one pinned read-only plan.

    Return no order/close/claim-release authority regardless of the outcome.
    The mock's TLS and final URL fields are syntactic claims, not proof.
    """
    def hold(why):
        return OfflineCollectionResult("hold", why)

    if (type(plan) is not OfflineInfoPlan or plan.status != "query_only"
            or plan.network_authorized or plan != build_offline_info_plan(
                scope=plan.scope, request_type=plan.request_type,
                start_ms=plan.start_ms, end_ms=plan.end_ms,
            ) or type(fixture_result) is not OfflineFixtureTransportResult
            or fixture_result.network_authorized
            or fixture_result.proxy_used is not False
            or type(fixture_result.body) is not bytes
            or type(captured_at_ms) is not int
            or type(now_ms) is not int
            or not 0 < captured_at_ms <= now_ms):
        return hold("invalid offline plan, transport type or captured clock")

    policy = inspect_http_envelope_offline(
        status_code=fixture_result.status_code,
        elapsed_ms=fixture_result.elapsed_ms,
        body_bytes=len(fixture_result.body),
        redirect_count=fixture_result.redirect_count,
        tls_verified=fixture_result.tls_verified,
        expected_url=plan.endpoint,
        final_url=fixture_result.final_url,
        network_error=fixture_result.network_error,
        content_type=fixture_result.content_type,
    )
    if policy.status != "review_only":
        return hold(policy.reason)

    capture = record_fixture_response_offline(
        plan=plan,
        raw_response=fixture_result.body,
        captured_at_ms=captured_at_ms,
        status_code=fixture_result.status_code,
        redirect_count=fixture_result.redirect_count,
    )
    if capture is None:
        return hold("unable to construct synthetic capture manifest")

    if plan.request_type == "orderStatus":
        if type(pinned_intent) is not dict:
            return hold("missing independent synthetic order intent")
        result = review_cloid_order_capture_offline(
            plan=plan, envelope=capture, intent=pinned_intent, now_ms=now_ms,
        )
        # Even a structurally matching CLOID response is HOLD.
        return OfflineCollectionResult(
            "hold", result.reason,
            structurally_consistent=result.structurally_consistent,
            observed_oid=result.observed_oid,
        )

    if pinned_intent is not None:
        return hold("unexpected order intent supplied for fill query")
    review = inspect_fixture_response_offline(
        plan=plan, envelope=capture, now_ms=now_ms,
    )
    return OfflineCollectionResult(
        review.status, review.reason, response_sha256=review.response_sha256,
    )
