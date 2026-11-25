"""Non-executable boundary for signer-free shadow cycle review reports.

This report is deliberately NOT a request/intent builder. It discloses only
aggregate counts and non-authorizing readiness flags, never coin, action,
size, side, nonce, endpoint, authentication token, signing key, account,
position references, or close instructions. No HTTP, DB, SDK, clock, signer,
network or persisted state. A future sender MUST NOT consume this as trading
authority. Any unknown result or inconsistent count stays HOLD.
"""
from dataclasses import dataclass
from sender_review.composed_shadow_worker_offline import ShadowWorkerCycle


@dataclass(frozen=True)
class ShadowBoundaryReport:
    state: str = "HOLD"
    reason: str = "untrusted review-only shadow cycle"
    review_ready: bool = False
    close_candidate_count: int = 0
    deferred_entry_count: int = 0
    deferred_flip_count: int = 0
    locked_mutation_count: int = 0
    lock_scope_count: int = 0
    possible_pending_lock_count: int = 0
    additional_spot_read_needed: bool = False
    body: None = None
    method: None = None
    path: None = None
    authorization: None = None
    request_authorized: bool = False
    submit_authorized: bool = False
    close_authorized: bool = False
    signing_enabled: bool = False


def inspect_shadow_report_boundary_offline(*, cycle):
    """Export safe counts, not trade intent fields or executable requests."""
    hold = ShadowBoundaryReport()
    if type(cycle) is not ShadowWorkerCycle:
        return hold
    # A constructed/spoofed or corrupted cycle cannot confer review status.
    # Only an explicit, source-established HOLD type can produce counts.
    if (cycle.state != "COMPOSED_SYNTHETIC_WORKER_HOLD"
            or cycle.review_ready is not True
            or cycle.request_authorized is not False
            or cycle.submit_authorized is not False
            or cycle.close_authorized is not False
            or cycle.signing_enabled is not False
            or cycle.exchange_origin_authenticated is not False
            or cycle.position_ownership_verified is not False
            or cycle.protective_close_verified is not False
            or cycle.durable_fence_reserved is not False
            or type(cycle.additional_spot_read_needed) is not bool):
        return hold
    collections = (
        cycle.close_review_proposals, cycle.deferred_entry_proposals,
        cycle.deferred_flip_entry_proposals, cycle.locked_review_proposals,
        cycle.reentry_lock_coins, cycle.possible_pending_lock_marks,
    )
    if any(type(items) is not tuple or len(items) > 256
           for items in collections):
        return hold
    # We intentionally do not iterate over or copy the order payload
    # dictionaries. Only metadata counts cross the safe report boundary.
    if len(cycle.deferred_flip_entry_proposals) > len(
        cycle.deferred_entry_proposals
    ):
        return hold
    return ShadowBoundaryReport(
        state="METADATA_ONLY_SHADOW_REPORT_HOLD",
        reason="aggregate synthetic review counts only; no executable output",
        review_ready=True,
        close_candidate_count=len(cycle.close_review_proposals),
        deferred_entry_count=len(cycle.deferred_entry_proposals),
        deferred_flip_count=len(cycle.deferred_flip_entry_proposals),
        locked_mutation_count=len(cycle.locked_review_proposals),
        lock_scope_count=len(cycle.reentry_lock_coins),
        possible_pending_lock_count=len(cycle.possible_pending_lock_marks),
        additional_spot_read_needed=cycle.additional_spot_read_needed,
    )
