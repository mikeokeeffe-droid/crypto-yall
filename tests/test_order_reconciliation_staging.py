import unittest
from order_reconciliation_staging import (
    OrderOutcome, can_resolve_entry_intent, may_submit_new_entry,
)


class ReconciliationPolicyTests(unittest.TestCase):
    def test_unknown_timeout_keeps_fence(self):
        self.assertFalse(can_resolve_entry_intent(
            OrderOutcome.UNKNOWN, order_final=False, position_flat=True
        ))

    def test_unknown_even_if_position_flat_keeps_fence(self):
        self.assertFalse(can_resolve_entry_intent(
            OrderOutcome.UNKNOWN, order_final=True, position_flat=True
        ))

    def test_rejected_but_position_not_flat_keeps_fence(self):
        self.assertFalse(can_resolve_entry_intent(
            OrderOutcome.REJECTED, order_final=True, position_flat=False
        ))

    def test_rejected_and_verified_flat_allows_resolution(self):
        self.assertTrue(can_resolve_entry_intent(
            OrderOutcome.REJECTED, order_final=True, position_flat=True
        ))

    def test_filled_order_does_not_auto_release(self):
        self.assertFalse(can_resolve_entry_intent(
            OrderOutcome.FILLED, order_final=True, position_flat=False
        ))

    def test_order_submit_requires_all_checks(self):
        for missing in range(4):
            args = [True] * 4
            args[missing] = False
            self.assertFalse(may_submit_new_entry(
                has_reservation=args[0], has_durable_intent=args[1],
                exchange_position_flat=args[2], exchange_orders_clear=args[3]
            ))
        self.assertTrue(may_submit_new_entry(
            has_reservation=True, has_durable_intent=True,
            exchange_position_flat=True, exchange_orders_clear=True
        ))


if __name__ == "__main__":
    unittest.main()
