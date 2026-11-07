"""Read-only Hyperliquid fill retrieval with injected fake Info client."""
import unittest
from hyperliquid_fill_readonly_staging import read_order_fill_snapshot

class FakeInfo:
    def __init__(self, fail=False):
        self.fail = fail
        self.calls = 0
    def user_fills(self, address):
        self.calls += 1
        if self.fail:
            raise ConnectionError("offline simulated outage")
        return [{"coin":"BTC","oid":42,"sz":"2"},
                {"coin":"BTC","oid":42,"sz":"3"},
                {"coin":"ETH","oid":99,"sz":"1"}]

class FillReadOnlyTests(unittest.TestCase):
    def test_reads_matching_fills_without_orders(self):
        info = FakeInfo()
        result = read_order_fill_snapshot(info, "fake-address", coin="BTC",
                    order_id=42, requested_size=5, order_final=True)
        self.assertTrue(result.complete)
        self.assertEqual(result.filled_size, 5)
        self.assertEqual(info.calls, 1)

    def test_outage_returns_unknown_not_zero_fill(self):
        info = FakeInfo(fail=True)
        self.assertIsNone(read_order_fill_snapshot(info, "fake-address",
                    coin="BTC", order_id=42, requested_size=5, order_final=False))

    def test_unknown_finality_does_not_read_exchange(self):
        info = FakeInfo()
        self.assertIsNone(read_order_fill_snapshot(info, "fake-address",
                    coin="BTC", order_id=42, requested_size=5, order_final=None))
        self.assertEqual(info.calls, 0)

if __name__ == "__main__":
    unittest.main()
