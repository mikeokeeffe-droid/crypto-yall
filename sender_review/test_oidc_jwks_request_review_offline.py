"""Synthetic JWKS -> signed HTTP boundary test; never a real issuer."""
import json
import unittest
from sender_review.oidc_jwks_request_review_offline import (
    inspect_remote_with_public_jwks_fixture_offline,
)
from sender_review.test_oidc_jwks_keyset_offline import (
    OfflinePublicJwksTests, encoded,
)
from sender_review.test_remote_request_boundary_offline import (
    OfflineRemoteRequestBoundaryTests, NOW,
)

class OfflineJwksRequestBoundaryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        OfflinePublicJwksTests.setUpClass()
        OfflineRemoteRequestBoundaryTests.setUpClass()
        cls.key = OfflinePublicJwksTests.key
        cls.fixture = OfflineRemoteRequestBoundaryTests()

    def check(self, keyset=None, token=None, body=None, headers=None):
        if keyset is None:
            keyset = {"keys": [self.key]}
        if token is None:
            token = self.fixture.token()
        if body is None:
            body = self.fixture.body()
        if headers is None:
            headers = [
                ("Authorization", "Bearer " + token),
                ("Content-Type", "application/json"),
            ]
        return inspect_remote_with_public_jwks_fixture_offline(
            issuer_fixture_jwks_bytes=encoded(keyset),
            method="POST", path="/v1/review-only/entry-intents",
            headers=headers, body=body, fixture_now_seconds=NOW,
        )

    def no_authority(self, result):
        for name in (
            "runtime_identity_authenticated", "tls_peer_authenticated",
            "issuer_jwks_verified", "key_rotation_verified",
            "replay_consumed", "journal_recorded", "request_authorized",
            "submit_authorized", "close_authorized", "signing_enabled",
        ):
            self.assertFalse(getattr(result, name), name)

    def test_all_three_bot_fixtures_are_only_reviewed(self):
        for bot in ("daily", "intraday", "aggressive"):
            with self.subTest(bot=bot):
                result = self.check(token=self.fixture.token(bot))
                self.assertEqual(
                    result.state, "signed_jwks_fixture_review_only_HOLD"
                )
                self.assertEqual(result.fixture_bot, bot)
                self.assertTrue(result.public_keyset_parsed)
                self.assertTrue(result.fixture_signature_checked)
                self.no_authority(result)

    def test_key_removed_rotated_or_invalid_never_authenticates(self):
        for keyset in (
            {"keys": [dict(self.key, kid="other-key")]},
            {"keys": [dict(self.key, alg="HS256")]},
            {"keys": [dict(self.key, d="private")]},
            {"keys": []},
            {"keys": [self.key, self.key]},
        ):
            with self.subTest(keys=str(keyset)[:80]):
                result = self.check(keyset=keyset)
                self.assertEqual(result.state, "hold")
                self.no_authority(result)
        # Key rotation can never be inferred just because another public
        # key appears in the caller's data.
        duplicate = dict(self.key, kid="future-key")
        result = self.check(keyset={"keys": [self.key, duplicate]})
        self.assertEqual(result.state, "signed_jwks_fixture_review_only_HOLD")
        self.assertFalse(result.key_rotation_verified)
        self.no_authority(result)

    def test_unknown_request_headers_claims_and_signature_fail_closed(self):
        token = self.fixture.token()
        for kwargs in (
            {"token": self.fixture.token(run_id="987654321")},
            {"token": self.fixture.token(event_name="pull_request_target")},
            {"token": self.fixture.token(exp=NOW-1)},
            {"headers": [
                ("Authorization", "Bearer " + token),
                ("Content-Type", "application/json"),
                ("X-JWKS", "https://evil.invalid/keys"),
            ]},
            {"body": self.fixture.body(submit_authorized=True)},
        ):
            with self.subTest(kwargs=str(kwargs)[:120]):
                result = self.check(**kwargs)
                self.assertEqual(result.state, "hold")
                self.no_authority(result)

if __name__ == "__main__":
    unittest.main()
