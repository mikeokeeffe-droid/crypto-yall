"""Offline original bot decision -> immutable review-only entry tests."""
import unittest
import json
from dataclasses import FrozenInstanceError

from offline_original_bot_intent_adapter import (project_original_entry,
    prepare_signer_free_entry_handoff_offline, review_signer_free_entry_ack_offline)

ACCOUNT = "0x" + "1" * 40
BOTS = ("daily", "intraday", "aggressive")


class OriginalBotIntentAdapterTests(unittest.TestCase):
    def project(self, bot="daily", action="open_long", side="long",
                coin="SOL", size="0.025", **kwargs):
        return project_original_entry(
            verified_bot=bot,
            trade={"action": action, "side": side, "hl_coin": coin},
            rounded_size=size, pinned_environment="mainnet",
            pinned_account=ACCOUNT, **kwargs,
        )

    def test_all_three_original_bots_have_same_review_only_shape(self):
        for bot in BOTS:
            for action, side in (("open_long", "long"),
                                 ("open_short", "short")):
                with self.subTest(bot=bot, action=action):
                    result = self.project(bot=bot, action=action, side=side)
                    self.assertIsNotNone(result)
                    self.assertEqual(result.bot, bot)
                    self.assertEqual(result.action, action)
                    self.assertEqual(result.coin, "SOL")
                    self.assertEqual(result.size, "0.025")
                    self.assertEqual(result.environment, "mainnet")
                    self.assertEqual(result.account, ACCOUNT)
                    self.assertEqual(result.dex, "")
                    self.assertFalse(result.submit_authorized)
                    with self.assertRaises(FrozenInstanceError):
                        result.size = "100"

    def test_pyramid_close_and_untrusted_side_never_project(self):
        for action, side in (("pyramid_long", "long"),
                             ("pyramid_short", "short"),
                             ("close", "long"),
                             ("open_long", "short"),
                             ("open_short", "long"),
                             ("open", "long")):
            with self.subTest(action=action, side=side):
                self.assertIsNone(self.project(action=action, side=side))

    def test_invalid_quantity_holds_including_floats(self):
        for size in ("0", "-1", "NaN", "Infinity", "1e4", " 2",
                     "0.0", "0.000", "", "1_000", "1.2.3",
                     1.25, 1, None, True):
            with self.subTest(size=size):
                self.assertIsNone(self.project(size=size))

    def test_verified_identity_and_pinned_scope_required(self):
        for bot in ("intradaay", "", None, 123):
            with self.subTest(bot=bot):
                self.assertIsNone(self.project(bot=bot))
        for change in (
            {"pinned_environment": "prod"},
            {"pinned_account": "0x" + "A" * 40},
            {"pinned_account": "0x" + "1" * 39},
            {"pinned_dex": "other"},
        ):
            with self.subTest(change=change):
                self.assertIsNone(project_original_entry(
                    verified_bot="daily",
                    trade={"action": "open_long", "side": "long",
                           "hl_coin": "SOL"},
                    rounded_size="0.025",
                    pinned_environment=change.get("pinned_environment",
                                                   "mainnet"),
                    pinned_account=change.get("pinned_account", ACCOUNT),
                    pinned_dex=change.get("pinned_dex", ""),
                ))

    def test_untrusted_trade_identity_fields_and_bad_coins_hold(self):
        for field, value in (
            ("bot", "intraday"),
            ("account", ACCOUNT),
            ("environment", "mainnet"),
            ("dex", ""),
            ("hl_coin", "sol"),
            ("hl_coin", "SOL/USDC"),
            ("hl_coin", ""),
        ):
            trade={"action": "open_long", "side": "long", "hl_coin": "SOL"}
            trade[field]=value
            with self.subTest(field=field, value=value):
                self.assertIsNone(project_original_entry(
                    verified_bot="daily", trade=trade,
                    rounded_size="1.5", pinned_environment="mainnet",
                    pinned_account=ACCOUNT,
                ))

    def test_never_loads_trading_sdk_or_original_executors(self):
        import sys
        self.assertNotIn("hyperliquid.exchange", sys.modules)
        self.assertNotIn("hyperliquid_executor", sys.modules)
        self.assertNotIn("intraday_executor", sys.modules)
        self.assertNotIn("aggressive_executor", sys.modules)


    def test_signer_free_entry_request_is_only_a_request(self):
        for bot in BOTS:
            for action, side in (("open_long", "long"), ("open_short", "short")):
                with self.subTest(bot=bot, action=action):
                    result=prepare_signer_free_entry_handoff_offline(
                        verified_bot=bot,
                        trade={"action":action,"side":side,"hl_coin":"SOL"},
                        rounded_size="0.025",pinned_environment="mainnet",
                        pinned_account=ACCOUNT,
                    )
                    self.assertEqual(result.state,"request_only")
                    self.assertFalse(result.submit_authorized)
                    self.assertEqual(json.loads(result.request_json),{
                        "operation":"request_entry","action":action,"side":side,
                        "hl_coin":"SOL","rounded_size":"0.025",
                    })
                    for forbidden in ("bot","account","environment","dex",
                                      "cloid","token","wallet","private_key"):
                        self.assertNotIn(forbidden,json.loads(result.request_json))

    def test_signer_free_handoff_denies_closes_pyramids_and_spoofing(self):
        for action,side in (("close","long"),("pyramid_long","long"),
                            ("pyramid_short","short"),("update_leverage","long")):
            with self.subTest(action=action):
                result=prepare_signer_free_entry_handoff_offline(
                    verified_bot="aggressive",
                    trade={"action":action,"side":side,"hl_coin":"SOL"},
                    rounded_size="0.025",pinned_environment="mainnet",
                    pinned_account=ACCOUNT,
                )
                self.assertEqual(result.state,"hold")
                self.assertIsNone(result.request_json)
        spoof=prepare_signer_free_entry_handoff_offline(
            verified_bot="daily",
            trade={"action":"open_long","side":"long","hl_coin":"SOL",
                   "account":ACCOUNT},
            rounded_size="0.025",pinned_environment="mainnet",
            pinned_account=ACCOUNT,
        )
        self.assertEqual(spoof.state,"hold")

    def test_signer_free_ack_cannot_authorize_exchange_submissions(self):
        for payload, expected in (
            (b'{"state":"reserved_offline_only","submit_authorized":false}',
             "recorded_offline_only"),
            (b'{"state":"hold","submit_authorized":false}',"hold"),
            (b'{"state":"reserved_offline_only","submit_authorized":true}',"hold"),
            (b'{"state":"reserved_offline_only","submit_authorized":false,"oid":10}',"hold"),
            (b'{"state":"reserved_offline_only","state":"hold","submit_authorized":false}',"hold"),
            (b'not json',"hold"),
            (b'{}',"hold"),
        ):
            with self.subTest(payload=payload):
                result=review_signer_free_entry_ack_offline(reply_bytes=payload)
                self.assertEqual(result.state,expected)
                self.assertFalse(result.submit_authorized)


if __name__ == "__main__":
    unittest.main()
