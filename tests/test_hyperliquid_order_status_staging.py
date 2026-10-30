"""Offline tests for authoritative order finality parsing."""
import unittest
from hyperliquid_order_status_staging import read_order_finality

class Info:
    def __init__(self, status, coin="BTC", oid=42, fail=False):
        self.status, self.coin, self.oid, self.fail = status, coin, oid, fail
    def order_status(self, address, oid):
        if self.fail:
            raise ConnectionError("simulated outage")
        return {"status":"order","order":{"order":{"coin":self.coin,"oid":self.oid},
                                            "status":self.status}}

class OrderFinalityTests(unittest.TestCase):
    def test_final_and_open_statuses(self):
        for status in ("filled", "canceled", "rejected", "expired"):
            with self.subTest(status=status):
                self.assertIs(read_order_finality(Info(status), "fake", coin="BTC", order_id=42), True)
        self.assertIs(read_order_finality(Info("open"), "fake", coin="BTC", order_id=42), False)

    def test_mismatched_order_fails_closed(self):
        self.assertIsNone(read_order_finality(Info("filled", coin="ETH"), "fake", coin="BTC", order_id=42))
        self.assertIsNone(read_order_finality(Info("filled", oid=99), "fake", coin="BTC", order_id=42))

    def test_outage_and_unknown_status_fail_closed(self):
        self.assertIsNone(read_order_finality(Info("filled", fail=True), "fake", coin="BTC", order_id=42))
        self.assertIsNone(read_order_finality(Info("unknown"), "fake", coin="BTC", order_id=42))

if __name__ == "__main__":
    unittest.main()
