"""Staging-only entry gate. Not imported by any live executor.

This adapter deliberately fails closed on database errors or ambiguous orders.
The caller MUST verify exchange positions after acquiring the durable intent.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Protocol


class ReservationStore(Protocol):
    def reserve(self, coin: str, bot: str, token: uuid.UUID) -> bool: ...
    def claim_intent(self, coin: str, bot: str, token: uuid.UUID) -> bool: ...


@dataclass(frozen=True)
class EntryPermit:
    coin: str
    bot: str
    token: uuid.UUID


def acquire_entry_permit(
    store: ReservationStore, coin: str, bot: str
) -> EntryPermit | None:
    """No permit unless BOTH atomic reservation and durable intent succeed.

    Never interpret exceptions as permission to trade. Do not automatically
    release a reservation/intent on an ambiguous database failure: a pending
    order may already exist, requiring reconciliation.
    """
    token = uuid.uuid4()
    try:
        if not store.reserve(coin, bot, token):
            return None
        if not store.claim_intent(coin, bot, token):
            return None
    except Exception:
        return None
    return EntryPermit(coin=coin, bot=bot, token=token)
