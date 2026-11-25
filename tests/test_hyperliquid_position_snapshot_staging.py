import unittest
from hyperliquid_position_snapshot_staging import inspect_user_state_position


class PositionSnapshotTests(unittest.TestCase):
    def inspect(self, positions, fresh=True):
        return inspect_user_state_position(
            {"assetPositions": positions}, "SOL", snapshot_fresh=fresh)

    def test_long_position_not_flat(self):
        x = self.inspect([{"position": {"coin": "SOL", "szi": "2.5"}}])
        self.assertTrue(x.valid)
        self.assertFalse(x.flat)
        self.assertEqual(x.signed_size, 2.5)

    def test_short_position_not_flat(self):
        x = self.inspect([{"position": {"coin": "SOL", "szi": "-1.2"}}])
        self.assertTrue(x.valid)
        self.assertFalse(x.flat)

    def test_no_coin_position_is_flat(self):
        x = self.inspect([{"position": {"coin": "BTC", "szi": "1"}}])
        self.assertTrue(x.valid)
        self.assertTrue(x.flat)

    def test_malformed_and_duplicate_records_fail_closed(self):
        self.assertFalse(self.inspect([{"position": {"coin": "SOL"}}]).valid)
        self.assertFalse(self.inspect([{"position": {"coin": "SOL", "szi": "1"}},
                                       {"position": {"coin": "SOL", "szi": "2"}}]).valid)

    def test_stale_or_missing_snapshot_fails_closed(self):
        self.assertFalse(self.inspect([], fresh=False).valid)
        self.assertFalse(inspect_user_state_position({}, "SOL", snapshot_fresh=True).valid)


if __name__ == "__main__":
    unittest.main()
