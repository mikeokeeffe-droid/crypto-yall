"""Offline worker loads disposable credentials itself before accepting IPC."""
import json
import os
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

class WorkerCredentialStartupTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.journal=os.path.join(self.temp.name,"claims.sqlite")
        self.replay=os.path.join(self.temp.name,"replay.sqlite")
        self.credentials=os.path.join(self.temp.name,"credentials.json")
        OfflineRestartJournal(self.journal,create=True)
        OfflinePersistentReplayLedger(self.replay,create=True)
    def tearDown(self):
        self.temp.cleanup()
    def write(self,data,mode=0o600):
        with open(self.credentials,"wb") as stream:
            stream.write(data)
        os.chmod(self.credentials,mode)
    def start(self):
        return OfflineWorkerAuthenticatedCoordinator(
            self.journal,self.replay,PRINCIPALS,credential_path=self.credentials)
    def test_worker_reads_valid_file_and_accepts_only_signed_request(self):
        self.write(json.dumps({"daily-principal":KEY.hex()}).encode())
        coordinator=self.start()
        try:
            signed=sign_fixture_request(KEY,"daily-principal","request_entry",INTENT,"n1")
            self.assertEqual(coordinator.request(signed),("reserved",False))
            self.assertEqual(coordinator.request(signed),("hold",False))
        finally:
            coordinator.close()
    def test_missing_invalid_or_exposed_credentials_prevent_worker_start(self):
        with self.assertRaises(RuntimeError):
            self.start()
        for data,mode in ((b"not json",0o600),(b"{}",0o600),
                          (json.dumps({"daily-principal":KEY.hex()}).encode(),0o644)):
            self.write(data,mode)
            with self.subTest(data=data,mode=mode),self.assertRaises(RuntimeError):
                self.start()
    def test_missing_credentials_on_restart_fail_closed(self):
        self.write(json.dumps({"daily-principal":KEY.hex()}).encode())
        coordinator=self.start()
        coordinator.close()
        os.unlink(self.credentials)
        with self.assertRaises(RuntimeError):
            self.start()

if __name__=="__main__":
    unittest.main()
