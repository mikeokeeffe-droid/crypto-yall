"""Source-extracted original entry calls yield non-executable V2 leverage drafts."""
import json
import unittest
from offline_leverage_bound_entry_draft_ci import OfflineLeverageBoundEntrySink

ACCOUNT = "0x" + "1" * 40


class OfflineLeverageDraftTests(unittest.TestCase):
    def make(self, bot="daily", action="open_long"):
        return OfflineLeverageBoundEntrySink(
            bot=bot,
            trade={"action": action, "hl_coin": "SOL"},
            environment="mainnet", account=ACCOUNT,
        )

    def test_original_entry_leverage_and_size_bound_for_review_only(self):
        for bot in ("daily", "intraday", "aggressive"):
            for action, is_buy in (("open_long", True), ("open_short", False)):
                with self.subTest(bot=bot, action=action):
                    sink = self.make(bot, action)
                    sink.update_leverage(2, "SOL", True)
                    result = sink.market_open("SOL", is_buy, 1.6)
                    self.assertEqual(result["status"], "offline_hold")
                    self.assertEqual(sink.last_draft.state, "review_only")
                    self.assertFalse(sink.last_draft.submit_authorized)
                    self.assertFalse(sink.last_draft.leverage_applied)
                    draft=json.loads(sink.last_draft.review_json)
                    self.assertEqual(draft, {
                        "operation":"review_entry_leverage_v2",
                        "action":action,
                        "side":"long" if is_buy else "short",
                        "hl_coin":"SOL",
                        "rounded_size":"1.6",
                        "requested_leverage":2,
                        "cross_margin_requested":True,
                    })
                    self.assertNotIn("account",draft)
                    self.assertNotIn("private_key",draft)

    def test_invalid_or_unverified_leverage_does_not_produce_draft(self):
        for leverage, coin, cross in (
            (0, "SOL", True), (101, "SOL", True),
            (2.0, "SOL", True), (2, "AVAX", True),
            (2, "SOL", False), (True, "SOL", True),
        ):
            with self.subTest(leverage=leverage,coin=coin,cross=cross):
                sink=self.make()
                sink.update_leverage(leverage,coin,cross)
                sink.market_open("SOL",True,1.6)
                self.assertEqual(sink.last_draft.state,"hold")
                self.assertIsNone(sink.last_draft.review_json)
                self.assertFalse(sink.last_draft.submit_authorized)
        sink=self.make()
        sink.market_open("SOL",True,1.6)
        self.assertEqual(sink.last_draft.state,"hold")
        sink=self.make()
        sink.update_leverage(2,"SOL",True)
        sink.update_leverage(3,"SOL",True)
        sink.market_open("SOL",True,1.6)
        self.assertEqual(sink.last_draft.state,"hold")

    def test_close_pyramid_and_mismatch_hold_even_with_valid_leverage(self):
        for action, is_buy in (("pyramid_long",True),
                                ("pyramid_short",False)):
            sink=self.make("aggressive",action)
            sink.update_leverage(2,"SOL",True)
            sink.market_open("SOL",is_buy,1.6)
            self.assertEqual(sink.last_draft.state,"hold")
        sink=self.make("daily","open_short")
        sink.update_leverage(2,"SOL",True)
        sink.market_open("SOL",True,1.6)
        self.assertEqual(sink.last_draft.state,"hold")
        sink=self.make()
        sink.market_close("SOL",0.5)
        self.assertEqual(sink.last_draft.state,"hold")
        self.assertFalse(sink.last_review.close_authorized)

    def test_v2_draft_cannot_pass_existing_v1_socket_schema(self):
        # Existing coordinator accepts only five strictly named fields.
        # Do not promote this draft into executable transport.
        from offline_original_bot_socket_bridge_ci import _FIELDS
        sink=self.make()
        sink.update_leverage(2,"SOL",True)
        sink.market_open("SOL",True,1.6)
        draft=json.loads(sink.last_draft.review_json)
        self.assertNotEqual(set(draft),_FIELDS)
        self.assertNotEqual(draft["operation"],"request_entry")


if __name__ == "__main__":
    unittest.main()
