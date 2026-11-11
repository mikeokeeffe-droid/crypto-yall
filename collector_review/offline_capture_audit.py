"""Offline-only, hash-chained evidence review for the testnet /info collector.

An audit record binds SYNTHETIC, caller-supplied request/response bytes and
times. SHA-256 protects against accidental modification relative to an
independently retained digest; it does NOT authenticate Hyperliquid, prove
account ownership, prevent rewriting a whole chain, or establish complete
order/fill history. No networking, storage, signer or trading imports.
"""
from dataclasses import asdict, dataclass
import hashlib
import json
import re

from collector_review.testnet_info_https import (
    ENDPOINT, MAX_BYTES, prepare_testnet_info_body,
    review_untrusted_http_capture,
)

GENESIS = "0" * 64
_SHA = re.compile(r"[0-9a-f]{64}\Z", re.ASCII)


@dataclass(frozen=True)
class OfflineAuditEvent:
    version: int
    environment: str
    endpoint: str
    account: str
    request_type: str
    sequence: int
    observed_at_ms: int
    previous_sha256: str
    request_sha256: str
    response_sha256: str
    http_status: int
    response_bytes: int
    elapsed_ms: int
    review_state: str
    event_sha256: str
    origin_authenticated: bool = False
    history_complete: bool = False
    ownership_verified: bool = False
    submit_authorized: bool = False


@dataclass(frozen=True)
class OfflineAuditChainReview:
    state: str = "hold"
    reason: str = "unverified synthetic audit chain"
    last_sha256: str | None = None
    events: int = 0
    origin_authenticated: bool = False
    history_complete: bool = False
    ownership_verified: bool = False
    submit_authorized: bool = False


def _digest_event(event):
    d = asdict(event)
    d.pop("event_sha256")
    canonical = json.dumps(d, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(canonical).hexdigest()


def _valid_event(event):
    if type(event) is not OfflineAuditEvent:
        return False
    if (type(event.version) is not int or event.version != 1
            or event.environment != "testnet" or event.endpoint != ENDPOINT
            or type(event.sequence) is not int or event.sequence < 1
            or type(event.observed_at_ms) is not int or event.observed_at_ms < 1
            or type(event.request_sha256) is not str
            or _SHA.fullmatch(event.request_sha256) is None
            or type(event.response_sha256) is not str
            or _SHA.fullmatch(event.response_sha256) is None
            or type(event.previous_sha256) is not str
            or _SHA.fullmatch(event.previous_sha256) is None
            or type(event.http_status) is not int
            or not 100 <= event.http_status <= 599
            or type(event.response_bytes) is not int
            or not 0 <= event.response_bytes <= MAX_BYTES + 1
            or type(event.elapsed_ms) is not int
            or not 0 <= event.elapsed_ms <= 10000
            or event.review_state not in ("hold", "fixture_only")
            or event.origin_authenticated is not False
            or event.history_complete is not False
            or event.ownership_verified is not False
            or event.submit_authorized is not False):
        return False
    body = prepare_testnet_info_body(
        account=event.account, kind=event.request_type)
    return (
        body is not None
        and event.request_sha256 == hashlib.sha256(body).hexdigest()
        and type(event.event_sha256) is str
        and event.event_sha256 == _digest_event(event)
    )


def append_offline_audit_event(*, account, kind, request_body, response_body,
                               status_code, content_type, content_encoding,
                               elapsed_ms, observed_at_ms, sequence,
                               previous=None):
    """Pure offline record builder; fail closed for invalid scope/clock/chain."""
    body = prepare_testnet_info_body(account=account, kind=kind)
    if (body is None or type(request_body) is not bytes
            or request_body != body or type(response_body) is not bytes
            or len(response_body) > MAX_BYTES + 1
            or type(status_code) is not int
            or not 100 <= status_code <= 599
            or type(elapsed_ms) is not int or not 0 <= elapsed_ms <= 10000
            or type(observed_at_ms) is not int or observed_at_ms <= 0
            or type(sequence) is not int or sequence <= 0):
        return None

    if previous is None:
        if sequence != 1:
            return None
        prior_hash = GENESIS
    else:
        if (not _valid_event(previous) or sequence != previous.sequence + 1
                or observed_at_ms <= previous.observed_at_ms
                or account != previous.account):
            return None
        prior_hash = previous.event_sha256

    review = review_untrusted_http_capture(
        account=account, kind=kind, sent_body=request_body,
        raw_body=response_body, status_code=status_code,
        content_type=content_type, content_encoding=content_encoding,
        elapsed_ms=elapsed_ms,
    )
    initial = OfflineAuditEvent(
        version=1, environment="testnet", endpoint=ENDPOINT,
        account=account, request_type=kind, sequence=sequence,
        observed_at_ms=observed_at_ms, previous_sha256=prior_hash,
        request_sha256=hashlib.sha256(request_body).hexdigest(),
        response_sha256=hashlib.sha256(response_body).hexdigest(),
        http_status=status_code, response_bytes=len(response_body),
        elapsed_ms=elapsed_ms, review_state=review.state, event_sha256="",
    )
    from dataclasses import replace
    return replace(initial, event_sha256=_digest_event(initial))


def review_offline_audit_chain(*, events, expected_account,
                               expected_head_sha256=None):
    """Check supplied chain consistency; no verification of external origin."""
    def hold(reason):
        return OfflineAuditChainReview(reason=reason)

    if type(events) not in (tuple, list) or not events or len(events) > 10000:
        return hold("empty or oversized event sequence")
    if expected_head_sha256 is not None and (
            type(expected_head_sha256) is not str
            or _SHA.fullmatch(expected_head_sha256) is None):
        return hold("invalid external head digest")
    previous = None
    had_hold = False
    for i, event in enumerate(events, start=1):
        if (not _valid_event(event) or event.sequence != i
                or event.account != expected_account):
            return hold("invalid, spoofed, or changed synthetic event")
        if previous is None:
            if event.previous_sha256 != GENESIS:
                return hold("missing genesis")
        elif (event.previous_sha256 != previous.event_sha256
              or event.observed_at_ms <= previous.observed_at_ms):
            return hold("gap, replay, stale timestamp, or chain fork")
        had_hold |= event.review_state != "fixture_only"
        previous = event
    if (expected_head_sha256 is not None
            and previous.event_sha256 != expected_head_sha256):
        return hold("head mismatch against supplied external digest")
    return OfflineAuditChainReview(
        state="hold" if had_hold else "fixture_only",
        reason=("failed capture(s) remain HOLD" if had_hold
                else "synthetic hash continuity only; no origin authentication"),
        last_sha256=previous.event_sha256, events=len(events),
    )
