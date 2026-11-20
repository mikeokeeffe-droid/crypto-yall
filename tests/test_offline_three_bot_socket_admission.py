"""Concurrent Daily/Intraday/Aggressive offline socket admission audit.

Same scope permits only one disposable reservation, regardless of bot.
No exchange SDK, signer, live secrets or trading.
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
BOTS=("daily","intraday","aggressive")

@unittest.skipUnless(hasattr(socket,"SO_PEERCRED") and hasattr(os,"getuid"),
                     "requires Linux SO_PEERCRED")
class OfflineThreeBotSocketAdmissionTests(unittest.TestCase):
    def test_three_bot_claims_same_scope_hold_except_one(self):
        with tempfile.TemporaryDirectory() as directory:
            journal=os.path.join(directory,"journal.sqlite")
            replay=os.path.join(directory,"replay.sqlite")
            OfflineRestartJournal(journal,create=True)
            OfflinePersistentReplayLedger(replay,create=True)
            barrier=threading.Barrier(len(BOTS))
            results={}
            errors=[]
            def attempt(bot):
                server,client=socket.socketpair(socket.AF_UNIX,socket.SOCK_STREAM)
                try:
                    request=dict(operation="request_entry",requested_bot=bot,
                                 environment="mainnet",account=ACCOUNT,
                                 dex="",coin="SOL",nonce="nonce-"+bot)
                    data=json.dumps(request).encode()
                    client.sendall(struct.pack("!I",len(data))+data)
                    barrier.wait(timeout=10)
                    results[bot]=handle_offline_journal_socket(
                        server,{os.getuid():(bot,"mainnet",ACCOUNT)},
                        replay,journal)
                except Exception as exc:
                    errors.append(str(exc))
                finally:
                    server.close()
                    client.close()
            threads=[threading.Thread(target=attempt,args=(bot,)) for bot in BOTS]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(timeout=15)
            self.assertFalse(any(thread.is_alive() for thread in threads))
            self.assertEqual(errors,[])
            self.assertEqual(list(results.values()).count(("reserved_offline_only",False)),1)
            self.assertEqual(list(results.values()).count(("hold",False)),2)
            claim=OfflineRestartJournal(journal).inspect(
                environment="mainnet",account=ACCOUNT,dex="",coin="SOL")
            self.assertIn(claim[0],BOTS)
            # Reopened journal must still reject all new entries to same scope.
            self.assertIsNone(OfflineRestartJournal(journal).reserve(
                bot="daily",environment="mainnet",account=ACCOUNT,dex="",coin="SOL"))

if __name__=="__main__":
    unittest.main()
