"""Staging-only durable ownership transition model.

Pure in-memory simulation. No exchange or database connections. Production
handoff requires an atomic DB transition and verified exchange evidence.
"""
from dataclasses import dataclass
from enum import Enum


class OwnershipPhase(Enum):
    INTENT = "intent"
    UNCERTAIN = "uncertain"
    OWNED = "owned"
    CLOSED = "closed"


@dataclass
class OwnershipRecord:
    coin: str
    bot: str
    token: str
    phase: OwnershipPhase = OwnershipPhase.INTENT
    exchange_order_id: str | None = None


class OwnershipLedger:
    def __init__(self):
        self._records: dict[str, OwnershipRecord] = {}

    def claim(self, coin: str, bot: str, token: str) -> bool:
        if not coin or not bot or not token or coin in self._records:
            return False
        self._records[coin] = OwnershipRecord(coin, bot, token)
        return True

    def mark_uncertain(self, coin: str, bot: str, token: str) -> bool:
        rec = self._match(coin, bot, token)
        if rec is None or rec.phase not in (OwnershipPhase.INTENT, OwnershipPhase.UNCERTAIN):
            return False
        rec.phase = OwnershipPhase.UNCERTAIN
        return True

    def handoff_filled(self, coin: str, bot: str, token: str, *,
                       exchange_fill_verified: bool, exchange_order_id: str) -> bool:
        rec = self._match(coin, bot, token)
        if (rec is None or rec.phase not in (OwnershipPhase.INTENT, OwnershipPhase.UNCERTAIN)
                or not exchange_fill_verified or not exchange_order_id):
            return False
        rec.phase = OwnershipPhase.OWNED
        rec.exchange_order_id = exchange_order_id
        return True

    def close_verified(self, coin: str, bot: str, token: str, *,
                       exchange_position_flat: bool, no_open_orders: bool) -> bool:
        rec = self._match(coin, bot, token)
        if (rec is None or rec.phase is not OwnershipPhase.OWNED
                or not exchange_position_flat or not no_open_orders):
            return False
        rec.phase = OwnershipPhase.CLOSED
        # The durable record remains fenced until a separate trusted
        # reconciler explicitly removes it after verification.
        return True

    def release_verified(self, coin: str, bot: str, token: str, *,
                         exchange_position_flat: bool, no_open_orders: bool) -> bool:
        rec = self._match(coin, bot, token)
        if (rec is None or rec.phase is not OwnershipPhase.CLOSED
                or not exchange_position_flat or not no_open_orders):
            return False
        del self._records[coin]
        return True

    def _match(self, coin: str, bot: str, token: str):
        rec = self._records.get(coin)
        return rec if rec is not None and (rec.bot, rec.token) == (bot, token) else None
