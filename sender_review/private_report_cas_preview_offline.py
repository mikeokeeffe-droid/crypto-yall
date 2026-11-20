"""Pure offline preview of private report compare-and-swap serialization.

No storage, network, clocks, Git, filesystem, subprocess, Gists, exchange or
signing. Report contents are never included in the result. A simulated head is
NOT proof that a durable compare-and-swap, private ACL or publication occurred.
"""
from dataclasses import dataclass, field
import datetime as dt
import hashlib
import re

from sender_review.isolated_report_handoff_offline import (
    review_private_report_handoff_offline,
)

_MAX_VERSION = 1_000_000_000
_HEX_SHA256 = re.compile(r"[0-9a-f]{64}", flags=re.ASCII)


@dataclass(frozen=True)
class SimulatedPrivateHead:
    version: int
    snapshot_sha256: str = field(repr=False)


@dataclass(frozen=True)
class PrivateReportCasPreview:
    verdict: str = "HOLD"
    reason: str = "untrusted offline report state"
    proposed_next_head: SimulatedPrivateHead | None = field(
        default=None, repr=False
    )
    report_published: bool = False
    private_store_verified: bool = False
    actual_atomicity_verified: bool = False
    trading_authorized: bool = False
    may_modify_main: bool = False


def _valid_head(head):
    return (type(head) is SimulatedPrivateHead
            and type(head.version) is int
            and 0 <= head.version < _MAX_VERSION
            and type(head.snapshot_sha256) is str
            and _HEX_SHA256.fullmatch(head.snapshot_sha256) is not None)


def preview_private_report_cas_offline(
    *, current_head: SimulatedPrivateHead,
    observed_head: SimulatedPrivateHead,
    previous: bytes, candidate: bytes, now: dt.datetime,
) -> PrivateReportCasPreview:
    """Preview an optimistic CAS, always without persistence or authority.

    A writer that read an earlier version must refuse after any other writer
    advances the simulated current head. Exact-byte history continuity is only
    synthetic and does not verify independently stored reports.
    """
    if not _valid_head(current_head) or not _valid_head(observed_head):
        return PrivateReportCasPreview()
    if current_head != observed_head:
        return PrivateReportCasPreview(
            verdict="CONFLICT_HOLD",
            reason="another simulated writer advanced the report head",
        )
    if type(previous) is not bytes or type(candidate) is not bytes:
        return PrivateReportCasPreview()
    if hashlib.sha256(previous).hexdigest() != observed_head.snapshot_sha256:
        return PrivateReportCasPreview(
            verdict="BASE_DIGEST_MISMATCH_HOLD",
            reason="supplied prior bytes do not match the simulated head",
        )
    reviewed = review_private_report_handoff_offline(
        previous=previous, candidate=candidate, now=now,
    )
    if reviewed.verdict != "CONTINUITY_METADATA_ONLY_HOLD":
        return PrivateReportCasPreview(
            verdict="CONTINUITY_HOLD",
            reason="synthetic private report history check refused",
        )
    candidate_digest = hashlib.sha256(candidate).hexdigest()
    if candidate_digest == current_head.snapshot_sha256:
        return PrivateReportCasPreview(
            verdict="DUPLICATE_HOLD",
            reason="no distinct candidate to review",
        )
    return PrivateReportCasPreview(
        verdict="CAS_PREVIEW_ONLY_HOLD",
        reason="synthetic version increment only, not a private-store write",
        proposed_next_head=SimulatedPrivateHead(
            version=current_head.version + 1,
            snapshot_sha256=candidate_digest,
        ),
    )
