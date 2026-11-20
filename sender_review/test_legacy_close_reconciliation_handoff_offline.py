"""Full original close call -> offline synthetic read-set, always HOLD."""
from copy import copy
from dataclasses import replace
import unittest

from sender_review.legacy_order_capture_preview import ReviewOnlyMutationBlocked
from sender_review.legacy_protective_close_capture_offline import LegacyProtectiveCloseCaptureOffline
from sender_review.legacy_close_reconciliation_handoff_offline import (
    inspect_legacy_close_with_synthetic_readset_offline,
)
from sender_review.test_legacy_order_capture_preview import (
    FILES, isolated_legacy_execute_trade,
)
from sender_review.test_account_wide_reconciliation_fixture_offline import (
    ACCOUNT, REF, history,
)
from sender_review.test_exchange_readset_gate_offline import manifest


class LegacyCloseReconciliationHandoffTests(unittest.TestCase):
    def capture(self, bot="daily", size=0.12, observed="0.20"):
        cap = LegacyProtectiveCloseCaptureOffline(
            fixture_bot=bot, fixture_nonce="e" * 32,
            expected_coin="SOL", fixture_position_side="long",
            fixture_position_ref=REF, fixture_observed_position_size=observed,
            fixture_exit_reason="profit_floor",
        )
        run_original = isolated_legacy_execute_trade(FILES[bot])
        with self.assertRaises(ReviewOnlyMutationBlocked):
            run_original(None, cap, {
                "hl_coin": "SOL", "action": "close", "close_size": size,
            }, 1000, 2)
        return cap

    def inspect(self, cap, *, synthetic_history=None, synthetic_manifest=None, fence=4):
        return inspect_legacy_close_with_synthetic_readset_offline(
            capture=cap, history=history() if synthetic_history is None else synthetic_history,
            readset=manifest() if synthetic_manifest is None else synthetic_manifest,
            expected_account=ACCOUNT, expected_fence=fence, now_epoch=102,
        )

    def assert_no_authority(self, verdict):
        self.assertEqual(verdict.state, "HOLD")
        for field in (
            "runtime_identity_authenticated", "exchange_provenance_verified",
            "position_ownership_verified", "effective_reduce_only_verified",
            "nonce_reserved", "fence_released", "request_authorized",
            "submit_authorized", "close_authorized", "retry_authorized",
            "signing_enabled",
        ):
            self.assertIs(getattr(verdict, field), False, field)

    def test_original_three_bot_closes_composed_with_consistent_history(self):
        base = history()
        for bot in FILES:
            with self.subTest(bot=bot):
                cap = self.capture(bot)
                h = replace(base,
                    orders=(replace(base.orders[0], bot=bot),),
                    claims=(replace(base.claims[0], bot=bot),),
                )
                verdict = self.inspect(cap, synthetic_history=h)
                self.assertTrue(verdict.synthetic_history_coherent)
                self.assertTrue(verdict.synthetic_manifest_coherent)
                self.assert_no_authority(verdict)

    def test_foreign_claim_stale_bookends_and_oversize_still_hold(self):
        base = history()
        cap = self.capture()
        cases = (
            dict(synthetic_history=replace(base,
                 claims=(replace(base.claims[0], bot="intraday"),))),
            dict(synthetic_history=replace(base,
                 orders=(replace(base.orders[0], status="unknown_ack"),))),
            dict(synthetic_history=replace(base, sampled_epoch=80)),
            dict(synthetic_manifest=manifest(outstanding_unknown_order_ids=("e"*32,))),
            dict(fence=5),
        )
        for kwargs in cases:
            with self.subTest(kwargs=kwargs):
                verdict=self.inspect(cap, **kwargs)
                self.assertFalse(verdict.synthetic_history_coherent)
                self.assert_no_authority(verdict)
        oversized = self.capture(size=0.30)
        verdict = self.inspect(oversized)
        self.assertFalse(verdict.synthetic_history_coherent)
        self.assert_no_authority(verdict)

    def test_capture_mutation_and_unsized_close_cannot_pass(self):
        good=self.capture()
        for field,value in (
            ("captured_close_size", "0.13"),
            ("expected_coin", "AVAX"),
            ("fixture_position_ref", "1"*32),
            ("fixture_exit_reason", "usd_loss_cap"),
            ("position_ownership_verified", True),
            ("signing_enabled", True),
            ("calls", ["legacy_market_close_blocked","legacy_market_close_blocked"]),
        ):
            with self.subTest(field=field):
                bad=copy(good)
                setattr(bad, field, value)
                verdict=self.inspect(bad)
                self.assertFalse(verdict.synthetic_history_coherent)
                self.assert_no_authority(verdict)

        unsized=LegacyProtectiveCloseCaptureOffline(
            fixture_bot="daily", fixture_nonce="e"*32,
            expected_coin="SOL", fixture_position_side="long",
            fixture_position_ref=REF, fixture_observed_position_size="0.20",
            fixture_exit_reason="profit_floor",
        )
        with self.assertRaises(ReviewOnlyMutationBlocked):
            unsized.market_close("SOL")
        verdict=self.inspect(unsized)
        self.assertFalse(verdict.synthetic_history_coherent)
        self.assert_no_authority(verdict)


if __name__ == "__main__":
    unittest.main()
