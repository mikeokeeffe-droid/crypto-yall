"""Mock-only server-key/clock preflight checks; zero exchange authority."""
import hashlib
import unittest
from unittest.mock import patch

from sender_review import server_oidc_preflight_review as preflight
from sender_review.github_oidc_public_keys_transport_review import (
    GithubPublicKeysTransportReview,
)
from sender_review.test_remote_request_boundary_offline import (
    OfflineRemoteRequestBoundaryTests, NOW,
)


class ServerOidcPreflightTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        OfflineRemoteRequestBoundaryTests.setUpClass()
        cls.fixture = OfflineRemoteRequestBoundaryTests()
        cls.keys = OfflineRemoteRequestBoundaryTests.keys
        cls.public = GithubPublicKeysTransportReview(
            state="candidate_public_keys_observed_review_only",
            keyset_sha256="d" * 64,
            public_key_count=1,
            candidate_public_keys=cls.keys,
        )

    def inspect(self, *, token=None, body=None, enabled=True, keys=None, now=NOW):
        if token is None:
            token = self.fixture.token("daily")
        if body is None:
            body = self.fixture.body()
        if keys is None:
            keys = self.public
        with patch.object(preflight.time, "time", return_value=now), patch.object(
            preflight, "review_github_public_jwks_transport", return_value=keys
        ) as fetch:
            result = preflight.inspect_server_oidc_preflight_review(
                token=token, request_body=body,
                approved_readonly_key_fetch=enabled,
            )
        return result, fetch

    def assert_no_authority(self, result):
        for field in (
            "runtime_identity_authenticated", "authenticated_request_body",
            "replay_consumed", "durable_fence_reserved",
            "verified_exchange_provenance", "request_authorized",
            "submit_authorized", "close_authorized", "signing_enabled",
        ):
            self.assertIs(getattr(result, field), False, field)

    def test_default_refuses_key_fetch_even_for_signed_fixture(self):
        with patch.object(
            preflight, "review_github_public_jwks_transport",
            side_effect=AssertionError("no network access")
        ):
            for enabled in (False, None, 1, "true"):
                with self.subTest(enabled=enabled):
                    r = preflight.inspect_server_oidc_preflight_review(
                        token=self.fixture.token("daily"),
                        request_body=self.fixture.body(),
                        approved_readonly_key_fetch=enabled,
                    )
                    self.assertEqual(r.state, "hold")
                    self.assert_no_authority(r)

    def test_three_bot_fixtures_with_mock_keys_and_server_clock_stay_hold(self):
        for bot in ("daily", "intraday", "aggressive"):
            with self.subTest(bot=bot):
                body = self.fixture.body(request_nonce="b" * 32)
                result, fetch = self.inspect(
                    token=self.fixture.token(bot), body=body,
                )
                self.assertEqual(
                    result.state, "candidate_signature_and_claims_reviewed_HOLD"
                )
                self.assertTrue(result.candidate_signature_checked)
                self.assertEqual(result.candidate_bot, bot)
                self.assertEqual(
                    result.body_sha256, hashlib.sha256(body).hexdigest()
                )
                self.assertEqual(result.public_key_sha256, "d" * 64)
                self.assertEqual(fetch.call_count, 1)
                self.assert_no_authority(result)

    def test_invalid_or_wrong_origin_public_key_data_cannot_authenticate(self):
        bad_keys = (
            GithubPublicKeysTransportReview(),
            GithubPublicKeysTransportReview(
                state="candidate_public_keys_observed_review_only",
                candidate_public_keys={},
                keyset_sha256="d" * 64,
            ),
            GithubPublicKeysTransportReview(
                state="candidate_public_keys_observed_review_only",
                candidate_public_keys={"other": self.keys["ci-fixture"]},
                keyset_sha256="d" * 64,
            ),
        )
        for keys in bad_keys:
            with self.subTest(keys=keys.state):
                result, _ = self.inspect(keys=keys)
                self.assertEqual(result.state, "hold")
                self.assert_no_authority(result)

    def test_expired_and_forged_claims_fail_closed(self):
        cases = (
            {"repository": "attacker/repo"},
            {"repository_id": "999"},
            {"run_attempt": True},
            {"event_name": "pull_request_target"},
            {"exp": NOW - 1},
        )
        for change in cases:
            with self.subTest(change=change):
                result, _ = self.inspect(token=self.fixture.token(**change))
                self.assertEqual(result.state, "hold")
                self.assert_no_authority(result)

    def test_invalid_request_does_not_fetch_keys(self):
        bad = self.fixture.body(submit_authorized=True)
        with patch.object(
            preflight, "review_github_public_jwks_transport",
            side_effect=AssertionError("unexpected fetch")
        ):
            result = preflight.inspect_server_oidc_preflight_review(
                token=self.fixture.token(), request_body=bad,
                approved_readonly_key_fetch=True,
            )
        self.assertEqual(result.state, "hold")
        self.assert_no_authority(result)


if __name__ == "__main__":
    unittest.main()
