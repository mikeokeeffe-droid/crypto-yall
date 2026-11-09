"""Explicit NO-GO audit of remaining same-UID coordinator bypasses.

These tests intentionally demonstrate that disposable process separation is
not an OS security boundary. No production files, credentials or orders.
"""
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

class SameUidBypassAudit(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.journal=os.path.join(self.temp.name,"journal.sqlite")
        self.replay=os.path.join(self.temp.name,"replay.sqlite")
        self.credentials=os.path.join(self.temp.name,"keys.json")
        OfflineRestartJournal(self.journal,create=True)
        OfflinePersistentReplayLedger(self.replay,create=True)
        with open(self.credentials,"w") as stream:
            json.dump({"daily-principal":KEY.hex()},stream)
        os.chmod(self.credentials,0o600)
    def tearDown(self):
        self.temp.cleanup()

    def test_same_uid_can_read_disposable_worker_secret_and_impersonate(self):
        # Demonstrates a remaining vulnerability, not a security success.
        with open(self.credentials) as stream:
            stolen=bytes.fromhex(json.load(stream)["daily-principal"])
        self.assertEqual(stolen,KEY)
        coordinator=OfflineWorkerAuthenticatedCoordinator(
            self.journal,self.replay,PRINCIPALS,self.credentials)
        try:
            forged=sign_fixture_request(stolen,"daily-principal",
                                        "request_entry",INTENT,"stolen-nonce")
            self.assertEqual(coordinator.request(forged),("reserved",False))
            self.assertEqual(coordinator.request(forged),("hold",False))
        finally:
            coordinator.close()

    def test_same_uid_can_directly_mutate_disposable_journal(self):
        # A valid HMAC does not protect the database against same-UID access.
        result=OfflineRestartJournal(self.journal).reserve(
            bot="intraday",environment="mainnet",account=ACCOUNT,dex="",coin="ETH")
        self.assertIsNotNone(result)

if __name__=="__main__":
    unittest.main()
