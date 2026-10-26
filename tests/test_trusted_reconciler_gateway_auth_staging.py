import unittest
from trusted_reconciler_gateway_auth_staging import (
    VerifiedGatewayPrincipal, authorize_verified_principal)

class GatewayAuthorizationTests(unittest.TestCase):
    def setUp(self):
        self.claims = dict(subject="reconciler-worker", issuer="trusted-idp",
                           audience="staging-reconciler",
                           scopes=frozenset({"reconciler:position-write"}),
                           expires_at=200)

    def check(self, **changes):
        return authorize_verified_principal(
            VerifiedGatewayPrincipal(**{**self.claims, **changes}),
            expected_issuer="trusted-idp", expected_audience="staging-reconciler",
            now=100)

    def test_valid_verified_principal(self):
        self.assertTrue(self.check())

    def test_unverified_dictionary_rejected(self):
        with self.assertRaises(PermissionError):
            authorize_verified_principal(self.claims, expected_issuer="trusted-idp",
                                         expected_audience="staging-reconciler", now=100)

    def test_invalid_clock_rejected(self):
        principal = VerifiedGatewayPrincipal(**self.claims)
        for clock in (None, True, "100", 100.0):
            with self.subTest(clock=clock):
                with self.assertRaises(PermissionError):
                    authorize_verified_principal(
                        principal, expected_issuer="trusted-idp",
                        expected_audience="staging-reconciler", now=clock)

    def test_invalid_claims_fail_closed(self):
        for changes in ({"subject": ""}, {"issuer": "untrusted"},
                        {"audience": "trading-bot"}, {"scopes": frozenset()},
                        {"expires_at": 100}, {"expires_at": True}):
            with self.subTest(changes=changes):
                with self.assertRaises(PermissionError):
                    self.check(**changes)

if __name__ == "__main__":
    unittest.main()
