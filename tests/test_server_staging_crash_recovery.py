"""Crash safety policy checks: purely in-memory offline simulations."""
import unittest
from server_staging_crash_recovery import OfflineCrashRecovery
from server_staging_control import Mode

SAFE = {
    "BOT_RUN_MODE": "offline",
    "ORDER_SUBMISSION_ENABLED": "false",
    "HL_TESTNET": "true",
    "SERVER_LIVE_TRADING_APPROVED": "false",
}


class CrashRecoveryTests(unittest.TestCase):
    def test_crash_stops_all_bots_and_restarts_offline(self):
        recovery = OfflineCrashRecovery()
        recovery.restart_offline(SAFE)
        self.assertEqual(recovery.crash()["mode"], "stopped")
        self.assertTrue(recovery.crashed)
        self.assertEqual(recovery.restart_offline(SAFE)["order_capable_processes_started"], 0)
        self.assertFalse(recovery.crashed)

    def test_unknown_intent_survives_simulated_crash_and_denies_restart(self):
        recovery = OfflineCrashRecovery()
        recovery.restart_offline(SAFE)
        recovery.observe_unknown_intent("daily:btc:1")
        recovery.crash()
        with self.assertRaises(RuntimeError):
            recovery.restart_offline(SAFE)
        self.assertEqual(recovery.control.mode, Mode.STOPPED)
        self.assertFalse(recovery.confirm_reconciled(
            "daily:btc:1", authoritative_order_final=False,
            authoritative_position_flat=True))
        self.assertFalse(recovery.confirm_reconciled(
            "daily:btc:1", authoritative_order_final=True,
            authoritative_position_flat=False))
        self.assertTrue(recovery.confirm_reconciled(
            "daily:btc:1", authoritative_order_final=True,
            authoritative_position_flat=True))
        self.assertEqual(recovery.restart_offline(SAFE)["mode"], "offline_preflight")

    def test_unsafe_restart_remains_stopped(self):
        recovery = OfflineCrashRecovery()
        recovery.crash()
        with self.assertRaises(Exception):
            recovery.restart_offline({**SAFE, "ORDER_SUBMISSION_ENABLED": "true"})
        self.assertEqual(recovery.control.mode, Mode.STOPPED)


if __name__ == "__main__":
    unittest.main()
