"""Offline framed Unix socket protocol tests; identity-only, no trading."""
import json
import os
import socket
import struct
import tempfile
import threading
import unittest
from offline_framed_unix_coordinator_fixture import (
    MAX_FRAME,handle_offline_framed_connection)

ACCOUNT="0x"+"1"*40
VALID=dict(operation="request_entry",requested_bot="daily",
           environment="mainnet",account=ACCOUNT)

@unittest.skipUnless(hasattr(socket,"SO_PEERCRED") and hasattr(os,"getuid"),
                     "requires Linux SO_PEERCRED")
class OfflineFramedSocketTests(unittest.TestCase):
    def exchange(self,wire,allowed=None):
        with tempfile.TemporaryDirectory() as directory:
            path=os.path.join(directory,"coordinator.sock")
            with socket.socket(socket.AF_UNIX,socket.SOCK_STREAM) as server:
                server.bind(path)
                server.listen(1)
                output=[]
                def worker():
                    connection,_=server.accept()
                    with connection:
                        output.append(handle_offline_framed_connection(
                            connection,{os.getuid():("daily","mainnet",ACCOUNT)}
                            if allowed is None else allowed))
                thread=threading.Thread(target=worker,daemon=True)
                thread.start()
                with socket.socket(socket.AF_UNIX,socket.SOCK_STREAM) as client:
                    client.connect(path)
                    if wire:
                        client.sendall(wire)
                thread.join(timeout=5)
                self.assertFalse(thread.is_alive())
                return output[0]
    def frame(self,payload):
        data=json.dumps(payload).encode()
        return struct.pack("!I",len(data))+data

    def test_valid_scope_only_verifies_identity_without_authority(self):
        self.assertEqual(self.exchange(self.frame(VALID)),
                         ("verified_identity_only",False))
    def test_spoofed_bot_and_wrong_scope_hold(self):
        for changed in (dict(VALID,requested_bot="intraday"),
                        dict(VALID,environment="testnet"),
                        dict(VALID,account="0x"+"2"*40),
                        dict(VALID,operation="request_close"),
                        dict(VALID,operation="request_dispatch")):
            with self.subTest(changed=changed):
                self.assertEqual(self.exchange(self.frame(changed)),("hold",False))
    def test_empty_truncated_oversized_and_malformed_hold(self):
        for wire in (b"",b"\x00\x00",struct.pack("!I",MAX_FRAME+1),
                     struct.pack("!I",10)+b"{}",struct.pack("!I",0),
                     struct.pack("!I",1)+b"{",self.frame({"operation":"request_entry"})):
            with self.subTest(wire=wire):
                self.assertEqual(self.exchange(wire),("hold",False))
    def test_unknown_uid_holds(self):
        self.assertEqual(self.exchange(self.frame(VALID),allowed={}),("hold",False))

if __name__=="__main__":
    unittest.main()
