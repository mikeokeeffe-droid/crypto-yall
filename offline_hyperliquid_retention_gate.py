"""Offline-only retention evidence gate; never authorizes exchange recovery.

Hyperliquid /info userFillsByTime has a documented recent-history limit.
An apparently empty, short or continuous response cannot establish that
older fills were not omitted. This guard requires independent positive
coverage evidence and still returns only a review status, never permission
to release a fence or trade. No network or database access.
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class RetentionReview:
    status: str
    reason: str


def inspect_retention_evidence_offline(*, required_start_ms, required_end_ms,
                                       earliest_proven_ms, latest_proven_ms,
                                       source, truncated, retention_unknown):
    def hold(reason):
        return RetentionReview("hold", reason)

    if (type(required_start_ms) is not int
            or type(required_end_ms) is not int
            or required_start_ms <= 0 or required_end_ms < required_start_ms
            or type(earliest_proven_ms) is not int
            or type(latest_proven_ms) is not int
            or earliest_proven_ms <= 0
            or latest_proven_ms < earliest_proven_ms):
        return hold("invalid evidence window")
    if (truncated is not False or retention_unknown is not False):
        return hold("truncated or unverified exchange retention")
    if source not in ("independently_archived_fill_log",):
        return hold("exchange recent-history query alone cannot prove retention")
    if (earliest_proven_ms > required_start_ms
            or latest_proven_ms < required_end_ms):
        return hold("required pre-submit history not covered")
    return RetentionReview(
        "review_only",
        "claimed independent archive coverage; authenticity and completeness still unverified",
    )
