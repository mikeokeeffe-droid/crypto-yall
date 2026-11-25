"""Hyperliquid-style fill parsing tests; all records are local fixtures."""
import unittest
from hyperliquid_fill_adapter_staging import snapshot_from_hyperliquid_fills as parse

class HyperliquidFillAdapterTests(unittest.TestCase):
    def test_matches_only_order_and_coin(self):
        result = parse(coin="BTC", order_id=42, requested_size=5,
                       fills=[{"coin":"BTC","oid":42,"sz":"2"},
                              {"coin":"ETH","oid":99,"sz":"100"},
                              {"coin":"BTC","oid":42,"sz":"1"}],
                       order_final=False)
        self.assertEqual(result.filled_size, 3)
        self.assertTrue(result.has_exposure)
        self.assertFalse(result.complete)

    def test_completed_order_with_multiple_fills(self):
        result = parse(coin="SOL", order_id="7", requested_size=4,
                       fills=[{"coin":"SOL","oid":7,"sz":"1.5"},
                              {"coin":"SOL","oid":7,"sz":"2.5"}],
                       order_final=True)
        self.assertEqual(result.remaining_size, 0)
        self.assertTrue(result.complete)

    def test_inconsistent_coin_and_malformed_size_fail_closed(self):
        for fills in ([{"coin":"ETH","oid":7,"sz":"1"}],
                      [{"coin":"BTC","oid":7,"sz":"nan"}],
                      [{"coin":"BTC","oid":7}]):
            with self.subTest(fills=fills):
                self.assertIsNone(parse(coin="BTC", order_id=7,
                    requested_size=5, fills=fills, order_final=True))

if __name__ == "__main__":
    unittest.main()
