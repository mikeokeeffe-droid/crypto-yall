"""Synthetic-only intent-bound receipt tests. Never authorizes a trade."""
import unittest
from offline_hyperliquid_intent_bound_fill import inspect_intent_bound_fill_offline

INTENT = {"oid": 42, "requested_size": "2", "coin": "SOL", "direction": "long"}

def receipt(oid=42, size="1"):
    return {"status": "ok", "response": {"type": "order", "data": {
        "statuses": [{"filled": {"oid": oid, "totalSz": size, "avgPx": "100"}}]}}}

class IntentBoundFillTests(unittest.TestCase):
    def test_matching_partial_and_full_receipts_still_hold(self):
        for amount in ("1", "2"):
            result = inspect_intent_bound_fill_offline(
                response=receipt(size=amount), intent=INTENT)
            self.assertEqual(result.status, "hold")
            self.assertIn("provenance", result.reason)

    def test_mismatched_order_id_and_overfill_hold(self):
        for raw in (receipt(oid=43), receipt(size="3")):
            result = inspect_intent_bound_fill_offline(response=raw, intent=INTENT)
            self.assertEqual(result.status, "hold")
            self.assertIn("does not match", result.reason)

    def test_unpinned_or_malformed_intents_hold(self):
        invalid = (
            None, {}, dict(INTENT, oid=True), dict(INTENT, oid=0),
            dict(INTENT, requested_size="NaN"),
            dict(INTENT, requested_size="-1"),
            dict(INTENT, coin="sol"),
            dict(INTENT, coin=""),
            dict(INTENT, direction=["long"]),
            dict(INTENT, direction={"long": True}),
            dict(INTENT, direction="close"),
            {k:v for k,v in INTENT.items() if k != "oid"},
            dict(INTENT, account="unverified"),
        )
        for intent in invalid:
            with self.subTest(intent=repr(intent)):
                result = inspect_intent_bound_fill_offline(
                    response=receipt(), intent=intent)
                self.assertEqual(result.status, "hold")

if __name__ == "__main__":
    unittest.main()
