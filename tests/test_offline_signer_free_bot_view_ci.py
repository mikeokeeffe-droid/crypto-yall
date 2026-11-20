"""No-network tests for synthetic three-bot Info + request-only boundary."""
import json
import unittest
from dataclasses import FrozenInstanceError

from offline_signer_free_bot_view_ci import make_offline_signer_free_bot_view

ACCOUNT = "0x" + "1" * 40


def fake_snapshot(account=ACCOUNT, environment="testnet"):
    return {
        "environment": environment,
        "account": account,
        "user_state": {"marginSummary": {"accountValue": "125"},
                       "assetPositions": [{"position": {
                           "coin": "SOL", "szi": "0.025", "entryPx": "100",
                           "unrealizedPnl": "1.5", "leverage": "2",
                       }}]},
        "spot_state": {"balances": [{"coin": "USDC", "total": "40"}]},
        "all_mids": {"SOL": "110"},
        "meta": {"universe": [{"name": "SOL", "szDecimals": 3}]},
    }


class OfflineSignerFreeBotViewTests(unittest.TestCase):
    def make(self, bot="daily", **overrides):
        args = dict(verified_bot=bot, pinned_environment="testnet",
                    pinned_account=ACCOUNT, snapshot=fake_snapshot())
        args.update(overrides)
        return make_offline_signer_free_bot_view(**args)

    def test_all_three_have_signer_free_reads_and_request_only_entries(self):
        for bot in ("daily", "intraday", "aggressive"):
            with self.subTest(bot=bot):
                view = self.make(bot)
                self.assertIsNotNone(view)
                self.assertEqual(view.info.user_state(ACCOUNT)
                                 ["marginSummary"]["accountValue"], "125")
                self.assertEqual(view.info.all_mids()["SOL"], "110")
                self.assertFalse(view.origin_authenticated)
                self.assertFalse(view.ownership_verified)
                self.assertFalse(view.submit_authorized)
                self.assertFalse(view.info.submit_authorized)
                for forbidden in ("market_open", "market_close",
                                  "update_leverage", "order", "cancel"):
                    self.assertFalse(hasattr(view.info, forbidden))
                    self.assertFalse(hasattr(view, forbidden))
                result = view.prepare_entry_request(
                    trade={"action": "open_long", "side": "long",
                           "hl_coin": "SOL"},
                    rounded_size="0.025",
                )
                self.assertEqual(result.state, "request_only")
                self.assertFalse(result.submit_authorized)
                data = json.loads(result.request_json)
                self.assertEqual(data["operation"], "request_entry")
                self.assertEqual(data["rounded_size"], "0.025")
                for forbidden in ("bot", "account", "environment",
                                  "wallet", "private_key", "cloid"):
                    self.assertNotIn(forbidden, data)
                with self.assertRaises(FrozenInstanceError):
                    view.account = "0x" + "2" * 40

    def test_malformed_scope_and_fake_data_fail_closed(self):
        for changes in (
            {"verified_bot": "unknown"},
            {"pinned_environment": "production"},
            {"pinned_account": "0x" + "2" * 40},
            {"pinned_dex": "other"},
            {"snapshot": {}},
        ):
            with self.subTest(changes=changes):
                args = dict(verified_bot="daily",
                            pinned_environment="testnet",
                            pinned_account=ACCOUNT,
                            snapshot=fake_snapshot())
                args.update(changes)
                self.assertIsNone(make_offline_signer_free_bot_view(**args))

    def test_protective_closes_leverage_and_pyramids_hold(self):
        view = self.make("aggressive")
        for action in ("close", "pyramid_long", "pyramid_short",
                       "update_leverage"):
            with self.subTest(action=action):
                result = view.prepare_entry_request(
                    trade={"action": action, "side": "long",
                           "hl_coin": "SOL"},
                    rounded_size="0.025",
                )
                self.assertEqual(result.state, "hold")
                self.assertIsNone(result.request_json)
                self.assertFalse(result.submit_authorized)

    def test_untrusted_identity_in_trade_cannot_override_scope(self):
        view = self.make("daily")
        for key, value in (("bot", "aggressive"),
                           ("account", "0x" + "2" * 40),
                           ("environment", "mainnet"),
                           ("dex", "")):
            with self.subTest(key=key):
                result = view.prepare_entry_request(
                    trade={"action": "open_long", "side": "long",
                           "hl_coin": "SOL", key: value},
                    rounded_size="0.025",
                )
                self.assertEqual(result.state, "hold")
                self.assertFalse(result.submit_authorized)

    def test_original_executors_and_signer_sdk_not_imported(self):
        import sys
        for module in ("hyperliquid_executor", "intraday_executor",
                       "aggressive_executor", "hyperliquid.exchange"):
            self.assertNotIn(module, sys.modules)


if __name__ == "__main__":
    unittest.main()
