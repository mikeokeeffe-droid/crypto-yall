"""Synthetic three-bot net-position checks, with zero close authority."""
import unittest
from offline_account_exposure_conservation_ci import (
    review_synthetic_account_exposure_offline as review,
)

ACCOUNT = "0x" + "1" * 40


def f(bot, side, size, order_id, timestamp_ms, suffix=None):
    return {
        "origin": "fixture",
        "fill_id": str(suffix or order_id),
        "bot": bot, "order_id": order_id,
        "cloid": "0x" + format(order_id, "032x"),
        "account": ACCOUNT, "environment": "mainnet",
        "coin": "SOL", "side": side, "size": size,
        "timestamp_ms": timestamp_ms,
    }


def snapshot(signed_size="0.35", as_of_ms=200):
    return {
        "origin": "fixture", "account": ACCOUNT,
        "environment": "mainnet", "coin": "SOL",
        "signed_size": signed_size, "as_of_ms": as_of_ms,
    }


def check(fills=None, position_snapshot=None, **overrides):
    opts = {
        "account": ACCOUNT, "environment": "mainnet", "coin": "SOL",
        "initial_flat": True, "complete_history": True,
        "fills": fills if fills is not None else [
            f("daily", "buy", "0.20", 1, 100),
            f("intraday", "buy", "0.10", 2, 110),
            f("aggressive", "buy", "0.05", 3, 120),
        ],
        "position_snapshot": position_snapshot or snapshot(),
    }
    opts.update(overrides)
    return review(**opts)


class ExposureConservationTests(unittest.TestCase):
    def assert_hold(self, outcome, consistent=False):
        self.assertEqual(outcome.state, "hold")
        self.assertEqual(outcome.structurally_consistent, consistent)
        self.assertFalse(outcome.ownership_verified)
        self.assertFalse(outcome.close_authorized)
        self.assertIsNone(outcome.executable_close_size)

    def test_three_bot_same_direction_reconciles_math_but_no_close_rights(self):
        decision = check()
        self.assert_hold(decision, consistent=True)
        self.assertIn("3 bot(s)", decision.reason)

    def test_partial_fills_same_order_can_conserve_without_ownership(self):
        fills = [
            f("daily", "buy", "0.125", 1, 100, suffix="part-1"),
            f("daily", "buy", "0.075", 1, 101, suffix="part-2"),
            f("intraday", "buy", "0.10", 2, 110),
            f("aggressive", "buy", "0.05", 3, 120),
        ]
        self.assert_hold(check(fills=fills), consistent=True)

    def test_manual_foreign_opposite_and_missing_history_hold(self):
        base = check()
        self.assert_hold(base, consistent=True)
        self.assert_hold(check(complete_history=False))
        self.assert_hold(check(initial_flat=False))
        self.assert_hold(check(position_snapshot=snapshot("0.40")))
        self.assert_hold(check(fills=[
            f("daily", "buy", "0.20", 1, 100),
            f("intraday", "sell", "0.10", 2, 110),
        ], position_snapshot=snapshot("0.10")))
        manual = f("daily", "buy", "0.35", 1, 100)
        manual["bot"] = "manual"
        self.assert_hold(check(fills=[manual]))
        foreign = f("daily", "buy", "0.35", 1, 100)
        foreign["account"] = "0x" + "2" * 40
        self.assert_hold(check(fills=[foreign]))

    def test_duplicate_cloid_conflict_stale_and_malformed_hold(self):
        original = f("daily", "buy", "0.20", 1, 100)
        repeated = dict(original, fill_id="same")
        self.assert_hold(check(fills=[original, original]))
        self.assert_hold(check(fills=[original, repeated]))
        changed = f("intraday", "buy", "0.15", 1, 110, suffix="new")
        self.assert_hold(check(fills=[original, changed]))
        reused = f("daily", "buy", "0.15", 2, 110, suffix="new")
        reused["cloid"] = original["cloid"]
        self.assert_hold(check(fills=[original, reused]))
        self.assert_hold(check(fills=[
            f("daily", "buy", "0.20", 1, 150),
            f("intraday", "buy", "0.15", 2, 110),
        ]))
        self.assert_hold(check(fills=[
            f("daily", "buy", "0.35", 1, 210),
        ]))
        self.assert_hold(check(fills=[
            {**f("daily", "buy", "0.35", 1, 100), "size": "NaN"},
        ]))
        self.assert_hold(check(fills=[
            {**f("daily", "buy", "0.35", 1, 100), "submit_authorized": True},
        ]))

    def test_zero_snapshot_no_matched_positive_fills_is_not_ownership(self):
        self.assert_hold(check(position_snapshot=snapshot("0")))

    def test_does_not_load_real_exchange_or_original_bots(self):
        import sys
        for name in ("eth_account", "hyperliquid.exchange",
                     "hyperliquid_executor", "intraday_executor",
                     "aggressive_executor"):
            self.assertNotIn(name, sys.modules)


if __name__ == "__main__":
    unittest.main()
