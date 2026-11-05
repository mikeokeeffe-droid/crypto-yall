"""Offline-only fence release review for synthetic order/fill evidence.

A 'filled' SDK result, matching order receipt, or caller-supplied approval
cannot authenticate provenance or prove durable cross-bot ownership.
No live integration, exchange calls, database, or credentials.
"""
from dataclasses import dataclass

@dataclass(frozen=True)
class ClaimReleaseReview:
    status: str
    reason: str
    release_claim: bool = False
    allow_new_entry: bool = False

def inspect_synthetic_claim_release_offline(*, legacy_result,
                                            strict_fill_review,
                                            ownership_review,
                                            restart_review):
    def hold(reason):
        return ClaimReleaseReview("hold", reason)
    if type(legacy_result) is not dict:
        return hold("missing legacy order result")
    if legacy_result.get("status") != "filled":
        return hold("order not confirmed filled")
    for name, review in (
        ("strict fill", strict_fill_review),
        ("ownership", ownership_review),
        ("restart", restart_review),
    ):
        try:
            status = getattr(review, "status", None)
        except Exception:
            return hold(name + " review inaccessible")
        if type(status) is not str or status not in (
            "hold", "parsed_untrusted", "review_only"):
            return hold(name + " review invalid")
        if status == "hold":
            return hold(name + " review still on hold")
    return hold("synthetic reviews cannot authenticate ownership or release a durable claim")
