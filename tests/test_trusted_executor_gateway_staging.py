import unittest
from trusted_executor_gateway_staging import stage_entry_claim


class GatewayTests(unittest.TestCase):
    def setUp(self):
        self.calls = []
        self.verify = lambda _: {"subject": "executor:intraday", "scope": "executor:entry", "verified": True}

    def rpc(self, name, params):
        self.calls.append((name, params))
        return True

    def claim(self, **overrides):
        args = dict(jwt_token="test", bot="intraday", coin="BTC",
                    action="open_long", verify_token=self.verify, rpc=self.rpc)
        args.update(overrides)
        return stage_entry_claim(**args)

    def test_claim_reserves_before_intent_without_live_authorization(self):
        claim = self.claim()
        self.assertTrue(claim.claimed)
        self.assertFalse(claim.live_order_authorized)
        self.assertEqual([x[0] for x in self.calls],
                         ["try_reserve_bot_entry", "claim_bot_entry_intent"])
        self.assertEqual(self.calls[0][1]["p_token"], self.calls[1][1]["p_token"])

    def test_wrong_bot_identity_fails_before_db(self):
        with self.assertRaises(PermissionError):
            self.claim(bot="daily")
        self.assertEqual(self.calls, [])

    def test_invalid_request_fails_before_db(self):
        with self.assertRaises(PermissionError):
            self.claim(action="close")
        self.assertEqual(self.calls, [])

    def test_failed_reservation_never_claims(self):
        with self.assertRaises(PermissionError):
            self.claim(rpc=lambda name, params: False)
        self.assertEqual(self.calls, [])

    def test_failed_intent_never_authorizes(self):
        def rpc(name, params):
            self.calls.append(name)
            return name == "try_reserve_bot_entry"
        with self.assertRaises(PermissionError):
            self.claim(rpc=rpc)
        self.assertEqual(self.calls, ["try_reserve_bot_entry", "claim_bot_entry_intent"])

    def test_unverified_identity_denied(self):
        with self.assertRaises(PermissionError):
            self.claim(verify_token=lambda _: {"subject": "executor:intraday",
                                               "scope": "executor:entry", "verified": False})
        self.assertEqual(self.calls, [])


if __name__ == "__main__":
    unittest.main()
