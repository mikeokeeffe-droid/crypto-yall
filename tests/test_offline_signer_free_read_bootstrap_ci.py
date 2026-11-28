"""Test the disabled synthetic read bootstrap; no original bot imports."""
import json
import unittest

from offline_signer_free_read_bootstrap_ci import (
    bootstrap_original_read_only_offline,
)

ACCOUNT = "0x" + "1" * 40


def snapshot():
    return {
        "environment": "testnet", "account": ACCOUNT,
        "user_state": {
            "marginSummary": {"accountValue": "150"},
            "assetPositions": [{"position": {
                "coin": "SOL", "szi": "0.5", "entryPx": "100",
                "unrealizedPnl": "1.5",
                "leverage": {"type": "cross", "value": 2},
            }}],
        },
        "spot_state": {"balances": [{"coin": "USDC", "total": "40"}]},
        "all_mids": {"SOL": "125"},
        "meta": {"universe": [{"name": "SOL", "szDecimals": 3}]},
    }


class SignerFreeReadBootstrapTests(unittest.TestCase):
    def build(self, bot="daily", **changes):
        values = {
            "verified_bot": bot,
            "pinned_environment": "testnet",
            "pinned_account": ACCOUNT, "snapshot": snapshot(),
        }
        values.update(changes)
        return bootstrap_original_read_only_offline(**values)

    def test_all_three_read_without_mutation_or_signer(self):
        for bot in ("daily", "intraday", "aggressive"):
            with self.subTest(bot=bot):
                view = self.build(bot)
                self.assertIsNotNone(view)
                self.assertEqual(view.info.all_mids()["SOL"], "125")
                self.assertEqual(
                    view.info.user_state(ACCOUNT)["marginSummary"]["accountValue"],
                    "150",
                )
                self.assertFalse(view.origin_authenticated)
                self.assertFalse(view.ownership_verified)
                self.assertFalse(view.submit_authorized)
                for name in (
                    "market_open", "market_close", "update_leverage",
                    "order", "cancel", "get_client", "submit", "sign",
                ):
                    self.assertFalse(hasattr(view, name))
                    self.assertFalse(hasattr(view.info, name))
                result = view.draft_entry_review(
                    trade={
                        "action": "open_long", "side": "long", "hl_coin": "SOL"
                    },
                    rounded_size="1.6", requested_leverage=2,
                )
                self.assertEqual(result.state, "review_only")
                self.assertFalse(result.submit_authorized)
                self.assertFalse(result.leverage_applied)
                payload = json.loads(result.review_json)
                self.assertEqual(payload, {
                    "operation": "review_entry_leverage_v2",
                    "action": "open_long",
                    "side": "long",
                    "hl_coin": "SOL",
                    "rounded_size": "1.6",
                    "requested_leverage": 2,
                    "cross_margin_requested": True,
                })
                for key in ("bot", "account", "environment",
                            "private_key", "submit_authorized"):
                    self.assertNotIn(key, payload)

    def test_bad_scope_snapshot_or_identity_cannot_bootstrap(self):
        for change in (
            {"verified_bot": "unknown"},
            {"pinned_account": "0x" + "2" * 40},
            {"pinned_environment": "production"},
            {"snapshot": {}},
        ):
            with self.subTest(change=change):
                self.assertIsNone(self.build(**change))

    def test_close_pyramid_wrong_side_and_spoofed_identity_hold(self):
        view = self.build("aggressive")
        for trade in (
            {"action": "close", "hl_coin": "SOL"},
            {"action": "pyramid_long", "side": "long", "hl_coin": "SOL"},
            {"action": "pyramid_short", "side": "short", "hl_coin": "SOL"},
            {"action": "update_leverage", "side": "long", "hl_coin": "SOL"},
            {"action": "open_long", "side": "short", "hl_coin": "SOL"},
            {"action": "open_long", "side": "long", "hl_coin": "SOL",
             "account": ACCOUNT},
            {"action": "open_long", "side": "long", "hl_coin": "SOL",
             "submit_authorized": True},
        ):
            with self.subTest(trade=trade):
                review = view.draft_entry_review(
                    trade=trade, rounded_size="1.6", requested_leverage=2,
                )
                self.assertEqual(review.state, "hold")
                self.assertIsNone(review.review_json)
                self.assertFalse(review.submit_authorized)

    def test_bad_size_and_leverage_hold(self):
        view = self.build()
        for size, leverage in (
            ("0", 2), ("-1", 2), ("NaN", 2), ("1e6", 2),
            ("1.5", 0), ("1.5", 6), ("1.5", True),
            ("1.5", 2.0),
        ):
            with self.subTest(size=size, leverage=leverage):
                result = view.draft_entry_review(
                    trade={"action": "open_short", "side": "short",
                           "hl_coin": "SOL"},
                    rounded_size=size, requested_leverage=leverage,
                )
                self.assertEqual(result.state, "hold")
                self.assertFalse(result.submit_authorized)

    def test_source_shaped_candidates_flow_only_to_non_executable_review(self):
        for bot in ("daily", "intraday", "aggressive"):
            view = self.build(bot)
            for action in ("open_long", "open_short"):
                with self.subTest(bot=bot, action=action):
                    long = action == "open_long"
                    candidate = {
                        "ticker": "SOL-USD", "hl_coin": "SOL",
                        "action": action,
                        "side": "long" if long else "short",
                        "reason": (
                            ("BUY signal" if long else "ENTER SHORT signal")
                            if bot == "daily" else
                            ("buy signal" if long else "enter_short signal")
                        ),
                        "confidence" if bot == "daily" else "priority": 0.7,
                    }
                    review = view.draft_original_candidate_review(
                        candidate=candidate, rounded_size="1.6",
                        requested_leverage=2,
                    )
                    self.assertEqual(review.state, "review_only")
                    self.assertFalse(review.submit_authorized)
                    self.assertFalse(review.leverage_applied)
                    envelope = json.loads(review.review_json)
                    self.assertEqual(
                        set(envelope),
                        {"operation", "action", "side", "hl_coin",
                         "rounded_size", "requested_leverage",
                         "cross_margin_requested"},
                    )
                    self.assertEqual(envelope["action"], action)
                    self.assertEqual(envelope["requested_leverage"], 2)
                    self.assertNotIn("ticker", envelope)
                    self.assertNotIn("reason", envelope)

    def test_unknown_candidate_fields_and_unapproved_actions_hold(self):
        view = self.build("aggressive")
        valid = {
            "ticker": "SOL-USD", "hl_coin": "SOL",
            "action": "open_long", "side": "long",
            "reason": "buy signal", "priority": 0.7,
        }
        invalids = [
            {**valid, "submit_authorized": True},
            {**valid, "ownership_verified": True},
            {**valid, "close_size": 0.25},
            {**valid, "action": "pyramid_long"},
            {**valid, "action": "close"},
            {**valid, "reason": "pyramid add #1 (osc re-entry)"},
            {**valid, "priority": float("nan")},
            {**valid, "ticker": "BTC-USD"},
        ]
        for candidate in invalids:
            with self.subTest(candidate=candidate):
                review = view.draft_original_candidate_review(
                    candidate=candidate, rounded_size="1.6",
                    requested_leverage=2,
                )
                self.assertEqual(review.state, "hold")
                self.assertIsNone(review.review_json)
                self.assertFalse(review.submit_authorized)

    def test_original_bots_and_sdk_never_imported(self):
        import sys
        for module in ("hyperliquid_executor", "intraday_executor",
                       "aggressive_executor", "eth_account",
                       "hyperliquid.exchange"):
            self.assertNotIn(module, sys.modules)


if __name__ == "__main__":
    unittest.main()
