"""Offline restart/recovery tests for uncertain order lifecycle.

No live executor, database, or exchange is contacted. Restart is represented
by reconstructing a lifecycle from a persisted phase snapshot.
"""
import unittest
from entry_lifecycle_staging import EntryLifecycle, Phase
from order_reconciliation_staging import OrderOutcome

class RestartRecoveryTests(unittest.TestCase):
    def make_submitted(self):
        l = EntryLifecycle()
        self.assertTrue(l.acquire(reserved=True, claimed=True,
                                  exchange_flat=True, no_open_orders=True))
        self.assertTrue(l.submit())
        return l

    def test_timeout_survives_restart_and_denies_duplicate_entry(self):
        l = self.make_submitted()
        l.observe(OrderOutcome.UNKNOWN)
        restarted = EntryLifecycle(phase=l.phase)
        self.assertEqual(restarted.phase, Phase.UNCERTAIN)
        self.assertFalse(restarted.acquire(reserved=True, claimed=True,
                                           exchange_flat=True, no_open_orders=True))
        self.assertFalse(restarted.resolve_rejection(order_final=True, exchange_flat=True))

    def test_delayed_fill_after_restart_marks_position_owned(self):
        l = self.make_submitted()
        l.observe(OrderOutcome.UNKNOWN)
        restarted = EntryLifecycle(phase=l.phase)
        restarted.observe(OrderOutcome.FILLED)
        self.assertEqual(restarted.phase, Phase.OWNED)
        self.assertFalse(restarted.acquire(reserved=True, claimed=True,
                                           exchange_flat=True, no_open_orders=True))

    def test_rejection_requires_final_and_flat_confirmation_after_restart(self):
        l = self.make_submitted()
        l.observe(OrderOutcome.REJECTED)
        restarted = EntryLifecycle(phase=l.phase)
        self.assertFalse(restarted.resolve_rejection(order_final=False, exchange_flat=True))
        self.assertFalse(restarted.resolve_rejection(order_final=True, exchange_flat=False))
        self.assertTrue(restarted.resolve_rejection(order_final=True, exchange_flat=True))
        self.assertEqual(restarted.phase, Phase.RELEASED)

    def test_open_order_prevents_entry_after_restart(self):
        restarted = EntryLifecycle()
        self.assertFalse(restarted.acquire(reserved=True, claimed=True,
                                           exchange_flat=True, no_open_orders=False))

if __name__ == "__main__":
    unittest.main()
