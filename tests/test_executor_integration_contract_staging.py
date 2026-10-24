import unittest
from executor_integration_contract_staging import evaluate_executor_trade


class FakeStore:
    def __init__(self, allowed=True):
        self.allowed = allowed
        self.claimed = set()
        self.calls = 0
    def reserve(self, coin, bot, token):
        self.calls += 1
        if not self.allowed or coin in self.claimed:
            return False
        self.claimed.add(coin)
        return True
    def claim_intent(self, coin, bot, token):
        self.calls += 1
        return self.allowed


class ExecutorIntegrationContractTests(unittest.TestCase):
    def test_all_three_bots_entry_is_simulation_only(self):
        for bot in ("aggressive", "intraday", "daily"):
            with self.subTest(bot=bot):
                result = evaluate_executor_trade(
                    FakeStore(), bot=bot,
                    trade={"hl_coin": "BTC", "action": "open_long"},
                    position_flat=True, no_open_orders=True,
                )
                self.assertEqual(result.decision, "eligible_for_future_review")
                self.assertFalse(result.order_submitted)

    def test_competing_bot_denied_for_same_coin(self):
        store = FakeStore()
        a = evaluate_executor_trade(store, bot="aggressive",
            trade={"hl_coin": "SOL", "action": "open_long"},
            position_flat=True, no_open_orders=True)
        b = evaluate_executor_trade(store, bot="daily",
            trade={"hl_coin": "SOL", "action": "open_short"},
            position_flat=True, no_open_orders=True)
        self.assertEqual(a.decision, "eligible_for_future_review")
        self.assertEqual(b.decision, "deny")

    def test_exit_never_queries_database(self):
        class ExplodingStore:
            def reserve(self, *args): raise AssertionError("exit touched database")
        result = evaluate_executor_trade(
            ExplodingStore(), bot="intraday",
            trade={"hl_coin": "ETH", "action": "close"},
            position_flat=False, no_open_orders=False)
        self.assertEqual(result.decision, "defer_to_existing_exit")
        self.assertFalse(result.order_submitted)

    def test_fail_closed_when_store_unavailable(self):
        result = evaluate_executor_trade(
            FakeStore(False), bot="daily",
            trade={"hl_coin": "BTC", "action": "open_long"},
            position_flat=True, no_open_orders=True)
        self.assertEqual(result.decision, "deny")

    def test_exchange_pending_order_blocks(self):
        result = evaluate_executor_trade(
            FakeStore(), bot="aggressive",
            trade={"hl_coin": "BTC", "action": "pyramid_long"},
            position_flat=True, no_open_orders=False)
        self.assertEqual(result.decision, "deny")


if __name__ == "__main__":
    unittest.main()
