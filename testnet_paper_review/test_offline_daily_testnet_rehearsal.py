"""Strictly offline tests of original Daily order sizing; no trading APIs."""
import os
import unittest
from unittest.mock import patch

from testnet_paper_review.offline_daily_testnet_rehearsal import (
    OfflineHold, rehearse_one_daily_action, reviewed_daily_function
)


class OfflineDailyTestnetRehearsalTests(unittest.TestCase):
    def test_long_and_short_are_fake_calls_only(self):
        for action, is_buy in (("open_long", True), ("open_short", False)):
            with self.subTest(action=action):
                result, calls = rehearse_one_daily_action(action)
                self.assertEqual(result["status"], "MOCK_OFFLINE_ONLY")
                self.assertEqual(calls, [
                    ("fake_leverage", 1, "SOL", True),
                    ("fake_open", "SOL", is_buy, 0.12),
                ])

    def test_close_path_is_mock_only(self):
        result, calls = rehearse_one_daily_action("close")
        self.assertEqual(result["status"], "MOCK_OFFLINE_ONLY")
        self.assertEqual(calls, [("fake_close", "SOL", None)])

    def test_small_allocation_does_not_generate_order(self):
        result, calls = rehearse_one_daily_action(
            "open_long", allocated_capital=1.0
        )
        self.assertEqual(result["status"], "skipped")
        self.assertEqual(calls, [])

    def test_unapproved_symbol_or_action_not_exposed(self):
        for action in ("pyramid_long", "ETH", "order", "/exchange", ""):
            with self.subTest(action=action), self.assertRaises(OfflineHold):
                rehearse_one_daily_action(action)

    def test_no_mainnet_fallback_or_unsafe_size(self):
        for capital, leverage in ((101, 1), (100, 2), (0, 1), (-1, 1),
                                  (100, 0), (100, 1.1), (True, 1),
                                  (100, True), ("100", 1)):
            with self.subTest(capital=capital, leverage=leverage):
                with self.assertRaises(OfflineHold):
                    rehearse_one_daily_action(
                        "open_long", allocated_capital=capital, leverage=leverage
                    )

    def test_environment_restored_no_secret_required(self):
        original = os.getenv("HL_TESTNET")
        with patch.dict(os.environ, {"HL_TESTNET": "false"}):
            rehearse_one_daily_action("open_short")
            self.assertEqual(os.getenv("HL_TESTNET"), "false")
        self.assertEqual(os.getenv("HL_TESTNET"), original)

    def test_source_pinned_and_reviewed_body_extracted(self):
        self.assertEqual(reviewed_daily_function().__name__, "execute_trade")


if __name__ == "__main__":
    unittest.main()
