"""Offline watchdog incident ledger tests; only disposable local state."""
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest

from testnet_paper_review.watchdog_incident_ledger import (
    WatchdogLedger, WatchdogStateHold
)

class WatchdogLedgerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="watchdog-ledger-")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        os.chmod(self.root, 0o700)
        self.path = self.root / "watchdog-incidents.sqlite3"

    def initialize(self):
        return WatchdogLedger(self.root, initialize=True)

    def test_explicit_initialization_and_clean_restart(self):
        with self.assertRaises(WatchdogStateHold):
            WatchdogLedger(self.root)
        self.assertFalse(self.path.exists())
        with self.initialize() as ledger:
            self.assertEqual(ledger.view(), (0,None))
            self.assertIsNone(ledger.begin())
            self.assertIsNone(ledger.finish("FLAT"))
        with WatchdogLedger(self.root) as ledger:
            self.assertEqual(ledger.view(), (0,None))
        with self.assertRaises(WatchdogStateHold):
            self.initialize()

    def test_critical_incident_persists_after_restart_and_flat(self):
        with self.initialize() as ledger:
            ledger.begin()
            self.assertEqual(ledger.finish("MISSING_STOP"), "MISSING_STOP")
        with WatchdogLedger(self.root) as ledger:
            self.assertEqual(ledger.begin(), "MISSING_STOP")
            self.assertEqual(ledger.finish("FLAT"), "MISSING_STOP")
        with WatchdogLedger(self.root) as ledger:
            self.assertEqual(ledger.view(), (0,"MISSING_STOP"))

    def test_interrupted_read_is_latched(self):
        with self.initialize() as ledger:
            ledger.begin()
        with WatchdogLedger(self.root) as ledger:
            self.assertEqual(ledger.begin(), "INTERRUPTED_OR_COMPETING_WATCH")
            self.assertEqual(ledger.finish("FLAT"), "INTERRUPTED_OR_COMPETING_WATCH")

    def test_competing_reads_cannot_clear_incident(self):
        with self.initialize() as first:
            with WatchdogLedger(self.root) as second:
                first.begin()
                self.assertEqual(second.begin(), "INTERRUPTED_OR_COMPETING_WATCH")
                self.assertEqual(first.finish("FLAT"), "INTERRUPTED_OR_COMPETING_WATCH")
                self.assertEqual(second.finish("FLAT"), "INTERRUPTED_OR_COMPETING_WATCH")

    def test_missing_ledger_does_not_auto_recreate(self):
        with self.initialize() as ledger:
            ledger.begin()
            ledger.finish("READ_FAILED")
        self.path.unlink()
        with self.assertRaises(WatchdogStateHold):
            WatchdogLedger(self.root)
        self.assertFalse(self.path.exists())

    def test_missing_control_row_cannot_be_repaired_silently(self):
        with self.initialize():
            pass
        with sqlite3.connect(self.path) as db:
            db.execute("DELETE FROM watchdog")
        with self.assertRaises(WatchdogStateHold):
            WatchdogLedger(self.root)

    def test_malformed_outcome_and_unexpected_completion_hold(self):
        with self.initialize() as ledger:
            self.assertEqual(ledger.finish("FLAT"), "UNEXPECTED_COMPLETION")
        with WatchdogLedger(self.root) as ledger:
            ledger.begin()
            self.assertEqual(ledger.finish("INVALID"), "UNEXPECTED_COMPLETION")

    def test_permissions_and_corruption_hold(self):
        with self.initialize():
            pass
        os.chmod(self.path, 0o644)
        with self.assertRaises(WatchdogStateHold):
            WatchdogLedger(self.root)
        os.chmod(self.path, 0o600)
        self.path.write_bytes(b"not sqlite")
        with self.assertRaises(WatchdogStateHold):
            WatchdogLedger(self.root)

if __name__ == "__main__":
    unittest.main()
