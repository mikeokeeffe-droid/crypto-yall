"""Offline bounded RSA JWKS parsing; no actual GitHub issuer trust."""
import base64
import json
import unittest

from sender_review.oidc_jwks_keyset_offline import inspect_public_jwks_offline
from sender_review.test_offline_oidc_identity_fixture import (
    SignedOidcFixtureTests, POLICY, NOW,
)
from sender_review.offline_oidc_identity_fixture import (
    verify_fixture_oidc_identity_offline,
)


def b64int(value):
    raw = value.to_bytes((value.bit_length() + 7) // 8, "big")
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def encoded(value):
    return json.dumps(value, separators=(",", ":"), sort_keys=True).encode("ascii")


class OfflinePublicJwksTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        SignedOidcFixtureTests.setUpClass()
        cls.fixture = SignedOidcFixtureTests()
        n, e = SignedOidcFixtureTests.keys["ci-fixture"]
        cls.key = {"kty": "RSA", "kid": "ci-fixture", "use": "sig",
                   "alg": "RS256", "n": b64int(n), "e": b64int(e)}

    def inspect(self, value):
        return inspect_public_jwks_offline(jwks_bytes=encoded(value))

    def no_authority(self, result):
        self.assertFalse(result.real_issuer_keys_authenticated)
        self.assertFalse(result.tls_origin_verified)
        self.assertFalse(result.cache_freshness_verified)
        self.assertFalse(result.runtime_identity_authenticated)
        self.assertFalse(result.request_authorized)
        self.assertFalse(result.submit_authorized)
        self.assertFalse(result.close_authorized)
        self.assertFalse(result.signing_enabled)

    def test_public_fixture_key_can_validate_fake_token_but_not_authenticate(self):
        result = self.inspect({"keys": [self.key]})
        self.assertEqual(result.state, "parsed_untrusted_public_keys_only")
        self.no_authority(result)
        verified = verify_fixture_oidc_identity_offline(
            token=self.fixture.token("daily"), policy=POLICY,
            trusted_fixture_keys=result.fixture_public_keys,
            fixture_now_seconds=NOW,
        )
        self.assertEqual(verified.state, "verified_fixture_only")
        self.assertFalse(verified.runtime_identity_authenticated)
        self.assertFalse(verified.submit_authorized)

    def test_missing_or_invalid_jwks_fail_closed(self):
        for payload in (
            {}, {"keys": []}, {"keys": [self.key, self.key]},
            {"keys": [dict(self.key, kid="")]},
            {"keys": [dict(self.key, kid="wrong key")]},
            {"keys": [dict(self.key, alg="HS256")]},
            {"keys": [dict(self.key, use="enc")]},
            {"keys": [dict(self.key, kty="oct")]},
            {"keys": [dict(self.key, d="not-public")]},
            {"keys": [dict(self.key, key_ops=["sign"])]},
            {"keys": [dict(self.key, e=b64int(3))]},
            {"keys": [dict(self.key, n="AA" + self.key["n"])]},
            {"keys": [dict(self.key, n="AA")]},
            {"keys": [dict(self.key, n=123)]},
            {"keys": [dict(self.key, x5c=["x" * 8193])]},
        ):
            with self.subTest(payload=payload):
                result = self.inspect(payload)
                self.assertEqual(result.state, "hold")
                self.no_authority(result)

    def test_bad_encoding_duplicate_keys_and_size_fail_closed(self):
        samples = (
            b'{"keys":[],"keys":[]}',
            b'{"keys":[{"kty":"RSA","kid":"a","kid":"b"}]}',
            b'{"keys":NaN}',
            b'{"keys":"wrong"}',
            b'{"keys":[{}]}',
            b'',
            b'{"keys":[]}' + b" " * 32769,
            b'\xff',
        )
        for raw in samples:
            with self.subTest(raw=raw[:40]):
                result = inspect_public_jwks_offline(jwks_bytes=raw)
                self.assertEqual(result.state, "hold")
                self.no_authority(result)
        for not_bytes in (None, {}, "{}", True):
            self.assertEqual(inspect_public_jwks_offline(
                jwks_bytes=not_bytes
            ).state, "hold")


if __name__ == "__main__":
    unittest.main()
