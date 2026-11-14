"""Source-shaped offline candidates -> strict non-authorizing entry handoff."""
import json
import unittest

from offline_original_signal_projection_ci import (
    project_original_entry_candidate_offline,
)
from offline_original_bot_intent_adapter import (
    prepare_signer_free_entry_handoff_offline,
)

ACCOUNT = "0x" + "1" * 40


def candidate(bot, action="open_long"):
    is_long = action == "open_long"
    return {
        "ticker": "SOL-USD", "hl_coin": "SOL", "action": action,
        "side": "long" if is_long else "short",
        "reason": (
            ("BUY signal" if is_long else "ENTER SHORT signal")
            if bot == "daily"
            else ("buy signal" if is_long else "enter_short signal")
        ),
        "confidence" if bot == "daily" else "priority": 0.85,
    }


class OriginalCandidateProjectionTests(unittest.TestCase):
    def test_three_original_candidate_shapes_produce_review_only_entries(self):
        for bot in ("daily", "intraday", "aggressive"):
            for action in ("open_long", "open_short"):
                with self.subTest(bot=bot, action=action):
                    projected = project_original_entry_candidate_offline(
                        verified_bot=bot, candidate=candidate(bot, action),
                    )
                    self.assertEqual(projected.state, "projected_review_only")
                    self.assertFalse(projected.submit_authorized)
                    self.assertFalse(projected.ownership_verified)
                    slim = json.loads(projected.trade_json)
                    self.assertEqual(set(slim), {"action", "side", "hl_coin"})
                    handoff = prepare_signer_free_entry_handoff_offline(
                        verified_bot=bot, trade=slim, rounded_size="0.025",
                        pinned_environment="mainnet", pinned_account=ACCOUNT,
                    )
                    self.assertEqual(handoff.state, "request_only")
                    self.assertFalse(handoff.submit_authorized)
                    self.assertNotIn("ticker", handoff.request_json)
                    self.assertNotIn("confidence", handoff.request_json)
                    self.assertNotIn("priority", handoff.request_json)

    def test_intraday_and_aggressive_sync_reasons_are_characterized_not_authority(self):
        for bot in ("intraday", "aggressive"):
            for action, reason in (
                ("open_long", "sync to hold_long"),
                ("open_short", "sync to hold_short"),
            ):
                with self.subTest(bot=bot, action=action):
                    trade = candidate(bot, action)
                    trade["reason"] = reason
                    projected = project_original_entry_candidate_offline(
                        verified_bot=bot, candidate=trade,
                    )
                    self.assertEqual(projected.state, "projected_review_only")
                    self.assertFalse(projected.submit_authorized)
                    self.assertFalse(projected.ownership_verified)

    def test_unknown_or_spoofed_metadata_always_holds(self):
        for bot in ("daily", "intraday", "aggressive"):
            for key, value in (
                ("bot", "daily"), ("account", ACCOUNT),
                ("submit_authorized", True), ("private_key", "fake"),
                ("unexpected_new_signal_field", 1),
                ("cloid", "fake"), ("leverage_applied", True),
                ("close_size", 0.5),
            ):
                with self.subTest(bot=bot, field=key):
                    trade = candidate(bot)
                    trade[key] = value
                    result = project_original_entry_candidate_offline(
                        verified_bot=bot, candidate=trade,
                    )
                    self.assertEqual(result.state, "hold")
                    self.assertIsNone(result.trade_json)
                    self.assertFalse(result.submit_authorized)

    def test_wrong_coin_ticker_action_score_and_reason_hold(self):
        for bot in ("daily", "intraday", "aggressive"):
            score = "confidence" if bot == "daily" else "priority"
            cases = (
                ("ticker", "BTC-USD"), ("ticker", "UNKNOWN"),
                ("hl_coin", "AVAX"), ("action", "close"),
                ("action", "pyramid_long"), ("side", "short"),
                ("reason", "arbitrary"), (score, -1),
                (score, float("nan")), (score, float("inf")),
                (score, "0.8"), (score, True),
            )
            for field, value in cases:
                with self.subTest(bot=bot, field=field, value=value):
                    trade = candidate(bot)
                    trade[field] = value
                    r = project_original_entry_candidate_offline(
                        verified_bot=bot, candidate=trade,
                    )
                    self.assertEqual(r.state, "hold")
                    self.assertIsNone(r.trade_json)

    def test_original_executors_and_sdk_not_imported(self):
        import sys
        for name in ("hyperliquid_executor", "intraday_executor",
                     "aggressive_executor", "eth_account",
                     "hyperliquid.exchange"):
            self.assertNotIn(name, sys.modules)


if __name__ == "__main__":
    unittest.main()
