"""Review-only bot-entry -> signed HTTP envelope handoff; NO I/O.

A future GitHub Actions worker will need to send an entry intent to a
separately authenticated, exclusively privileged protected sender. This
module joins the *existing* signer-free entry fixture builder and HTTP
contract without changing any live bot. The supplied token is UNTRUSTED:
its apparent JWT shape does not establish GitHub origin, audience, identity
or safety. No network, DB, exchange client, signer, secrets or trade path.
It intentionally cannot produce pyramid, leverage, or close operations.
"""
from dataclasses import dataclass, field
import hashlib
import re

from sender_review.worker_intent_fixture_builder_offline import (
    build_worker_intent_fixture_offline,
)

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
