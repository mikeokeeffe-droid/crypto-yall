import unittest
from intraday_entry_observer_staging import observe_intraday_entry


class ObserverTests(unittest.TestCase):
    def test_entry_candidate_is_not_permission(self):
        result = observe_intraday_entry(trade={"hl_coin": "SOL", "action": "open_long"})
        self.assertTrue(result["candidate_valid"])
        self.assertFalse(result["reservation_verified"])
        self.assertFalse(result["order_submitted"])
        self.assertTrue(result["decision"].startswith("blocked"))

    def test_malformed_trade_remains_blocked(self):
        result = observe_intraday_entry(trade={})
        self.assertFalse(result["candidate_valid"])
        self.assertFalse(result["order_submitted"])


if __name__ == "__main__":
    unittest.main()
