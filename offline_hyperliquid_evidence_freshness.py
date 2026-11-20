"""Offline-only freshness gate for hypothetical Hyperliquid evidence.

No clock reads, HTTP, secrets, DB or executor imports. All times are
caller-supplied synthetic test values. Passing is review-only, not proof
of server authenticity, complete fills, or authorization to trade.
"""
from dataclasses import dataclass

@dataclass(frozen=True)
class FreshnessReview:
    status: str
    reason: str

def inspect_evidence_freshness_offline(*, query_started_ms, response_received_ms,
                                       review_now_ms, maximum_age_ms=30000,
                                       maximum_duration_ms=10000):
    def hold(reason):
        return FreshnessReview("hold", reason)
    times = (query_started_ms, response_received_ms, review_now_ms)
    if (any(type(value) is not int or value <= 0 for value in times)
            or type(maximum_age_ms) is not int or maximum_age_ms <= 0
            or type(maximum_duration_ms) is not int
            or maximum_duration_ms <= 0):
        return hold("invalid capture time or policy")
    if not query_started_ms <= response_received_ms <= review_now_ms:
        return hold("future, reversed or inconsistent timestamps")
    if response_received_ms - query_started_ms > maximum_duration_ms:
        return hold("capture exceeded allowed duration")
    if review_now_ms - response_received_ms > maximum_age_ms:
        return hold("stale response cannot support a current review")
    return FreshnessReview(
        "review_only",
        "synthetic timing consistent; clock and source authenticity unverified",
    )
