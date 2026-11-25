"""Offline staging-only HS256 JWT verifier. No endpoint, secret loading or deployment.

A production gateway should prefer a dedicated asymmetric identity provider with
JWKS rotation, revocation controls, and restricted DB principal mapping.
"""
import time

from staging_jwt_verification import verify_signed_staging_jwt
from trusted_reconciler_gateway_auth_staging import (
    authorize_verified_principal,
)


def verify_staging_jwt(token, secret, *, issuer, audience, now=None):
    """Verify a reconciler JWT and apply only the reconciler scope policy."""
    principal = verify_signed_staging_jwt(
        token, secret, issuer=issuer, audience=audience, now=now)
    authorize_verified_principal(principal, expected_issuer=issuer,
                                 expected_audience=audience,
                                 now=int(time.time()) if now is None else now)
    return principal
