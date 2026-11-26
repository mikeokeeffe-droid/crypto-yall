"""Offline test of irreversible emergency-close claim journal.

Creates ephemeral HOME-like location by patching module fixed path,
never uses production journal or access to a signer.
"""
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import testnet_paper_review.emergency_close_one_shot_journal as mod


class EmergencyJournalTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix="emergency-journal-test-")
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        os.chmod(self.root,0o700)
        self.path=str(self.root/"testnet-emergency-close.sqlite3")
        p=patch.object(mod,"JOURNAL_PATH",self.path)
        p.start()
        self.addCleanup(p.stop)

    def test_missing_and_no_overwrite(self):
        with self.assertRaises(mod.EmergencyJournalHold):
            mod.EmergencyCloseJournal()
        with mod.EmergencyCloseJournal(initialize=True) as j:
            self.assertIsNone(j.view())
        with self.assertRaises(mod.EmergencyJournalHold):
            mod.EmergencyCloseJournal(initialize=True)
        os.unlink(self.path)
        with self.assertRaises(mod.EmergencyJournalHold):
            mod.EmergencyCloseJournal()

    def test_persistent_replay_hold_after_restart_and_unknown_ack(self):
        with mod.EmergencyCloseJournal(initialize=True) as j:
            self.assertEqual(j.reserve(request_id="emergency-sol-00001",plan_hash="a"*64),
                             "EMERGENCY_CLAIM_SPENT_NO_RETRY")
        with mod.EmergencyCloseJournal() as j:
            self.assertEqual(j.view()[2],"RESERVED")
            with self.assertRaises(mod.EmergencyJournalHold):
                j.reserve(request_id="emergency-sol-00002",plan_hash="b"*64)
            j.note_ack(request_id="emergency-sol-00001",known_ack=False)
        with mod.EmergencyCloseJournal() as j:
            self.assertEqual(j.view()[2],"UNKNOWN_ACK")
            with self.assertRaises(mod.EmergencyJournalHold):
                j.reserve(request_id="emergency-sol-00003",plan_hash="b"*64)

    def test_competing_writers_and_known_ack_still_spent(self):
        with mod.EmergencyCloseJournal(initialize=True) as a:
            with mod.EmergencyCloseJournal() as b:
                a.reserve(request_id="emergency-sol-00001",plan_hash="a"*64)
                with self.assertRaises(mod.EmergencyJournalHold):
                    b.reserve(request_id="emergency-sol-00002",plan_hash="b"*64)
                a.note_ack(request_id="emergency-sol-00001",known_ack=True)
        with mod.EmergencyCloseJournal() as j:
            self.assertEqual(j.view()[2],"ACK_SEEN")
            with self.assertRaises(mod.EmergencyJournalHold):
                j.reserve(request_id="emergency-sol-00001",plan_hash="a"*64)

    def test_bad_permissions_and_corruption_hold(self):
        with mod.EmergencyCloseJournal(initialize=True):pass
        os.chmod(self.path,0o644)
        with self.assertRaises(mod.EmergencyJournalHold):
            mod.EmergencyCloseJournal()
        os.chmod(self.path,0o600)
        Path(self.path).write_bytes(b"bad sqlite")
        with self.assertRaises(mod.EmergencyJournalHold):
            mod.EmergencyCloseJournal()

    def test_private_parent_required(self):
        os.chmod(self.root,0o755)
        with self.assertRaises(mod.EmergencyJournalHold):
            mod.EmergencyCloseJournal(initialize=True)

if __name__=="__main__":
    unittest.main()
