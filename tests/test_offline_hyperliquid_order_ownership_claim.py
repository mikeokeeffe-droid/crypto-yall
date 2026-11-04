"""Synthetic order-ownership claims are never sufficient to unlock trading."""
import unittest
from offline_hyperliquid_order_ownership_claim import inspect_claimed_order_ownership_offline

PINNED = {"account": "0xabc", "coin": "SOL", "direction": "long", "oid": 42}

class OrderOwnershipClaimTests(unittest.TestCase):
    def test_exact_matching_claim_remains_on_hold(self):
        result = inspect_claimed_order_ownership_offline(
            intent=PINNED, claim=dict(PINNED))
        self.assertEqual(result.status, "hold")
        self.assertIn("not authenticated", result.reason)

    def test_any_mismatched_identity_holds(self):
        for key, value in (
            ("account", "0xdef"), ("coin", "ETH"),
            ("direction", "short"), ("oid", 43),
        ):
            with self.subTest(key=key):
                claim = dict(PINNED, **{key: value})
                result = inspect_claimed_order_ownership_offline(
                    intent=PINNED, claim=claim)
                self.assertEqual(result.status, "hold")
                self.assertIn("contradicts", result.reason)

    def test_invalid_or_extra_claim_fields_hold(self):
        for claim in (
            None, {}, dict(PINNED, oid=True), dict(PINNED, oid="42"),
            dict(PINNED, account=""), dict(PINNED, coin=""),
            dict(PINNED, direction=["long"]),
            dict(PINNED, unverified=True),
        ):
            with self.subTest(claim=repr(claim)):
                self.assertEqual(inspect_claimed_order_ownership_offline(
                    intent=PINNED, claim=claim).status, "hold")

if __name__ == "__main__":
    unittest.main()
