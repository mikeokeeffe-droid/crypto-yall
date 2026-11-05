"""Offline-only provenance review of a hypothetical read-only /info capture.

This validates *claims* about the capture boundary; Python dictionaries are
forgeable and cannot authenticate TLS, the server, account ownership, or
exchange history. No HTTP, credentials, wallet or trading integration.
"""
from dataclasses import dataclass

from offline_hyperliquid_transport_plan import review_readonly_transport_plan_offline


@dataclass(frozen=True)
class ProvenanceReview:
    status: str
    reason: str


def inspect_capture_claim_offline(*, environment, endpoint, account,
                                  expected_account, dex, request_type,
                                  capture):
    def hold(reason):
        return ProvenanceReview("hold", reason)

    plan = review_readonly_transport_plan_offline(
        environment=environment, endpoint=endpoint, account=account,
        expected_account=expected_account, dex=dex, method="POST",
        request_type=request_type, allow_network=False,
    )
    if plan.status != "plan_only":
        return hold("capture outside pinned read-only query scope")
    if type(capture) is not dict:
        return hold("capture metadata missing")
    # Never trust an arbitrary 'authenticated' flag supplied by a fixture.
    # These fields can only demonstrate internal consistency of an offline
    # test; real provenance must be established by a reviewed transport.
    if (capture.get("environment") != environment
            or capture.get("endpoint") != endpoint
            or capture.get("account") != account
            or capture.get("dex") != dex
            or capture.get("request_type") != request_type
            or capture.get("method") != "POST"
            or capture.get("response_origin") != "simulated"
            or capture.get("transport_verified") is not False):
        return hold("capture scope mismatch or unverifiable origin claim")
    if capture.get("authenticated") is True:
        return hold("synthetic metadata cannot authenticate exchange origin")
    return ProvenanceReview(
        "review_only",
        "synthetic capture scope consistent; source and ownership unverified",
    )
