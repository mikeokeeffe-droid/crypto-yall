"""Offline contract for a future shared *durable* cross-bot entry coordinator.

NOT connected to the original executors; does not grant real trade permission.
A supplied backend must atomically reserve the coin AND persist the matching
unresolved intent in a shared database, authenticated to the bot, before it
reports success. Gist state and GitHub Actions concurrency do NOT satisfy it.

The draft deliberately has no HTTP client, database credentials, automatic
claim expiry/release, or Hyperliquid order submission.
"""
from dataclasses import dataclass
import uuid

ENTRY_ACTIONS = frozenset(("open_long", "open_short", "pyramid_long", "pyramid_short"))
BOTS = frozenset(("daily", "intraday", "aggressive"))


@dataclass(frozen=True)
class ClaimDecision:
    accepted: bool
    reason: str
    intent_id: str = ""
    fence_token: int = 0


def claim_shared_entry(backend, *, bot: str, coin: str, action: str,
                       request_id: str) -> ClaimDecision:
    """Fail closed unless an injected trusted coordinator returns exact proof.

    This is an *interface contract*, not verification of database durability,
    authenticated identity or exchange execution. Production must validate the
    backend implementation, SQL grants, reconciler and order boundary.
    """
    if (type(bot) is not str or type(action) is not str
            or bot not in BOTS or action not in ENTRY_ACTIONS):
        return ClaimDecision(False, "invalid_bot_or_entry_action")
    if type(coin) is not str or not coin or not coin.isascii() or not coin.isalnum() or coin != coin.upper():
        return ClaimDecision(False, "invalid_coin")
    try:
        request_uuid = str(uuid.UUID(request_id))
        if request_uuid != request_id:
            return ClaimDecision(False, "invalid_request_id")
    except (TypeError, ValueError, AttributeError):
        return ClaimDecision(False, "invalid_request_id")
    if backend is None:
        return ClaimDecision(False, "shared_coordinator_unavailable")

    try:
        reply = backend.claim_intent(bot=bot, coin=coin, action=action,
                                     request_id=request_id)
    except Exception:
        # Unknown outcome may already have committed a claim. Never retry by
        # treating a timeout as a clear/released lock.
        return ClaimDecision(False, "coordinator_result_uncertain")

    if type(reply) is not dict or type(reply.get("status")) is not str or reply["status"] != "claimed":
        return ClaimDecision(False, "not_claimed")
    if any(reply.get(k) != v for k, v in
           (("bot", bot), ("coin", coin), ("action", action),
            ("request_id", request_id))):
        return ClaimDecision(False, "identity_or_intent_mismatch")
    token = reply.get("fence_token")
    intent = reply.get("intent_id")
    if type(token) is not int or token < 1 or not isinstance(intent, str):
        return ClaimDecision(False, "invalid_claim_evidence")
    try:
        if str(uuid.UUID(intent)) != intent:
            return ClaimDecision(False, "invalid_claim_evidence")
    except ValueError:
        return ClaimDecision(False, "invalid_claim_evidence")
    return ClaimDecision(True, "shared_intent_claimed", intent, token)
