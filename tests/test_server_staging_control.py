"""Regression tests for offline-only three-bot startup/shutdown plan."""
import unittest
from server_staging_control import OfflineServerControl, Mode

SAFE = {
    "BOT_RUN_MODE": "offline",
    "ORDER_SUBMISSION_ENABLED": "false",
    "HL_TESTNET": "true",
    "SERVER_LIVE_TRADING_APPROVED": "false",
}


class ServerControlTests(unittest.TestCase):
    def test_three_bot_start_stop_restart_does_not_launch_processes(self):
        control = OfflineServerControl()
        for _ in range(3):
            status = control.start(SAFE)
            self.assertEqual(status["bot_identities"],
                             ["aggressive", "daily", "intraday"])
            self.assertEqual(status["order_capable_processes_started"], 0)
            self.assertEqual(control.stop()["mode"], "stopped")
            self.assertEqual(control.enabled_bots, frozenset())

    def test_unsafe_settings_do_not_transition_to_running(self):
        for key in SAFE:
            control = OfflineServerControl()
            bad = dict(SAFE)
            bad[key] = "true" if SAFE[key] == "false" else "false"
            with self.subTest(key=key), self.assertRaises(Exception):
                control.start(bad)
            self.assertEqual(control.mode, Mode.STOPPED)

    def test_double_start_is_denied(self):
        control = OfflineServerControl()
        control.start(SAFE)
        with self.assertRaises(RuntimeError):
            control.start(SAFE)

    def test_unknown_bot_denied(self):
        control = OfflineServerControl()
        with self.assertRaises(ValueError):
            control.start(SAFE, bots=["unknown"])
        self.assertEqual(control.mode, Mode.STOPPED)


if __name__ == "__main__":
    unittest.main()
