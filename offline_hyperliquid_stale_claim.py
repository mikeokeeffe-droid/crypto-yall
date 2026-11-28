"""Offline-only stale claim review. Age is never evidence of nonexecution.

No clock, exchange, database, or live executor access. A timed-out order may
have reached the exchange; automatic TTL release is unsafe without a verified
durable reconciliation and fencing protocol.
"""
from dataclasses import dataclass

@dataclass(frozen=True)
class StaleClaimReview:
    status: str
    reason: str
    release_claim: bool = False
    allow_new_entry: bool = False

def inspect_stale_claim_offline(*, claim, now_ms, ttl_ms,
                                claimed_order_absent, claimed_flat_position):
    def hold(reason):
        return StaleClaimReview("hold", reason)
    if type(claim) is not dict or set(claim) != {
        "intent_id", "fence_token", "created_ms", "state"}:
        return hold("missing or malformed durable claim")
    if (type(claim["intent_id"]) is not str or not claim["intent_id"]
            or type(claim["fence_token"]) is not int or claim["fence_token"] < 1
            or type(claim["created_ms"]) is not int or claim["created_ms"] < 0
            or type(claim["state"]) is not str
            or claim["state"] not in ("pending", "uncertain")):
        return hold("invalid claim identity or unresolved state")
    if (type(now_ms) is not int or now_ms < claim["created_ms"]
            or type(ttl_ms) is not int or ttl_ms <= 0
            or type(claimed_order_absent) is not bool
            or type(claimed_flat_position) is not bool):
        return hold("invalid time or reconciliation claims")
    age = now_ms - claim["created_ms"]
    if age >= ttl_ms:
        return hold("claim expired by age only; exchange execution remains unknown")
    return hold("unresolved claim remains reserved regardless of age")
