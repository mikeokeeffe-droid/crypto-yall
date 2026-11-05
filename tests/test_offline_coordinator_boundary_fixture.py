"""Offline coordinator client/server boundary tests."""
import os
import tempfile
import unittest
from offline_bot_identity_fixture import OfflineIdentityVerifier, VerifiedFixtureIdentity
from offline_sender_restart_journal import OfflineRestartJournal
from offline_protected_journal_fixture import OfflineProtectedJournalFixture
from offline_coordinator_boundary_fixture import (
    OfflineCoordinatorServerFixture, OfflineCoordinatorClientFixture,
    OfflineEntryIntent)

ACCOUNT="0x"+"1"*40
SCOPE=dict(environment="mainnet",account=ACCOUNT,dex="",coin="SOL")

class CoordinatorBoundaryFixtureTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.journal=OfflineRestartJournal(
            os.path.join(self.tmp.name,"claims.sqlite"),create=True)
        protected=OfflineProtectedJournalFixture(
            verifier=OfflineIdentityVerifier({
                "daily-principal":VerifiedFixtureIdentity("daily","mainnet",ACCOUNT),
                "intraday-principal":VerifiedFixtureIdentity("intraday","mainnet",ACCOUNT),
            }),journal=self.journal)
        self.server=OfflineCoordinatorServerFixture(protected)
        self.daily=OfflineCoordinatorClientFixture(
            send=self.server.handle,principal="daily-principal")
        self.intraday=OfflineCoordinatorClientFixture(
            send=self.server.handle,principal="intraday-principal")
        self.intent=OfflineEntryIntent(requested_bot="daily",**SCOPE)
    def tearDown(self):
        self.tmp.cleanup()

    def test_verified_request_reserves_without_submit_authority(self):
        result=self.daily.request_entry(self.intent)
        self.assertEqual(result.state,"reserved")
        self.assertFalse(result.submit_authorized)

    def test_impersonation_rejected(self):
        result=self.daily.request_entry(OfflineEntryIntent(
            requested_bot="intraday",**SCOPE))
        self.assertEqual(result.state,"hold")
        self.assertIsNone(self.journal.inspect(**SCOPE))

    def test_competing_bot_rejected(self):
        self.assertEqual(self.daily.request_entry(self.intent).state,"reserved")
        other=OfflineEntryIntent(requested_bot="intraday",**SCOPE)
        self.assertEqual(self.intraday.request_entry(other).state,"hold")

    def test_unknown_operation_and_malformed_request_hold(self):
        self.assertEqual(self.server.handle(
            principal="daily-principal",operation="raw_sql",intent=self.intent).state,"hold")
        self.assertEqual(self.daily.request_entry({"bot":"daily"}).state,"hold")
        self.assertEqual(self.server.handle(
            principal="daily-principal",operation="request_entry",intent=None).state,"hold")

    def test_dispatch_close_and_transport_failure_hold(self):
        self.assertEqual(self.daily.request_dispatch().state,"hold")
        self.assertEqual(self.daily.request_close().state,"hold")
        broken=OfflineCoordinatorClientFixture(
            principal="daily-principal",
            send=lambda **kwargs: (_ for _ in ()).throw(ConnectionError("offline")))
        self.assertEqual(broken.request_entry(self.intent).state,"hold")
        self.assertFalse(broken.request_entry(self.intent).submit_authorized)

    def test_client_interface_has_no_journal_field(self):
        self.assertFalse(hasattr(self.daily,"_journal"))
        self.assertFalse(hasattr(self.daily,"journal"))
        self.assertFalse(hasattr(self.daily,"path"))

if __name__=="__main__":
    unittest.main()
