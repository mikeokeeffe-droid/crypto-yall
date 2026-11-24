"""Offline synthetic policy tests; no sockets, firewall modifications or orders."""
import copy
import json
import unittest
from readonly_connection_review import testnet_egress_policy_review_offline as review


def safe_frames():
    return [
        {
            "scheme": "https", "host": "api.hyperliquid-testnet.xyz",
            "port": 443, "method": "POST", "path": "/info",
            "body": json.dumps({
                "type": kind, "user": review.FIXED_ACCOUNT, "dex": ""
            }, separators=(",", ":"))
        } for kind in review.TYPES
    ]


class OfflineEgressPolicyTests(unittest.TestCase):
    def setUp(self):
        self.policy = review.load_review_contract()

    def test_exact_disabled_review_policy_and_two_frames(self):
        self.assertTrue(review.policy_contract(self.policy))
        self.assertTrue(review.inspect_synthetic_requests(self.policy, safe_frames()))
        self.assertIs(self.policy["network_authorized"], False)
        self.assertIs(self.policy["gateway_implemented"], False)

    def test_fail_closed_if_any_authority_is_enabled(self):
        for key in (
            "network_authorized", "gateway_implemented", "automatic_execution",
            "deployable_as_is", "credential_access_authorized",
            "order_execution_authorized", "mainnet_access_authorized"
        ):
            changed = copy.deepcopy(self.policy)
            changed[key] = True
            with self.subTest(key=key), self.assertRaises(review.PolicyHold):
                review.policy_contract(changed)

    def test_rejects_broader_gateway_and_runner(self):
        cases = (
            ("proposed_runner", "direct_network", "allow"),
            ("proposed_runner", "allow_signing_credentials", True),
            ("proposed_runner", "allow_privileged_unix_sockets", True),
            ("proposed_gateway", "allow_exchange_endpoint", True),
            ("proposed_gateway", "allow_redirects", True),
            ("proposed_gateway", "allow_connect_proxy", True),
            ("proposed_gateway", "max_requests_per_run", 3),
            ("proposed_gateway", "public_account", "0x" + "0" * 40),
        )
        for section, key, value in cases:
            changed = copy.deepcopy(self.policy)
            changed[section][key] = value
            with self.subTest(section=section, key=key), self.assertRaises(review.PolicyHold):
                review.policy_contract(changed)

    def test_rejects_wrong_network_destination(self):
        for key, bad in (
            ("scheme", "http"), ("host", "api.hyperliquid.xyz"),
            ("port", 80), ("method", "GET"), ("path", "/exchange")
        ):
            frames = safe_frames()
            frames[0][key] = bad
            with self.subTest(key=key), self.assertRaises(review.PolicyHold):
                review.inspect_synthetic_requests(self.policy, frames)

    def test_rejects_duplicates_unapproved_types_and_accounts(self):
        cases = [
            (safe_frames()[:1], "missing second frame"),
            (safe_frames() + safe_frames()[:1], "extra frame"),
        ]
        for frames, why in cases:
            with self.subTest(why=why), self.assertRaises(review.PolicyHold):
                review.inspect_synthetic_requests(self.policy, frames)
        for body in (
            '{"type":"order","user":"' + review.FIXED_ACCOUNT + '","dex":""}',
            '{"type":"openOrders","user":"' + review.FIXED_ACCOUNT + '","dex":""}',
            '{"type":"clearinghouseState","user":"' + ("0x" + "0" * 40) + '","dex":""}',
            '{"type":"clearinghouseState","user":"' + review.FIXED_ACCOUNT + '","dex":"","extra":1}',
            '{"type":"clearinghouseState","type":"clearinghouseState","user":"' + review.FIXED_ACCOUNT + '","dex":""}',
        ):
            frames = safe_frames()
            frames[0]["body"] = body
            with self.subTest(body=body[:55]), self.assertRaises(review.PolicyHold):
                review.inspect_synthetic_requests(self.policy, frames)


if __name__ == "__main__":
    unittest.main()
