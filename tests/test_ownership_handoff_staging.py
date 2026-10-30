import unittest
from ownership_handoff_staging import OwnershipLedger, OwnershipPhase


class OwnershipHandoffTests(unittest.TestCase):
    def setUp(self):
        self.ledger = OwnershipLedger()
        self.assertTrue(self.ledger.claim("BTC", "aggressive", "token-a"))

    def test_unverified_fill_cannot_handoff(self):
        self.assertFalse(self.ledger.handoff_filled(
            "BTC", "aggressive", "token-a",
            exchange_fill_verified=False, exchange_order_id="123"))
        self.assertFalse(self.ledger.claim("BTC", "daily", "token-b"))

    def test_verified_fill_keeps_other_bots_fenced(self):
        self.assertTrue(self.ledger.handoff_filled(
            "BTC", "aggressive", "token-a",
            exchange_fill_verified=True, exchange_order_id="123"))
        self.assertFalse(self.ledger.claim("BTC", "intraday", "token-b"))

    def test_uncertain_result_blocks_other_bots(self):
        self.assertTrue(self.ledger.mark_uncertain("BTC", "aggressive", "token-a"))
        self.assertFalse(self.ledger.claim("BTC", "daily", "token-b"))
        self.assertTrue(self.ledger.handoff_filled(
            "BTC", "aggressive", "token-a",
            exchange_fill_verified=True, exchange_order_id="123"))

    def test_wrong_bot_or_token_cannot_claim_ownership(self):
        self.assertFalse(self.ledger.handoff_filled(
            "BTC", "daily", "token-a",
            exchange_fill_verified=True, exchange_order_id="123"))
        self.assertFalse(self.ledger.handoff_filled(
            "BTC", "aggressive", "wrong",
            exchange_fill_verified=True, exchange_order_id="123"))

    def test_release_requires_verified_flat_and_no_orders(self):
        self.assertTrue(self.ledger.handoff_filled(
            "BTC", "aggressive", "token-a",
            exchange_fill_verified=True, exchange_order_id="123"))
        self.assertFalse(self.ledger.close_verified(
            "BTC", "aggressive", "token-a",
            exchange_position_flat=False, no_open_orders=True))
        self.assertTrue(self.ledger.close_verified(
            "BTC", "aggressive", "token-a",
            exchange_position_flat=True, no_open_orders=True))
        self.assertFalse(self.ledger.release_verified(
            "BTC", "aggressive", "token-a",
            exchange_position_flat=True, no_open_orders=False))
        self.assertFalse(self.ledger.claim("BTC", "daily", "token-b"))
        self.assertTrue(self.ledger.release_verified(
            "BTC", "aggressive", "token-a",
            exchange_position_flat=True, no_open_orders=True))
        self.assertTrue(self.ledger.claim("BTC", "daily", "token-b"))


if __name__ == "__main__":
    unittest.main()
