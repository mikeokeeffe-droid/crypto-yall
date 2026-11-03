"""Final offline safety boundary: synthetic evidence can never release an entry.

All review results, including a structurally perfect review_only result,
are untrusted and cannot authorize a live action or release an entry fence.
No exchange, executor, network, credentials, or database imports.
"""
from dataclasses import dataclass

@dataclass(frozen=True)
class EntryReleaseReview:
    status: str
    reason: str
    allow_entry: bool = False
    release_fence: bool = False

def inspect_synthetic_entry_release_offline(*, pipeline_review,
                                             claimed_open_orders_empty,
                                             claimed_position_verified,
                                             claimed_history_complete,
                                             claimed_source_authenticated):
    if getattr(pipeline_review, "status", None) not in ("hold", "review_only"):
        reason = "unknown or invalid upstream review"
    elif getattr(pipeline_review, "status", None) == "hold":
        reason = "upstream evidence is on hold"
    elif any(type(value) is not bool for value in (
        claimed_open_orders_empty, claimed_position_verified,
        claimed_history_complete, claimed_source_authenticated,
    )):
        reason = "invalid account or provenance claims"
    else:
        reason = "synthetic claims cannot prove account state, history or provenance"
    return EntryReleaseReview("hold", reason)
