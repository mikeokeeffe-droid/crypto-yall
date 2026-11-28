"""Pure synthetic tests: scoped evidence is never trusted or authorized."""
import unittest

from offline_hyperliquid_scoped_fixture_review import inspect_scoped_fixture_offline

ACCOUNT = "0x" + "a" * 40


def inspect(**changes):
    args = {
        "environment": "mainnet",
        "endpoint": "https://api.hyperliquid.xyz/info",
        "account": ACCOUNT,
        "expected_account": ACCOUNT,
        "dex": "",
        "kind": "orderStatus",
        "oid": 123,
        "coin": "SOL",
        "direction": "long",
        "requested_size": "2",
        "submitted_at_ms": 100,
        "response": {
            "status": "order",
            "order": {
                "status": "filled", "statusTimestamp": 110,
                "order": {"oid": 123, "coin": "SOL", "side": "B",
                          "origSz": "2", "sz": "0", "limitPx": "100",
                          "reduceOnly": False, "timestamp": 100},
            },
        },
    }
    args.update(changes)
    return inspect_scoped_fixture_offline(**args)


class ScopedFixtureTests(unittest.TestCase):
    def test_matching_order_still_review_only(self):
        result = inspect()
        self.assertEqual(result.status, "review_only")
        self.assertIn("unverified", result.reason)

    def test_cross_account_or_environment_holds(self):
        self.assertEqual(inspect(
            expected_account="0x" + "b" * 40).status, "hold")
        self.assertEqual(inspect(environment="testnet").status, "hold")
        self.assertEqual(inspect(dex="spot").status, "hold")

    def test_wrong_order_or_unsupported_kind_holds(self):
        self.assertEqual(inspect(oid=999).status, "hold")
        self.assertEqual(inspect(kind="exchange").status, "hold")
        self.assertEqual(inspect(direction="short").status, "hold")

    def test_empty_fills_remain_review_only_not_no_fill(self):
        result = inspect(
            kind="userFillsByTime", response=[], start_ms=100, end_ms=200,
        )
        self.assertEqual(result.status, "review_only")
        self.assertIn("unverified", result.reason)

    def test_bad_fills_scope_holds(self):
        result = inspect(
            kind="userFillsByTime", response=[], start_ms=201, end_ms=200,
        )
        self.assertEqual(result.status, "hold")


if __name__ == "__main__":
    unittest.main()
