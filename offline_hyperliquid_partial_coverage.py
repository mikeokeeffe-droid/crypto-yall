"""Offline-only partial-fill and historical coverage safety gate.

A time window or a synthetic archive claim never proves complete exchange
history. This gate cannot authorize ownership, no-fill, recovery or trading.
"""
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

@dataclass(frozen=True)
class CoverageReview:
    status: str
    reason: str

def _positive(value):
    if type(value) is not str:
        return None
    try:
        parsed = Decimal(value)
    except (InvalidOperation, ValueError):
        return None
    return parsed if parsed.is_finite() and parsed > 0 else None

def inspect_partial_fill_coverage_offline(*, requested_size, observed_fill_sizes,
                                          required_start_ms, required_end_ms,
                                          queried_start_ms, queried_end_ms,
                                          archive_review, saturated,
                                          missing_windows, order_status):
    def hold(reason):
        return CoverageReview("hold", reason)
    size = _positive(requested_size)
    if (size is None or type(observed_fill_sizes) is not tuple
            or type(required_start_ms) is not int
            or type(required_end_ms) is not int
            or type(queried_start_ms) is not int
            or type(queried_end_ms) is not int
            or required_start_ms <= 0
            or required_end_ms < required_start_ms
            or queried_start_ms > required_start_ms
            or queried_end_ms < required_end_ms):
        return hold("invalid or insufficient requested history window")
    if saturated is not False or missing_windows is not False:
        return hold("saturated or incomplete fill history")
    if getattr(archive_review, "status", None) != "review_only":
        return hold("independent historical archive claim missing")
    if order_status not in ("filled", "rejected"):
        return hold("order status unknown or nonterminal")
    total = Decimal(0)
    for raw in observed_fill_sizes:
        amount = _positive(raw)
        if amount is None:
            return hold("invalid observed fill amount")
        total += amount
        if total > size:
            return hold("observed fills exceed submitted order")
    if total == 0:
        return hold("empty history does not establish no-fill")
    if total < size:
        return hold("partial fill or missing historical fills")
    if order_status != "filled":
        return hold("rejected status conflicts with observed full fills")
    return CoverageReview(
        "review_only",
        "synthetic full-size fills and archive claims agree; completeness and provenance unverified",
    )
