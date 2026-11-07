"""Review-only executor gateway contract.

No HTTP server, credentials, exchange client, database connection or order
submission. Deliberately denies all entry requests until independently
reviewed authentication and restricted database transport exist.
"""
from dataclasses import dataclass

ENTRY_ACTIONS = frozenset(("open_long", "open_short", "pyramid_long", "pyramid_short"))
BOTS = frozenset(("aggressive", "intraday", "daily"))


@dataclass(frozen=True)
class GatewayDecision:
    allowed: bool
    reason: str


def authorize_entry(*, bot: str, coin: str, action: str) -> GatewayDecision:
    """Fail closed. This placeholder must never authorize a live order."""
    if bot not in BOTS or not isinstance(coin, str) or not coin:
        return GatewayDecision(False, "invalid executor identity or coin")
    if action not in ENTRY_ACTIONS:
        return GatewayDecision(False, "not an entry request")
    return GatewayDecision(False, "gateway not deployed; entries disabled")
