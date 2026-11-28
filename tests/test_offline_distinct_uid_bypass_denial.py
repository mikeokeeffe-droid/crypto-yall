"""Offline distinct-UID attempted journal write and credential theft audit.

Run only as root on disposable Linux CI. This checks OS permissions, not
authenticated IPC or real deployment isolation. No production secrets/orders.
"""
import os
import pwd
import sqlite3
import subprocess
import sys
import tempfile
import unittest

@unittest.skipUnless(sys.platform.startswith("linux") and hasattr(os,"geteuid")
                     and os.geteuid()==0,
                     "requires disposable Linux root runner")
class DistinctUidBypassDenialTests(unittest.TestCase):
    def test_other_uid_cannot_read_key_or_modify_real_disposable_sqlite(self):
        from offline_sender_restart_journal import OfflineRestartJournal
        users=[p for p in pwd.getpwall() if p.pw_uid>0 and p.pw_uid!=os.geteuid()]
        if not users:
            self.skipTest("no distinct non-root UID")
        bot=users[0]
        with tempfile.TemporaryDirectory() as root:
            os.chmod(root,0o711)
            private=os.path.join(root,"coordinator")
            os.mkdir(private,0o700)
            key=os.path.join(private,"fixture.key")
            with open(key,"wb") as stream:
                stream.write(b"offline-disposable-test-key")
            os.chmod(key,0o600)
            db=os.path.join(private,"claims.sqlite")
            OfflineRestartJournal(db,create=True)
            os.chmod(db,0o600)
            def drop():
                os.setgroups([])
                os.setgid(bot.pw_gid)
                os.setuid(bot.pw_uid)
            attempts=[
                ("import pathlib,sys; pathlib.Path(sys.argv[1]).read_bytes()",key),
                ("import sqlite3,sys; sqlite3.connect('file:'+sys.argv[1]+'?mode=rw',uri=True).execute('CREATE TABLE bypass(x)')",db),
            ]
            for code,path in attempts:
                result=subprocess.run([sys.executable,"-c",code,path],
                                      preexec_fn=drop,capture_output=True,
                                      text=True,timeout=5)
                self.assertNotEqual(result.returncode,0,result.stdout)
                self.assertTrue("PermissionError" in result.stderr or
                                "unable to open database file" in result.stderr,
                                result.stderr)
            self.assertEqual(open(key,"rb").read(),b"offline-disposable-test-key")
            with sqlite3.connect(db) as connection:
                self.assertIsNone(connection.execute(
                    "SELECT name FROM sqlite_master WHERE name='bypass'").fetchone())

if __name__=="__main__":
    unittest.main()
