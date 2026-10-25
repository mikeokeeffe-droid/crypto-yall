"""Offline regression tests for Intraday close-only execution.

All exchange calls use a fake object. Never submit real orders.
"""
import unittest
from unittest.mock import patch

import intraday_executor as executor


class FakeExchange:
    def __init__(self):
        self.closes = []
        self.opens = []

    def market_close(self, coin, sz=None):
        self.closes.append((coin, sz))
        return {"status": "ok"}

    def market_open(self, coin, is_buy, size):
        self.opens.append((coin, is_buy, size))
        raise AssertionError("A new entry must never be submitted")


class IntradayCloseOnlyExecutionTests(unittest.TestCase):
    def setUp(self):
        self.exchange = FakeExchange()

    def test_existing_long_close_uses_requested_size(self):
        trade = {"ticker": "SOL-USD", "hl_coin": "SOL", "action": "close",
                 "side": "long", "close_size": 0.4}
        with patch.object(executor, "_parse_response", return_value={"status": "filled"}):
            result = executor.execute_trade(None, self.exchange, trade, 100, 2)
        self.assertEqual(result["status"], "filled")
        self.assertEqual(self.exchange.closes, [("SOL", 0.4)])
        self.assertEqual(self.exchange.opens, [])

    def test_existing_short_close_uses_requested_size(self):
        trade = {"ticker": "SOL-USD", "hl_coin": "SOL", "action": "close",
                 "side": "short", "close_size": 0.2}
        with patch.object(executor, "_parse_response", return_value={"status": "filled"}):
            executor.execute_trade(None, self.exchange, trade, 100, 2)
        self.assertEqual(self.exchange.closes, [("SOL", 0.2)])
        self.assertEqual(self.exchange.opens, [])

    def test_draft_branch_blocks_new_long_and_short(self):
        for action in ("open_long", "open_short"):
            with self.subTest(action=action):
                trade = {"ticker": "SOL-USD", "hl_coin": "SOL", "action": action}
                result = executor.execute_trade(None, self.exchange, trade, 100, 2)
                self.assertEqual(result["status"], "skipped")
        self.assertEqual(self.exchange.opens, [])

    def test_exchange_close_failure_is_not_reported_as_fill(self):
        trade = {"ticker": "SOL-USD", "hl_coin": "SOL", "action": "close",
                 "close_size": 0.3}
        with patch.object(self.exchange, "market_close", side_effect=RuntimeError("offline exchange")):
            with self.assertRaises(RuntimeError):
                executor.execute_trade(None, self.exchange, trade, 100, 2)
        self.assertEqual(self.exchange.opens, [])


if __name__ == "__main__":
    unittest.main()
