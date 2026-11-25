"""No-network regression tests for future server staging start gate."""
import unittest
from server_staging_guard import UnsafeStartup, validate_offline_startup

SAFE = {
    "BOT_RUN_MODE": "offline",
    "ORDER_SUBMISSION_ENABLED": "false",
    "HL_TESTNET": "true",
    "SERVER_LIVE_TRADING_APPROVED": "false",
}


class ServerGuardTests(unittest.TestCase):
    def test_safe_offline_environment(self):
        self.assertTrue(validate_offline_startup(SAFE))

    def test_missing_or_unsafe_flags_fail_closed(self):
        for key in SAFE:
            for value in ("", "true" if SAFE[key] == "false" else "false"):
                with self.subTest(key=key, value=value):
                    env = dict(SAFE)
                    env[key] = value
                    with self.assertRaises(UnsafeStartup):
                        validate_offline_startup(env)

    def test_secret_leakage_fails_closed(self):
        for key in ("HL_PRIVATE_KEY", "HYPERLIQUID_PRIVATE_KEY", "SUPABASE_SERVICE_ROLE_KEY"):
            with self.subTest(key=key):
                env = dict(SAFE)
                env[key] = "dummy-not-a-real-secret"
                with self.assertRaises(UnsafeStartup):
                    validate_offline_startup(env)


if __name__ == "__main__":
    unittest.main()
