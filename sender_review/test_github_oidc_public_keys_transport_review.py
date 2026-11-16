"""Test the disabled-by-default public OIDC key transport using mocks only."""
import io
import json
import unittest
from unittest.mock import patch

from sender_review import github_oidc_public_keys_transport_review as transport
from sender_review.test_oidc_jwks_keyset_offline import b64int, encoded
from sender_review.test_offline_oidc_identity_fixture import SignedOidcFixtureTests


class Response:
    def __init__(self, url, data, status=200, content_type="application/json"):
        self.url = url
        self.bytes = io.BytesIO(data)
        self.status = status
        self.headers = {"Content-Type": content_type}

    def geturl(self):
        return self.url

    def read(self, count):
        return self.bytes.read(count)

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return None


class FakeOpener:
    def __init__(self, responses):
        self.responses = responses
        self.calls = []

    def open(self, request, timeout):
        self.calls.append((request.full_url, request.get_method(), timeout))
        return self.responses.pop(0)


class PublicKeyTransportReviewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        SignedOidcFixtureTests.setUpClass()
        n, e = SignedOidcFixtureTests.keys["ci-fixture"]
        cls.public_key = {"kid": "ci-fixture", "kty": "RSA", "alg": "RS256",
                          "use": "sig", "n": b64int(n), "e": b64int(e)}

    def fake(self, discovery=None, jwks=None):
        discovery = discovery if discovery is not None else {
            "issuer": transport.ISSUER, "jwks_uri": transport.JWKS_URL
        }
        jwks = jwks if jwks is not None else {"keys": [self.public_key]}
        return FakeOpener([
            Response(transport.DISCOVERY_URL, encoded(discovery)),
            Response(transport.JWKS_URL, encoded(jwks)),
        ])

    def no_authority(self, result):
        self.assertFalse(result.issuer_authenticated)
        self.assertFalse(result.trusted_runtime_identity)
        self.assertFalse(result.replay_consumed)
        self.assertFalse(result.authorization_granted)
        self.assertFalse(result.signing_enabled)
        self.assertFalse(result.submit_authorized)
        self.assertFalse(result.close_authorized)

    def test_default_does_not_make_network_call(self):
        with patch.object(transport.urllib.request, "build_opener",
                          side_effect=AssertionError("network forbidden")):
            for value in (False, None, 0, "true", {}, []):
                with self.subTest(value=value):
                    outcome = transport.review_github_public_jwks_transport(
                        approved_readonly_network=value)
                    self.assertEqual(outcome.state, "hold")
                    self.no_authority(outcome)

    def test_mock_https_parses_only_candidate_keys(self):
        fake = self.fake()
        with patch.object(transport.urllib.request, "build_opener",
                          return_value=fake):
            outcome = transport.review_github_public_jwks_transport(
                approved_readonly_network=True)
        self.assertEqual(outcome.state,
                         "candidate_public_keys_observed_review_only")
        self.assertEqual(outcome.public_key_count, 1)
        self.assertTrue(outcome.keyset_sha256)
        self.assertEqual(len(fake.calls), 2)
        self.assertEqual([x[0] for x in fake.calls],
                         [transport.DISCOVERY_URL, transport.JWKS_URL])
        self.no_authority(outcome)

    def test_wrong_discovery_issuer_or_jwks_url_does_not_fetch_keys(self):
        for discovery in (
            {"issuer": "https://evil.invalid", "jwks_uri": transport.JWKS_URL},
            {"issuer": transport.ISSUER, "jwks_uri": "https://evil.invalid/jwks"},
            {"issuer": transport.ISSUER},
        ):
            fake = self.fake(discovery=discovery)
            with self.subTest(discovery=discovery), patch.object(
                transport.urllib.request, "build_opener", return_value=fake
            ):
                outcome = transport.review_github_public_jwks_transport(
                    approved_readonly_network=True)
            self.assertEqual(outcome.state, "hold")
            self.assertEqual(len(fake.calls), 1)
            self.no_authority(outcome)

    def test_bad_https_metadata_and_malformed_jwks_hold(self):
        for change in ("redirect", "status", "content_type", "invalid_jwks"):
            fake = self.fake()
            if change == "redirect":
                fake.responses[0].url = "https://evil.invalid/"
            elif change == "status":
                fake.responses[0].status = 429
            elif change == "content_type":
                fake.responses[0].headers["Content-Type"] = "text/html"
            elif change == "invalid_jwks":
                fake.responses[1].bytes = io.BytesIO(b'{"keys":[]}')
            with self.subTest(change=change), patch.object(
                transport.urllib.request, "build_opener", return_value=fake
            ):
                outcome = transport.review_github_public_jwks_transport(
                    approved_readonly_network=True)
            self.assertEqual(outcome.state, "hold")
            self.no_authority(outcome)

    def test_endpoint_allowlist_is_constant(self):
        fake = self.fake()
        with self.assertRaises(ValueError):
            transport._exact_https_get(fake, "https://evil.invalid/jwks", 200)


if __name__ == "__main__":
    unittest.main()
