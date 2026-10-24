"""Offline safety checks for the proposed trading-state migration.

No credentials, network calls, exchange orders, or live state modifications.
"""
import json
import unittest

REQUIRED_BOTS = ("aggressive", "intraday", "daily")
CRITICAL_FIELDS = (
    "owned_coins",
    "pending_entry_claims",
    "peak_pnl",
    "peak_return_pct",
    "reentry_locks",
)

def validate_snapshot(state):
    if not isinstance(state, dict):
        raise ValueError("State must be a JSON object")
    encoded = json.dumps(state, allow_nan=False)
    decoded = json.loads(encoded)
    if decoded != state:
        raise ValueError("State JSON round-trip mismatch")
    return decoded

class StateMigrationSafetyTests(unittest.TestCase):
    def test_supported_bot_names(self):
        self.assertEqual(len(set(REQUIRED_BOTS)), 3)

    def test_round_trip_preserves_protection_data(self):
        sample = {
            "owned_coins": ["BTC", "ETH"],
            "pending_entry_claims": {"BTC": {"side": "long"}},
            "peak_pnl": {"BTC": 1.25},
            "peak_return_pct": {"BTC": 0.75},
            "reentry_locks": {"ETH": {"reason": "cooldown"}},
            "trade_history": [{"coin": "BTC", "pnl": 0.02}],
        }
        restored = validate_snapshot(sample)
        for field in CRITICAL_FIELDS:
            self.assertEqual(restored[field], sample[field])

    def test_rejects_non_object(self):
        with self.assertRaises(ValueError):
            validate_snapshot([])

    def test_rejects_non_json_number(self):
        with self.assertRaises(ValueError):
            validate_snapshot({"peak_pnl": {"BTC": float("nan")}})

if __name__ == "__main__":
    unittest.main()
