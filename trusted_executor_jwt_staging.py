"""Fail-closed staging-only JWT authentication for the three executors."""
from dataclasses import dataclass
from collections.abc import Mapping

from staging_executor_gateway_contract import BOTS
from staging_jwt_verification import verify_signed_staging_jwt

EXECUTOR_ENTRY_SCOPE = "executor:entry"


@dataclass(frozen=True)
class VerifiedExecutorPrincipal:
    bot: str
    subject: str
    issuer: str
    audience: str
    scopes: frozenset[str]
    expires_at: int


def verify_executor_jwt(token, signing_keys, *, bot, issuer, audience, now=None):
    """Verify a bot-bound token using that bot's distinct staging key."""
    if type(bot) is not str or bot not in BOTS:
        raise PermissionError("unknown executor bot")
    if not isinstance(signing_keys, Mapping):
        raise PermissionError("per-bot executor signing keys required")
    if set(signing_keys) != BOTS:
        raise PermissionError("complete per-bot executor signing keys required")
    secrets = tuple(signing_keys.values())
    if (any(type(secret) is not bytes or len(secret) < 32 for secret in secrets)
            or len(set(secrets)) != len(BOTS)):
        raise PermissionError("executor signing keys must be distinct and at least 32 bytes")
    secret = signing_keys.get(bot)
    principal = verify_signed_staging_jwt(
        token, secret, issuer=issuer, audience=audience, now=now)
    if (principal.subject != "executor:" + bot
            or principal.scopes != frozenset((EXECUTOR_ENTRY_SCOPE,))):
        raise PermissionError("executor identity or scope rejected")
    return VerifiedExecutorPrincipal(
        bot=bot,
        subject=principal.subject,
        issuer=principal.issuer,
        audience=principal.audience,
        scopes=principal.scopes,
        expires_at=principal.expires_at,
    )