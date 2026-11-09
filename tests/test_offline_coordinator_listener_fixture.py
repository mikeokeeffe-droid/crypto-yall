"""Disposable offline listener integration tests; no trading."""
import json
import os
import socket
import struct
import tempfile
import threading
import unittest
from offline_coordinator_listener_fixture import serve_offline_socket_once
from offline_sender_restart_journal import OfflineRestartJournal
from offline_persistent_replay_ledger import OfflinePersistentReplayLedger

ACCOUNT="0x"+"1"*40

@unittest.skipUnless(hasattr(socket,"SO_PEERCRED"),"Linux socket credentials required")
class OfflineCoordinatorListenerTests(unittest.TestCase):
    def test_one_request_claim_and_clean_socket_shutdown(self):
        with tempfile.TemporaryDirectory() as directory:
            journal=os.path.join(directory,"journal.sqlite")
            replay=os.path.join(directory,"replay.sqlite")
            path=os.path.join(directory,"coordinator.sock")
            OfflineRestartJournal(journal,create=True)
            OfflinePersistentReplayLedger(replay,create=True)
            ready=threading.Event()
            results=[]
            def serve():
                results.append(serve_offline_socket_once(
                    path,{os.getuid():("daily","mainnet",ACCOUNT)},
                    replay,journal,ready=ready))
            thread=threading.Thread(target=serve)
            thread.start()
            self.assertTrue(ready.wait(5))
            payload=dict(operation="request_entry",requested_bot="daily",
                         environment="mainnet",account=ACCOUNT,dex="",
                         coin="SOL",nonce="one")
            data=json.dumps(payload).encode()
            with socket.socket(socket.AF_UNIX,socket.SOCK_STREAM) as client:
                client.connect(path)
                client.sendall(struct.pack("!I",len(data))+data)
            thread.join(5)
            self.assertFalse(thread.is_alive())
            self.assertEqual(results,[("reserved_offline_only",False)])
            self.assertFalse(os.path.lexists(path))
            self.assertIsNotNone(OfflineRestartJournal(journal).inspect(
                environment="mainnet",account=ACCOUNT,dex="",coin="SOL"))

    def test_existing_socket_path_not_overwritten(self):
        with tempfile.TemporaryDirectory() as directory:
            path=os.path.join(directory,"coordinator.sock")
            with open(path,"w") as handle:
                handle.write("preserve")
            journal=os.path.join(directory,"journal.sqlite")
            replay=os.path.join(directory,"replay.sqlite")
            OfflineRestartJournal(journal,create=True)
            OfflinePersistentReplayLedger(replay,create=True)
            with self.assertRaises(FileExistsError):
                serve_offline_socket_once(path,{os.getuid():("daily","mainnet",ACCOUNT)},
                                          replay,journal)
            with open(path) as handle:
                self.assertEqual(handle.read(),"preserve")

    def test_missing_state_never_recreated(self):
        with tempfile.TemporaryDirectory() as directory:
            path=os.path.join(directory,"coordinator.sock")
            with self.assertRaises((FileNotFoundError,ValueError)):
                serve_offline_socket_once(path,{os.getuid():("daily","mainnet",ACCOUNT)},
                                          os.path.join(directory,"missing-replay.sqlite"),
                                          os.path.join(directory,"missing-journal.sqlite"))
            self.assertFalse(os.path.exists(path))

if __name__=="__main__":
    unittest.main()
