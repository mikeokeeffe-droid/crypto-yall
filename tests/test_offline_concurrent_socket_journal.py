"""Concurrent offline socket-to-journal claim audit.

All connections are disposable local Unix socket pairs, with real SO_PEERCRED.
No exchange SDK, signer, live credentials or orders.
"""
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
class OfflineConcurrentSocketJournalTests(unittest.TestCase):
    def test_concurrent_unique_nonces_reserve_only_one_scope(self):
        with tempfile.TemporaryDirectory() as directory:
            journal=os.path.join(directory,"claims.sqlite")
            replay=os.path.join(directory,"nonces.sqlite")
            OfflineRestartJournal(journal,create=True)
            OfflinePersistentReplayLedger(replay,create=True)
            count=12
            barrier=threading.Barrier(count)
            results=[None]*count
            errors=[]
            def client(index):
                server,peer=socket.socketpair(socket.AF_UNIX,socket.SOCK_STREAM)
                try:
                    payload=dict(operation="request_entry",requested_bot="daily",
                                 environment="mainnet",account=ACCOUNT,dex="",
                                 coin="SOL",nonce=f"parallel-{index}")
                    data=json.dumps(payload).encode("utf-8")
                    peer.sendall(struct.pack("!I",len(data))+data)
                    barrier.wait(timeout=10)
                    results[index]=handle_offline_journal_socket(
                        server,{os.getuid():("daily","mainnet",ACCOUNT)},
                        replay,journal)
                except Exception as exc:
                    errors.append(repr(exc))
                finally:
                    server.close()
                    peer.close()
            threads=[threading.Thread(target=client,args=(i,)) for i in range(count)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(timeout=15)
            self.assertFalse(any(thread.is_alive() for thread in threads))
            self.assertEqual(errors,[])
            self.assertEqual(results.count(("reserved_offline_only",False)),1)
            self.assertEqual(results.count(("hold",False)),count-1)
            claim=OfflineRestartJournal(journal).inspect(
                environment="mainnet",account=ACCOUNT,dex="",coin="SOL")
            self.assertIsNotNone(claim)
            self.assertEqual(claim[0],"daily")

if __name__=="__main__":
    unittest.main()
