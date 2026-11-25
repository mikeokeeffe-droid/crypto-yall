"""Offline restart safety checks: reservation ownership must survive process restart.

Uses a shared in-memory store to model durable DB state; not production persistence.
"""
import unittest
from unittest.mock import patch
from entry_gate_staging import acquire_entry_permit


class SharedStore:
    def __init__(self):
        self.reservations = {}
        self.intents = set()

    def reserve(self, coin, bot, token):
        if coin in self.reservations:
            return False
        self.reservations[coin] = (bot, token)
        return True

    def claim_intent(self, coin, bot, token):
        if self.reservations.get(coin) != (bot, token):
            return False
        self.intents.add((coin, bot, token))
        return True


class RestartSafetyTests(unittest.TestCase):
    def test_restart_does_not_clear_existing_reservation(self):
        store = SharedStore()
        first = acquire_entry_permit(store, "SOL", "intraday")
        self.assertIsNotNone(first)
        self.assertIn(("SOL", "intraday", first.token), store.intents)
        # Simulate process restart: new caller, same shared backing store.
        self.assertIsNone(acquire_entry_permit(store, "SOL", "aggressive"))
        self.assertIsNone(acquire_entry_permit(store, "SOL", "intraday"))

    def test_crash_after_reserve_before_claim_keeps_fence(self):
        store = SharedStore()
        with patch.object(store, "claim_intent", side_effect=RuntimeError("crash")):
            self.assertIsNone(acquire_entry_permit(store, "AVAX", "daily"))
        self.assertIn("AVAX", store.reservations)
        self.assertIsNone(acquire_entry_permit(store, "AVAX", "intraday"))

    def test_crash_after_claim_before_order_keeps_fence(self):
        store = SharedStore()
        first = acquire_entry_permit(store, "LINK", "daily")
        self.assertIsNotNone(first)
        self.assertIsNone(acquire_entry_permit(store, "LINK", "aggressive"))
        self.assertEqual(len(store.intents), 1)


if __name__ == "__main__":
    unittest.main()
