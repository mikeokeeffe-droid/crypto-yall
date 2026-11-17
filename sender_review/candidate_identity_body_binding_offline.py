"""Mock-only workload identity + exact request byte binding (never authority).

Connects the separately reviewed fixed-origin JWKS *candidate result* to
the existing strict fixture identity and request contract. Neither this
module nor the key candidate is imported by the actual ASGI ingress or
legacy workflows. It has NO HTTP, database, signer, order, replay store
or deployment path. Key provenance from mocked HTTPS is NOT sufficient
to authenticate a real GitHub workload.

The binding only records hashes of an exact synthetic request and a signed
fixture JTI. The result is irrevocably HOLD, even for matching inputs.
"""
from dataclasses import dataclass, replace
import hashlib

from sender_review.github_oidc_fixed_origin_transport_candidate import (
    FixedOriginPublicKeysCandidate,
)
from sender_review.offline_oidc_identity_fixture import (
    verify_fixture_oidc_identity_offline,
)
from sender_review.remote_request_boundary_offline import OFFLINE_REQUEST_POLICY
from sender_review.request_contract import inspect_sender_entry_request_offline


@dataclass(frozen=True)
class CandidateIdentityBodyBinding:
    state: str = "HOLD"
    reason: str = "no independently verified identity or operational replay store"
    candidate_bot: str | None = None
    body_sha256: str | None = None
    candidate_jti_sha256: str | None = None
    candidate_keyset_sha256: str | None = None
    fake_identity_and_exact_body_reviewed: bool = False
    runtime_identity_authenticated: bool = False
    exact_body_authenticated: bool = False
    replay_consumed: bool = False
    durable_fence_reserved: bool = False
    journal_recorded: bool = False
    submit_authorized: bool = False
    close_authorized: bool = False
    signing_enabled: bool = False


def inspect_candidate_identity_body_binding_offline(
    *, token, request_body, candidate_keys, fixture_now_seconds,
):
    """Review mock RSA fixture signature and exact bytes; never issue GO.

    Public keys and fixture clock remain input to an OFFLINE preview, not
    a trusted server-side source. Caller cannot choose the expected repo,
    audience or bot identity. No request supplied by this function can
    authorize an exchange order or bind a real user account.
    """
    hold = CandidateIdentityBodyBinding()
    if (type(token) is not str or not 0 < len(token) <= 16000
            or type(request_body) is not bytes
            or type(fixture_now_seconds) is not int
            or type(candidate_keys) is not FixedOriginPublicKeysCandidate
            or candidate_keys.state != "candidate_fixed_origin_keys_review_only_HOLD"
            or type(candidate_keys.keyset_sha256) is not str
            or len(candidate_keys.keyset_sha256) != 64
            or any(c not in "0123456789abcdef"
                   for c in candidate_keys.keyset_sha256)
            or type(candidate_keys.candidate_public_keys) is not dict
            or candidate_keys.public_key_count != len(
                candidate_keys.candidate_public_keys
            ) or not 0 < candidate_keys.public_key_count <= 16
            or candidate_keys.runtime_identity_authenticated is not False
            or candidate_keys.submit_authorized is not False
            or candidate_keys.close_authorized is not False
            or candidate_keys.signing_enabled is not False):
        return hold
    try:
        contract = inspect_sender_entry_request_offline(body=request_body)
        if contract.state != "review_only":
            return hold
        # The run/attempt pins were synthetic in the earlier fixture policy.
        # Do not trust a token's self-asserted run ID as external approval.
        fixture_policy = replace(
            OFFLINE_REQUEST_POLICY,
            expected_run_id=None, expected_run_attempt=None,
        )
        identity = verify_fixture_oidc_identity_offline(
            token=token, policy=fixture_policy,
            trusted_fixture_keys=candidate_keys.candidate_public_keys,
            fixture_now_seconds=fixture_now_seconds,
        )
        if (identity.state != "verified_fixture_only"
                or identity.fixture_bot not in ("daily", "intraday", "aggressive")
                or type(identity.fixture_jti) is not str):
            return hold
        return CandidateIdentityBodyBinding(
            state="SYNTHETIC_IDENTITY_EXACT_BODY_HOLD",
            reason="mock public key and fixture identity matched exact body; "
                   "issuer provenance, runtime identity, replay and trade denied",
            candidate_bot=identity.fixture_bot,
            candidate_jti_sha256=hashlib.sha256(
                identity.fixture_jti.encode("ascii")
            ).hexdigest(),
            body_sha256=hashlib.sha256(request_body).hexdigest(),
            candidate_keyset_sha256=candidate_keys.keyset_sha256,
            fake_identity_and_exact_body_reviewed=True,
        )
    except (ValueError, TypeError, OverflowError, UnicodeError):
        return hold
