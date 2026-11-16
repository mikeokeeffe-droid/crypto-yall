"""Strict GitHub OIDC JWKS public-key adapter; OFFLINE REVIEW ONLY.

Accepts PUBLIC JWK bytes purportedly obtained from an issuer, but it has
NO network, DNS, TLS, discovery, cache freshness, trusted issuer provenance,
server clock, workload authorization, exchange access, signer, or database.
NEVER accept a JWKS supplied in an incoming request. A future trusted server
must authenticate the GitHub discovery/JWKS origin and key rotation before
passing verified issuer-owned bytes to this parser. A valid key set is never
proof of GitHub provenance and is NEVER permission to trade.
"""
import base64
from dataclasses import dataclass
import json
import re

_KID = re.compile(r"[A-Za-z0-9._:-]{1,128}\Z", re.ASCII)
_B64 = re.compile(r"[A-Za-z0-9_-]+\Z", re.ASCII)
_PRIVATE = frozenset(("d", "p", "q", "dp", "dq", "qi", "oth", "k"))
# Only public RSA signing keys are supported by the current RS256 verifier.
_ALLOWED_FIELDS = frozenset((
    "kty", "kid", "use", "key_ops", "alg", "n", "e",
    "x5c", "x5t", "x5t#S256",
))


@dataclass(frozen=True)
class OfflineJwksKeysetReview:
    state: str = "hold"
    reason: str = "issuer JWKS provenance unverified"
    # Dictionary used ONLY for the existing offline fixture JWT verifier.
    # The caller must never promote the result to authentication authority.
    fixture_public_keys: dict | None = None
    real_issuer_keys_authenticated: bool = False
    tls_origin_verified: bool = False
    cache_freshness_verified: bool = False
    runtime_identity_authenticated: bool = False
    request_authorized: bool = False
    submit_authorized: bool = False
    close_authorized: bool = False
    signing_enabled: bool = False


def _unique_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON property")
        result[key] = value
    return result


def _reject_constant(_):
    raise ValueError("nonfinite JSON number")


def _positive_uint(segment, max_chars):
    if (type(segment) is not str or not 1 <= len(segment) <= max_chars
            or _B64.fullmatch(segment) is None):
        raise ValueError("invalid JWK integer")
    value = base64.urlsafe_b64decode(segment + "=" * (-len(segment) % 4))
    if (not value or value[0] == 0
            or base64.urlsafe_b64encode(value).rstrip(b"=").decode() != segment):
        raise ValueError("noncanonical JWK integer")
    return int.from_bytes(value, "big")


def inspect_public_jwks_offline(*, jwks_bytes):
    """Parse a bounded RSA signing keyset; never assert issuer authenticity.

    Keys must be provisioned by a SEPARATE trusted server-side component,
    not by a token, request header, runner, or request JSON. This parser
    rejects duplicate kids and private material; it never returns a GO state.
    """
    hold = OfflineJwksKeysetReview()
    if type(jwks_bytes) is not bytes or not 0 < len(jwks_bytes) <= 32768:
        return hold
    try:
        doc = json.loads(
            jwks_bytes.decode("utf-8"),
            object_pairs_hook=_unique_pairs,
            parse_constant=_reject_constant,
        )
        if type(doc) is not dict or set(doc) != {"keys"}:
            return hold
        entries = doc["keys"]
        if type(entries) is not list or not 1 <= len(entries) <= 16:
            return hold
        keys = {}
        for jwk in entries:
            if (type(jwk) is not dict
                    or not {"kty", "kid", "n", "e"} <= set(jwk)
                    or not set(jwk) <= _ALLOWED_FIELDS
                    or set(jwk) & _PRIVATE
                    or jwk["kty"] != "RSA"
                    or type(jwk["kid"]) is not str
                    or _KID.fullmatch(jwk["kid"]) is None
                    or jwk["kid"] in keys
                    or jwk.get("use", "sig") != "sig"
                    or jwk.get("alg", "RS256") != "RS256"):
                return hold
            ops = jwk.get("key_ops")
            if ops is not None and (type(ops) is not list
                                    or ops != ["verify"]):
                return hold
            n = _positive_uint(jwk["n"], 800)
            e = _positive_uint(jwk["e"], 10)
            if not 2048 <= n.bit_length() <= 4096 or e != 65537:
                return hold
            # Allow standard public certificate metadata, but never use
            # x5c as an alternative source of issuer trust or key material.
            for field in ("x5t", "x5t#S256"):
                if field in jwk and (type(jwk[field]) is not str
                                     or not 1 <= len(jwk[field]) <= 128):
                    return hold
            if "x5c" in jwk and (type(jwk["x5c"]) is not list
                                or not 1 <= len(jwk["x5c"]) <= 4
                                or any(type(x) is not str or len(x) > 8192
                                       for x in jwk["x5c"])):
                return hold
            keys[jwk["kid"]] = (n, e)
        return OfflineJwksKeysetReview(
            state="parsed_untrusted_public_keys_only",
            reason="RSA JWKS syntax valid; origin, cache, rotation and "
                   "runtime workload identity NOT verified",
            fixture_public_keys=keys,
        )
    except (ValueError, UnicodeError, TypeError, OverflowError):
        return hold
