"""P3 offline incident triage decision table. Synthetic fixtures, NO authority.

This file is intentionally NOT an execution or recovery state machine:
no exchange reads, database, network, signer, retry, protective-close send,
nonce reservation, lock/fence release or operator approval mechanism.
A triage category is a documentation label for a human reviewer, never GO.
"""
from dataclasses import dataclass

from sender_review.protective_recovery_simulator_offline import RecoveryReview


@dataclass(frozen=True)
class OfflineRecoveryTriage:
    state: str = "HOLD"
    category: str = "untrusted-fixture"
    escalation: str = "manual-security-review"
    evidence_needed: tuple[str, ...] = (
        "independently-authenticated-workload-identity",
        "complete-authoritative-account-wide-position-order-and-fill-history",
        "verified-account-wide-fence-and-nonce-provenance",
    )
    trusted_exchange_state: bool = False
    trusted_position_ownership: bool = False
    retry_authorized: bool = False
    protective_close_authorized: bool = False
    submit_authorized: bool = False
    fence_release_authorized: bool = False


# A decision table, not a policy granting action. A synthetic "filled" or
# "canceled" result cannot be taken as proof of a flat account.
_CASES = {
    "not-sent-is-not-proof-of-safe-retry": (
        "no-send-unproven",
        ("durable-sender-attempt-history", "cross-checked-client-order-id"),
    ),
    "unknown-ack-permanent-hold": (
        "unknown-ack",
        ("full-order-status-by-client-order-id", "time-bounded-fill-history"),
    ),
    "open-order-already-outstanding": (
        "open-order",
        ("verified-live-order-set", "live-position-exposure"),
    ),
    "partial-fill-needs-independent-reconciliation": (
        "partial-exposure",
        ("cumulative-fills-from-authoritative-source",
         "remaining-exchange-native-position-size"),
    ),
    "fixture-canceled-still-no-release": (
        "canceled-unverified",
        ("cancel-ack-and-prior-fills", "independent-position-reconciliation"),
    ),
    "fixture-filled-still-no-release": (
        "filled-unverified",
        ("exchange-fill-completeness", "independent-flatness-reconciliation"),
    ),
    "duplicate-request-nonce": (
        "nonce-contention",
        ("account-wide-nonce-journal", "all-bot-order-provenance"),
    ),
    "competing-active-nonce": (
        "fence-contention",
        ("account-wide-active-fence", "all-bot-order-provenance"),
    ),
    "missing-order-provenance": (
        "missing-provenance",
        ("complete-authoritative-orders-and-fills", "durable-attempt-record"),
    ),
    "mismatched-order-provenance": (
        "conflicting-provenance",
        ("matched-account-coin-side-nonce-fence-and-client-order-id",
         "full-order-status-history"),
    ),
    "contradictory-fill-accounting": (
        "contradictory-fills",
        ("fresh-exchange-fill-ledger", "independent-position-snapshot"),
    ),
}

_COMMON_EVIDENCE = (
    "independently-authenticated-workload-identity",
    "complete-authoritative-account-wide-position-order-and-fill-history",
    "verified-account-wide-fence-and-nonce-provenance",
)


def triage_simulated_recovery_offline(review: RecoveryReview) -> OfflineRecoveryTriage:
    """Route one simulator HOLD to a non-executable review category.

    Synthetic results never become trusted data; spoofed permission or success
    fields cause an invalid-fixture HOLD, even if the reason string looks valid.
    No operator decision or exchange-side action is modeled here.
    """
    if (
        type(review) is not RecoveryReview
        or review.state != "HOLD"
        or type(review.fixture_matched) is not bool
        or any((
            review.runtime_identity_authenticated,
            review.exchange_snapshot_verified,
            review.position_ownership_verified,
            review.nonce_reserved,
            review.fence_released,
            review.retry_authorized,
            review.close_authorized,
            review.submit_authorized,
            review.signing_enabled,
        ))
    ):
        return OfflineRecoveryTriage(category="invalid-or-authorizing-input")
    entry = _CASES.get(review.reason) if type(review.reason) is str else None
    if entry is None:
        return OfflineRecoveryTriage(category="incomplete-or-invalid-fixture")
    category, extra = entry
    # Matched case labels are diagnostic only, not evidence of authenticated
    # identity, exchange fill, order ownership or safe lock release.
    if category in (
        "no-send-unproven", "unknown-ack", "open-order", "partial-exposure",
        "canceled-unverified", "filled-unverified",
    ) and not review.fixture_matched:
        return OfflineRecoveryTriage(category="incomplete-or-invalid-fixture")
    return OfflineRecoveryTriage(
        category=category, escalation="manual-exchange-reconciliation-required",
        evidence_needed=_COMMON_EVIDENCE + extra,
    )
