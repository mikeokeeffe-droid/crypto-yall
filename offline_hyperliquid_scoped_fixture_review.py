"""Offline binding of a proposed Hyperliquid /info query to fake evidence.

No transport, secrets, network, exchange authentication or trading capability.
This guard is for review-only test fixtures; it never proves response origin,
history completeness, ownership, or authorization to release an entry claim.
"""
from dataclasses import dataclass

from offline_hyperliquid_transport_plan import review_readonly_transport_plan_offline
from offline_hyperliquid_readonly_boundary import (
    build_order_status_query_offline, build_fills_query_offline,
    inspect_order_response_offline, inspect_fills_response_offline,
)


@dataclass(frozen=True)
class ScopeReview:
    status: str
    reason: str
    records: tuple = ()


def inspect_scoped_fixture_offline(*, environment, endpoint, account,
                                   expected_account, dex, kind, response,
                                   oid=None, coin=None, direction=None,
                                   requested_size=None, submitted_at_ms=None,
                                   start_ms=None, end_ms=None):
    def hold(reason):
        return ScopeReview("hold", reason)

    plan = review_readonly_transport_plan_offline(
        environment=environment, endpoint=endpoint, account=account,
        expected_account=expected_account, dex=dex, method="POST",
        request_type=kind, allow_network=False,
    )
    if plan.status != "plan_only":
        return hold("unapproved environment, account or request scope")

    if kind == "orderStatus":
        query = build_order_status_query_offline(account=account, oid=oid)
        if query.status != "query_only":
            return hold("invalid order query")
        parsed = inspect_order_response_offline(
            query=query, response=response, account=expected_account,
            coin=coin, oid=oid, direction=direction,
            requested_size=requested_size, submitted_at_ms=submitted_at_ms,
        )
    elif kind == "userFillsByTime":
        query = build_fills_query_offline(
            account=account, start_ms=start_ms, end_ms=end_ms,
        )
        if query.status != "query_only":
            return hold("invalid fills query")
        parsed = inspect_fills_response_offline(
            query=query, response=response, account=expected_account,
            start_ms=start_ms, end_ms=end_ms,
        )
    else:
        return hold("unsupported read-only request")

    if parsed.status != "parsed_untrusted":
        return hold("fake exchange evidence failed strict inspection")
    return ScopeReview(
        "review_only",
        "fake scoped evidence parsed; transport, source and completeness unverified",
        parsed.records,
    )
