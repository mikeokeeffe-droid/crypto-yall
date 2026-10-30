import unittest
from shared_entry_gate_staging import inspect_entry


class FakeStore:
    def __init__(self, permitted=True):
        self.permitted = permitted
        self.calls = 0
    def reserve(self, coin, bot, token):
        self.calls += 1
        return self.permitted
    def claim_intent(self, coin, bot, token):
        self.calls += 1
        return self.permitted


class SharedGateTests(unittest.TestCase):
    def test_all_three_bots_use_same_simulation(self):
        for bot in ("aggressive", "intraday", "daily"):
            with self.subTest(bot=bot):
                store = FakeStore()
                result = inspect_entry(
                    store, bot=bot,
                    trade={"hl_coin": "BTC", "action": "open_long"},
                    exchange_position_flat=True, exchange_orders_clear=True,
                )
                self.assertTrue(result.simulated_allowed)
                self.assertFalse(result.live_order_submitted)
                self.assertEqual(store.calls, 2)

    def test_close_never_uses_entry_gate(self):
        store = FakeStore(permitted=False)
        result = inspect_entry(
            store, bot="intraday",
            trade={"hl_coin": "ETH", "action": "close"},
            exchange_position_flat=False, exchange_orders_clear=False,
        )
        self.assertFalse(result.live_order_submitted)
        self.assertEqual(store.calls, 0)

    def test_pyramid_requires_permission(self):
        store = FakeStore(permitted=False)
        result = inspect_entry(
            store, bot="aggressive",
            trade={"hl_coin": "SOL", "action": "pyramid_long"},
            exchange_position_flat=True, exchange_orders_clear=True,
        )
        self.assertFalse(result.simulated_allowed)

    def test_unknown_action_denied(self):
        store = FakeStore()
        result = inspect_entry(
            store, bot="daily",
            trade={"hl_coin": "BTC", "action": "unknown"},
            exchange_position_flat=True, exchange_orders_clear=True,
        )
        self.assertFalse(result.simulated_allowed)
        self.assertEqual(store.calls, 0)


if __name__ == "__main__":
    unittest.main()
