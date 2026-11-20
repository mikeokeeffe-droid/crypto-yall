"""Fail-closed offline classification of an interrupted *private* report publish.

Pure review fixtures: no storage read/write, no network, no recovery action,
no trading. Current-head observations are untrusted synthetic inputs; even a
matching checksum is NOT a durable private-store attestation or permission
to re-run a job, roll back state, publish, or trade.
"""
from dataclasses import dataclass

from sender_review.private_report_cas_preview_offline import (
    SimulatedPrivateHead, _valid_head,
)


@dataclass(frozen=True)
class PrivateReportRecoveryReview:
    verdict: str = "UNKNOWN_OUTCOME_HOLD"
    reason: str = "unverified report publish outcome"
    publish_complete_verified: bool = False
    automatic_retry_authorized: bool = False
    rollback_authorized: bool = False
    last_good_restored_verified: bool = False
    external_private_store_verified: bool = False
    restart_authorized: bool = False
    trading_authorized: bool = False


def classify_interrupted_private_publish_offline(
    *, prior: SimulatedPrivateHead,
    proposed: SimulatedPrivateHead,
    observed_after_failure: SimulatedPrivateHead | None,
) -> PrivateReportRecoveryReview:
    """Compare synthetic versions only, never mutate or confer authority."""
    hold = PrivateReportRecoveryReview()
    if not _valid_head(prior) or not _valid_head(proposed):
        return hold
    if (proposed.version != prior.version + 1
            or proposed.snapshot_sha256 == prior.snapshot_sha256):
        return PrivateReportRecoveryReview(
            verdict="INVALID_PROPOSAL_HOLD",
            reason="candidate digest/version is not a strict next head",
        )
    if not _valid_head(observed_after_failure):
        return hold
    if observed_after_failure == prior:
        return PrivateReportRecoveryReview(
            verdict="OLD_HEAD_OBSERVED_HOLD",
            reason="synthetic head unchanged; uncommitted staging still unverified",
        )
    if observed_after_failure == proposed:
        return PrivateReportRecoveryReview(
            verdict="PROPOSED_HEAD_OBSERVED_HOLD",
            reason="synthetic head matches intended version; persistence unverified",
        )
    return PrivateReportRecoveryReview(
        verdict="CONFLICT_OR_CORRUPTION_HOLD",
        reason="observed synthetic head is inconsistent with previous or candidate",
    )
