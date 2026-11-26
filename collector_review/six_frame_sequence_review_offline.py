"""OFFLINE, untrusted six-frame *ordering* fixture, never an egress gate.

No network, time source, process identity, credential, account discovery,
durable state, signer, order action or database I/O. The timestamps and frames
here are caller-supplied and cannot establish real-world freshness or origin.
A locally coherent sequence is still HOLD, never permission for testnet.
"""
from dataclasses import dataclass

from collector_review.six_frame_request_contract_offline import (
    FIXTURE_ACCOUNT, _MS_MAX, plan_synthetic_six_frame_readset_offline,
)

# Synthetic 30-second capture span is only a test fixture, NOT a runtime
# deadline. A future gateway needs independently enforced clock/sequence
# checks and durable replay prevention.
_MAX_LOCAL_SPAN_MS = 30_000


@dataclass(frozen=True)
class UntrustedObservedFrame:
    step: int
    method: str
    path: str
    body: bytes
    observed_at_ms: int


@dataclass(frozen=True)
class OfflineSequenceReview:
    state: str = "HOLD"
    reason: str = "no real transport, authenticated origin or replay evidence"
    locally_ordered: bool = False
    frames_reviewed: int = 0
    network_performed: bool = False
    origin_authenticated: bool = False
    account_authenticated: bool = False
    replay_resistant: bool = False
    trustworthy_timestamps: bool = False
    history_complete: bool = False
    position_ownership_verified: bool = False
    collection_authorized: bool = False
    order_authorized: bool = False
    close_authorized: bool = False
    signing_enabled: bool = False


def inspect_untrusted_six_frame_sequence_offline(
    *, account, start_ms, end_ms, frames,
):
    """Match exact order, canonical body bytes and monotonic fixture times.

    A complete second replay of the same six records also looks locally
    coherent: no durable nonce or independent monotonic clock exists here.
    Never rely on this fixture as a real gateway policy or access decision.
    """
    deny = OfflineSequenceReview()
    plan = plan_synthetic_six_frame_readset_offline(
        account=account, start_ms=start_ms, end_ms=end_ms)
    if (account != FIXTURE_ACCOUNT or not plan.matches_fixture
            or type(frames) is not tuple or len(frames) != 6):
        return deny
    first = last = None
    for expected, observed in zip(plan.frames, frames):
        if (type(observed) is not UntrustedObservedFrame
                or type(observed.step) is not int
                or observed.step != expected.step
                or type(observed.method) is not str
                or observed.method != expected.method
                or type(observed.path) is not str
                or observed.path != expected.path
                or type(observed.body) is not bytes
                or observed.body != expected.body
                or type(observed.observed_at_ms) is not int
                or not 0 < observed.observed_at_ms <= _MS_MAX
                or (last is not None and observed.observed_at_ms <= last)):
            return deny
        if first is None:
            first = observed.observed_at_ms
        last = observed.observed_at_ms
    if last - first > _MAX_LOCAL_SPAN_MS:
        return deny
    return OfflineSequenceReview(
        reason="six caller-supplied frames locally ordered only; timestamps, "
               "origin, durable replay prevention and all authority unverified",
        locally_ordered=True, frames_reviewed=6,
    )
