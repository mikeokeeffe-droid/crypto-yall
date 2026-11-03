"""No-network tests for a future strictly scoped read-only /info plan."""
import unittest

from offline_hyperliquid_transport_plan import (
    review_readonly_transport_plan_offline,
)

ACCOUNT = "0x" + "a" * 40


def review(**overrides):
    args = {
        "environment": "mainnet",
        "endpoint": "https://api.hyperliquid.xyz/info",
        "account": ACCOUNT,
        "expected_account": ACCOUNT,
        "dex": "",
        "method": "POST",
        "request_type": "orderStatus",
        "allow_network": False,
    }
    args.update(overrides)
    return review_readonly_transport_plan_offline(**args)


class OfflineTransportPlanTests(unittest.TestCase):
    def test_default_mainnet_is_plan_only(self):
        result = review()
        self.assertEqual(result.status, "plan_only")
        self.assertIn("unverified", result.reason)

    def test_testnet_must_match_endpoint(self):
        self.assertEqual(review(
            environment="testnet",
            endpoint="https://api.hyperliquid-testnet.xyz/info",
        ).status, "plan_only")
        self.assertEqual(review(environment="testnet").status, "hold")

    def test_wrong_account_and_dex_hold(self):
        self.assertEqual(review(
            expected_account="0x" + "b" * 40).status, "hold")
        self.assertEqual(review(dex="other-dex").status, "hold")
        self.assertEqual(review(account="invalid").status, "hold")

    def test_network_or_trading_methods_hold(self):
        for changes in (
            {"allow_network": True}, {"allow_network": None},
            {"method": "GET"}, {"request_type": "exchange"},
            {"request_type": "clearinghouseState"},
        ):
            with self.subTest(changes=changes):
                self.assertEqual(review(**changes).status, "hold")

    def test_host_rewrites_and_query_strings_hold(self):
        for endpoint in (
            "http://api.hyperliquid.xyz/info",
            "https://evil.example/info",
            "https://api.hyperliquid.xyz/info?type=exchange",
            "https://api.hyperliquid.xyz@evil.example/info",
        ):
            with self.subTest(endpoint=endpoint):
                self.assertEqual(review(endpoint=endpoint).status, "hold")

    def test_no_live_transport_functions(self):
        import offline_hyperliquid_transport_plan as module
        self.assertFalse(hasattr(module, "request"))
        self.assertFalse(hasattr(module, "send_order"))


if __name__ == "__main__":
    unittest.main()
