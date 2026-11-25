"""Original legacy protective-close proposal -> offline account-wide HOLD.

This only combines locally supplied, untrusted synthetic evidence. It does
not check actual exchange ownership, authenticate a runtime, reserve a nonce,
send orders, sign transactions, or release fences. Even coherent fixtures
remain HOLD. Never import into live executor or server.
"""
from dataclasses import dataclass

from sender_review.legacy_protective_close_capture_offline import (
    LegacyProtectiveCloseCaptureOffline,
)
from sender_review.exchange_readset_gate_offline import (
    inspect_close_reconciliation_with_readset_offline,
)


@dataclass(frozen=True)
class LegacyCloseReconciliationHandoff:
    state: str = "HOLD"
    reason: str = "no trusted exchange or workload evidence"
    synthetic_history_coherent: bool = False
    synthetic_manifest_coherent: bool = False
    runtime_identity_authenticated: bool = False
    exchange_provenance_verified: bool = False
    position_ownership_verified: bool = False
    effective_reduce_only_verified: bool = False
    nonce_reserved: bool = False
    fence_released: bool = False
    request_authorized: bool = False
    submit_authorized: bool = False
    close_authorized: bool = False
    retry_authorized: bool = False
    signing_enabled: bool = False


def inspect_legacy_close_with_synthetic_readset_offline(
    *, capture, history, readset, expected_account, expected_fence, now_epoch,
):
    """Check exact original close-capture bytes against synthetic read-set.

    A post-constructed mutable capture is not trusted. Assert that it
    contains only the one blocked close and that the size captured directly
    from the original market_close(sz=...) still agrees with the proposal.
    All successful consistency checks are diagnostics, never trade authority.
    """
    hold = LegacyCloseReconciliationHandoff()
    if (
        type(capture) is not LegacyProtectiveCloseCaptureOffline
        or capture.calls != ["legacy_market_close_blocked"]
        or type(capture.proposed_body) is not bytes
        or type(capture.captured_close_size) is not str
        or capture.position_ownership_verified is not False
        or capture.exchange_state_verified is not False
        or capture.effective_reduce_only_verified is not False
        or capture.close_authorized is not False
        or capture.submit_authorized is not False
        or capture.signing_enabled is not False
    ):
        return hold

    from sender_review.proposed_intent_interfaces_offline import (
        inspect_proposed_intent_offline,
    )
    from sender_review.worker_intent_fixture_builder_offline import (
        build_worker_intent_fixture_offline,
    )
    import json

    parsed = inspect_proposed_intent_offline(
        body=capture.proposed_body, fixture_bot=capture.fixture_bot,
    )
    if parsed.state != "parsed_review_only_HOLD" or parsed.parsed_action != "protective_close":
        return hold
    try:
        doc = json.loads(capture.proposed_body)
    except (TypeError, ValueError, UnicodeError):
        return hold
    if (
        doc["coin"] != capture.expected_coin
        or doc["request_nonce"] != capture.fixture_nonce
        or doc["position_ref"] != capture.fixture_position_ref
        or doc["side"] != capture.fixture_position_side
        or doc["exit_reason"] != capture.fixture_exit_reason
        or doc["observed_position_size"] != capture.fixture_observed_position_size
        or doc["close_size"] != capture.captured_close_size
        or doc["reduce_only"] is not True
    ):
        return hold

    canonical = build_worker_intent_fixture_offline(
        fixture_bot=capture.fixture_bot,
        action="protective_close",
        coin=capture.expected_coin, side=capture.fixture_position_side,
        request_nonce=capture.fixture_nonce,
        close_size=capture.captured_close_size,
        observed_position_size=capture.fixture_observed_position_size,
        position_ref=capture.fixture_position_ref,
        exit_reason=capture.fixture_exit_reason, reduce_only=True,
    )
    if canonical.fixture_body != capture.proposed_body:
        return hold

    verdict = inspect_close_reconciliation_with_readset_offline(
        body=capture.proposed_body, fixture_bot=capture.fixture_bot,
        history=history, readset=readset,
        expected_account=expected_account,
        expected_fence=expected_fence, now_epoch=now_epoch,
    )
    return LegacyCloseReconciliationHandoff(
        reason="synthetic fixture diagnostics only: " + verdict.reason,
        synthetic_history_coherent=verdict.fixture_reconciliation_coherent,
        synthetic_manifest_coherent=verdict.fixture_manifest_coherent,
    )
