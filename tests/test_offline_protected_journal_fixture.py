"""Protected journal fixture tests, offline only."""
import os
import tempfile
import unittest
from offline_bot_identity_fixture import OfflineIdentityVerifier, VerifiedFixtureIdentity
from offline_sender_restart_journal import OfflineRestartJournal
from offline_protected_journal_fixture import OfflineProtectedJournalFixture

ACCOUNT="0x"+"1"*40
SCOPE=dict(environment="mainnet",account=ACCOUNT,dex="",coin="SOL")

class ProtectedJournalFixtureTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.journal=OfflineRestartJournal(
            os.path.join(self.tmp.name,"claims.sqlite"),create=True)
        self.fixture=OfflineProtectedJournalFixture(
            verifier=OfflineIdentityVerifier({
                "daily-principal":VerifiedFixtureIdentity("daily","mainnet",ACCOUNT),
                "intraday-principal":VerifiedFixtureIdentity("intraday","mainnet",ACCOUNT),
            }),journal=self.journal)
    def tearDown(self):
        self.tmp.cleanup()

    def request(self,principal,bot,**changes):
        return self.fixture.request_entry(
            principal=principal,requested_bot=bot,**dict(SCOPE,**changes))

    def test_verified_daily_reserves_without_dispatch_authority(self):
        result=self.request("daily-principal","daily")
        self.assertEqual(result.state,"reserved")
        self.assertFalse(result.submit_authorized)
        self.assertEqual(self.journal.inspect(**SCOPE)[0],"daily")

    def test_daily_cannot_claim_as_intraday(self):
        self.assertEqual(self.request("daily-principal","intraday").state,"hold")
        self.assertIsNone(self.journal.inspect(**SCOPE))

    def test_intraday_cannot_take_daily_claim(self):
        self.assertEqual(self.request("daily-principal","daily").state,"reserved")
        self.assertEqual(self.request("intraday-principal","intraday").state,"hold")

    def test_wrong_account_and_network_fail_closed(self):
        self.assertEqual(self.request(
            "daily-principal","daily",account="0x"+"2"*40).state,"hold")
        self.assertEqual(self.request(
            "daily-principal","daily",environment="testnet").state,"hold")
        self.assertIsNone(self.journal.inspect(**SCOPE))

    def test_unknown_identity_cannot_reserve(self):
        self.assertEqual(self.request("unknown","daily").state,"hold")
        self.assertIsNone(self.journal.inspect(**SCOPE))

    def test_missing_identity_cannot_reserve(self):
        self.assertEqual(self.request(None,"daily").state,"hold")
        self.assertIsNone(self.journal.inspect(**SCOPE))

    def test_deleted_journal_holds_without_recreating_database(self):
        os.unlink(self.journal.path)
        result=self.request("daily-principal","daily")
        self.assertEqual(result.state,"hold")
        self.assertFalse(result.submit_authorized)
        self.assertFalse(os.path.exists(self.journal.path))

    def test_corrupted_journal_holds_without_claim(self):
        with open(self.journal.path,"wb") as handle:
            handle.write(b"corrupt offline fixture")
        result=self.request("daily-principal","daily")
        self.assertEqual(result.state,"hold")
        self.assertFalse(result.submit_authorized)

    def test_underlying_journal_reference_bypasses_fixture_identity_gate(self):
        # Known NO-GO: Python attribute access is not a security boundary.
        # An untrusted in-process caller can still reach the journal.
        bypass=self.fixture._journal.reserve(bot="aggressive",**SCOPE)
        self.assertIsNotNone(bypass)
        self.assertEqual(self.journal.inspect(**SCOPE)[0],"aggressive")
        self.assertEqual(self.request("daily-principal","daily").state,"hold")

    def test_same_process_can_open_journal_path_and_bypass_fixture(self):
        # A separate journal instance with filesystem access can reserve.
        reopened=OfflineRestartJournal(self.journal.path)
        claim=reopened.reserve(bot="intraday",**SCOPE)
        self.assertIsNotNone(claim)
        self.assertEqual(self.journal.inspect(**SCOPE)[0],"intraday")

    def test_close_and_dispatch_are_always_held(self):
        self.assertEqual(self.fixture.request_close(
            principal="daily-principal",coin="SOL").state,"hold")
        self.assertEqual(self.fixture.request_dispatch(
            principal="daily-principal",coin="SOL").state,"hold")
        self.assertFalse(self.fixture.request_close().submit_authorized)
        self.assertFalse(self.fixture.request_dispatch().submit_authorized)

if __name__=="__main__":
    unittest.main()
