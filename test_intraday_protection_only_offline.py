"""Offline safety tests for Intraday protection-only decision logic.

No Hyperliquid client, credentials, network calls or real orders are used.
"""
import importlib
import os
import unittest
from unittest.mock import patch


class IntradayProtectionOnlyTests(unittest.TestCase):
    def setUp(self):
        self.flag = patch.dict(os.environ, {
            "INTRADAY_PROTECTION_ONLY": "ON",
            "INTRADAY_PROFIT_PROTECTION": "ON",
            "INTRADAY_LIVE_LOSS_CAP_USD": "0",
        })
        self.flag.start()
        import intraday_profit_protection
        self.wrapper = importlib.reload(intraday_profit_protection)

    def tearDown(self):
        self.flag.stop()

    def test_never_invokes_normal_entry_decisions(self):
        wrapper = self.wrapper
        state = {"peak_return_pct": {}}
        with patch.object(wrapper, "_state", state), \
             patch.object(wrapper, "_original_decide_trades", side_effect=AssertionError("normal strategy called")), \
             patch.object(wrapper, "refresh_locks", return_value={}), \
             patch.object(wrapper, "block_locked_entries", side_effect=lambda trades, locks: trades):
            trades = wrapper._protected_decide_trades({}, {}, 3)
        self.assertEqual(trades, [])

    def test_protection_only_can_generate_close_but_no_open(self):
        wrapper = self.wrapper
        coin = next(iter(wrapper.base.HL_SYMBOL_MAP.values()))
        position = {"entry_px": 100.0, "size": 1.0, "unrealized_pnl": 0.0}
        state = {"peak_return_pct": {coin: 1.5}}
        with patch.object(wrapper, "_state", state), \
             patch.object(wrapper, "_original_decide_trades", side_effect=AssertionError("normal strategy called")), \
             patch.object(wrapper, "refresh_locks", return_value={}), \
             patch.object(wrapper, "block_locked_entries", side_effect=lambda trades, locks: trades), \
             patch.object(wrapper, "mark_pending_lock"):
            trades = wrapper._protected_decide_trades({}, {coin: position}, 3)
        self.assertEqual(len(trades), 1)
        self.assertEqual(trades[0]["action"], "close")
        self.assertFalse(any(t.get("action") in {"open_long", "open_short"} for t in trades))


if __name__ == "__main__":
    unittest.main()
