import unittest
from trusted_reconciliation_staging import verify_handoff, verify_release

COIN = "SOL"
FILL = [{"coin": COIN, "oid": 123, "sz": "0.5"}]
OPEN = [{"coin": COIN, "oid": 123}]
ACTIVE = {"assetPositions": [{"position": {"coin": COIN, "szi": "0.5"}}]}
FLAT = {"assetPositions": []}

class ReconciliationTests(unittest.TestCase):
    def test_matching_fill_and_position(self):
        self.assertTrue(verify_handoff(coin=COIN, order_id="123", fills=FILL,
                        open_orders=[], user_state=ACTIVE, fresh=True).allowed)

    def test_stale_fill_rejected(self):
        self.assertFalse(verify_handoff(coin=COIN, order_id="123", fills=FILL,
                         open_orders=[], user_state=ACTIVE, fresh=False).allowed)

    def test_open_order_blocks_handoff(self):
        self.assertFalse(verify_handoff(coin=COIN, order_id="123", fills=FILL,
                         open_orders=OPEN, user_state=ACTIVE, fresh=True).allowed)

    def test_flat_position_blocks_handoff(self):
        self.assertFalse(verify_handoff(coin=COIN, order_id="123", fills=FILL,
                         open_orders=[], user_state=FLAT, fresh=True).allowed)

    def test_flat_no_orders_allows_release(self):
        self.assertTrue(verify_release(coin=COIN, open_orders=[],
                        user_state=FLAT, fresh=True).allowed)

    def test_open_order_blocks_release(self):
        self.assertFalse(verify_release(coin=COIN, open_orders=OPEN,
                         user_state=FLAT, fresh=True).allowed)

    def test_active_position_blocks_release(self):
        self.assertFalse(verify_release(coin=COIN, open_orders=[],
                         user_state=ACTIVE, fresh=True).allowed)

    def test_missing_order_snapshot_blocks_release(self):
        self.assertFalse(verify_release(coin=COIN, open_orders=None,
                         user_state=FLAT, fresh=True).allowed)

    def test_stale_snapshot_blocks_release(self):
        self.assertFalse(verify_release(coin=COIN, open_orders=[],
                         user_state=FLAT, fresh=False).allowed)

if __name__ == "__main__":
    unittest.main()
