import unittest
from intraday_single_bot_trial_staging import TrialConfig, simulate_trial_trade


class Store:
    def __init__(self): self.reserved = set()
    def reserve(self, coin, bot, token):
        if coin in self.reserved: return False
        self.reserved.add(coin)
        return True
    def claim_intent(self, coin, bot, token): return True


class SingleBotTrialTests(unittest.TestCase):
    def test_intraday_allowed_only_for_simulated_entry(self):
        result = simulate_trial_trade(Store(), bot="intraday",
            trade={"hl_coin": "SOL", "action": "open_long"},
            position_flat=True, no_open_orders=True)
        self.assertEqual(result["decision"], "eligible_for_future_review")
        self.assertFalse(result["order_submitted"])

    def test_other_bots_disabled(self):
        for bot in ("aggressive", "daily"):
            result = simulate_trial_trade(Store(), bot=bot,
                trade={"hl_coin": "SOL", "action": "open_short"},
                position_flat=True, no_open_orders=True)
            self.assertEqual(result["decision"], "bot_disabled")

    def test_duplicate_entry_fenced(self):
        store = Store()
        kwargs = dict(bot="intraday", trade={"hl_coin": "SOL", "action": "open_long"},
                      position_flat=True, no_open_orders=True)
        self.assertEqual(simulate_trial_trade(store, **kwargs)["decision"],
                         "eligible_for_future_review")
        self.assertEqual(simulate_trial_trade(store, **kwargs)["decision"], "deny")

    def test_nonflat_position_denies_entry(self):
        result = simulate_trial_trade(Store(), bot="intraday",
            trade={"hl_coin": "SOL", "action": "open_long"},
            position_flat=False, no_open_orders=True)
        self.assertEqual(result["decision"], "deny")

    def test_submission_cannot_be_enabled(self):
        with self.assertRaises(ValueError):
            simulate_trial_trade(Store(), bot="intraday",
                trade={"hl_coin": "SOL", "action": "open_long"},
                position_flat=True, no_open_orders=True,
                config=TrialConfig(order_submission_enabled=True))


if __name__ == "__main__":
    unittest.main()
