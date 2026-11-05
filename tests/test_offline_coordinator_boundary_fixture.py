"""Offline coordinator client/server boundary tests."""
import os
import tempfile
from concurrent.futures import ThreadPoolExecutor
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

    def test_unknown_principal_cannot_reserve(self):
        unknown=OfflineCoordinatorClientFixture(
            send=self.server.handle,principal="unknown-principal")
        result=unknown.request_entry(self.intent)
        self.assertEqual(result.state,"hold")
        self.assertFalse(result.submit_authorized)
        self.assertIsNone(self.journal.inspect(**SCOPE))

    def test_other_account_cannot_be_claimed(self):
        wrong=OfflineEntryIntent(
            requested_bot="daily",**dict(SCOPE,account="0x"+"2"*40))
        result=self.daily.request_entry(wrong)
        self.assertEqual(result.state,"hold")
        self.assertFalse(result.submit_authorized)
        self.assertIsNone(self.journal.inspect(**SCOPE))

    def test_other_environment_cannot_be_claimed(self):
        wrong=OfflineEntryIntent(
            requested_bot="daily",**dict(SCOPE,environment="testnet"))
        result=self.daily.request_entry(wrong)
        self.assertEqual(result.state,"hold")
        self.assertFalse(result.submit_authorized)
        self.assertIsNone(self.journal.inspect(**SCOPE))

    def test_restart_preserves_claim_and_blocks_competing_bot(self):
        self.assertEqual(self.daily.request_entry(self.intent).state,"reserved")
        reopened=OfflineRestartJournal(self.journal.path)
        protected=OfflineProtectedJournalFixture(
            verifier=OfflineIdentityVerifier({
                "daily-principal":VerifiedFixtureIdentity("daily","mainnet",ACCOUNT),
                "intraday-principal":VerifiedFixtureIdentity("intraday","mainnet",ACCOUNT),
            }),journal=reopened)
        restarted=OfflineCoordinatorServerFixture(protected)
        competing=OfflineCoordinatorClientFixture(
            send=restarted.handle,principal="intraday-principal")
        other=OfflineEntryIntent(requested_bot="intraday",**SCOPE)
        result=competing.request_entry(other)
        self.assertEqual(result.state,"hold")
        self.assertFalse(result.submit_authorized)
        self.assertEqual(reopened.inspect(**SCOPE)[0],"daily")

    def test_deleted_journal_fails_closed_through_coordinator(self):
        os.unlink(self.journal.path)
        result=self.daily.request_entry(self.intent)
        self.assertEqual(result.state,"hold")
        self.assertFalse(result.submit_authorized)
        self.assertFalse(os.path.exists(self.journal.path))

    def test_corrupt_journal_fails_closed_through_coordinator(self):
        with open(self.journal.path,"wb") as handle:
            handle.write(b"invalid offline coordinator journal")
        result=self.daily.request_entry(self.intent)
        self.assertEqual(result.state,"hold")
        self.assertFalse(result.submit_authorized)

    def test_simultaneous_bots_only_one_can_reserve_same_scope(self):
        daily_intent=self.intent
        intraday_intent=OfflineEntryIntent(requested_bot="intraday",**SCOPE)
        with ThreadPoolExecutor(max_workers=2) as pool:
            a=pool.submit(self.daily.request_entry,daily_intent)
            b=pool.submit(self.intraday.request_entry,intraday_intent)
            results=[a.result(),b.result()]
        self.assertEqual(sorted(result.state for result in results),
                         ["hold","reserved"])
        self.assertTrue(all(not result.submit_authorized for result in results))
        row=self.journal.inspect(**SCOPE)
        self.assertIn(row[0],("daily","intraday"))

    def test_duplicate_same_bot_request_cannot_create_second_claim(self):
        first=self.daily.request_entry(self.intent)
        self.assertEqual(first.state,"reserved")
        before=self.journal.inspect(**SCOPE)
        again=self.daily.request_entry(self.intent)
        self.assertEqual(again.state,"hold")
        self.assertFalse(again.submit_authorized)
        self.assertEqual(self.journal.inspect(**SCOPE),before)

    def test_replayed_request_after_restart_cannot_replace_claim(self):
        self.assertEqual(self.daily.request_entry(self.intent).state,"reserved")
        before=self.journal.inspect(**SCOPE)
        reopened=OfflineRestartJournal(self.journal.path)
        protected=OfflineProtectedJournalFixture(
            verifier=OfflineIdentityVerifier({
                "daily-principal":VerifiedFixtureIdentity("daily","mainnet",ACCOUNT),
            }),journal=reopened)
        replay_client=OfflineCoordinatorClientFixture(
            send=OfflineCoordinatorServerFixture(protected).handle,
            principal="daily-principal")
        result=replay_client.request_entry(self.intent)
        self.assertEqual(result.state,"hold")
        self.assertFalse(result.submit_authorized)
        self.assertEqual(reopened.inspect(**SCOPE),before)

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
