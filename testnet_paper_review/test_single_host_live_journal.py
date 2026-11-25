"""Single-host persistent journal safety tests; NO exchange calls or keys."""
import os
from pathlib import Path
import tempfile
import unittest

from testnet_paper_review.single_host_live_journal import (
    SingleHostOneShotJournal, PersistentHold
)


class OneShotJournalTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(prefix="one-shot-review-")
        self.root=Path(self.tmp.name)
        os.chmod(self.root,0o700)
        self.path=self.root/"testnet-one-shot.sqlite3"

    def tearDown(self):
        self.tmp.cleanup()

    def initialize(self):
        return SingleHostOneShotJournal(self.path,initialize=True)

    def reserve(self,journal, request_id="manual-sol-000001"):
        return journal.reserve(request_id=request_id,
                               request_hash="a"*64,code_sha="b"*40)

    def test_missing_state_always_holds(self):
        with self.assertRaises(PersistentHold):
            SingleHostOneShotJournal(self.path)
        with self.initialize() as j:
            self.assertIsNone(j.view()["claim"])
        with self.assertRaises(PersistentHold):
            self.initialize()
        self.path.unlink()
        with self.assertRaises(PersistentHold):
            SingleHostOneShotJournal(self.path)

    def test_claim_persists_across_restart_and_replay(self):
        with self.initialize() as j:
            self.assertEqual(self.reserve(j),"RESERVED_NO_RETRY")
            with self.assertRaises(PersistentHold):
                self.reserve(j)
        with SingleHostOneShotJournal(self.path) as j:
            self.assertEqual(j.view()["claim"][0],"manual-sol-000001")
            with self.assertRaises(PersistentHold):
                self.reserve(j,"manual-sol-000002")
            self.assertEqual(j.report_response(request_id="manual-sol-000001",known_success=False),
                             "HOLD_UNTIL_INDEPENDENT_RECONCILIATION")
        with SingleHostOneShotJournal(self.path) as j:
            self.assertEqual(j.view()["claim"][3],"UNKNOWN_ACK")
            with self.assertRaises(PersistentHold):
                self.reserve(j,"manual-sol-000003")

    def test_emergency_freeze_persists(self):
        with self.initialize() as j:
            self.assertEqual(j.freeze(),"FROZEN_NO_MORE_ORDERS")
            with self.assertRaises(PersistentHold):
                self.reserve(j)
        with SingleHostOneShotJournal(self.path) as j:
            self.assertTrue(j.view()["frozen"])
            with self.assertRaises(PersistentHold):
                self.reserve(j)

    def test_two_connections_no_second_writer(self):
        with self.initialize() as first:
            with SingleHostOneShotJournal(self.path) as second:
                self.reserve(first)
                with self.assertRaises(PersistentHold):
                    self.reserve(second,"manual-sol-000002")

    def test_corruption_and_permissions_fail_closed(self):
        with self.initialize() as j:
            self.reserve(j)
        os.chmod(self.path,0o644)
        with self.assertRaises(PersistentHold):
            SingleHostOneShotJournal(self.path)
        os.chmod(self.path,0o600)
        self.path.write_bytes(b"invalid SQLite data")
        with self.assertRaises(PersistentHold):
            SingleHostOneShotJournal(self.path)

    def test_safety_requires_private_parent(self):
        os.chmod(self.root,0o755)
        with self.assertRaises(PersistentHold):
            self.initialize()

if __name__=="__main__":
    unittest.main()
