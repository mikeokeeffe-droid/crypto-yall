"""Non-production distinct-UID journal access test (Linux/POSIX, root only).

Run only in a disposable test VM/container as root. It uses local child
processes and temporary files; never production paths, network or trading.
Ordinary CI users skip this test rather than claiming UID isolation passed.
"""
import os
import pwd
import stat
import subprocess
import sys
import tempfile
import unittest
from offline_sender_restart_journal import OfflineRestartJournal

@unittest.skipUnless(
    sys.platform.startswith("linux") and hasattr(os,"geteuid")
    and os.geteuid()==0,
    "requires disposable Linux root test environment with distinct UIDs")
class DistinctUidJournalIsolation(unittest.TestCase):
    def test_other_uid_cannot_open_owner_only_journal(self):
        candidates=[entry for entry in pwd.getpwall()
                    if entry.pw_uid not in (0,os.geteuid()) and entry.pw_uid>0]
        if not candidates:
            self.skipTest("no non-root UID available")
        other=candidates[0]
        with tempfile.TemporaryDirectory() as root:
            os.chmod(root,0o700)
            path=os.path.join(root,"claims.sqlite")
            OfflineRestartJournal(path,create=True)
            os.chmod(path,0o600)
            self.assertEqual(stat.S_IMODE(os.stat(path).st_mode),0o600)
            code=("import sqlite3,sys; "
                  "sqlite3.connect('file:'+sys.argv[1]+'?mode=rw',uri=True)")
            def drop_privileges():
                os.setgroups([])
                os.setgid(other.pw_gid)
                os.setuid(other.pw_uid)
            result=subprocess.run(
                [sys.executable,"-c",code,path],
                capture_output=True,text=True,timeout=5,
                preexec_fn=drop_privileges,check=False)
            self.assertNotEqual(result.returncode,0)
            self.assertTrue(
                "unable to open database file" in result.stderr
                or "permission denied" in result.stderr.lower(),
                result.stderr)
            # The owner still has access; the denial must not be a bad DB.
            self.assertIsNotNone(OfflineRestartJournal(path))

if __name__=="__main__":
    unittest.main()
