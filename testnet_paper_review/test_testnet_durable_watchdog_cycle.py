"""Offline durable watchdog integration tests; no API, signer or credentials."""
from dataclasses import replace
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch, Mock
from contextlib import redirect_stdout, redirect_stderr
from io import StringIO

from testnet_paper_review.test_offline_watchdog_receipt_bridge import flat
from testnet_paper_review.watchdog_incident_ledger import WatchdogLedger, WatchdogStateHold
from testnet_paper_review.testnet_durable_watchdog_cycle import run_cycle, main

class DurableWatchdogTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        with WatchdogLedger(self.root, initialize=True):
            pass

    def cycle(self, inspect=flat, times=(1,2)):
        return run_cycle(self.root, inspect=inspect, clock=Mock(side_effect=times))

    def test_flat_cycle_no_authority(self):
        result = self.cycle()
        self.assertEqual(result.outcome, "FLAT")
        self.assertIsNone(result.incident)
        self.assertFalse(result.needs_operator)
        self.assertFalse(result.may_trade)
        self.assertFalse(result.may_close)

    def test_unknown_ack_then_flat_remains_critical(self):
        result = self.cycle(lambda: replace(flat(), stage="UNKNOWN_ACK_OR_UNRESOLVED_ENTRY", needs_operator=True))
        self.assertEqual(result.incident, "UNKNOWN_ACK")
        result = self.cycle()
        self.assertEqual(result.incident, "UNKNOWN_ACK")
        self.assertTrue(result.needs_operator)

    def test_missing_receipt_latches(self):
        self.assertEqual(self.cycle(lambda: None).incident, "READ_FAILED")
        self.assertTrue(self.cycle().needs_operator)

    def test_read_exception_latches(self):
        self.assertEqual(self.cycle(Mock(side_effect=TimeoutError)).incident, "READ_FAILED")

    def test_stale_cycle_latches(self):
        self.assertEqual(self.cycle(times=(1,12)).incident, "STALE_OBSERVATION")

    def test_clock_reversal_latches(self):
        self.assertEqual(self.cycle(times=(2,1)).incident, "STALE_OBSERVATION")

    def test_interruption_leaves_pending_and_restart_latches(self):
        with self.assertRaises(KeyboardInterrupt):
            self.cycle(Mock(side_effect=KeyboardInterrupt))
        with WatchdogLedger(self.root) as ledger:
            self.assertEqual(ledger.view(), (1,None))
        self.assertEqual(self.cycle().incident, "INTERRUPTED_OR_COMPETING_WATCH")

    def test_bad_receipt_latches(self):
        self.assertEqual(self.cycle(lambda: replace(flat(), may_trade=True)).incident, "UNVERIFIED")

    def test_bracket_is_attention_not_authority(self):
        result = self.cycle(lambda: replace(flat(),stage="BRACKET_MATCHED_ONE_OBSERVATION",
            position_count=1,open_order_count=2,observed_bracket=True,needs_operator=True))
        self.assertEqual(result.outcome,"BRACKET_OBSERVED")
        self.assertTrue(result.needs_operator)
        self.assertFalse(result.may_trade)
        self.assertFalse(result.may_close)

    def test_missing_ledger_prevents_observation(self):
        (self.root / "watchdog-incidents.sqlite3").unlink()
        inspect = Mock()
        with self.assertRaises(WatchdogStateHold):
            self.cycle(inspect)
        inspect.assert_not_called()

    def test_cli_fails_closed(self):
        with patch("testnet_paper_review.testnet_durable_watchdog_cycle.run_cycle") as run:
            with redirect_stdout(StringIO()), redirect_stderr(StringIO()):
                self.assertEqual(main([]),2)
                run.assert_not_called()
                run.side_effect = RuntimeError("private diagnostic")
                self.assertEqual(main(["--read-only-cycle"]),2)

if __name__ == "__main__":
    unittest.main()
