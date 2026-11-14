"""Offline Linux Unix socket tests with real kernel peer credentials."""
import os
import socket
import tempfile
import threading
import unittest
from offline_unix_peer_identity_fixture import (
    offline_peer_identity,offline_socket_request)

@unittest.skipUnless(hasattr(socket,"SO_PEERCRED") and hasattr(os,"getuid"),
                     "requires Linux SO_PEERCRED")
class OfflineUnixPeerIdentityTests(unittest.TestCase):
    def exchange(self,allowed,claimed):
        with tempfile.TemporaryDirectory() as temp:
            path=os.path.join(temp,"peer.sock")
            listener=socket.socket(socket.AF_UNIX,socket.SOCK_STREAM)
            listener.bind(path)
            listener.listen(1)
            output=[]
            def server():
                try:
                    connection,_=listener.accept()
                    with connection:
                        output.append(offline_socket_request(connection,allowed,claimed))
                finally:
                    listener.close()
            thread=threading.Thread(target=server)
            thread.start()
            with socket.socket(socket.AF_UNIX,socket.SOCK_STREAM) as client:
                client.connect(path)
            thread.join(timeout=5)
            self.assertFalse(thread.is_alive())
            return output[0]

    def test_kernel_uid_maps_to_expected_bot_only(self):
        allowed={os.getuid():("daily","mainnet","0x"+"1"*40)}
        self.assertEqual(self.exchange(allowed,"daily"),
                         ("verified_identity_only",False))
        self.assertEqual(self.exchange(allowed,"intraday"),("hold",False))

    def test_unrecognized_uid_fails_closed(self):
        self.assertEqual(self.exchange({},"daily"),("hold",False))

    def test_identity_never_grants_order_authority(self):
        allowed={os.getuid():("daily","mainnet","0x"+"1"*40)}
        self.assertFalse(self.exchange(allowed,"daily")[1])

if __name__=="__main__":
    unittest.main()
