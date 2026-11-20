"""Offline bot identity trust-boundary tests, no live credentials."""
import unittest
from offline_bot_identity_fixture import (
    OfflineIdentityVerifier, VerifiedFixtureIdentity,
)

ACCOUNT_A = "0x" + "1" * 40
ACCOUNT_B = "0x" + "2" * 40

class OfflineIdentityTests(unittest.TestCase):
    def setUp(self):
        self.verifier = OfflineIdentityVerifier({
            "principal-daily": VerifiedFixtureIdentity("daily", "mainnet", ACCOUNT_A),
            "principal-intraday": VerifiedFixtureIdentity("intraday", "mainnet", ACCOUNT_A),
            "principal-aggressive": VerifiedFixtureIdentity("aggressive", "testnet", ACCOUNT_B),
        })

    def verify(self, principal, bot="daily", environment="mainnet", account=ACCOUNT_A):
        return self.verifier.verify(
            principal=principal, requested_bot=bot,
            environment=environment, account=account,
        )

    def test_matching_identity(self):
        self.assertEqual(self.verify("principal-daily").bot, "daily")

    def test_daily_cannot_impersonate_intraday(self):
        self.assertIsNone(self.verify("principal-daily", bot="intraday"))

    def test_intraday_cannot_impersonate_daily(self):
        self.assertIsNone(self.verify("principal-intraday", bot="daily"))

    def test_unknown_or_missing_principal_fails_closed(self):
        self.assertIsNone(self.verify("unknown"))
        self.assertIsNone(self.verify(None))

    def test_correct_identity_wrong_account_or_environment_fails_closed(self):
        self.assertIsNone(self.verify("principal-daily", account=ACCOUNT_B))
        self.assertIsNone(self.verify("principal-daily", environment="testnet"))

    def test_aggressive_identity_only_works_in_own_scope(self):
        self.assertIsNotNone(self.verify(
            "principal-aggressive", bot="aggressive",
            environment="testnet", account=ACCOUNT_B))
        self.assertIsNone(self.verify("principal-aggressive", bot="aggressive"))

    def test_caller_supplied_identity_object_is_not_authority(self):
        forged = VerifiedFixtureIdentity("daily", "mainnet", ACCOUNT_A)
        self.assertIsNone(self.verify(forged))

if __name__ == "__main__":
    unittest.main()
