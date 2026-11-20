"""Offline authenticated adapter tests, including restart and spoof denial."""
import os
import tempfile
import unittest
from offline_sender_restart_journal import OfflineRestartJournal
from offline_persistent_replay_ledger import OfflinePersistentReplayLedger
from offline_authenticated_envelope_fixture import sign_fixture_request
from offline_authenticated_process_coordinator_fixture import OfflineAuthenticatedProcessCoordinator

ACCOUNT="0x"+"1"*40
KEY_D=b"d"*32
KEY_I=b"i"*32
PRINCIPALS={"daily-principal":("daily","mainnet",ACCOUNT),
            "intraday-principal":("intraday","mainnet",ACCOUNT)}
KEYS={"daily-principal":KEY_D,"intraday-principal":KEY_I}
INTENT=dict(requested_bot="daily",environment="mainnet",
            account=ACCOUNT,dex="",coin="SOL")

class AuthenticatedCoordinatorTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.journal=os.path.join(self.temp.name,"journal.sqlite")
        self.replay=os.path.join(self.temp.name,"replay.sqlite")
        OfflineRestartJournal(self.journal,create=True)
        OfflinePersistentReplayLedger(self.replay,create=True)
    def tearDown(self):
        self.temp.cleanup()
    def start(self):
        return OfflineAuthenticatedProcessCoordinator(
            self.journal,self.replay,PRINCIPALS,KEYS)
    def signed(self,nonce,principal="daily-principal",key=KEY_D,intent=None,
               operation="request_entry"):
        return sign_fixture_request(key,principal,operation,
                                    INTENT if intent is None else intent,nonce)

    def test_valid_claim_and_replay_hold_after_process_restart(self):
        request=self.signed("n1")
        first=self.start()
        try:
            self.assertEqual(first.request(request),("reserved",False))
            self.assertEqual(first.request(request),("hold",False))
        finally:
            first.close()
        second=self.start()
        try:
            self.assertEqual(second.request(request),("hold",False))
            self.assertEqual(second.request(self.signed("n2")),("hold",False))
        finally:
            second.close()

    def test_spoofing_tamper_and_wrong_key_hold(self):
        coordinator=self.start()
        try:
            spoof=self.signed("n1",principal="intraday-principal")
            self.assertEqual(coordinator.request(spoof),("hold",False))
            wrong=self.signed("n2",key=KEY_I)
            self.assertEqual(coordinator.request(wrong),("hold",False))
            tampered=dict(self.signed("n3"),operation="request_close")
            self.assertEqual(coordinator.request(tampered),("hold",False))
            self.assertEqual(coordinator.request(self.signed("n4")),("reserved",False))
        finally:
            coordinator.close()

    def test_signed_close_and_dispatch_always_hold(self):
        coordinator=self.start()
        try:
            for index,operation in enumerate(("request_close","request_dispatch")):
                self.assertEqual(coordinator.request(
                    self.signed(str(index),operation=operation)),("hold",False))
        finally:
            coordinator.close()

    def test_missing_replay_store_fails_closed(self):
        coordinator=self.start()
        try:
            os.unlink(self.replay)
            self.assertEqual(coordinator.request(self.signed("n1")),("hold",False))
        finally:
            coordinator.close()

if __name__=="__main__":
    unittest.main()
