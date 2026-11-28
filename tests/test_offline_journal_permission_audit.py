"""Offline Unix journal permission audit (not an OS-identity integration test).

Checks filesystem mode invariants only. It cannot establish that separate
bot workloads lack access: that requires distinct real UIDs and deployment ACLs.
No exchange SDK, secrets, network or production filesystem paths.
"""
import os
import stat
import tempfile
import unittest
from offline_sender_restart_journal import OfflineRestartJournal

class OfflineJournalPermissionAudit(unittest.TestCase):
    @unittest.skipUnless(os.name=="posix","POSIX permission semantics required")
    def test_world_or_group_readable_journal_is_not_isolated(self):
        with tempfile.TemporaryDirectory() as root:
            path=os.path.join(root,"claims.sqlite")
            OfflineRestartJournal(path,create=True)
            os.chmod(path,0o644)
            mode=stat.S_IMODE(os.stat(path).st_mode)
            self.assertTrue(mode & (stat.S_IRGRP|stat.S_IROTH))
            # Deliberately documents a bad mode; no security guarantee.

    @unittest.skipUnless(os.name=="posix","POSIX permission semantics required")
    def test_owner_only_mode_does_not_isolate_same_uid(self):
        with tempfile.TemporaryDirectory() as root:
            path=os.path.join(root,"claims.sqlite")
            OfflineRestartJournal(path,create=True)
            os.chmod(path,0o600)
            self.assertEqual(stat.S_IMODE(os.stat(path).st_mode),0o600)
            # Same UID can still reopen it: chmod 0600 is insufficient.
            reopened=OfflineRestartJournal(path)
            claim=reopened.reserve(bot="intraday",environment="mainnet",
                account="0x"+"1"*40,dex="",coin="SOL")
            self.assertIsNotNone(claim)

    @unittest.skipUnless(os.name=="posix","POSIX permission semantics required")
    def test_parent_directory_mode_is_part_of_isolation(self):
        with tempfile.TemporaryDirectory() as root:
            os.chmod(root,0o700)
            self.assertEqual(stat.S_IMODE(os.stat(root).st_mode),0o700)
            path=os.path.join(root,"claims.sqlite")
            OfflineRestartJournal(path,create=True)
            os.chmod(path,0o600)
            self.assertEqual(stat.S_IMODE(os.stat(path).st_mode),0o600)
            self.assertIsNotNone(OfflineRestartJournal(path))
            # Distinct-UID denial must still be verified in a separate test.

if __name__=="__main__":
    unittest.main()
