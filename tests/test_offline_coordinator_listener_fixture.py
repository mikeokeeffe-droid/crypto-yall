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
            os.chmod(journal,0o600)
            os.chmod(replay,0o600)
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

    def test_disconnect_then_restart_holds_without_claim(self):
        with tempfile.TemporaryDirectory() as directory:
            journal=os.path.join(directory,"journal.sqlite")
            replay=os.path.join(directory,"replay.sqlite")
            path=os.path.join(directory,"coordinator.sock")
            OfflineRestartJournal(journal,create=True)
            OfflinePersistentReplayLedger(replay,create=True)
            os.chmod(journal,0o600)
            os.chmod(replay,0o600)
            allowed={os.getuid():("daily","mainnet",ACCOUNT)}
            for attempt in range(2):
                ready=threading.Event()
                results=[]
                def serve():
                    results.append(serve_offline_socket_once(
                        path,allowed,replay,journal,ready=ready))
                thread=threading.Thread(target=serve)
                thread.start()
                self.assertTrue(ready.wait(5))
                with socket.socket(socket.AF_UNIX,socket.SOCK_STREAM) as client:
                    client.connect(path)
                    if attempt==1:
                        client.sendall(struct.pack("!I",100)+b'{"operation":')
                thread.join(5)
                self.assertFalse(thread.is_alive())
                self.assertEqual(results,[("hold",False)])
                self.assertFalse(os.path.lexists(path))
            self.assertIsNone(OfflineRestartJournal(journal).inspect(
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
            os.chmod(journal,0o600)
            os.chmod(replay,0o600)
            with self.assertRaises(FileExistsError):
                serve_offline_socket_once(path,{os.getuid():("daily","mainnet",ACCOUNT)},
                                          replay,journal)
            with open(path) as handle:
                self.assertEqual(handle.read(),"preserve")

    def test_listener_socket_permissions_and_timeout_cleanup(self):
        with tempfile.TemporaryDirectory() as directory:
            journal=os.path.join(directory,"journal.sqlite")
            replay=os.path.join(directory,"replay.sqlite")
            path=os.path.join(directory,"coordinator.sock")
            OfflineRestartJournal(journal,create=True)
            OfflinePersistentReplayLedger(replay,create=True)
            os.chmod(journal,0o600)
            os.chmod(replay,0o600)
            ready=threading.Event()
            errors=[]
            def serve():
                try:
                    serve_offline_socket_once(
                        path,{os.getuid():("daily","mainnet",ACCOUNT)},
                        replay,journal,ready=ready,timeout=0.2)
                except socket.timeout:
                    errors.append("timeout")
            thread=threading.Thread(target=serve)
            thread.start()
            self.assertTrue(ready.wait(5))
            self.assertEqual(os.stat(path).st_mode & 0o777,0o600)
            thread.join(5)
            self.assertFalse(thread.is_alive())
            self.assertEqual(errors,["timeout"])
            self.assertFalse(os.path.lexists(path))
            self.assertIsNone(OfflineRestartJournal(journal).inspect(
                environment="mainnet",account=ACCOUNT,dex="",coin="SOL"))

    def test_world_writable_directory_denied_before_bind(self):
        with tempfile.TemporaryDirectory() as directory:
            unsafe=os.path.join(directory,"unsafe")
            os.mkdir(unsafe,0o777)
            os.chmod(unsafe,0o777)
            path=os.path.join(unsafe,"coordinator.sock")
            with self.assertRaises(PermissionError):
                serve_offline_socket_once(
                    path,{os.getuid():("daily","mainnet",ACCOUNT)},
                    os.path.join(directory,"missing-replay.sqlite"),
                    os.path.join(directory,"missing-journal.sqlite"))
            self.assertFalse(os.path.lexists(path))

    def test_duplicate_bot_identity_and_invalid_uids_denied(self):
        with tempfile.TemporaryDirectory() as directory:
            path=os.path.join(directory,"coordinator.sock")
            replay=os.path.join(directory,"missing-replay.sqlite")
            journal=os.path.join(directory,"missing-journal.sqlite")
            invalid=(
                {1001:("daily","mainnet",ACCOUNT),
                 1002:("daily","mainnet",ACCOUNT)},
                {"1001":("daily","mainnet",ACCOUNT)},
                {1001:("unknown","mainnet",ACCOUNT)},
                {1001:("daily","mainnet",ACCOUNT),1002:["intraday","mainnet",ACCOUNT]},
            )
            for mapping in invalid:
                with self.subTest(mapping=mapping):
                    with self.assertRaises(ValueError):
                        serve_offline_socket_once(path,mapping,replay,journal)
                    self.assertFalse(os.path.lexists(path))

    def test_shared_database_permissions_fail_before_socket_bind(self):
        with tempfile.TemporaryDirectory() as directory:
            journal=os.path.join(directory,"journal.sqlite")
            replay=os.path.join(directory,"replay.sqlite")
            path=os.path.join(directory,"coordinator.sock")
            OfflineRestartJournal(journal,create=True)
            OfflinePersistentReplayLedger(replay,create=True)
            os.chmod(journal,0o600)
            os.chmod(replay,0o644)
            with self.assertRaises(PermissionError):
                serve_offline_socket_once(path,{os.getuid():("daily","mainnet",ACCOUNT)},
                                          replay,journal)
            self.assertFalse(os.path.lexists(path))
            os.chmod(replay,0o600)
            os.chmod(journal,0o666)
            with self.assertRaises(PermissionError):
                serve_offline_socket_once(path,{os.getuid():("daily","mainnet",ACCOUNT)},
                                          replay,journal)
            self.assertFalse(os.path.lexists(path))

    def test_symlink_database_path_rejected_before_socket_bind(self):
        with tempfile.TemporaryDirectory() as directory:
            journal=os.path.join(directory,"journal.sqlite")
            replay=os.path.join(directory,"replay.sqlite")
            linked=os.path.join(directory,"journal-link.sqlite")
            path=os.path.join(directory,"coordinator.sock")
            OfflineRestartJournal(journal,create=True)
            OfflinePersistentReplayLedger(replay,create=True)
            os.chmod(journal,0o600)
            os.chmod(replay,0o600)
            os.symlink(journal,linked)
            with self.assertRaises(PermissionError):
                serve_offline_socket_once(
                    path,{os.getuid():("daily","mainnet",ACCOUNT)},
                    replay,linked)
            self.assertFalse(os.path.lexists(path))
            self.assertTrue(os.path.islink(linked))
            self.assertTrue(os.path.isfile(journal))

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
