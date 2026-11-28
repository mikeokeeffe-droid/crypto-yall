"""Offline end-to-end socket journal and replay tests."""
import json
import os
import socket
import struct
import tempfile
import threading
import unittest
from offline_persistent_replay_ledger import OfflinePersistentReplayLedger
from offline_sender_restart_journal import OfflineRestartJournal
from offline_socket_journal_bridge_fixture import handle_offline_journal_socket

ACCOUNT="0x"+"1"*40

@unittest.skipUnless(hasattr(socket,"SO_PEERCRED") and hasattr(os,"getuid"),
                     "requires Linux SO_PEERCRED")
class OfflineSocketJournalBridgeTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.journal=os.path.join(self.temp.name,"claims.sqlite")
        self.replay=os.path.join(self.temp.name,"nonces.sqlite")
        OfflineRestartJournal(self.journal,create=True)
        OfflinePersistentReplayLedger(self.replay,create=True)
        self.payload=dict(operation="request_entry",requested_bot="daily",
                          environment="mainnet",account=ACCOUNT,dex="",
                          coin="SOL",nonce="n1")

    def exchange(self,payload,allowed=None):
        path=os.path.join(self.temp.name,"server.sock")
        if os.path.exists(path):
            os.unlink(path)
        with socket.socket(socket.AF_UNIX,socket.SOCK_STREAM) as listener:
            listener.bind(path)
            listener.listen(1)
            result=[]
            def serve():
                connection,_=listener.accept()
                with connection:
                    result.append(handle_offline_journal_socket(
                        connection,{os.getuid():("daily","mainnet",ACCOUNT)}
                        if allowed is None else allowed,self.replay,self.journal))
            worker=threading.Thread(target=serve,daemon=True)
            worker.start()
            data=json.dumps(payload).encode()
            with socket.socket(socket.AF_UNIX,socket.SOCK_STREAM) as client:
                client.connect(path)
                client.sendall(struct.pack("!I",len(data))+data)
            worker.join(timeout=5)
            self.assertFalse(worker.is_alive())
            return result[0]

    def test_claim_then_replay_and_restart_hold(self):
        self.assertEqual(self.exchange(self.payload),("reserved_offline_only",False))
        self.assertEqual(self.exchange(self.payload),("hold",False))
        self.assertEqual(self.exchange(dict(self.payload,nonce="n2")),("hold",False))
        self.assertIsNotNone(OfflineRestartJournal(self.journal).inspect(
            environment="mainnet",account=ACCOUNT,dex="",coin="SOL"))

    def test_spoofed_and_unknown_uid_do_not_claim(self):
        self.assertEqual(self.exchange(dict(self.payload,requested_bot="intraday")),
                         ("hold",False))
        self.assertEqual(self.exchange(self.payload,allowed={}),("hold",False))
        self.assertIsNone(OfflineRestartJournal(self.journal).inspect(
            environment="mainnet",account=ACCOUNT,dex="",coin="SOL"))

    def test_invalid_scope_does_not_consume_nonce(self):
        self.assertEqual(self.exchange(dict(self.payload,coin="bad!")),("hold",False))
        self.assertEqual(self.exchange(self.payload),("reserved_offline_only",False))

    def test_missing_replay_ledger_holds_without_claim(self):
        os.unlink(self.replay)
        self.assertEqual(self.exchange(self.payload),("hold",False))
        self.assertIsNone(OfflineRestartJournal(self.journal).inspect(
            environment="mainnet",account=ACCOUNT,dex="",coin="SOL"))

if __name__=="__main__":
    unittest.main()
