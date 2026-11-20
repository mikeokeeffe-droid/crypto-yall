"""Original three-bot close syntax is captured but can NEVER close a trade."""
import json
import unittest

from sender_review.legacy_order_capture_preview import ReviewOnlyMutationBlocked
from sender_review.legacy_protective_close_capture_offline import (
    LegacyProtectiveCloseCaptureOffline,
)
from sender_review.test_legacy_order_capture_preview import (
    FILES, isolated_legacy_execute_trade,
)
from sender_review.proposed_intent_interfaces_offline import (
    inspect_proposed_intent_offline,
)
from sender_review.request_contract import inspect_sender_entry_request_offline

NONCE = "a" * 32
REF = "b" * 32


class LegacyProtectiveCloseCaptureTests(unittest.TestCase):
    def adapter(self, bot="daily", observed="0.50", reason="profit_floor"):
        return LegacyProtectiveCloseCaptureOffline(
            fixture_bot=bot, fixture_nonce=NONCE,
            expected_coin="SOL", fixture_position_side="long",
            fixture_position_ref=REF, fixture_observed_position_size=observed,
            fixture_exit_reason=reason,
        )

    def assert_untrusted(self, capture):
        for attribute in (
            "position_ownership_verified", "exchange_state_verified",
            "effective_reduce_only_verified", "close_authorized",
            "submit_authorized", "signing_enabled",
        ):
            self.assertFalse(getattr(capture, attribute), attribute)

    def test_original_sized_close_is_only_captured_never_acknowledged(self):
        for bot in FILES:
            for reason in (
                "signal_exit", "profit_floor", "trailing_protection",
                "usd_loss_cap",
            ):
                with self.subTest(bot=bot, reason=reason):
                    fn = isolated_legacy_execute_trade(FILES[bot])
                    capture = self.adapter(bot=bot, reason=reason)
                    with self.assertRaisesRegex(
                        ReviewOnlyMutationBlocked, "NO_SEND_REVIEW_ONLY"
                    ):
                        fn(None, capture, {
                            "hl_coin": "SOL", "action": "close",
                            "close_size": 0.25,
                        }, 1000, 2)
                    self.assertEqual(
                        capture.calls, ["legacy_market_close_blocked"]
                    )
                    self.assert_untrusted(capture)
                    proposal = json.loads(capture.proposed_body)
                    self.assertEqual(
                        set(proposal),
                        {
                            "version", "action", "side", "coin",
                            "request_nonce", "close_size",
                            "observed_position_size", "position_ref",
                            "exit_reason", "reduce_only",
                        },
                    )
                    self.assertEqual(proposal["action"], "protective_close")
                    self.assertEqual(proposal["coin"], "SOL")
                    self.assertEqual(proposal["close_size"], "0.25")
                    self.assertEqual(proposal["observed_position_size"], "0.50")
                    self.assertEqual(proposal["position_ref"], REF)
                    self.assertEqual(proposal["exit_reason"], reason)
                    self.assertIs(proposal["reduce_only"], True)
                    review = inspect_proposed_intent_offline(
                        body=capture.proposed_body, fixture_bot=bot,
                    )
                    self.assertEqual(review.state, "parsed_review_only_HOLD")
                    self.assertFalse(review.close_authorized)
                    self.assertFalse(review.effective_reduce_only_verified)
                    # No protective close can enter existing S1 entry journal.
                    self.assertEqual(
                        inspect_sender_entry_request_offline(
                            body=capture.proposed_body
                        ).state, "hold"
                    )

    def test_original_unsized_close_never_creates_a_proposal(self):
        for bot in FILES:
            with self.subTest(bot=bot):
                fn = isolated_legacy_execute_trade(FILES[bot])
                capture = self.adapter(bot=bot)
                with self.assertRaises(ReviewOnlyMutationBlocked):
                    fn(None, capture, {
                        "hl_coin": "SOL", "action": "close",
                    }, 1000, 2)
                self.assertIsNone(capture.proposed_body)
                self.assert_untrusted(capture)

    def test_oversized_mismatched_or_invalid_scope_rejected(self):
        cases = (
            ("daily", "0.50", "profit_floor", "AVAX", 0.1),
            ("daily", "0.50", "profit_floor", "SOL", 0),
            ("daily", "0.50", "profit_floor", "SOL", -1),
            ("daily", "0.50", "profit_floor", "SOL", float("nan")),
            ("daily", "0.50", "profit_floor", "SOL", 0.60),
            ("daily", "0", "profit_floor", "SOL", 0.2),
            ("daily", "0.50", "unauthorized", "SOL", 0.2),
            ("unknown", "0.50", "profit_floor", "SOL", 0.2),
        )
        for bot, observed, reason, coin, qty in cases:
            with self.subTest(bot=bot, qty=qty, reason=reason, coin=coin):
                capture = self.adapter(bot=bot, observed=observed, reason=reason)
                with self.assertRaises(ReviewOnlyMutationBlocked):
                    capture.market_close(coin, sz=qty)
                self.assertIsNone(capture.proposed_body)
                self.assert_untrusted(capture)

    def test_double_close_and_old_unsized_call_both_refused(self):
        capture = self.adapter()
        with self.assertRaises(ReviewOnlyMutationBlocked):
            capture.market_close("SOL", sz=0.25)
        self.assertIsNotNone(capture.proposed_body)
        with self.assertRaises(ReviewOnlyMutationBlocked):
            capture.market_close("SOL", sz=0.25)
        self.assertEqual(capture.calls, [
            "legacy_market_close_blocked", "legacy_market_close_blocked",
        ])
        self.assert_untrusted(capture)
        empty = self.adapter()
        with self.assertRaises(ReviewOnlyMutationBlocked):
            empty.market_close("SOL")
        self.assertIsNone(empty.proposed_body)


if __name__ == "__main__":
    unittest.main()
