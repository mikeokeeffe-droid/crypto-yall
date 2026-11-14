"""Offline coverage for all original bot order-mutation categories."""
import json
import unittest

from offline_three_bot_mutation_review_ci import (
    review_original_bot_mutation_offline as review,
)

ACCOUNT = "0x" + "1" * 40
BOTS = ("daily", "intraday", "aggressive")


def check(caller_bot, action, *, size="0.025", coin="SOL", **extra):
    return review(
        verified_bot=caller_bot,
        trade={"action": action, "side":
               ("short" if action.endswith("_short") else "long"),
               "hl_coin": coin, **extra},
        rounded_size=size,
        pinned_environment="mainnet", pinned_account=ACCOUNT,
    )


class ThreeBotMutationReviewTests(unittest.TestCase):
    def test_new_entries_are_request_only_and_no_signer_rights(self):
        for bot in BOTS:
            for action in ("open_long", "open_short"):
                with self.subTest(bot=bot, action=action):
                    r = check(bot, action)
                    self.assertEqual(r.state, "request_only")
                    self.assertEqual(r.action_class, "new_entry")
                    self.assertFalse(r.submit_authorized)
                    self.assertFalse(r.ownership_verified)
                    self.assertFalse(r.close_authorized)
                    self.assertEqual(json.loads(r.request_json)["operation"],
                                     "request_entry")
                    for forbidden in ("bot", "account", "environment",
                                      "private_key", "cloid", "token"):
                        self.assertNotIn(forbidden, json.loads(r.request_json))

    def test_aggressive_pyramids_are_detected_but_never_sent(self):
        for action in ("pyramid_long", "pyramid_short"):
            with self.subTest(action=action):
                r = check("aggressive", action)
                self.assertEqual(r.action_class, "pyramid_increase")
                self.assertEqual(r.state, "hold")
                self.assertIsNone(r.request_json)
                self.assertFalse(r.submit_authorized)
                for bot in ("daily", "intraday"):
                    self.assertEqual(check(bot, action).state, "hold")

    def test_sized_and_unsized_closes_are_held(self):
        for bot in BOTS:
            for size in (None, "", "0", "-1", "NaN", "0.25", "200", 0.25,
                         1, "1e9", " 1", "0.000"):
                with self.subTest(bot=bot, size=size):
                    data = {} if size is None else {"close_size": size}
                    r = check(bot, "close", **data)
                    self.assertEqual(r.action_class, "close")
                    self.assertEqual(r.state, "hold")
                    self.assertIsNone(r.request_json)
                    self.assertFalse(r.close_authorized)
                    self.assertFalse(r.ownership_verified)
                    self.assertFalse(r.submit_authorized)

    def test_leverage_and_unknown_mutations_fail_closed(self):
        for bot in BOTS:
            for action in ("update_leverage", "cancel", "market_open", "close_all"):
                with self.subTest(bot=bot, action=action):
                    r = check(bot, action)
                    self.assertEqual(r.state, "hold")
                    self.assertIsNone(r.request_json)
                    self.assertFalse(r.submit_authorized)

    def test_spoofed_scope_or_client_authority_is_rejected(self):
        for field, value in (
            ("bot", "intraday"), ("account", ACCOUNT),
            ("environment", "testnet"), ("dex", ""), ("cloid", "0xabc"),
            ("submit_authorized", True), ("private_key", "test"),
        ):
            with self.subTest(field=field):
                r = check("daily", "open_long", **{field: value})
                self.assertEqual(r.state, "hold")
                self.assertIsNone(r.request_json)
                self.assertFalse(r.submit_authorized)

    def test_wrong_bot_and_bad_size_do_not_build_entry_requests(self):
        for bot in ("unknown", None, "", 123):
            with self.subTest(bot=bot):
                self.assertEqual(check(bot, "open_long").state, "hold")
        for size in ("0", "-1", "NaN", "1e8", " 2", 1.2, None):
            with self.subTest(size=size):
                self.assertEqual(check("daily", "open_long", size=size).state,
                                 "hold")

    def test_no_original_executor_or_exchange_sdk_import(self):
        import sys
        for module in ("hyperliquid_executor", "intraday_executor",
                       "aggressive_executor", "hyperliquid.exchange"):
            self.assertNotIn(module, sys.modules)


if __name__ == "__main__":
    unittest.main()
