"""Offline synthetic account-impact and partial-cancel tests."""
import unittest

from offline_hyperliquid_account_impact import inspect_account_order_impact_offline

TARGET = ("SOL", 123, 1, 150, "B", "Open Long", "2")
OTHER = ("SOL", 999, 2, 151, "B", "Open Long", "1")


def inspect(**changes):
    args = dict(target_oid=123, target_coin="SOL", order_status="filled",
                requested_size="2", fills=(TARGET,),
                open_orders_known_empty=True, position_snapshot_verified=True)
    args.update(changes)
    return inspect_account_order_impact_offline(**args)


class AccountImpactTests(unittest.TestCase):
    def test_matching_fake_state_remains_review_only(self):
        result = inspect()
        self.assertEqual(result.status, "review_only")
        self.assertIn("unverified", result.reason)

    def test_other_order_same_coin_holds(self):
        self.assertEqual(inspect(fills=(TARGET, OTHER)).status, "hold")

    def test_partial_fill_then_cancel_or_reject_holds(self):
        partial = (("SOL", 123, 1, 150, "B", "Open Long", "1"),)
        for status in ("canceled", "cancelled", "rejected"):
            with self.subTest(status=status):
                self.assertEqual(inspect(
                    order_status=status, fills=partial).status, "hold")

    def test_even_full_fill_cancel_status_holds(self):
        self.assertEqual(inspect(order_status="canceled").status, "hold")

    def test_missing_open_orders_or_position_evidence_holds(self):
        self.assertEqual(inspect(open_orders_known_empty=False).status, "hold")
        self.assertEqual(inspect(position_snapshot_verified=False).status, "hold")
        self.assertEqual(inspect(position_snapshot_verified=None).status, "hold")

    def test_missing_or_excess_fill_holds(self):
        self.assertEqual(inspect(fills=()).status, "hold")
        self.assertEqual(inspect(fills=(
            ("SOL", 123, 1, 150, "B", "Open Long", "3"),)).status, "hold")

    def test_other_coin_fill_also_holds_account_review(self):
        result = inspect(fills=(TARGET, ("BTC", 999, 2, 151, "B", "Open Long", "1")))
        self.assertEqual(result.status, "hold")


if __name__ == "__main__":
    unittest.main()
