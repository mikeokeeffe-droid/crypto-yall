"""Offline integration of real executor function bodies with staging entry fence."""
import unittest
from test_real_executor_order_boundaries_offline import load_function, FILES, FakeExchange
from real_executor_entry_fence_staging import execute_with_staging_fence

class OfflineExchange(FakeExchange):
    is_offline_fake = True

class Store:
    def __init__(self, allowed):
        self.allowed = allowed
    def reserve(self, coin, bot, token):
        return self.allowed
    def claim_intent(self, coin, bot, token):
        return self.allowed

class OfflineFenceTests(unittest.TestCase):
    def test_denied_entries_never_open(self):
        for bot, filename in zip(("aggressive", "intraday", "daily"), FILES):
            with self.subTest(bot=bot):
                exchange = OfflineExchange()
                result = execute_with_staging_fence(
                    load_function(filename), object(), exchange,
                    {"hl_coin": "BTC", "action": "open_long"}, 1000.0, 1.0,
                    bot=bot, store=Store(False),
                    exchange_position_flat=True, exchange_orders_clear=True)
                self.assertEqual(result["status"], "skipped")
                self.assertEqual(exchange.calls, [])

    def test_allowed_entries_reach_fake_exchange(self):
        for bot, filename in zip(("aggressive", "intraday", "daily"), FILES):
            with self.subTest(bot=bot):
                exchange = OfflineExchange()
                result = execute_with_staging_fence(
                    load_function(filename), object(), exchange,
                    {"hl_coin": "BTC", "action": "open_long"}, 1000.0, 1.0,
                    bot=bot, store=Store(True),
                    exchange_position_flat=True, exchange_orders_clear=True)
                self.assertEqual(result["status"], "filled")
                self.assertEqual(sum(c[0] == "open" for c in exchange.calls), 1)

    def test_non_fake_exchange_rejected(self):
        for bot, filename in zip(("aggressive", "intraday", "daily"), FILES):
            with self.subTest(bot=bot):
                exchange = FakeExchange()
                result = execute_with_staging_fence(
                    load_function(filename), object(), exchange,
                    {"hl_coin": "BTC", "action": "open_long"}, 1000.0, 1.0,
                    bot=bot, store=Store(True),
                    exchange_position_flat=True, exchange_orders_clear=True)
                self.assertEqual(result["status"], "skipped")
                self.assertEqual(exchange.calls, [])

if __name__ == "__main__":
    unittest.main()
