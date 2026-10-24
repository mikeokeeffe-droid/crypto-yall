import unittest
from hyperliquid_fill_verification_staging import verify_order_fills


def verify(fills, **kwargs):
    return verify_order_fills(fills=fills, coin="SOL", order_id="123",
                              snapshot_fresh=kwargs.get("fresh", True),
                              open_orders=kwargs.get("orders", []))


class FillVerificationTests(unittest.TestCase):
    def test_matching_real_user_fills_fields(self):
        result = verify([{"coin": "SOL", "oid": 123, "sz": "1.5"}])
        self.assertTrue(result.verified)
        self.assertEqual(result.filled_size, 1.5)

    def test_partial_fills_same_order_are_summed(self):
        result = verify([{"coin": "SOL", "oid": 123, "sz": "0.5"},
                         {"coin": "SOL", "oid": 123, "sz": "0.75"}])
        self.assertTrue(result.verified)
        self.assertEqual(result.filled_size, 1.25)

    def test_wrong_coin_or_order_does_not_verify(self):
        self.assertFalse(verify([{"coin": "BTC", "oid": 123, "sz": "2"}]).verified)
        self.assertFalse(verify([{"coin": "SOL", "oid": 124, "sz": "2"}]).verified)

    def test_stale_or_outstanding_order_is_not_verified(self):
        fills = [{"coin": "SOL", "oid": 123, "sz": "2"}]
        self.assertFalse(verify(fills, fresh=False).verified)
        self.assertFalse(verify(fills, orders=[{"coin": "SOL"}]).verified)

    def test_invalid_size_denied(self):
        self.assertFalse(verify([{"coin": "SOL", "oid": 123, "sz": "nan"}]).verified)
        self.assertFalse(verify([{"coin": "SOL", "oid": 123, "sz": "-1"}]).verified)


if __name__ == "__main__":
    unittest.main()
