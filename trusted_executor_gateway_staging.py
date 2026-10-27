"""Authenticated staging entry gateway. No network listener or exchange orders.

JWT verification is injected by trusted server wiring, not by the caller.
A successful reservation+intent is evidence for offline testing ONLY; it is
not permission to submit a live order. Live executors do not import this.
"""
from dataclasses import dataclass
from uuid import uuid4

from staging_executor_gateway_contract import BOTS, ENTRY_ACTIONS


@dataclass(frozen=True)
class StagedEntryClaim:
    bot: str
    coin: str
    token: str
    claimed: bool
    live_order_authorized: bool = False


def stage_entry_claim(*, jwt_token, bot, coin, action, verify_token, rpc,
                      ttl_seconds=120):
    """Verify caller identity and persist a fenced intent; fail closed."""
    if (bot not in BOTS or action not in ENTRY_ACTIONS
            or type(coin) is not str or not coin.isascii()
            or not coin.isalnum() or coin != coin.upper()):
        raise PermissionError("invalid entry request")
    if not callable(verify_token) or not callable(rpc):
        raise PermissionError("trusted gateway dependencies required")
    if type(ttl_seconds) is not int or not 30 <= ttl_seconds <= 600:
        raise PermissionError("invalid reservation duration")

    # The verifier must validate signature, issuer, audience and expiry.
    principal = verify_token(jwt_token)
    if (type(principal) is not dict
            or principal.get("subject") != "executor:" + bot
            or principal.get("scope") != "executor:entry"
            or principal.get("verified") is not True):
        raise PermissionError("executor identity rejected")

    token = str(uuid4())
    params = {"p_coin": coin, "p_bot": bot, "p_token": token}
    if rpc("try_reserve_bot_entry", dict(params, p_ttl_seconds=ttl_seconds)) is not True:
        raise PermissionError("reservation denied")
    # On claim failure, retain reservation conservatively. A reconciler must
    # inspect uncertain outcomes; never automatically clear a durable intent.
    if rpc("claim_bot_entry_intent", params) is not True:
        raise PermissionError("entry intent denied")
    return StagedEntryClaim(bot=bot, coin=coin, token=token, claimed=True)
