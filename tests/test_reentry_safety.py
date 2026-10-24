"""Offline re-entry safety checks. No Hyperliquid, Gist or Supabase access."""
import datetime as dt
import unittest
from unittest.mock import patch

from reentry_lock import (
    block_locked_entries,
    mark_pending_lock,
    refresh_locks,
)

SYMBOLS = {"BTC": "BTC"}


class ReentrySafetyTests(unittest.TestCase):
    def test_pending_exit_is_confirmed_after_position_disappears(self):
        state = {}
        mark_pending_lock(state, "BTC", "long")
        locks = refresh_locks(
            state, {"BTC": {"action": "hold_long"}}, SYMBOLS, {}
        )
        self.assertFalse(locks["BTC"]["pending"])
        self.assertIn("confirmed_at", locks)
        self.assertEqual(
            block_locked_entries(
                [{"action": "open_long", "hl_coin": "BTC"}], locks
            ), [],
        )

    def test_pending_exit_clears_if_position_still_open(self):
        state = {}
        mark_pending_lock(state, "BTC", "long")
        locks = refresh_locks(
            state, {"BTC": {"action": "hold_long"}}, SYMBOLS,
            {"BTC": {"size": 0.1}},
        )
        self.assertNotIn("BTC", locks)

    def test_reset_releases_long_lock(self):
        state = {}
        mark_pending_lock(state, "BTC", "long")
        refresh_locks(state, {"BTC": {"action": "hold_long"}}, SYMBOLS, {})
        locks = refresh_locks(
            state, {"BTC": {"action": "enter_short"}}, SYMBOLS, {}
        )
        self.assertNotIn("BTC", locks)

    def test_short_same_signal_blocks_entry(self):
        state = {}
        mark_pending_lock(state, "BTC", "short")
        locks = refresh_locks(
            state, {"BTC": {"action": "hold_short"}}, SYMBOLS, {}
        )
        self.assertEqual(
            block_locked_entries(
                [{"action": "open_short", "hl_coin": "BTC"}], locks
            ), [],
        )

    def test_cooldown_releases_old_lock(self):
        state = {
            "profit_reentry_locks": {
                "BTC": {
                    "side": "long",
                    "pending": False,
                    "confirmed_at": (
                        dt.datetime.now(dt.UTC) - dt.timedelta(minutes=20)
                    ).isoformat(),
                }
            }
        }
        locks = refresh_locks(
            state, {"BTC": {"action": "hold_long"}}, SYMBOLS, {},
            cooldown_minutes=15,
        )
        self.assertNotIn("BTC", locks)


if __name__ == "__main__":
    unittest.main()
