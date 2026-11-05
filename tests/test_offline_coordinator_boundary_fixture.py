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

    def test_claim_identifiers_cannot_authorize_dispatch_or_close(self):
        self.assertEqual(self.daily.request_entry(self.intent).state,"reserved")
        bot,token,cloid,fence,state=self.journal.inspect(**SCOPE)
        for client in (self.daily,self.intraday):
            self.assertEqual(client.request_dispatch(
                token=token,cloid=cloid,fence=fence,**SCOPE).state,"hold")
            self.assertEqual(client.request_close(
                token=token,cloid=cloid,fence=fence,**SCOPE).state,"hold")
        self.assertEqual(self.journal.inspect(**SCOPE)[-1],"reserved")

    def test_claim_identifier_replay_across_account_and_environment_holds(self):
        self.assertEqual(self.daily.request_entry(self.intent).state,"reserved")
        before=self.journal.inspect(**SCOPE)
        _,token,cloid,fence,_=before
        for scope in (
            dict(SCOPE,account="0x"+"2"*40),
            dict(SCOPE,environment="testnet"),
        ):
            for operation in ("request_dispatch","request_close","mark_dispatch_unknown"):
                result=self.server.handle(
                    principal="daily-principal",operation=operation,
                    intent={"token":token,"cloid":cloid,"fence":fence,**scope})
                self.assertEqual(result.state,"hold")
                self.assertFalse(result.submit_authorized)
        self.assertEqual(self.journal.inspect(**SCOPE),before)

    def test_ambiguous_dispatch_marker_blocks_retry_and_competing_bot(self):
        self.assertEqual(self.daily.request_entry(self.intent).state,"reserved")
        bot,token,cloid,fence,state=self.journal.inspect(**SCOPE)
        # Simulate the coordinator's internal pre-dispatch durable marker;
        # client requests never receive this capability.
        self.assertTrue(self.journal.mark_dispatch_unknown(
            token=token,fence=fence,**SCOPE))
        before=self.journal.inspect(**SCOPE)
        self.assertEqual(before[-1],"dispatch_unknown")
        daily_retry=self.daily.request_entry(self.intent)
        intraday_retry=self.intraday.request_entry(
            OfflineEntryIntent(requested_bot="intraday",**SCOPE))
        self.assertEqual(daily_retry.state,"hold")
        self.assertEqual(intraday_retry.state,"hold")
        self.assertFalse(daily_retry.submit_authorized)
        self.assertFalse(intraday_retry.submit_authorized)
        self.assertEqual(self.journal.inspect(**SCOPE),before)

    def test_ambiguous_dispatch_marker_survives_coordinator_restart(self):
        self.assertEqual(self.daily.request_entry(self.intent).state,"reserved")
        _,token,_,fence,_=self.journal.inspect(**SCOPE)
        self.assertTrue(self.journal.mark_dispatch_unknown(
            token=token,fence=fence,**SCOPE))
        before=self.journal.inspect(**SCOPE)
        reopened=OfflineRestartJournal(self.journal.path)
        protected=OfflineProtectedJournalFixture(
            verifier=OfflineIdentityVerifier({
                "daily-principal":VerifiedFixtureIdentity("daily","mainnet",ACCOUNT),
            }),journal=reopened)
        restarted=OfflineCoordinatorClientFixture(
            send=OfflineCoordinatorServerFixture(protected).handle,
            principal="daily-principal")
        result=restarted.request_entry(self.intent)
        self.assertEqual(result.state,"hold")
        self.assertFalse(result.submit_authorized)
        self.assertEqual(reopened.inspect(**SCOPE),before)

    def test_stale_reconciliation_cannot_release_uncertain_claim(self):
        self.assertEqual(self.daily.request_entry(self.intent).state,"reserved")
        _,token,_,fence,_=self.journal.inspect(**SCOPE)
        self.assertTrue(self.journal.mark_dispatch_unknown(
            token=token,fence=fence,**SCOPE))
        before=self.journal.inspect(**SCOPE)
        result=self.server.handle(
            principal="daily-principal",operation="reconcile",
            intent={"fresh":False,"token":token,"fence":fence,**SCOPE})
        self.assertEqual(result.state,"hold")
        self.assertFalse(result.submit_authorized)
        self.assertEqual(self.journal.inspect(**SCOPE),before)

    def test_incomplete_reconciliation_cannot_release_uncertain_claim(self):
        self.assertEqual(self.daily.request_entry(self.intent).state,"reserved")
        _,token,_,fence,_=self.journal.inspect(**SCOPE)
        self.assertTrue(self.journal.mark_dispatch_unknown(
            token=token,fence=fence,**SCOPE))
        before=self.journal.inspect(**SCOPE)
        for incomplete in (
            {"orders":[],"fills":None,"position":None},
            {"orders":None,"fills":[],"position":{"coin":"SOL"}},
            {"orders":[],"fills":[],"position":None},
        ):
            result=self.server.handle(
                principal="daily-principal",operation="reconcile",
                intent={"token":token,"fence":fence,**SCOPE,**incomplete})
            self.assertEqual(result.state,"hold")
            self.assertFalse(result.submit_authorized)
            self.assertEqual(self.journal.inspect(**SCOPE),before)

    def test_other_bot_matching_coin_side_cannot_authorize_close(self):
        self.assertEqual(self.daily.request_entry(self.intent).state,"reserved")
        before=self.journal.inspect(**SCOPE)
        for client in (self.daily,self.intraday):
            result=client.request_close(
                owner_bot="daily",requesting_bot="intraday",
                coin="SOL",side="long",position_side="long",
                account=ACCOUNT,environment="mainnet",
                token=before[1],cloid=before[2],fence=before[3])
            self.assertEqual(result.state,"hold")
            self.assertFalse(result.submit_authorized)
        self.assertEqual(self.journal.inspect(**SCOPE),before)

    def test_unknown_or_manual_position_never_authorizes_close(self):
        self.assertEqual(self.daily.request_entry(self.intent).state,"reserved")
        before=self.journal.inspect(**SCOPE)
        for origin in ("manual","unknown",None):
            result=self.daily.request_close(
                coin="SOL",side="long",position_origin=origin,
                position_size="1.0",requested_close_size="1.0")
            self.assertEqual(result.state,"hold")
            self.assertFalse(result.submit_authorized)
        self.assertEqual(self.journal.inspect(**SCOPE),before)

    def test_mismatched_side_or_size_never_authorizes_close(self):
        self.assertEqual(self.daily.request_entry(self.intent).state,"reserved")
        before=self.journal.inspect(**SCOPE)
        for side,size in (("short","1.0"),("long","2.0"),("long",None)):
            result=self.daily.request_close(
                coin="SOL",side=side,position_side="long",
                position_size="1.0",requested_close_size=size)
            self.assertEqual(result.state,"hold")
            self.assertFalse(result.submit_authorized)
        self.assertEqual(self.journal.inspect(**SCOPE),before)

    def test_simultaneous_close_requests_never_authorize_or_mutate_claim(self):
        self.assertEqual(self.daily.request_entry(self.intent).state,"reserved")
        before=self.journal.inspect(**SCOPE)
        with ThreadPoolExecutor(max_workers=2) as pool:
            daily_close=pool.submit(self.daily.request_close,
                                    coin="SOL",side="long",size="1")
            intraday_close=pool.submit(self.intraday.request_close,
                                       coin="SOL",side="long",size="1")
            results=(daily_close.result(),intraday_close.result())
        self.assertTrue(all(result.state=="hold" for result in results))
        self.assertTrue(all(not result.submit_authorized for result in results))
        self.assertEqual(self.journal.inspect(**SCOPE),before)

    def test_repeated_close_request_never_authorizes_or_mutates_claim(self):
        self.assertEqual(self.daily.request_entry(self.intent).state,"reserved")
        before=self.journal.inspect(**SCOPE)
        for _ in range(3):
            result=self.daily.request_close(
                coin="SOL",side="long",size="1",
                token=before[1],fence=before[3])
            self.assertEqual(result.state,"hold")
            self.assertFalse(result.submit_authorized)
        self.assertEqual(self.journal.inspect(**SCOPE),before)

    def test_ambiguous_close_acknowledgement_never_allows_retry(self):
        self.assertEqual(self.daily.request_entry(self.intent).state,"reserved")
        before=self.journal.inspect(**SCOPE)
        for acknowledgement in (None,"timeout","unknown","connection_lost"):
            result=self.server.handle(
                principal="daily-principal",operation="close_acknowledgement",
                intent={"acknowledgement":acknowledgement,
                        "token":before[1],"fence":before[3],**SCOPE})
            self.assertEqual(result.state,"hold")
            self.assertFalse(result.submit_authorized)
            retry=self.daily.request_close(
                coin="SOL",token=before[1],fence=before[3])
            self.assertEqual(retry.state,"hold")
            self.assertFalse(retry.submit_authorized)
        self.assertEqual(self.journal.inspect(**SCOPE),before)

    def test_ambiguous_close_acknowledgement_cannot_release_claim(self):
        self.assertEqual(self.daily.request_entry(self.intent).state,"reserved")
        before=self.journal.inspect(**SCOPE)
        for operation in ("release_claim","retry_close","confirm_close"):
            result=self.server.handle(
                principal="daily-principal",operation=operation,
                intent={"token":before[1],"fence":before[3],
                        "close_acknowledgement":"unknown",**SCOPE})
            self.assertEqual(result.state,"hold")
            self.assertFalse(result.submit_authorized)
        self.assertEqual(self.journal.inspect(**SCOPE),before)

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
