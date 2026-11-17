"""Isolated fixed-origin GitHub OIDC PUBLIC-key retrieval candidate.

NOT imported by ingress, workers, authentication preflight, or any trading
path. This is a source-review candidate for a future independent security
review, not an approved deployed runtime. It fetches only PUBLIC JSON from
two fixed GitHub HTTPS paths, with no request input, bearer token, proxy,
redirect, credential, database, wallet signer, or exchange connection.

Even a well-formed response ALWAYS means HOLD. A real authenticated sender
still needs independently verified host isolation, durable token replay,
body/account binding, cutover controls, and separate operator approval.
The existing github_oidc_public_keys_transport_review entrypoint stays inert.
"""
from dataclasses import dataclass, field
import hashlib
import http.client
import json
import ssl

from sender_review.oidc_jwks_keyset_offline import inspect_public_jwks_offline

_HOST = "token.actions.githubusercontent.com"
_ISSUER = "https://" + _HOST
_DISCOVERY_PATH = "/.well-known/openid-configuration"
_JWKS_PATH = "/.well-known/jwks"
_DISCOVERY_LIMIT = 16384
_JWKS_LIMIT = 32768


@dataclass(frozen=True)
class FixedOriginPublicKeysCandidate:
    state: str = "hold"
    reason: str = "fixed-origin public-key transport not independently approved"
    keyset_sha256: str | None = None
    public_key_count: int = 0
    # Candidate evidence only; never use as authorization.
    candidate_public_keys: dict | None = field(default=None, repr=False)
    runtime_identity_authenticated: bool = False
    authenticated_request_body: bool = False
    replay_consumed: bool = False
    request_authorized: bool = False
    submit_authorized: bool = False
    close_authorized: bool = False
    signing_enabled: bool = False


def _unique_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _reject_constant(_):
    raise ValueError("nonfinite JSON value")


def _read_fixed_public_https(path, max_bytes):
    """Bounded direct TLS public read; no redirects, proxies or caller URLs.

    Private helper only: NOT called by the live sender, existing ingress,
    or CI test executions. Unit tests patch HTTPSConnection before invocation.
    """
    if (path, max_bytes) not in (
        (_DISCOVERY_PATH, _DISCOVERY_LIMIT),
        (_JWKS_PATH, _JWKS_LIMIT),
    ):
        raise ValueError("unsupported public-key endpoint")
    context = ssl.create_default_context()
    conn = http.client.HTTPSConnection(
        _HOST, port=443, timeout=3.0, context=context,
    )
    try:
        conn.request("GET", path, headers={
            "Accept": "application/json",
            "Accept-Encoding": "identity",
            "Connection": "close",
            "User-Agent": "protected-sender-public-key-review/1.0",
        })
        response = conn.getresponse()
        # In particular, 3xx responses MUST NOT trigger a location follow.
        if type(response.status) is not int or response.status != 200:
            raise ValueError("non-200 key response")
        headers = response.getheaders()
        if type(headers) not in (tuple, list) or len(headers) > 64:
            raise ValueError("invalid response headers")
        selected = {}
        for name, value in headers:
            if (type(name) is not str or type(value) is not str
                    or len(name) > 80 or len(value) > 4096
                    or any(c in name + value for c in "\r\n\0")):
                raise ValueError("malformed response header")
            normalized = name.lower()
            if normalized in (
                "content-type", "content-length", "content-encoding",
                "transfer-encoding", "location",
            ):
                if normalized in selected:
                    raise ValueError("duplicate response header")
                selected[normalized] = value.strip().lower()
        if selected.get("content-type") not in (
            "application/json", "application/json; charset=utf-8",
        ):
            raise ValueError("wrong public key content type")
        if selected.get("content-encoding", "identity") != "identity":
            raise ValueError("unexpected content encoding")
        if "location" in selected:
            raise ValueError("unexpected redirect location")
        if selected.get("transfer-encoding", "chunked") != "chunked":
            raise ValueError("unsupported response framing")
        length = selected.get("content-length")
        if length is not None and "transfer-encoding" in selected:
            raise ValueError("conflicting response framing")
        if length is not None:
            if (not length.isascii() or not length.isdecimal()
                    or len(length) > 10 or int(length) > max_bytes
                    or int(length) == 0):
                raise ValueError("invalid response length")
        payload = response.read(max_bytes + 1)
        if (type(payload) is not bytes or not 0 < len(payload) <= max_bytes
                or (length is not None and len(payload) != int(length))):
            raise ValueError("oversized or incomplete response")
        return payload
    finally:
        conn.close()


def _valid_fixed_discovery(raw):
    if type(raw) is not bytes or not 0 < len(raw) <= _DISCOVERY_LIMIT:
        return False
    doc = json.loads(
        raw.decode("utf-8"),
        object_pairs_hook=_unique_pairs,
        parse_constant=_reject_constant,
    )
    return (
        type(doc) is dict
        and doc.get("issuer") == _ISSUER
        and doc.get("jwks_uri") == _ISSUER + _JWKS_PATH
        and type(doc.get("id_token_signing_alg_values_supported")) is list
        and "RS256" in doc["id_token_signing_alg_values_supported"]
        and all(type(x) is str
                for x in doc["id_token_signing_alg_values_supported"])
    )


def inspect_fixed_origin_public_keys_candidate():
    """Public issuer-discovery/JWKS HTTPS transport candidate; ALWAYS HOLD.

    Invoke only under a separately approved isolated public-network review;
    never from an incoming request or as a side effect of import.
    No caller controls endpoints, TLS policy, identity, or signing authority.
    """
    hold = FixedOriginPublicKeysCandidate()
    try:
        discovery = _read_fixed_public_https(
            _DISCOVERY_PATH, _DISCOVERY_LIMIT,
        )
        if not _valid_fixed_discovery(discovery):
            return hold
        raw_keys = _read_fixed_public_https(_JWKS_PATH, _JWKS_LIMIT)
        parsed = inspect_public_jwks_offline(jwks_bytes=raw_keys)
        if (parsed.state != "parsed_untrusted_public_keys_only"
                or type(parsed.fixture_public_keys) is not dict
                or not parsed.fixture_public_keys):
            return hold
        return FixedOriginPublicKeysCandidate(
            state="candidate_fixed_origin_keys_review_only_HOLD",
            reason="public TLS responses are parsable; independent runtime, "
                   "key rotation, replay fencing and host trust still unverified",
            keyset_sha256=hashlib.sha256(raw_keys).hexdigest(),
            public_key_count=len(parsed.fixture_public_keys),
            candidate_public_keys=parsed.fixture_public_keys,
        )
    except Exception:
        # Fail closed. Do not surface response bodies, exceptions or keys.
        return hold
