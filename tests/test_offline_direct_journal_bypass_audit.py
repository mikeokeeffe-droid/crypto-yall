"""Offline trust-boundary audit: direct journal access bypasses fixture verifier.

These tests deliberately document a NO-GO architectural gap; they do not
exercise live bots, credentials, networks or order submission.
"""
import os
import tempfile
import unittest
from offline_sender_restart_journal import OfflineRestartJournal
from offline_bot_identity_fixture import OfflineIdentityVerifier, VerifiedFixtureIdentity
from offline_verified_claim_fixture import reserve_verified_fixture

SCOPE=dict(environment="mainnet",account="0x"+"1"*40,dex="",coin="SOL")

class DirectJournalBypassAudit(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.journal=OfflineRestartJournal(
            os.path.join(self.temp.name,"claims.sqlite"),create=True)
        self.verifier=OfflineIdentityVerifier({
            "daily-principal":VerifiedFixtureIdentity(
                "daily","mainnet",SCOPE["account"]),
        })
    def tearDown(self):
        self.temp.cleanup()

    def test_verified_wrapper_rejects_spoofed_intraday(self):
        result=reserve_verified_fixture(
            verifier=self.verifier,journal=self.journal,
            principal="daily-principal",requested_bot="intraday",**SCOPE)
        self.assertEqual(result.state,"hold")
        self.assertFalse(result.submit_authorized)
        self.assertIsNone(self.journal.inspect(**SCOPE))

    def test_direct_journal_reserve_still_accepts_unverified_bot_name(self):
        # Known bypass: caller-controlled bot name is accepted directly.
        # Passing this test is evidence of a blocker, NOT proof of safety.
        claim=self.journal.reserve(bot="intraday",**SCOPE)
        self.assertIsNotNone(claim)
        self.assertEqual(self.journal.inspect(**SCOPE)[0],"intraday")
        self.assertIsNone(self.journal.reserve(bot="daily",**SCOPE))

    def test_direct_mark_accepts_claim_without_verifying_bot_identity(self):
        token,_,fence=self.journal.reserve(bot="intraday",**SCOPE)
        self.assertTrue(self.journal.mark_dispatch_unknown(
            token=token,fence=fence,**SCOPE))
        self.assertEqual(self.journal.inspect(**SCOPE)[-1],"dispatch_unknown")

if __name__=="__main__":
    unittest.main()
