"""Disposable Linux distinct-UID credential and journal access audit.

Only runs with root in isolated CI/VM. No production paths, live keys, exchange
SDK or network. Verifies kernel file permissions, NOT production deployment.
"""
import os
import pwd
import subprocess
import sys
import tempfile
import unittest

@unittest.skipUnless(sys.platform.startswith("linux") and hasattr(os,"geteuid")
                     and os.geteuid()==0,
                     "requires disposable Linux root runner")
class OfflineCredentialUidIsolationTests(unittest.TestCase):
    def test_bot_uid_cannot_read_coordinator_private_files(self):
        candidates=[p for p in pwd.getpwall() if p.pw_uid>0 and p.pw_uid!=os.geteuid()]
        if not candidates:
            self.skipTest("no distinct non-root UID")
        bot=candidates[0]
        with tempfile.TemporaryDirectory() as root:
            os.chmod(root,0o711)
            private=os.path.join(root,"coordinator")
            os.mkdir(private,0o700)
            secret=os.path.join(private,"fixture.key")
            journal=os.path.join(private,"journal.sqlite")
            for path in (secret,journal):
                with open(path,"wb") as stream:
                    stream.write(b"disposable test fixture only")
                os.chmod(path,0o600)
            def drop():
                os.setgroups([])
                os.setgid(bot.pw_gid)
                os.setuid(bot.pw_uid)
            code=("import pathlib,sys; "
                  "pathlib.Path(sys.argv[1]).read_bytes()")
            for path in (secret,journal):
                result=subprocess.run([sys.executable,"-c",code,path],
                                      preexec_fn=drop,capture_output=True,
                                      text=True,timeout=5)
                self.assertNotEqual(result.returncode,0)
                self.assertIn("PermissionError",result.stderr)
                self.assertEqual(open(path,"rb").read(),
                                 b"disposable test fixture only")

if __name__=="__main__":
    unittest.main()
