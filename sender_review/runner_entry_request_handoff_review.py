"""Review-only bot-entry -> signed HTTP envelope handoff; NO I/O.

A future GitHub Actions worker will need to send an entry intent to a
separately authenticated, exclusively privileged protected sender. This
module joins the *existing* signer-free entry fixture builder and HTTP
contract without changing any live bot. The supplied token is UNTRUSTED:
its apparent JWT shape does not establish GitHub origin, audience, identity
or safety. No network, DB, exchange client, signer, secrets or trade path.
It intentionally cannot produce pyramid, leverage, or close operations.
A separate offline adapter can compare existing legacy entry-sizing capture
bytes to this strict request format. That comparison never grants authority.
"""
from dataclasses import dataclass, field
import hashlib
import json
import re

from sender_review.worker_intent_fixture_builder_offline import (
    build_worker_intent_fixture_offline,
)
from sender_review.legacy_order_capture_preview import LegacyOrderCapturePreview
from sender_review.request_contract import inspect_sender_entry_request_offline
from sender_review.testnet_only_scope_offline import inspect_testnet_only_scope_offline

_JWT_SHAPE = re.compile(
    r"[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\Z", re.ASCII
)
_PATH = "/v1/review-only/entry-intents"


@dataclass(frozen=True)
class RunnerEntryHandoffReview:
    state: str = "hold"
    reason: str = "no trusted GitHub identity or remote sender"
    method: str | None = None
    path: str | None = None
    # Never log authentication tokens or the Authorization envelope.
    headers: tuple | None = field(default=None, repr=False, compare=False)
    body: bytes | None = field(default=None, repr=False, compare=False)
    body_sha256: str | None = None
    fixture_bot: str | None = None
    # No function may set these to true, including on syntactically valid data.
    identity_authenticated: bool = False
    server_authenticated: bool = False
    nonce_reserved: bool = False
    journal_recorded: bool = False
    account_scope_verified: bool = False
    exchange_state_verified: bool = False
    request_authorized: bool = False
    submit_authorized: bool = False
    close_authorized: bool = False
    signing_enabled: bool = False


def prepare_runner_entry_handoff_review_only(
    *, candidate_runner_jwt, fixture_bot, action, coin, side,
    request_nonce, rounded_size, requested_leverage,
):
    """Build exact request bytes for a future server, but NEVER send them.

    The only present consumer is offline mock-boundary tests. Do not use
    this in any original executor or GitHub trading workflow. Only the
    independently verified server may authenticate claims and bind scope.
    """
    denied = RunnerEntryHandoffReview()
    if (type(candidate_runner_jwt) is not str
            or not 100 <= len(candidate_runner_jwt) <= 16000
            or _JWT_SHAPE.fullmatch(candidate_runner_jwt) is None):
        return denied
    if type(action) is not str or action not in ("open_long", "open_short"):
        return denied
    draft = build_worker_intent_fixture_offline(
        fixture_bot=fixture_bot, action=action, coin=coin, side=side,
        request_nonce=request_nonce, rounded_size=rounded_size,
        requested_leverage=requested_leverage,
    )
    if draft.state != "fixture_body_review_only_HOLD":
        return denied
    body = draft.fixture_body
    return RunnerEntryHandoffReview(
        state="unsigned_authority_runner_handoff_review_only_HOLD",
        reason="request shape constructed; token untrusted, no transport or trade",
        method="POST",
        path=_PATH,
        headers=(
            ("Authorization", "Bearer " + candidate_runner_jwt),
            ("Content-Type", "application/json"),
        ),
        body=body,
        body_sha256=hashlib.sha256(body).hexdigest(),
        fixture_bot=fixture_bot,
    )


def prepare_captured_legacy_entry_handoff_review_only(
    *, capture, candidate_runner_jwt,
):
    """Compare an isolated legacy ENTRY-sizing capture to exact envelope bytes.

    A capture is caller-controlled synthetic data, not workload identity,
    position ownership, an actual order or authority to trade. Check the
    captured strategy and record before re-creating canonical entry bytes.
    Pyramid, leverage-only, and close intents never enter this S1 adapter.
    No networking, database, exchange SDK, signer or secret read occurs.
    """
    denied = RunnerEntryHandoffReview()
    if (
        type(capture) is not LegacyOrderCapturePreview
        or capture.expected_action not in ("open_long", "open_short")
        or capture.proposed_action != capture.expected_action
        or type(capture.proposed_body) is not bytes
        or capture.calls != ["reviewed_leverage_only", "entry_proposal_only"]
        or capture.fixture_parent_position_ref is not None
        or type(capture.observed_coin) is not str
        or type(capture.observed_leverage) is not int
        or capture.signing_enabled is not False
        or capture.submit_authorized is not False
        or capture.close_authorized is not False
        or capture.leverage_authorized is not False
    ):
        return denied
    parsed = inspect_sender_entry_request_offline(
        body=capture.proposed_body, asserted_bot=capture.fixture_bot,
    )
    if parsed.state != "review_only":
        return denied
    try:
        # The strict entry parser has rejected any duplicates/extra fields.
        doc = json.loads(capture.proposed_body)
    except (ValueError, TypeError, UnicodeError):
        return denied
    if (
        doc["action"] != capture.expected_action
        or doc["coin"] != capture.observed_coin
        or doc["request_nonce"] != capture.fixture_nonce
        or doc["requested_leverage"] != capture.observed_leverage
    ):
        return denied
    envelope = prepare_runner_entry_handoff_review_only(
        candidate_runner_jwt=candidate_runner_jwt,
        fixture_bot=capture.fixture_bot,
        action=capture.expected_action,
        coin=capture.observed_coin,
        side=doc["side"],
        request_nonce=capture.fixture_nonce,
        rounded_size=doc["rounded_size"],
        requested_leverage=capture.observed_leverage,
    )
    if envelope.body != capture.proposed_body:
        return denied
    return envelope

def prepare_testnet_only_runner_entry_handoff_review_only(
    *, proposed_network, proposed_api_url=None, candidate_runner_jwt,
    fixture_bot, action, coin, side, request_nonce, rounded_size,
    requested_leverage,
):
    """Fail-closed Testnet review scope around the existing no-send handoff.

    No environment flag or URL can select Mainnet. This only checks caller-
    supplied test metadata; it is NOT a server-side environment restriction,
    authenticated identity, trusted endpoint, or permission to send an order.
    The real protected sender is not wired to this interface.
    """
    scope = inspect_testnet_only_scope_offline(
        proposed_network=proposed_network,
        proposed_api_url=proposed_api_url,
    )
    if scope.state != "REVIEW_ONLY_HOLD" or not scope.candidate_parsed:
        return RunnerEntryHandoffReview()
    return prepare_runner_entry_handoff_review_only(
        candidate_runner_jwt=candidate_runner_jwt,
        fixture_bot=fixture_bot,
        action=action,
        coin=coin,
        side=side,
        request_nonce=request_nonce,
        rounded_size=rounded_size,
        requested_leverage=requested_leverage,
    )
