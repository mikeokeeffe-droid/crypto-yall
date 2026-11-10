"""Offline atomic socket bridge regression tests. No exchange or signer."""
import json
import os
import socket
import struct
import tempfile
import threading
import unittest
from offline_atomic_coordinator_fixture import OfflineAtomicCoordinator
from offline_atomic_socket_bridge_fixture import handle_offline_atomic_socket

ACCOUNT="0x"+"1"*40

@unittest.skipUnless(hasattr(socket,"SO_PEERCRED"),"Linux peer credentials required")
class OfflineAtomicSocketBridgeTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.db=os.path.join(self.temp.name,"atomic.sqlite")
        OfflineAtomicCoordinator(self.db,create=True)
        self.payload=dict(operation="request_entry",requested_bot="daily",
                          environment="mainnet",account=ACCOUNT,dex="",
                          coin="SOL",nonce="n1")

    def exchange(self,payload,allowed=None):
        path=os.path.join(self.temp.name,"socket")
        if os.path.lexists(path):
            os.unlink(path)
        with socket.socket(socket.AF_UNIX,socket.SOCK_STREAM) as listener:
            listener.bind(path)
            listener.listen(1)
            output=[]
            def server():
                conn,_=listener.accept()
                with conn:
                    output.append(handle_offline_atomic_socket(
                        conn,{os.getuid():("daily","mainnet",ACCOUNT)}
                        if allowed is None else allowed,self.db))
            worker=threading.Thread(target=server,daemon=True)
            worker.start()
            data=json.dumps(payload).encode("utf-8")
            with socket.socket(socket.AF_UNIX,socket.SOCK_STREAM) as client:
                client.connect(path)
                client.sendall(struct.pack("!I",len(data))+data)
            worker.join(timeout=5)
            self.assertFalse(worker.is_alive())
            return output[0]

    def test_atomic_claim_replay_and_new_nonce_hold(self):
        self.assertEqual(self.exchange(self.payload),("reserved_offline_only",False))
        self.assertEqual(self.exchange(self.payload),("hold",False))
        self.assertEqual(self.exchange(dict(self.payload,nonce="n2")),("hold",False))
        with OfflineAtomicCoordinator(self.db)._connect() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM claims").fetchone()[0],1)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM replay_nonces").fetchone()[0],1)

    def test_spoofed_bot_and_unknown_uid_hold(self):
        self.assertEqual(self.exchange(dict(self.payload,requested_bot="intraday")),
                         ("hold",False))
        self.assertEqual(self.exchange(self.payload,allowed={}),("hold",False))
        self.assertEqual(self.exchange(self.payload),("reserved_offline_only",False))

    def test_invalid_scope_does_not_burn_nonce(self):
        self.assertEqual(self.exchange(dict(self.payload,coin="bad!")),("hold",False))
        self.assertEqual(self.exchange(self.payload),("reserved_offline_only",False))

    def test_missing_database_holds_without_recreation(self):
        os.unlink(self.db)
        self.assertEqual(self.exchange(self.payload),("hold",False))
        self.assertFalse(os.path.exists(self.db))

if __name__=="__main__":
    unittest.main()
