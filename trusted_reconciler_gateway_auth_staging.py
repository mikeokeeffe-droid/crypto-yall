"""Offline staging gateway authorization; no server, secrets, or deployment.

An authenticated gateway must validate issuer/audience/signature and supply
verified claims. This module does NOT validate a JWT or authenticate callers.
"""
from dataclasses import dataclass

_ALLOWED_SCOPES = frozenset({"reconciler:position-write"})

@dataclass(frozen=True)
class VerifiedGatewayPrincipal:
    subject: str
    issuer: str
    audience: str
    scopes: frozenset[str]
    expires_at: int

def authorize_verified_principal(principal, *, expected_issuer, expected_audience, now):
    """Accept only typed, previously verified identity claims, fail closed."""
    if not isinstance(principal, VerifiedGatewayPrincipal):
        raise PermissionError("verified gateway identity required")
    if (not principal.subject or not principal.issuer or not principal.audience
            or principal.issuer != expected_issuer
            or principal.audience != expected_audience
            or not isinstance(principal.expires_at, int)
            or isinstance(principal.expires_at, bool)
            or principal.expires_at <= now
            or not isinstance(principal.scopes, frozenset)
            or not _ALLOWED_SCOPES.issubset(principal.scopes)):
        raise PermissionError("reconciler identity rejected")
    return True
