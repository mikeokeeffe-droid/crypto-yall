"""Offline composition of public JWKS parsing and fake signed HTTP review.

No network/issuer discovery, TLS, trusted key provenance, clock, DB, signer,
wallet or exchange. Public JWKS bytes MUST NOT come from a caller/request;
they are synthetic harness material here. This module NEVER authorizes
trading, remote identity, persistence, retries, close or deployment.
"""
from dataclasses import dataclass

from sender_review.oidc_jwks_keyset_offline import inspect_public_jwks_offline
from sender_review.remote_request_boundary_offline import (
    inspect_signed_remote_request_offline,
)


@dataclass(frozen=True)
class OfflineJwksRequestReview:
    state: str = "hold"
    reason: str = "no verified issuer origin, transport or runtime identity"
    fixture_bot: str | None = None
    request_sha256: str | None = None
    public_keyset_parsed: bool = False
    fixture_signature_checked: bool = False
    runtime_identity_authenticated: bool = False
    tls_peer_authenticated: bool = False
    issuer_jwks_verified: bool = False
    key_rotation_verified: bool = False
    replay_consumed: bool = False
    journal_recorded: bool = False
    request_authorized: bool = False
    submit_authorized: bool = False
    close_authorized: bool = False
    signing_enabled: bool = False


def inspect_remote_with_public_jwks_fixture_offline(
    *, issuer_fixture_jwks_bytes, method, path, headers, body,
    fixture_now_seconds,
):
    """Join two inert parsers; all resulting authorization flags stay false.

    The fixture-only JWKS is an explicitly independent input, NOT taken
    from the HTTP envelope or token. It has no authentic provenance.
    Unknown/rotated key IDs, invalid JWTs or invalid envelopes remain HOLD.
    """
    hold = OfflineJwksRequestReview()
    jwks = inspect_public_jwks_offline(jwks_bytes=issuer_fixture_jwks_bytes)
    if jwks.state != "parsed_untrusted_public_keys_only":
        return hold
    request = inspect_signed_remote_request_offline(
        method=method, path=path, headers=headers, body=body,
        trusted_fixture_keys=jwks.fixture_public_keys,
        fixture_now_seconds=fixture_now_seconds,
    )
    if request.state != "signed_fixture_review_only":
        return OfflineJwksRequestReview(public_keyset_parsed=True)
    return OfflineJwksRequestReview(
        state="signed_jwks_fixture_review_only_HOLD",
        reason="synthetic JWKS signed request parsed; no trusted issuer "
               "origin, HTTPS, runtime auth, persistent replay or trading",
        fixture_bot=request.fixture_bot,
        request_sha256=request.request_sha256,
        public_keyset_parsed=True,
        fixture_signature_checked=True,
    )
