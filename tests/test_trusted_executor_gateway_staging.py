import base64
import hashlib
import hmac
import json
import unittest
from trusted_executor_gateway_staging import stage_entry_claim
from trusted_executor_jwt_staging import verify_executor_jwt

KEYS = {
    "aggressive": b"aggressive-staging-key-at-least-32-bytes",
    "intraday": b"intraday-staging-key-at-least-32-bytes!!",
    "daily": b"daily-staging-key-at-least-32-bytes!!!!!!",
}
ISSUER = "staging-idp"
AUDIENCE = "staging-executor-gateway"


def signed_token(*, bot="intraday", scope="executor:entry", issuer=ISSUER,
                 audience=AUDIENCE, expires=200, key=None):
    def encode(value):
        return base64.urlsafe_b64encode(
            json.dumps(value).encode()).rstrip(b"=").decode()

    header = encode({"alg": "HS256", "typ": "JWT"})
    if key is None:
        key = KEYS[bot]
    payload = encode({"sub": "executor:" + bot, "iss": issuer,
                      "aud": audience, "scope": scope,
                      "iat": 90, "nbf": 90, "exp": expires})
    signing_input = header + "." + payload
    signature = base64.urlsafe_b64encode(
        hmac.new(key, signing_input.encode(), hashlib.sha256).digest()
    ).rstrip(b"=").decode()
    return signing_input + "." + signature


class GatewayTests(unittest.TestCase):
    def setUp(self):
        self.calls = []

    def rpc(self, name, params):
        self.calls.append((name, params))
        return True

    def claim(self, **overrides):
        args = dict(jwt_token=signed_token(), bot="intraday", coin="BTC",
                    action="open_long", signing_keys=KEYS, issuer=ISSUER,
                    audience=AUDIENCE, now=100, rpc=self.rpc)
        args.update(overrides)
        return stage_entry_claim(**args)

    def test_valid_bot_specific_tokens(self):
        for bot in ("aggressive", "intraday", "daily"):
            with self.subTest(bot=bot):
                principal = verify_executor_jwt(
                    signed_token(bot=bot), KEYS, bot=bot, issuer=ISSUER,
                    audience=AUDIENCE, now=100)
                self.assertEqual(principal.bot, bot)
                self.assertEqual(principal.scopes, frozenset(("executor:entry",)))

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

    def test_cross_bot_token_impersonation_fails_before_db(self):
        with self.assertRaises(PermissionError):
            self.claim(jwt_token=signed_token(bot="daily"))
        self.assertEqual(self.calls, [])

    def test_reused_key_material_is_rejected(self):
        reused_keys = {bot: KEYS["intraday"] for bot in KEYS}
        with self.assertRaises(PermissionError):
            self.claim(signing_keys=reused_keys)
        self.assertEqual(self.calls, [])

    def test_incomplete_key_map_is_rejected(self):
        with self.assertRaises(PermissionError):
            self.claim(signing_keys={"intraday": KEYS["intraday"]})
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

    def test_failed_authentication_never_calls_database(self):
        invalid_tokens = (
            "not.a.jwt",
            signed_token(issuer="untrusted-idp"),
            signed_token(audience="reconciler-gateway"),
            signed_token(expires=100),
            signed_token(key=b"different-test-signing-key-minimum-32-bytes"),
            signed_token(scope="reconciler:position-write"),
            signed_token(scope="executor:entry reconciler:position-write"),
        )
        for candidate in invalid_tokens:
            with self.subTest(candidate=candidate[:24]):
                with self.assertRaises(PermissionError):
                    self.claim(jwt_token=candidate)
        self.assertEqual(self.calls, [])


if __name__ == "__main__":
    unittest.main()
