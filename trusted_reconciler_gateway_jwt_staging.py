"""Offline staging-only HS256 JWT verifier. No endpoint, secret loading or deployment.

A production gateway should prefer a dedicated asymmetric identity provider with
JWKS rotation, revocation controls, and restricted DB principal mapping.
"""
import base64
import hashlib
import hmac
import json
import time

from trusted_reconciler_gateway_auth_staging import (
    VerifiedGatewayPrincipal, authorize_verified_principal,
)

def _decode(segment):
    if not isinstance(segment, str) or not segment or len(segment) > 8192:
        raise PermissionError("invalid token segment")
    try:
        return base64.b64decode(segment + "=" * (-len(segment) % 4),
                                altchars=b"-_", validate=True)
    except (ValueError, base64.binascii.Error):
        raise PermissionError("invalid token encoding") from None

def verify_staging_jwt(token, secret, *, issuer, audience, now=None):
    """Verify signature and essential claims; never accept caller-supplied claims."""
    if not isinstance(token, str) or len(token) > 16384 or any(ch.isspace() for ch in token):
        raise PermissionError("invalid token")
    if not isinstance(secret, bytes) or len(secret) < 32:
        raise ValueError("staging signing key must contain at least 32 bytes")
    parts = token.split(".")
    if len(parts) != 3:
        raise PermissionError("invalid token structure")
    def reject_duplicate_claims(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate token field")
            result[key] = value
        return result
    try:
        header = json.loads(_decode(parts[0]), object_pairs_hook=reject_duplicate_claims)
        payload = json.loads(_decode(parts[1]), object_pairs_hook=reject_duplicate_claims)
        signature = _decode(parts[2])
    except (ValueError, TypeError, UnicodeDecodeError):
        raise PermissionError("invalid token JSON") from None
    if (not isinstance(header, dict) or set(header) != {"alg", "typ"}
            or header.get("alg") != "HS256" or header.get("typ") != "JWT"):
        raise PermissionError("unexpected signing algorithm")
    if not isinstance(payload, dict):
        raise PermissionError("invalid claims")
    expected = hmac.new(secret, (parts[0] + "." + parts[1]).encode("ascii"),
                        hashlib.sha256).digest()
    if not hmac.compare_digest(signature, expected):
        raise PermissionError("invalid signature")
    clock = int(time.time()) if now is None else now
    if not isinstance(clock, int) or isinstance(clock, bool):
        raise PermissionError("invalid clock")
    issued = payload.get("iat")
    not_before = payload.get("nbf")
    if (not isinstance(issued, int) or isinstance(issued, bool)
            or not isinstance(not_before, int) or isinstance(not_before, bool)
            or issued > clock or not_before > clock):
        raise PermissionError("invalid token timing")
    scopes = payload.get("scope")
    if not isinstance(scopes, str):
        raise PermissionError("invalid token scope")
    principal = VerifiedGatewayPrincipal(
        subject=payload.get("sub"), issuer=payload.get("iss"),
        audience=payload.get("aud"), scopes=frozenset(scopes.split()),
        expires_at=payload.get("exp"))
    authorize_verified_principal(principal, expected_issuer=issuer,
                                 expected_audience=audience, now=clock)
    return principal
