"""Offline cross-bot close ownership characterization. No exchange or bot imports.

These tests deliberately demonstrate that coin-level local ownership is insufficient.
They do not authorize closing or modify any production executor.
"""
import unittest

from offline_protective_exit_policy import (
    review_pinned_close_identity_offline,
    review_protective_exit_offline,
)


class CrossBotCloseOwnershipTests(unittest.TestCase):
    def setUp(self):
        self.account = "0xSyntheticSharedAccount"
        self.exchange_position = {"coin": "SOL", "side": "long", "size": "3"}
        self.local_claims = {
            "daily": {"SOL"},
            "intraday": {"SOL"},
            "aggressive": set(),
        }

    def review(self, bot, observed_bot, *, owned=False, close_size="1"):
        intended = dict(bot=bot, account=self.account, coin="SOL", side="long")
        observed = dict(intended, bot=observed_bot)
        identity = review_pinned_close_identity_offline(
            intended=intended, observed=observed
        )
        eligibility = review_protective_exit_offline(
            action="close", reduce_only=True, account_verified=True,
            position_owned=owned, position_side="long", position_size="3",
            close_size=close_size, snapshot_fresh=True, entries_disabled=True,
        )
        return identity, eligibility

    def test_two_bots_claim_same_coin_neither_has_verified_ownership(self):
        self.assertIn("SOL", self.local_claims["daily"])
        self.assertIn("SOL", self.local_claims["intraday"])
        for bot in ("daily", "intraday"):
            with self.subTest(bot=bot):
                identity, eligibility = self.review(bot, bot, owned=False)
                self.assertEqual(identity.status, "review_only")
                self.assertEqual(eligibility.status, "hold")
                self.assertFalse(identity.submit_authorized)
                self.assertFalse(eligibility.submit_authorized)

    def test_cross_bot_identity_mismatch_is_held(self):
        identity, eligibility = self.review("daily", "intraday")
        self.assertEqual(identity.status, "hold")
        self.assertEqual(eligibility.status, "hold")

    def test_unverified_full_shared_close_is_held(self):
        identity, eligibility = self.review(
            "intraday", "intraday", owned=False, close_size="3"
        )
        self.assertEqual(identity.status, "review_only")
        self.assertEqual(eligibility.status, "hold")

    def test_even_claimed_verified_partial_close_remains_review_only(self):
        # A caller-provided True is not authenticated order/fill evidence.
        identity, eligibility = self.review(
            "daily", "daily", owned=True, close_size="1"
        )
        self.assertEqual(identity.status, "review_only")
        self.assertEqual(eligibility.status, "review_only")
        self.assertFalse(identity.submit_authorized)
        self.assertFalse(eligibility.submit_authorized)

    def test_oversized_close_is_held_even_with_claimed_ownership(self):
        _, eligibility = self.review(
            "daily", "daily", owned=True, close_size="4"
        )
        self.assertEqual(eligibility.status, "hold")


if __name__ == "__main__":
    unittest.main()
