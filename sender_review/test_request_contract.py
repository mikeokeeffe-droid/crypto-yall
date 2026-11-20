"""S1 sender request validation is a fail-closed, non-executable interface."""
import json
import sys
import unittest

from sender_review.request_contract import inspect_sender_entry_request_offline


def request(**changes):
    payload = {
        "version": 1,
        "action": "open_long",
        "side": "long",
        "coin": "SOL",
        "rounded_size": "0.16",
        "requested_leverage": 2,
        "request_nonce": "a" * 32,
    }
    payload.update(changes)
    return json.dumps(payload, sort_keys=True).encode()


class SenderRequestContractTests(unittest.TestCase):
    def assert_no_authority(self, review):
        self.assertFalse(review.workload_identity_authenticated)
        self.assertFalse(review.account_scope_verified)
        self.assertFalse(review.nonce_reserved)
        self.assertFalse(review.request_authorized)
        self.assertFalse(review.submit_authorized)
        self.assertFalse(review.close_authorized)
        self.assertFalse(review.signing_enabled)

    def test_original_bot_entry_intents_are_review_only(self):
        for bot in ("daily", "intraday", "aggressive"):
            for action, side in (("open_long", "long"), ("open_short", "short")):
                with self.subTest(bot=bot, action=action):
                    result = inspect_sender_entry_request_offline(
                        body=request(action=action, side=side),
                        asserted_bot=bot,
                    )
                    self.assertEqual(result.state, "review_only")
                    self.assertEqual(result.parsed_coin, "SOL")
                    self.assert_no_authority(result)

    def test_no_identity_claim_can_authorize_execution(self):
        for identity in ("daily", "intraday", "aggressive", None):
            with self.subTest(identity=identity):
                result = inspect_sender_entry_request_offline(
                    body=request(), asserted_bot=identity,
                )
                self.assert_no_authority(result)
                self.assertEqual(result.state, "review_only")

    def test_close_pyramid_leverage_and_unapproved_fields_hold(self):
        baseline = json.loads(request())
        for changes in (
            {"action": "close"}, {"action": "pyramid_long"},
            {"action": "update_leverage"}, {"action": "market_open"},
            {"action": "open_short", "side": "long"},
            {"side": "short"}, {"coin": "sol"},
            {"coin": "../SOL"}, {"rounded_size": "0"},
            {"rounded_size": "-1"}, {"rounded_size": "1e2"},
            {"rounded_size": "NaN"}, {"rounded_size": "0.000000001"},
            {"rounded_size": "1000001"}, {"requested_leverage": 0},
            {"requested_leverage": 6}, {"requested_leverage": True},
            {"request_nonce": "a" * 31}, {"request_nonce": "A" * 32},
            {"submit_authorized": True}, {"bot": "daily"},
            {"account": "0x" + "1" * 40}, {"environment": "mainnet"},
            {"cloid": "0x" + "1" * 32},
            {"ownership_verified": True}, {"close_size": "1"},
        ):
            with self.subTest(changes=changes):
                result = inspect_sender_entry_request_offline(
                    body=json.dumps(dict(baseline, **changes)).encode(),
                    asserted_bot="daily",
                )
                self.assertEqual(result.state, "hold")
                self.assert_no_authority(result)

    def test_reject_ambiguous_wire_and_identity_inputs(self):
        for body in (
            b"", b"not-json", b"\xff",
            b'{"version":1,"version":1}',
            b'{"x":NaN}',
            b" " * 1025,
        ):
            with self.subTest(body=body[:45]):
                result = inspect_sender_entry_request_offline(body=body)
                self.assertEqual(result.state, "hold")
                self.assert_no_authority(result)
        for bot in ("unknown", True, 1, [], {}):
            with self.subTest(bot=bot):
                result = inspect_sender_entry_request_offline(
                    body=request(), asserted_bot=bot,
                )
                self.assertEqual(result.state, "hold")
                self.assert_no_authority(result)

    def test_never_imports_exchange_signing_client(self):
        inspect_sender_entry_request_offline(body=request())
        for name in (
            "eth_account", "hyperliquid.exchange",
            "hyperliquid_executor", "intraday_executor",
            "aggressive_executor",
        ):
            self.assertNotIn(name, sys.modules)


if __name__ == "__main__":
    unittest.main()
