"""Offline GitHub OIDC public-key review; network permanently disabled.

This is NOT an authentication service. No caller Boolean can fetch keys.
All actual HTTPS key retrieval must be introduced in a separate approved
change, after runtime isolation, independent review and operator approval.
No listener, tokens, secrets, trading SDK, database, order or authorization.
"""
from dataclasses import dataclass
import json

from sender_review.oidc_jwks_keyset_offline import inspect_public_jwks_offline

ISSUER = "https://token.actions.githubusercontent.com"
DISCOVERY_URL = ISSUER + "/.well-known/openid-configuration"
JWKS_URL = ISSUER + "/.well-known/jwks"


@dataclass(frozen=True)
class GithubPublicKeysTransportReview:
    state: str = "hold"
    reason: str = "read-only network access not approved"
    keyset_sha256: str | None = None
    public_key_count: int = 0
    # This is *only* candidate public-key data; no runtime trust is claimed.
    candidate_public_keys: dict | None = None
    issuer_authenticated: bool = False
    trusted_runtime_identity: bool = False
    replay_consumed: bool = False
    authorization_granted: bool = False
    signing_enabled: bool = False
    submit_authorized: bool = False
    close_authorized: bool = False


def _strict_json(raw):
    def unique(items):
        obj = {}
        for k, v in items:
            if k in obj:
                raise ValueError("duplicate discovery field")
            obj[k] = v
        return obj

    def bad_constant(_):
        raise ValueError("nonfinite JSON constant")

    return json.loads(raw.decode("utf-8"),
                      object_pairs_hook=unique, parse_constant=bad_constant)


def review_github_public_jwks_transport(*, approved_readonly_network=False):
    """Always deny outbound HTTPS until an independent reviewed implementation.

    Candidate public keys may still be validated by
    inspect_public_jwks_offline() on separately supplied fixture bytes.
    A caller Boolean is NOT an authorization or an egress boundary.
    """
    return GithubPublicKeysTransportReview()
