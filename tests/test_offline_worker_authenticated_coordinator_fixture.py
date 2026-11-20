"""Offline worker-side authentication and durable replay checks."""
import os
import json
import tempfile
import unittest
from offline_sender_restart_journal import OfflineRestartJournal
from offline_persistent_replay_ledger import OfflinePersistentReplayLedger
from offline_authenticated_envelope_fixture import sign_fixture_request
from offline_worker_authenticated_coordinator_fixture import OfflineWorkerAuthenticatedCoordinator

ACCOUNT="0x"+"1"*40
KEY=b"d"*32
PRINCIPALS={"daily-principal":("daily","mainnet",ACCOUNT)}
INTENT=dict(requested_bot="daily",environment="mainnet",
            account=ACCOUNT,dex="",coin="SOL")

class WorkerAuthenticationTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.journal=os.path.join(self.temp.name,"claims.sqlite")
        self.replay=os.path.join(self.temp.name,"replay.sqlite")
        OfflineRestartJournal(self.journal,create=True)
        OfflinePersistentReplayLedger(self.replay,create=True)
        self.credentials=os.path.join(self.temp.name,'credentials.json')
        with open(self.credentials,'w') as stream:
            json.dump({'daily-principal':KEY.hex()},stream)
        os.chmod(self.credentials,0o600)
    def tearDown(self):
        self.temp.cleanup()
    def start(self):
        return OfflineWorkerAuthenticatedCoordinator(
            self.journal,self.replay,PRINCIPALS,self.credentials)
    def signed(self,nonce,operation="request_entry"):
        return sign_fixture_request(KEY,"daily-principal",operation,INTENT,nonce)

    def test_worker_verifies_and_rejects_replay_after_restart(self):
        envelope=self.signed("n1")
        first=self.start()
        try:
            self.assertEqual(first.request(envelope),("reserved",False))
            self.assertEqual(first.request(envelope),("hold",False))
        finally:
            first.close()
        second=self.start()
        try:
            self.assertEqual(second.request(envelope),("hold",False))
            self.assertEqual(second.request(self.signed("n2")),("hold",False))
        finally:
            second.close()

    def test_unsigned_tampered_and_unsupported_requests_hold(self):
        coordinator=self.start()
        try:
            self.assertEqual(coordinator.request(
                dict(principal="daily-principal",operation="request_entry",intent=INTENT)),
                ("hold",False))
            tampered=dict(self.signed("n1"),intent=dict(INTENT,coin="ETH"))
            self.assertEqual(coordinator.request(tampered),("hold",False))
            self.assertEqual(coordinator.request(self.signed("n2","request_close")),
                             ("hold",False))
            self.assertEqual(coordinator.request(self.signed("n3","request_dispatch")),
                             ("hold",False))
            self.assertEqual(coordinator.request(self.signed("n4")),("reserved",False))
        finally:
            coordinator.close()

    def test_missing_replay_ledger_prevents_worker_start(self):
        os.unlink(self.replay)
        with self.assertRaises(RuntimeError):
            self.start()

if __name__=="__main__":
    unittest.main()
