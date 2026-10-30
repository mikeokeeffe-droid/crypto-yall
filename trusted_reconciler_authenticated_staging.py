"""Offline staging orchestration: verify signed identity before evidence or RPC.

No HTTP listener, production credentials, deployment, or trading orders.
The receiving gateway must provision and protect the signing key, enforce
revocation and bind RPC credentials to a restricted database principal.
"""
from trusted_reconciler_gateway_jwt_staging import verify_staging_jwt
from trusted_reconciler_service_staging import (
    authorized_reconcile_submitted_entry, authorized_reconcile_flat_owner,
)

def _verify_bot_identity(auth_token, signing_key, *, issuer, audience, now, bot):
    principal = verify_staging_jwt(
        auth_token, signing_key, issuer=issuer, audience=audience, now=now
    )
    if type(bot) is not str or principal.subject != "reconciler:" + bot:
        raise PermissionError("reconciler identity is not bound to requested bot")


def reconcile_entry_with_token(info, address, rpc, *, auth_token, signing_key,
                               issuer, audience, now, **entry):
    _verify_bot_identity(
        auth_token, signing_key, issuer=issuer, audience=audience, now=now,
        bot=entry.get("bot"),
    )
    return authorized_reconcile_submitted_entry(
        info, address, rpc, authorized=True, **entry)

def reconcile_release_with_token(info, address, rpc, *, auth_token, signing_key,
                                 issuer, audience, now, **owner):
    _verify_bot_identity(
        auth_token, signing_key, issuer=issuer, audience=audience, now=now,
        bot=owner.get("bot"),
    )
    return authorized_reconcile_flat_owner(
        info, address, rpc, authorized=True, **owner)
