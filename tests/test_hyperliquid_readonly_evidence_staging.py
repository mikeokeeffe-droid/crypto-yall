import unittest
from hyperliquid_readonly_evidence_staging import fetch_exchange_snapshot, is_fresh

ADDRESS = "0x" + "a" * 40

class FakeInfo:
    def user_state(self, address):
        return {"assetPositions": []}
    def open_orders(self, address):
        return []
    def user_fills(self, address):
        return []

class ReadOnlyEvidenceTests(unittest.TestCase):
    def test_complete_snapshot(self):
        snap = fetch_exchange_snapshot(FakeInfo(), ADDRESS, clock=lambda: 100.0)
        self.assertEqual(snap.user_state["assetPositions"], [])
        self.assertTrue(is_fresh(snap, now=110))
        self.assertFalse(is_fresh(snap, now=116))

    def test_future_timestamp_rejected(self):
        snap = fetch_exchange_snapshot(FakeInfo(), ADDRESS, clock=lambda: 100.0)
        self.assertFalse(is_fresh(snap, now=99))

    def test_invalid_address_rejected(self):
        with self.assertRaises(ValueError):
            fetch_exchange_snapshot(FakeInfo(), "invalid")

    def test_malformed_exchange_data_rejected(self):
        class BadInfo(FakeInfo):
            def open_orders(self, address):
                return None
        with self.assertRaises(ValueError):
            fetch_exchange_snapshot(BadInfo(), ADDRESS)

    def test_exchange_exception_propagates(self):
        class BrokenInfo(FakeInfo):
            def user_fills(self, address):
                raise ConnectionError("offline")
        with self.assertRaises(ConnectionError):
            fetch_exchange_snapshot(BrokenInfo(), ADDRESS)

if __name__ == "__main__":
    unittest.main()
