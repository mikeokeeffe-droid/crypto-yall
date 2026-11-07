"""Staging-only Supabase RPC adapter; NOT imported by live executors.

Inject a trusted server-side RPC client. Never embed a service-role key here.
The client must be configured for the same database for all bots.
"""
from __future__ import annotations
import uuid
from typing import Any


class SupabaseEntryReservationStore:
    def __init__(self, client: Any):
        self._client = client

    def _rpc_boolean(self, name: str, payload: dict) -> bool:
        response = self._client.rpc(name, payload).execute()
        # Only the literal PostgreSQL boolean true grants permission.
        # None, errors, dicts, and unexpected payloads all fail closed.
        return response.data is True

    def reserve(self, coin: str, bot: str, token: uuid.UUID) -> bool:
        return self._rpc_boolean("try_reserve_bot_entry", {
            "p_coin": coin, "p_bot": bot, "p_token": str(token),
            "p_ttl_seconds": 120,
        })

    def claim_intent(self, coin: str, bot: str, token: uuid.UUID) -> bool:
        return self._rpc_boolean("claim_bot_entry_intent", {
            "p_coin": coin, "p_bot": bot, "p_token": str(token),
        })
