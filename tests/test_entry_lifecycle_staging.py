import unittest
from entry_lifecycle_staging import EntryLifecycle, Phase
from order_reconciliation_staging import OrderOutcome


class LifecycleTests(unittest.TestCase):
    def permit(self, lifecycle):
        return lifecycle.acquire(
            reserved=True, claimed=True,
            exchange_flat=True, no_open_orders=True,
        )

    def test_rejected_requires_independent_confirmation(self):
        l = EntryLifecycle()
        self.assertTrue(self.permit(l))
        self.assertTrue(l.submit())
        l.observe(OrderOutcome.REJECTED)
        self.assertFalse(l.resolve_rejection(
            order_final=False, exchange_flat=True
        ))
        self.assertTrue(l.resolve_rejection(
            order_final=True, exchange_flat=True
        ))
        self.assertEqual(l.phase, Phase.RELEASED)

    def test_timeout_keeps_fence_and_blocks_new_entry(self):
        l = EntryLifecycle()
        self.assertTrue(self.permit(l))
        self.assertTrue(l.submit())
        l.observe(OrderOutcome.UNKNOWN)
        self.assertEqual(l.phase, Phase.UNCERTAIN)
        self.assertFalse(self.permit(l))
        self.assertFalse(l.resolve_rejection(
            order_final=True, exchange_flat=True
        ))

    def test_delayed_fill_after_timeout_is_owned(self):
        l = EntryLifecycle()
        self.assertTrue(self.permit(l))
        l.submit()
        l.observe(OrderOutcome.UNKNOWN)
        l.observe(OrderOutcome.FILLED)
        self.assertEqual(l.phase, Phase.OWNED)
        self.assertFalse(self.permit(l))

    def test_open_exchange_position_blocks_new_entry(self):
        l = EntryLifecycle()
        self.assertFalse(l.acquire(
            reserved=True, claimed=True,
            exchange_flat=False, no_open_orders=True,
        ))
        self.assertEqual(l.phase, Phase.IDLE)

    def test_unresolved_exchange_order_blocks_new_entry(self):
        l = EntryLifecycle()
        self.assertFalse(l.acquire(
            reserved=True, claimed=True,
            exchange_flat=True, no_open_orders=False,
        ))


if __name__ == "__main__":
    unittest.main()
