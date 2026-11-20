"""Root-only disposable Linux socket access denial audit.

Uses a separate nonroot UID and a protected Unix socket. No production paths,
trading credentials, exchange SDK or live orders.
"""
import os
import pwd
import socket
import subprocess
import sys
import tempfile
import unittest

@unittest.skipUnless(sys.platform.startswith("linux") and hasattr(os,"geteuid")
                     and os.geteuid()==0,
                     "requires disposable Linux root runner")
class OfflineDistinctUidSocketPermissionTests(unittest.TestCase):
    def test_unauthorized_uid_cannot_connect_to_protected_socket(self):
        users=[entry for entry in pwd.getpwall() if entry.pw_uid>0]
        if not users:
            self.skipTest("no nonroot UID")
        bot=users[0]
        with tempfile.TemporaryDirectory() as root:
            os.chmod(root,0o711)
            private=os.path.join(root,"coordinator")
            os.mkdir(private,0o700)
            path=os.path.join(private,"service.sock")
            with socket.socket(socket.AF_UNIX,socket.SOCK_STREAM) as server:
                server.bind(path)
                os.chmod(path,0o600)
                server.listen(1)
                def drop():
                    os.setgroups([])
                    os.setgid(bot.pw_gid)
                    os.setuid(bot.pw_uid)
                code=("import socket,sys; s=socket.socket(socket.AF_UNIX);"
                      "s.connect(sys.argv[1])")
                result=subprocess.run([sys.executable,"-c",code,path],
                                      preexec_fn=drop,capture_output=True,
                                      text=True,timeout=5)
                self.assertNotEqual(result.returncode,0)
                self.assertIn("PermissionError",result.stderr)
                server.settimeout(0.2)
                with self.assertRaises(socket.timeout):
                    server.accept()

if __name__=="__main__":
    unittest.main()
