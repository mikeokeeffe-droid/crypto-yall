"""Offline verified-claim admission tests: no SDK, secrets, or live orders."""
import os
import tempfile
import unittest
from offline_bot_identity_fixture import OfflineIdentityVerifier, VerifiedFixtureIdentity
from offline_sender_restart_journal import OfflineRestartJournal
from offline_verified_claim_fixture import reserve_verified_fixture

A = "0x" + "1"*40
B = "0x" + "2"*40
SCOPE = dict(environment="mainnet", account=A, dex="", coin="SOL")

class VerifiedClaimTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.journal=OfflineRestartJournal(
            os.path.join(self.temp.name,"claims.sqlite"),create=True)
        self.verifier=OfflineIdentityVerifier({
            "daily-workload": VerifiedFixtureIdentity("daily","mainnet",A),
            "intraday-workload": VerifiedFixtureIdentity("intraday","mainnet",A),
            "aggressive-workload": VerifiedFixtureIdentity("aggressive","testnet",B),
        })
    def tearDown(self):
        self.temp.cleanup()
    def reserve(self,principal,requested_bot,**changes):
        scope=dict(SCOPE,**changes)
        return reserve_verified_fixture(
            verifier=self.verifier,journal=self.journal,
            principal=principal,requested_bot=requested_bot,**scope)

    def test_verified_daily_can_reserve_once_without_dispatch_authority(self):
        result=self.reserve("daily-workload","daily")
        self.assertEqual(result.state,"reserved")
        self.assertFalse(result.submit_authorized)
        self.assertEqual(self.journal.inspect(**SCOPE)[0],"daily")
        self.assertEqual(self.reserve("daily-workload","daily").state,"hold")

    def test_daily_cannot_impersonate_intraday_or_aggressive(self):
        self.assertEqual(self.reserve("daily-workload","intraday").state,"hold")
        self.assertEqual(self.reserve("daily-workload","aggressive").state,"hold")
        self.assertIsNone(self.journal.inspect(**SCOPE))

    def test_unknown_principal_cannot_claim_any_bot(self):
        self.assertEqual(self.reserve("unknown","daily").state,"hold")
        self.assertIsNone(self.journal.inspect(**SCOPE))

    def test_correct_principal_wrong_account_or_network_rejected(self):
        self.assertEqual(self.reserve("daily-workload","daily",account=B).state,"hold")
        self.assertEqual(self.reserve("daily-workload","daily",environment="testnet").state,"hold")
        self.assertIsNone(self.journal.inspect(**SCOPE))

    def test_intraday_cannot_take_verified_daily_claim(self):
        self.assertEqual(self.reserve("daily-workload","daily").state,"reserved")
        self.assertEqual(self.reserve("intraday-workload","intraday").state,"hold")
        self.assertEqual(self.journal.inspect(**SCOPE)[0],"daily")

    def test_aggressive_claim_requires_its_own_scope(self):
        self.assertEqual(self.reserve("aggressive-workload","aggressive").state,"hold")
        scope=dict(SCOPE,environment="testnet",account=B)
        self.assertEqual(self.reserve("aggressive-workload","aggressive",**{
            "environment":"testnet","account":B}).state,"reserved")
        self.assertEqual(self.journal.inspect(**scope)[0],"aggressive")

if __name__=="__main__":
    unittest.main()
