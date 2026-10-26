"""Offline fail-closed database exception tests across all three bots."""
import unittest
from shared_entry_gate_staging import inspect_entry

class ErrorStore:
    def __init__(self, fail_at):
        self.fail_at = fail_at
        self.calls = []
    def reserve(self, coin, bot, token):
        self.calls.append("reserve")
        if self.fail_at == "reserve":
            raise ConnectionError("simulated DB outage")
        return True
    def claim_intent(self, coin, bot, token):
        self.calls.append("claim")
        if self.fail_at == "claim":
            raise TimeoutError("ambiguous DB response")
        return True

class DatabaseOutageTests(unittest.TestCase):
    def test_reservation_and_claim_outages_fail_closed(self):
        for bot in ("aggressive", "intraday", "daily"):
            for fail_at in ("reserve", "claim"):
                with self.subTest(bot=bot, fail_at=fail_at):
                    store = ErrorStore(fail_at)
                    result = inspect_entry(store, bot=bot,
                        trade={"hl_coin":"BTC", "action":"open_long"},
                        exchange_position_flat=True, exchange_orders_clear=True)
                    self.assertFalse(result.simulated_allowed)
                    self.assertFalse(result.live_order_submitted)
                    self.assertEqual(store.calls,
                        ["reserve"] if fail_at == "reserve" else ["reserve", "claim"])

if __name__ == "__main__":
    unittest.main()
