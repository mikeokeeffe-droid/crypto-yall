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
        self.coordinator=OfflineAtomicCoordinator(self.db,create=True)
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
                        if allowed is None else allowed,self.coordinator))
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

    def test_restart_preserves_replay_and_scope_claim(self):
        self.assertEqual(self.exchange(self.payload),("reserved_offline_only",False))
        # Each exchange constructs a fresh coordinator, as after a restart.
        self.assertEqual(self.exchange(self.payload),("hold",False))
        self.assertEqual(self.exchange(dict(self.payload,nonce="after-restart")),
                         ("hold",False))
        self.assertEqual(OfflineAtomicCoordinator(self.db).inspect(
            environment="mainnet",account=ACCOUNT,dex="",coin="SOL")[0],"daily")

    def test_simultaneous_socket_requests_only_one_claim(self):
        import concurrent.futures
        # Use distinct socket paths: each handler is a separate offline
        # connection, but all transactions compete for the same DB scope.
        def attempt(index):
            path=os.path.join(self.temp.name,"parallel-"+str(index)+".sock")
            with socket.socket(socket.AF_UNIX,socket.SOCK_STREAM) as listener:
                listener.bind(path)
                listener.listen(1)
                output=[]
                def server():
                    conn,_=listener.accept()
                    with conn:
                        output.append(handle_offline_atomic_socket(
                            conn,{os.getuid():("daily","mainnet",ACCOUNT)},self.coordinator))
                worker=threading.Thread(target=server,daemon=True)
                worker.start()
                payload=dict(self.payload,nonce="parallel-"+str(index))
                data=json.dumps(payload).encode()
                with socket.socket(socket.AF_UNIX,socket.SOCK_STREAM) as client:
                    client.connect(path)
                    client.sendall(struct.pack("!I",len(data))+data)
                worker.join(timeout=10)
                self.assertFalse(worker.is_alive())
                return output[0]
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            results=list(pool.map(attempt,range(12)))
        self.assertEqual(results.count(("reserved_offline_only",False)),1)
        self.assertEqual(results.count(("hold",False)),11)
        with OfflineAtomicCoordinator(self.db)._connect() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM claims").fetchone()[0],1)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM replay_nonces").fetchone()[0],1)

    def test_lost_response_after_commit_retry_holds(self):
        # Client closes immediately after sending: there is no response
        # channel and no acknowledgement, even if the reservation commits.
        path=os.path.join(self.temp.name,"lost-ack.sock")
        with socket.socket(socket.AF_UNIX,socket.SOCK_STREAM) as listener:
            listener.bind(path)
            listener.listen(1)
            output=[]
            def server():
                conn,_=listener.accept()
                with conn:
                    output.append(handle_offline_atomic_socket(
                        conn,{os.getuid():("daily","mainnet",ACCOUNT)},self.coordinator))
            worker=threading.Thread(target=server,daemon=True)
            worker.start()
            data=json.dumps(self.payload).encode("utf-8")
            with socket.socket(socket.AF_UNIX,socket.SOCK_STREAM) as client:
                client.connect(path)
                client.sendall(struct.pack("!I",len(data))+data)
                # Close without waiting for or reading any reply.
            worker.join(timeout=5)
            self.assertFalse(worker.is_alive())
            self.assertEqual(output,[("reserved_offline_only",False)])
        self.assertEqual(self.exchange(self.payload),("hold",False))
        self.assertEqual(self.exchange(dict(self.payload,nonce="lost-ack-retry")),
                         ("hold",False))
        with OfflineAtomicCoordinator(self.db)._connect() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM claims").fetchone()[0],1)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM replay_nonces").fetchone()[0],1)

    def test_malformed_frames_do_not_consume_state(self):
        cases=[
            b"",
            struct.pack("!I",0),
            struct.pack("!I",4097),
            struct.pack("!I",9)+b"{}",
            struct.pack("!I",3)+b"bad",
            struct.pack("!I",2)+b"[]",
        ]
        for index,wire in enumerate(cases):
            with self.subTest(index=index):
                path=os.path.join(self.temp.name,"bad-"+str(index)+".sock")
                with socket.socket(socket.AF_UNIX,socket.SOCK_STREAM) as listener:
                    listener.bind(path)
                    listener.listen(1)
                    output=[]
                    def server():
                        conn,_=listener.accept()
                        with conn:
                            output.append(handle_offline_atomic_socket(
                                conn,{os.getuid():("daily","mainnet",ACCOUNT)},self.coordinator))
                    worker=threading.Thread(target=server,daemon=True)
                    worker.start()
                    with socket.socket(socket.AF_UNIX,socket.SOCK_STREAM) as client:
                        client.connect(path)
                        if wire:
                            client.sendall(wire)
                        client.shutdown(socket.SHUT_WR)
                    worker.join(timeout=5)
                    self.assertFalse(worker.is_alive())
                    self.assertEqual(output,[("hold",False)])
        with OfflineAtomicCoordinator(self.db)._connect() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM claims").fetchone()[0],0)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM replay_nonces").fetchone()[0],0)
        self.assertEqual(self.exchange(self.payload),("reserved_offline_only",False))

    def test_invalid_payload_shapes_never_write_state(self):
        cases=[
            dict(self.payload,unexpected="field"),
            {key:value for key,value in self.payload.items() if key!="nonce"},
            dict(self.payload,nonce=7),
            dict(self.payload,nonce=""),
            dict(self.payload,nonce="x"*129),
            dict(self.payload,operation="cancel_order"),
            dict(self.payload,requested_bot="aggressive"),
            dict(self.payload,account="0x"+"2"*40),
            dict(self.payload,environment="testnet"),
            dict(self.payload,coin=[]),
        ]
        for index,payload in enumerate(cases):
            with self.subTest(index=index):
                self.assertEqual(self.exchange(payload),("hold",False))
        with OfflineAtomicCoordinator(self.db)._connect() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM claims").fetchone()[0],0)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM replay_nonces").fetchone()[0],0)
        self.assertEqual(self.exchange(self.payload),("reserved_offline_only",False))

    def test_corrupt_database_holds_without_recreation(self):
        with open(self.db,"wb") as file:
            file.write(b"not a sqlite database")
        self.assertEqual(self.exchange(self.payload),("hold",False))
        with open(self.db,"rb") as file:
            self.assertEqual(file.read(),b"not a sqlite database")

    def test_replaced_database_is_rejected_by_pinned_coordinator(self):
        replacement=os.path.join(self.temp.name,"replacement.sqlite")
        OfflineAtomicCoordinator(replacement,create=True)
        os.replace(replacement,self.db)
        self.assertEqual(self.exchange(self.payload),("hold",False))
        with OfflineAtomicCoordinator(self.db)._connect() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM claims").fetchone()[0],0)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM replay_nonces").fetchone()[0],0)

    def test_replaced_database_parent_rejected_by_pinned_socket(self):
        protected=os.path.join(self.temp.name,"protected")
        os.mkdir(protected,0o700)
        db=os.path.join(protected,"state.sqlite")
        coordinator=OfflineAtomicCoordinator(db,create=True)
        old_coordinator=self.coordinator
        self.coordinator=coordinator
        try:
            moved=os.path.join(self.temp.name,"moved-parent")
            os.rename(protected,moved)
            os.mkdir(protected,0o700)
            OfflineAtomicCoordinator(db,create=True)
            self.assertEqual(self.exchange(self.payload),("hold",False))
            with OfflineAtomicCoordinator(db)._connect() as opened:
                self.assertEqual(opened.execute(
                    "SELECT COUNT(*) FROM claims").fetchone()[0],0)
                self.assertEqual(opened.execute(
                    "SELECT COUNT(*) FROM replay_nonces").fetchone()[0],0)
        finally:
            self.coordinator=old_coordinator

    def test_symlink_replacement_rejected_by_pinned_socket(self):
        original=os.path.join(self.temp.name,"original.sqlite")
        os.rename(self.db,original)
        os.symlink(original,self.db)
        self.assertEqual(self.exchange(self.payload),("hold",False))
        self.assertTrue(os.path.islink(self.db))
        with OfflineAtomicCoordinator(original)._connect() as opened:
            self.assertEqual(opened.execute(
                "SELECT COUNT(*) FROM claims").fetchone()[0],0)
            self.assertEqual(opened.execute(
                "SELECT COUNT(*) FROM replay_nonces").fetchone()[0],0)

    def test_database_lock_timeout_holds_without_state_write(self):
        import sqlite3
        with sqlite3.connect(self.db,timeout=1,isolation_level=None) as locked:
            locked.execute("BEGIN EXCLUSIVE")
            self.assertEqual(self.exchange(self.payload),("hold",False))
            locked.rollback()
        with OfflineAtomicCoordinator(self.db)._connect() as opened:
            self.assertEqual(opened.execute(
                "SELECT COUNT(*) FROM claims").fetchone()[0],0)
            self.assertEqual(opened.execute(
                "SELECT COUNT(*) FROM replay_nonces").fetchone()[0],0)
        self.assertEqual(self.exchange(self.payload),("reserved_offline_only",False))

    def test_missing_database_holds_without_recreation(self):
        os.unlink(self.db)
        self.assertEqual(self.exchange(self.payload),("hold",False))
        self.assertFalse(os.path.exists(self.db))

if __name__=="__main__":
    unittest.main()
