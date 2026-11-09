"""Offline durable replay tests: restart, parallel verifier, and storage failure."""
import os
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from offline_authenticated_envelope_fixture import (
    OfflineAuthenticatedEnvelopeVerifier,sign_fixture_request)
from offline_persistent_replay_ledger import OfflinePersistentReplayLedger

KEY=b"k"*32
INTENT=dict(requested_bot="daily",environment="mainnet",
            account="0x"+"1"*40,dex="",coin="SOL")

class DurableReplayTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.path=os.path.join(self.temp.name,"replay.sqlite")
        self.ledger=OfflinePersistentReplayLedger(self.path,create=True)
    def tearDown(self):
        self.temp.cleanup()
    def signed(self,nonce="nonce-1"):
        return sign_fixture_request(KEY,"daily-principal","request_entry",INTENT,nonce)
    def verifier(self):
        return OfflineAuthenticatedEnvelopeVerifier(
            {"daily-principal":KEY},ledger=OfflinePersistentReplayLedger(self.path))

    def test_replay_rejected_after_restart(self):
        envelope=self.signed()
        self.assertIsNotNone(self.verifier().verify(envelope))
        self.assertIsNone(self.verifier().verify(envelope))

    def test_parallel_verifiers_allow_one_nonce(self):
        envelope=self.signed()
        with ThreadPoolExecutor(max_workers=8) as pool:
            results=list(pool.map(lambda _:self.verifier().verify(envelope),range(8)))
        self.assertEqual(sum(result is not None for result in results),1)

    def test_tampered_request_does_not_consume_valid_nonce(self):
        valid=self.signed()
        tampered=dict(valid,operation="request_close")
        self.assertIsNone(self.verifier().verify(tampered))
        self.assertIsNotNone(self.verifier().verify(valid))

    def test_missing_or_corrupt_ledger_fails_closed(self):
        envelope=self.signed()
        os.unlink(self.path)
        verifier=OfflineAuthenticatedEnvelopeVerifier(
            {"daily-principal":KEY},ledger=self.ledger)
        self.assertIsNone(verifier.verify(envelope))
        with open(self.path,"wb") as file:
            file.write(b"not sqlite")
        self.assertIsNone(verifier.verify(self.signed("nonce-2")))

    def test_missing_ledger_is_not_recreated_on_reopen(self):
        os.unlink(self.path)
        with self.assertRaises(Exception):
            OfflinePersistentReplayLedger(self.path)

if __name__=="__main__":
    unittest.main()
