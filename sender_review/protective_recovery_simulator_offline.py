"""Deterministic, no-I/O protective-close / unknown-ACK recovery simulator.

Only synthetic fixture observations are accepted. It never authenticates
workloads, obtains exchange truth, releases fences, retries, signs, or sends.
Every outcome is a HOLD, even when the fixtures appear complete. This is not
an emergency-close mechanism, live state machine, or deployed risk control.
"""
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
import json

from sender_review.proposed_intent_interfaces_offline import (
    inspect_proposed_intent_offline,
)


@dataclass(frozen=True)
class SimulatedObservation:
    """Explicitly UNTRUSTED synthetic input; not exchange attestation."""
    bot: str
    account: str
    coin: str
    side: str
    position_ref: str
    position_size: str
    position_age_seconds: int
    owned_by_requesting_bot: bool
    fence: int
    active_nonce: str | None = None


@dataclass(frozen=True)
class SimulatedOrder:
    """Untrusted synthetic saved order/fill evidence, never trade authority."""
    nonce: str
    account: str
    coin: str
    side: str
    fence: int
    cloid: str
    status: str   # not_sent, unknown_ack, open, partial, filled, canceled
    submitted_size: str
    cumulative_fill: str
    remaining_size: str


@dataclass(frozen=True)
class RecoveryReview:
    state: str = "HOLD"
    reason: str = "insufficient trusted evidence"
    diagnostic: str = "no execution permitted"
    simulated_remaining: str | None = None
    fixture_matched: bool = False
    runtime_identity_authenticated: bool = False
    exchange_snapshot_verified: bool = False
    position_ownership_verified: bool = False
    nonce_reserved: bool = False
    fence_released: bool = False
    retry_authorized: bool = False
    close_authorized: bool = False
    submit_authorized: bool = False
    signing_enabled: bool = False


def _qty(value):
    if type(value) is not str or not 0 < len(value) <= 32:
        return None
    try:
        number = Decimal(value)
    except (InvalidOperation, ValueError):
        return None
    if not number.is_finite() or number < 0 or number > Decimal("1000000"):
        return None
    if number.as_tuple().exponent < -8:
        return None
    return number


def review_close_and_recovery_offline(
    *, body: bytes, fixture_bot: str, position: SimulatedObservation | None,
    order: SimulatedOrder | None, expected_account: str, expected_fence: int,
    max_position_age_seconds: int = 10,
    seen_nonces: frozenset[str] = frozenset(),
) -> RecoveryReview:
    """Conservatively analyze synthetic scenarios without any GO outcome.

    If a fixture says a position or an order is flat/canceled, this remains
    unauthenticated; no automatic lock release, retry, or close is possible.
    This method does not accept an arbitrary 'trusted=True' override.
    """
    hold = RecoveryReview()
    parsed = inspect_proposed_intent_offline(body=body, fixture_bot=fixture_bot)
    if parsed.state != "parsed_review_only_HOLD" or parsed.parsed_action != "protective_close":
        return RecoveryReview(reason="invalid-or-non-close-request")
    try:
        request = json.loads(body)
    except (ValueError, TypeError):
        return hold
    if (
        not isinstance(position, SimulatedObservation)
        or type(expected_account) is not str
        or type(expected_fence) is not int or expected_fence <= 0
        or type(max_position_age_seconds) is not int
        or not 0 <= max_position_age_seconds <= 60
        or type(seen_nonces) is not frozenset
    ):
        return RecoveryReview(reason="missing-scope-or-position-fixture")
    if (
        position.account != expected_account
        or position.bot != fixture_bot
        or position.coin != request["coin"]
        or position.side != request["side"]
        or position.position_ref != request["position_ref"]
        or type(position.fence) is not int or position.fence != expected_fence
        or type(position.position_age_seconds) is not int
        or position.position_age_seconds < 0
        or position.position_age_seconds > max_position_age_seconds
    ):
        return RecoveryReview(reason="stale-or-mismatched-scope")
    if position.owned_by_requesting_bot is not True:
        return RecoveryReview(reason="unproven-fixture-position-ownership")
    if request["request_nonce"] in seen_nonces:
        return RecoveryReview(reason="duplicate-request-nonce")
    if position.active_nonce not in (None, request["request_nonce"]):
        return RecoveryReview(reason="competing-active-nonce")
    current = _qty(position.position_size)
    requested = _qty(request["close_size"])
    observed = _qty(request["observed_position_size"])
    if (
        current is None or requested is None or observed is None
        or current <= 0 or requested <= 0
        or observed != current or requested > current
    ):
        return RecoveryReview(reason="stale-or-oversized-close-fixture")
    if order is None:
        # Not seeing an order is NOT evidence that it was never sent.
        return RecoveryReview(reason="missing-order-provenance")
    if not isinstance(order, SimulatedOrder):
        return RecoveryReview(reason="invalid-order-fixture")
    if (
        order.nonce != request["request_nonce"]
        or order.account != expected_account
        or order.coin != request["coin"]
        or order.side != request["side"]
        or type(order.fence) is not int
        or order.fence != expected_fence
        or type(order.cloid) is not str
        or len(order.cloid) != 34
        or not order.cloid.startswith("0x")
        or any(x not in "0123456789abcdef" for x in order.cloid[2:])
    ):
        return RecoveryReview(reason="mismatched-order-provenance")
    submitted = _qty(order.submitted_size)
    filled = _qty(order.cumulative_fill)
    remaining = _qty(order.remaining_size)
    if (
        submitted is None or filled is None or remaining is None
        or submitted <= 0 or submitted != requested
        or filled > submitted or filled + remaining != submitted
    ):
        return RecoveryReview(reason="contradictory-fill-accounting")
    if order.status == "unknown_ack":
        return RecoveryReview(reason="unknown-ack-permanent-hold",
                              simulated_remaining=str(remaining), fixture_matched=True)
    if order.status == "not_sent":
        return RecoveryReview(reason="not-sent-is-not-proof-of-safe-retry",
                              simulated_remaining=str(remaining), fixture_matched=True)
    if order.status == "partial":
        if filled <= 0 or remaining <= 0:
            return RecoveryReview(reason="contradictory-partial-status")
        return RecoveryReview(reason="partial-fill-needs-independent-reconciliation",
                              simulated_remaining=str(remaining), fixture_matched=True)
    if order.status == "filled":
        if filled != submitted or remaining != 0:
            return RecoveryReview(reason="contradictory-filled-status")
        return RecoveryReview(reason="fixture-filled-still-no-release",
                              simulated_remaining="0", fixture_matched=True)
    if order.status == "canceled":
        # A canceled remainder may coexist with a prior partial fill.
        return RecoveryReview(reason="fixture-canceled-still-no-release",
                              simulated_remaining=str(remaining), fixture_matched=True)
    if order.status == "open":
        return RecoveryReview(reason="open-order-already-outstanding",
                              simulated_remaining=str(remaining), fixture_matched=True)
    return RecoveryReview(reason="unrecognized-order-status")
