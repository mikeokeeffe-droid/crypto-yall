"""Offline tests cannot establish authentic Hyperliquid response provenance."""
import unittest

from offline_hyperliquid_capture_provenance import inspect_capture_claim_offline

ACCOUNT = "0x" + "a" * 40
ENDPOINT = "https://api.hyperliquid.xyz/info"


def inspect(**overrides):
    args = {
        "environment": "mainnet", "endpoint": ENDPOINT,
        "account": ACCOUNT, "expected_account": ACCOUNT, "dex": "",
        "request_type": "orderStatus",
        "capture": {
            "environment": "mainnet", "endpoint": ENDPOINT,
            "account": ACCOUNT, "dex": "", "request_type": "orderStatus",
            "method": "POST", "response_origin": "simulated",
            "transport_verified": False, "authenticated": False,
        },
    }
    args.update(overrides)
    return inspect_capture_claim_offline(**args)


class CaptureProvenanceTests(unittest.TestCase):
    def test_consistent_synthetic_capture_is_review_only(self):
        result = inspect()
        self.assertEqual(result.status, "review_only")
        self.assertIn("unverified", result.reason)

    def test_fake_authenticated_flag_holds(self):
        cap = dict(inspect_capture())
        cap["authenticated"] = True
        self.assertEqual(inspect(capture=cap).status, "hold")

    def test_claimed_verified_transport_holds(self):
        cap = dict(inspect_capture())
        cap["transport_verified"] = True
        self.assertEqual(inspect(capture=cap).status, "hold")

    def test_wrong_origin_or_account_holds(self):
        for key, value in (
            ("response_origin", "hyperliquid"),
            ("account", "0x" + "b" * 40),
            ("environment", "testnet"),
            ("method", "GET"),
            ("request_type", "exchange"),
        ):
            with self.subTest(key=key):
                cap = dict(inspect_capture())
                cap[key] = value
                self.assertEqual(inspect(capture=cap).status, "hold")

    def test_wrong_outer_account_holds(self):
        self.assertEqual(inspect(
            expected_account="0x" + "b" * 40).status, "hold")


def inspect_capture():
    return {
        "environment": "mainnet", "endpoint": ENDPOINT,
        "account": ACCOUNT, "dex": "", "request_type": "orderStatus",
        "method": "POST", "response_origin": "simulated",
        "transport_verified": False, "authenticated": False,
    }


if __name__ == "__main__":
    unittest.main()
