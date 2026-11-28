"""Offline Unix socket access and interrupted connection tests.

No trading, SDK, signer, journal or network service. These tests deliberately
use local disposable sockets and do not claim deployment isolation.
"""
import os
import socket
import tempfile
import threading
import unittest
from offline_unix_peer_identity_fixture import offline_socket_request

class OfflineSocketAccessTests(unittest.TestCase):
    def test_owner_only_socket_permissions(self):
        with tempfile.TemporaryDirectory() as directory:
            os.chmod(directory,0o700)
            path=os.path.join(directory,"coordinator.sock")
            with socket.socket(socket.AF_UNIX,socket.SOCK_STREAM) as listener:
                listener.bind(path)
                os.chmod(path,0o600)
                self.assertEqual(os.stat(path).st_mode & 0o777,0o600)
                self.assertEqual(os.stat(directory).st_mode & 0o777,0o700)

    @unittest.skipUnless(hasattr(socket,"SO_PEERCRED") and hasattr(os,"getuid"),
                         "requires Linux SO_PEERCRED")
    def test_disconnected_client_does_not_authorize_operation(self):
        with tempfile.TemporaryDirectory() as directory:
            path=os.path.join(directory,"coordinator.sock")
            with socket.socket(socket.AF_UNIX,socket.SOCK_STREAM) as listener:
                listener.bind(path)
                listener.listen(1)
                output=[]
                def serve():
                    connection,_=listener.accept()
                    with connection:
                        output.append(offline_socket_request(
                            connection,{os.getuid():("daily","mainnet","0x"+"1"*40)},
                            "daily"))
                        connection.settimeout(1)
                        output.append(connection.recv(1))
                worker=threading.Thread(target=serve)
                worker.start()
                with socket.socket(socket.AF_UNIX,socket.SOCK_STREAM) as client:
                    client.connect(path)
                worker.join(timeout=5)
                self.assertFalse(worker.is_alive())
                self.assertEqual(output,[("verified_identity_only",False),b""])

if __name__=="__main__":
    unittest.main()
