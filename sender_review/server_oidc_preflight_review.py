"""Non-authorizing server-side GitHub OIDC preflight; disabled by default.

This is a first boundary to replace fixture-supplied public keys and clock
with a fixed-origin HTTPS key lookup and local UTC clock. It is NOT an HTTP
server or trusted runtime deployment, and the caller's token must never
choose the issuer, JWKS URL, trust policy, audience, account or permissions.

An authenticated sender requires separate TLS ingress, deployed service
isolation, identity-to-body binding, persistent JTI/nonce replay fencing,
complete exchange reconciliation, independent review and operator approval.
Every outcome stays HOLD. Never import this into the three live executors.
"""
from dataclasses import dataclass
from dataclasses import replace
import hashlib
import time

from sender_review.github_oidc_public_keys_transport_review import (
    review_github_public_jwks_transport,
)
from sender_review.offline_oidc_identity_fixture import (
    verify_fixture_oidc_identity_offline,
)
from sender_review.remote_request_boundary_offline import (
    OFFLINE_REQUEST_POLICY,
)
from sender_review.request_contract import inspect_sender_entry_request_offline


@dataclass(frozen=True)
class ServerOidcPreflightReview:
    state: str = "hold"
    reason: str = "no approved authenticated server"
    candidate_bot: str | None = None
    candidate_jti_sha256: str | None = None
    body_sha256: str | None = None
    public_key_sha256: str | None = None
    # A candidate signature match is NOT runtime authentication.
    candidate_signature_checked: bool = False
    # NO auth, DB or trading authority exists in this preflight.
    runtime_identity_authenticated: bool = False
    authenticated_request_body: bool = False
    replay_consumed: bool = False
    durable_fence_reserved: bool = False
    verified_exchange_provenance: bool = False
    request_authorized: bool = False
    submit_authorized: bool = False
    close_authorized: bool = False
    signing_enabled: bool = False


def inspect_server_oidc_preflight_review(
    *, token, request_body, approved_readonly_key_fetch=False,
):
    """Read keys only on explicit opt-in; never send, persist or authenticate.

    This component does not accept public key bytes, the clock, a claim
    policy or account from its caller. Real host controls and independent
    approval must precede switching on even this public read-only fetch.
    """
    denied = ServerOidcPreflightReview()
    if (approved_readonly_key_fetch is not True
            or type(token) is not str
            or not 0 < len(token) <= 16000
            or type(request_body) is not bytes):
        return denied
    parsed = inspect_sender_entry_request_offline(body=request_body)
    if parsed.state != "review_only":
        return denied
    try:
        now = int(time.time())
        if now <= 0:
            return denied
        keys = review_github_public_jwks_transport(
            approved_readonly_network=True,
        )
        if (keys.state != "candidate_public_keys_observed_review_only"
                or type(keys.candidate_public_keys) is not dict
                or type(keys.keyset_sha256) is not str
                or len(keys.keyset_sha256) != 64):
            return denied
        # The fixture policy pins a fake run/attempt. A future verifier must
        # use server-side replay persistence instead. Do not adopt run ids
        # from JWT claims as expectations.
        policy = replace(
            OFFLINE_REQUEST_POLICY,
            expected_run_id=None,
            expected_run_attempt=None,
        )
        identity = verify_fixture_oidc_identity_offline(
            token=token,
            policy=policy,
            trusted_fixture_keys=keys.candidate_public_keys,
            fixture_now_seconds=now,
        )
        if identity.state != "verified_fixture_only":
            return denied
        return ServerOidcPreflightReview(
            state="candidate_signature_and_claims_reviewed_HOLD",
            reason="strict signed claims and request format pass; no trusted "
                   "sender ingress, replay fencing, host attestation or trade",
            candidate_bot=identity.fixture_bot,
            candidate_jti_sha256=hashlib.sha256(
                identity.fixture_jti.encode("ascii")
            ).hexdigest(),
            body_sha256=hashlib.sha256(request_body).hexdigest(),
            public_key_sha256=keys.keyset_sha256,
            candidate_signature_checked=True,
        )
    except (ValueError, TypeError, UnicodeError, OSError, OverflowError):
        return denied
