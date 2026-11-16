"""Review-only GitHub OIDC discovery/JWKS transport, disabled by default.

This is NOT an authentication service. A future restricted server may reuse
the pinning and HTTPS transport *after* explicit read-only network approval,
effective host isolation, security review, key-cache/rotation policy, runtime
clock, signed-claim binding and replay persistence. NEVER pass a caller's URL.
No listener, tokens, secrets, trading SDK, database, order or authorization.
"""
from dataclasses import dataclass
import hashlib
import json
import ssl
import urllib.error
import urllib.request

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


class _DenyRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        return None


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


def _exact_https_get(opener, url, limit):
    # The two URLs are constant and never come from a token, caller, header
    # or untrusted discovery document. No proxies or redirects allowed.
    if url not in (DISCOVERY_URL, JWKS_URL):
        raise ValueError("unexpected endpoint")
    request = urllib.request.Request(
        url, headers={"Accept": "application/json"}, method="GET"
    )
    with opener.open(request, timeout=5) as response:
        if (response.status != 200 or response.geturl() != url
                or response.headers.get("Content-Type", "").split(";")[0]
                .strip().lower() != "application/json"):
            raise ValueError("bad HTTPS response metadata")
        raw = response.read(limit + 1)
        if not 0 < len(raw) <= limit:
            raise ValueError("response size limit")
        return raw


def review_github_public_jwks_transport(*, approved_readonly_network=False):
    """Optional real HTTPS read, ONLY with explicit authorization elsewhere.

    This boolean cannot attest to operator approval. Even when true, the
    result cannot authenticate a bot or authorize any account operation.
    Actual runtime rollout requires independent approvals and measurement.
    """
    hold = GithubPublicKeysTransportReview()
    if approved_readonly_network is not True:
        return hold
    try:
        opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({}),
            _DenyRedirect(),
            urllib.request.HTTPSHandler(context=ssl.create_default_context()),
        )
        discovery_raw = _exact_https_get(opener, DISCOVERY_URL, 16384)
        discovery = _strict_json(discovery_raw)
        if (type(discovery) is not dict
                or discovery.get("issuer") != ISSUER
                or discovery.get("jwks_uri") != JWKS_URL):
            return hold
        jwks_raw = _exact_https_get(opener, JWKS_URL, 32768)
        parsed = inspect_public_jwks_offline(jwks_bytes=jwks_raw)
        if parsed.state != "parsed_untrusted_public_keys_only":
            return hold
        return GithubPublicKeysTransportReview(
            state="candidate_public_keys_observed_review_only",
            reason="HTTPS public-key read parsed; runtime identity, replay,"
                   " host policy, issuer/key-rotation approval NOT attested",
            keyset_sha256=hashlib.sha256(jwks_raw).hexdigest(),
            public_key_count=len(parsed.fixture_public_keys),
            candidate_public_keys=parsed.fixture_public_keys,
        )
    except (OSError, ValueError, TypeError, UnicodeError,
            urllib.error.URLError):
        return hold
