"""GitHub public JWKS transport is inert regardless of caller input."""
import unittest

from sender_review import github_oidc_public_keys_transport_review as r


class PublicKeyTransportReviewTests(unittest.TestCase):
    def test_network_activation_flags_are_always_denied(self):
        for flag in (False, True, None, 1, "true", {}, []):
            with self.subTest(flag=flag):
                result = r.review_github_public_jwks_transport(
                    approved_readonly_network=flag,
                )
                self.assertEqual(result.state, "hold")
                self.assertFalse(result.candidate_public_keys)
                self.assertEqual(result.public_key_count, 0)
                self.assertIsNone(result.keyset_sha256)
                for field in ("issuer_authenticated", "trusted_runtime_identity",
                              "replay_consumed", "authorization_granted",
                              "signing_enabled", "submit_authorized",
                              "close_authorized"):
                    self.assertFalse(getattr(result, field), field)

    def test_offline_strict_json_only(self):
        self.assertEqual(r._strict_json(b'{"issuer":"example"}'),
                         {"issuer": "example"})
        for raw in (b'{"x":1,"x":2}', b'{"x":NaN}', b'not json',
                    b'{"x":'):
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                r._strict_json(raw)

    def test_no_legacy_http_transport_remaining(self):
        self.assertFalse(hasattr(r, "_exact_https_get"))
        self.assertFalse(hasattr(r, "_DenyRedirect"))
        self.assertFalse(hasattr(r, "urllib"))


if __name__ == "__main__":
    unittest.main()
