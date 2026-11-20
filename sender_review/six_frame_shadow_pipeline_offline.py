"""Wire six synthetic /info frames to a three-bot SHADOW report; always HOLD.

This is a pure, non-executable integration seam for PR #42. It contains no
collector, network, exchange authentication, issuer trust, protected sender,
signer, database, wallet, real signal provenance or order dispatch.

Caller-provided /info frames can be forged. Local frame agreement is NOT
historical completeness, current exposure, bot ownership, real protection or
permission to trade. The final boundary emits ONLY aggregate reviewer counts,
never order bodies, account/coin details or actionable close instructions.
"""
from dataclasses import dataclass
import json

from sender_review.six_frame_payload_binding_offline import (
    inspect_synthetic_info_payload_binding_offline,
)
from sender_review.composed_shadow_worker_offline import (
    inspect_shadow_worker_cycle_offline,
)
from sender_review.shadow_report_boundary_offline import (
    inspect_shadow_report_boundary_offline,
)


@dataclass(frozen=True)
class SixFrameShadowPipelineReview:
    state: str = "HOLD"
    reason: str = "no authenticated data source or executable sender"
    exact_synthetic_wiring: bool = False
    locally_consistent: bool = False
    shadow_reviewable: bool = False
    frame_count: int = 0
    close_candidate_count: int = 0
    deferred_entry_count: int = 0
    deferred_flip_count: int = 0
    locked_mutation_count: int = 0
    missing_spot_read: bool = False
    network_performed: bool = False
    exchange_origin_authenticated: bool = False
    account_scope_verified: bool = False
    historical_completeness_verified: bool = False
    position_ownership_verified: bool = False
    runtime_identity_authenticated: bool = False
    effective_reduce_only_verified: bool = False
    durable_fence_reserved: bool = False
    submit_authorized: bool = False
    close_authorized: bool = False
    signing_enabled: bool = False


def _unique_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate key")
        result[key] = value
    return result


def _reject_nonfinite(_value):
    raise ValueError("non-finite number")


def inspect_six_frame_shadow_pipeline_offline(
    *, account, start_time_ms, end_time_ms, frames, bot, signals,
    max_positions, synthetic_now_epoch, locks=(), peak_returns=None,
    pyramid_state=None, protection_only=False, protection_enabled=True,
):
    """Inspect exact six-frame fixtures, then return only inert metadata.

    Never infer account ownership, a historical flat baseline, or trusted
    snapshot freshness from local agreement. The six-frame readset omits
    spotUserState, so if the legacy equity rule needs spot data we HOLD.
    """
    denied = SixFrameShadowPipelineReview()
    binding = inspect_synthetic_info_payload_binding_offline(
        account=account, start_time_ms=start_time_ms,
        end_time_ms=end_time_ms, frames=frames,
    )
    if not (binding.exact_synthetic_wiring is True
            and binding.locally_consistent is True
            and binding.frames_reviewed == 6):
        return denied
    # The binder validates JSON, length, response type and exact requested
    # endpoint/step; reparse its two account frames without trusting any
    # separately supplied account_view (which could bypass readset checks).
    # We intentionally demand equality of ALL fields, including equity,
    # leverage, entry-price and PnL, not only net position sizes.
    try:
        before = json.loads(
            frames[0].response_body.decode("utf-8"),
            object_pairs_hook=_unique_pairs, parse_constant=_reject_nonfinite,
        )
        after = json.loads(
            frames[5].response_body.decode("utf-8"),
            object_pairs_hook=_unique_pairs, parse_constant=_reject_nonfinite,
        )
    except (TypeError, UnicodeError, ValueError, OverflowError, AttributeError):
        return denied
    if type(before) is not dict or type(after) is not dict or before != after:
        return SixFrameShadowPipelineReview(
            reason="account snapshots differ in value, leverage or PnL; HOLD",
            exact_synthetic_wiring=True, locally_consistent=True, frame_count=6,
        )
    shadow = inspect_shadow_worker_cycle_offline(
        bot=bot, user_state=before, signals=signals,
        max_positions=max_positions, locks=locks,
        synthetic_now_epoch=synthetic_now_epoch,
        peak_returns=peak_returns, pyramid_state=pyramid_state,
        protection_only=protection_only, protection_enabled=protection_enabled,
    )
    report = inspect_shadow_report_boundary_offline(cycle=shadow)
    if report.state != "METADATA_ONLY_SHADOW_REPORT_HOLD":
        return SixFrameShadowPipelineReview(
            reason="untrusted account view or shadow strategy failed closed",
            exact_synthetic_wiring=True, locally_consistent=True, frame_count=6,
            missing_spot_read=shadow.additional_spot_read_needed,
        )
    return SixFrameShadowPipelineReview(
        state="SYNTHETIC_SIX_FRAME_SHADOW_REPORT_HOLD",
        reason="locally coherent synthetic readset and three-bot shadow "
               "preview only; NO trusted exchange, history, ownership or trade",
        exact_synthetic_wiring=True, locally_consistent=True,
        shadow_reviewable=True, frame_count=6,
        close_candidate_count=report.close_candidate_count,
        deferred_entry_count=report.deferred_entry_count,
        deferred_flip_count=report.deferred_flip_count,
        locked_mutation_count=report.locked_mutation_count,
    )
