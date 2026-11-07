"""Offline negative entry-gate tests for all three bots. No live orders."""
import unittest
from shared_entry_gate_staging import inspect_entry

class RejectingStore:
    def __init__(self, reserve_ok=True, claim_ok=True):
        self.reserve_ok, self.claim_ok = reserve_ok, claim_ok
        self.calls = []
    def reserve(self, coin, bot, token):
        self.calls.append("reserve")
        return self.reserve_ok
    def claim_intent(self, coin, bot, token):
        self.calls.append("claim")
        return self.claim_ok

class EntryDenialTests(unittest.TestCase):
    def test_reservation_rejection_denies_all_bots(self):
        for bot in ("aggressive", "intraday", "daily"):
            with self.subTest(bot=bot):
                store = RejectingStore(reserve_ok=False)
                result = inspect_entry(store, bot=bot,
                    trade={"hl_coin":"BTC", "action":"open_long"},
                    exchange_position_flat=True, exchange_orders_clear=True)
                self.assertFalse(result.simulated_allowed)
                self.assertFalse(result.live_order_submitted)
                self.assertEqual(store.calls, ["reserve"])

    def test_claim_rejection_denies_all_bots(self):
        for bot in ("aggressive", "intraday", "daily"):
            with self.subTest(bot=bot):
                store = RejectingStore(claim_ok=False)
                result = inspect_entry(store, bot=bot,
                    trade={"hl_coin":"ETH", "action":"open_short"},
                    exchange_position_flat=True, exchange_orders_clear=True)
                self.assertFalse(result.simulated_allowed)
                self.assertFalse(result.live_order_submitted)
                self.assertEqual(store.calls, ["reserve", "claim"])

    def test_existing_exchange_position_denies_all_bots(self):
        for bot in ("aggressive", "intraday", "daily"):
            with self.subTest(bot=bot):
                result = inspect_entry(RejectingStore(), bot=bot,
                    trade={"hl_coin":"SOL", "action":"open_long"},
                    exchange_position_flat=False, exchange_orders_clear=True)
                self.assertFalse(result.simulated_allowed)
                self.assertFalse(result.live_order_submitted)

if __name__ == "__main__":
    unittest.main()
