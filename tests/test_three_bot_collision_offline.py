"""Deterministic, offline cross-bot entry collision tests; no exchange orders."""
import threading
import unittest
from shared_entry_gate_staging import inspect_entry


class AtomicFakeStore:
    """A fake shared database lock, NOT proof of production atomicity."""
    def __init__(self):
        self.lock = threading.Lock()
        self.owner = {}
        self.calls = []
    def reserve(self, coin, bot, token):
        with self.lock:
            self.calls.append(("reserve", coin, bot))
            if coin in self.owner:
                return False
            self.owner[coin] = (bot, token)
            return True
    def claim_intent(self, coin, bot, token):
        with self.lock:
            self.calls.append(("claim", coin, bot))
            return self.owner.get(coin) == (bot, token)


class ThreeBotCollisionTests(unittest.TestCase):
    def test_only_one_bot_can_reserve_same_coin_concurrently(self):
        store = AtomicFakeStore()
        barrier = threading.Barrier(3)
        results = {}
        failures = []
        def worker(bot):
            try:
                barrier.wait(timeout=5)
                results[bot] = inspect_entry(
                    store, bot=bot, trade={"hl_coin": "BTC", "action": "open_long"},
                    exchange_position_flat=True, exchange_orders_clear=True)
            except Exception as exc:
                failures.append(exc)
        threads = [threading.Thread(target=worker, args=(bot,))
                   for bot in ("aggressive", "intraday", "daily")]
        for t in threads: t.start()
        for t in threads: t.join(timeout=6)
        self.assertFalse(failures, failures)
        self.assertTrue(all(not t.is_alive() for t in threads))
        self.assertEqual(sum(x.simulated_allowed for x in results.values()), 1)
        self.assertTrue(all(not x.live_order_submitted for x in results.values()))

    def test_different_coins_can_be_reserved(self):
        store = AtomicFakeStore()
        for bot, coin in (("aggressive", "BTC"), ("intraday", "ETH"), ("daily", "SOL")):
            result = inspect_entry(store, bot=bot,
                                   trade={"hl_coin": coin, "action": "open_short"},
                                   exchange_position_flat=True, exchange_orders_clear=True)
            self.assertTrue(result.simulated_allowed)
            self.assertFalse(result.live_order_submitted)

    def test_exchange_open_orders_block_simulated_entry(self):
        store = AtomicFakeStore()
        result = inspect_entry(store, bot="intraday",
                               trade={"hl_coin": "BTC", "action": "open_long"},
                               exchange_position_flat=True, exchange_orders_clear=False)
        self.assertFalse(result.simulated_allowed)
        self.assertFalse(result.live_order_submitted)


if __name__ == "__main__":
    unittest.main()
