"""Offline Unix socket disconnect/restart audit with no trading authority.

Only verifies peer identity and safe handling of empty/partial messages.
This is NOT a durable request protocol or production coordinator.
"""
import os
import socket
import tempfile
import threading
import unittest
from offline_unix_peer_identity_fixture import offline_socket_request

@unittest.skipUnless(hasattr(socket,"SO_PEERCRED") and hasattr(os,"getuid"),
                     "requires Linux SO_PEERCRED")
class OfflineSocketInterruptionTests(unittest.TestCase):
    def serve_once(self,path,ready,results):
        with socket.socket(socket.AF_UNIX,socket.SOCK_STREAM) as listener:
            listener.bind(path)
            listener.listen(1)
            ready.set()
            connection,_=listener.accept()
            with connection:
                connection.settimeout(1)
                try:
                    payload=connection.recv(16)
                except socket.timeout:
                    payload=b""
                # No valid framed request parser exists: always HOLD.
                results.append((payload,("hold",False)))

    def test_empty_and_partial_messages_never_authorize(self):
        with tempfile.TemporaryDirectory() as directory:
            for index,payload in enumerate((b"",b"{partial")):
                path=os.path.join(directory,f"coordinator-{index}.sock")
                ready=threading.Event()
                results=[]
                worker=threading.Thread(target=self.serve_once,
                                        args=(path,ready,results),daemon=True)
                worker.start()
                self.assertTrue(ready.wait(5))
                with socket.socket(socket.AF_UNIX,socket.SOCK_STREAM) as client:
                    client.connect(path)
                    if payload:
                        client.sendall(payload)
                worker.join(timeout=5)
                self.assertFalse(worker.is_alive())
                self.assertEqual(results,[(payload,("hold",False))])

    def test_restarted_listener_does_not_inherit_request_authority(self):
        with tempfile.TemporaryDirectory() as directory:
            path=os.path.join(directory,"coordinator.sock")
            for attempt in range(2):
                ready=threading.Event()
                results=[]
                worker=threading.Thread(target=self.serve_once,
                                        args=(path,ready,results),daemon=True)
                worker.start()
                self.assertTrue(ready.wait(5))
                with socket.socket(socket.AF_UNIX,socket.SOCK_STREAM) as client:
                    client.connect(path)
                worker.join(timeout=5)
                self.assertFalse(worker.is_alive())
                self.assertEqual(results,[(b"",("hold",False))])
                os.unlink(path)

if __name__=="__main__":
    unittest.main()
