"""Disposable Linux root-only cross-UID SO_PEERCRED test.

A subprocess drops privileges and connects to a Unix socket. The server
checks kernel UID rather than a client-asserted bot name. No exchange,
signer, journal mutation, network listener, or live order capability.
"""
import os
import pwd
import socket
import subprocess
import sys
import tempfile
import threading
import unittest
from offline_unix_peer_identity_fixture import offline_socket_request

@unittest.skipUnless(sys.platform.startswith("linux") and hasattr(os,"geteuid")
                     and os.geteuid()==0 and hasattr(socket,"SO_PEERCRED"),
                     "requires disposable Linux root runner and SO_PEERCRED")
class OfflineDistinctUidSocketTests(unittest.TestCase):
    def test_distinct_uid_verified_and_spoofed_name_denied(self):
        candidates=[p for p in pwd.getpwall() if p.pw_uid>0]
        if not candidates:
            self.skipTest("no nonroot UID")
        bot=candidates[0]
        with tempfile.TemporaryDirectory() as directory:
            os.chmod(directory,0o711)
            path=os.path.join(directory,"coordinator.sock")
            listener=socket.socket(socket.AF_UNIX,socket.SOCK_STREAM)
            listener.bind(path)
            os.chmod(path,0o666)  # intentionally accessible for identity audit
            listener.listen(2)
            results=[]
            allowed={bot.pw_uid:("daily","mainnet","0x"+"1"*40)}
            def server():
                try:
                    for claimed in ("daily","intraday"):
                        connection,_=listener.accept()
                        with connection:
                            results.append(offline_socket_request(
                                connection,allowed,claimed))
                finally:
                    listener.close()
            thread=threading.Thread(target=server,daemon=True)
            thread.start()
            def drop():
                os.setgroups([])
                os.setgid(bot.pw_gid)
                os.setuid(bot.pw_uid)
            code=("import socket,sys; s=socket.socket(socket.AF_UNIX);"
                  "s.connect(sys.argv[1]); s.close()")
            for _ in range(2):
                completed=subprocess.run([sys.executable,"-c",code,path],
                                         preexec_fn=drop,capture_output=True,
                                         text=True,timeout=5)
                self.assertEqual(completed.returncode,0,completed.stderr)
            thread.join(timeout=5)
            self.assertFalse(thread.is_alive())
            self.assertEqual(results,[("verified_identity_only",False),
                                      ("hold",False)])

if __name__=="__main__":
    unittest.main()
