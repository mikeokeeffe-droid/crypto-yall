"""Offline conservative partial-fill / ambiguous order acceptance cases.

OrderOutcome currently has no PARTIAL value; partial fills are represented as
UNKNOWN until an authoritative exchange reconciliation establishes ownership.
This is deliberately NOT a production exchange integration.
"""
import unittest
from entry_lifecycle_staging import EntryLifecycle, Phase
from order_reconciliation_staging import OrderOutcome, can_resolve_entry_intent

class PartialFillRecoveryTests(unittest.TestCase):
    def start(self):
        l = EntryLifecycle()
        self.assertTrue(l.acquire(reserved=True, claimed=True,
                                  exchange_flat=True, no_open_orders=True))
        self.assertTrue(l.submit())
        return l

    def test_partial_fill_remains_fenced_as_ambiguous(self):
        l = self.start()
        l.observe(OrderOutcome.UNKNOWN)
        self.assertEqual(l.phase, Phase.UNCERTAIN)
        self.assertFalse(l.acquire(reserved=True, claimed=True,
                                   exchange_flat=True, no_open_orders=True))
        self.assertFalse(can_resolve_entry_intent(
            OrderOutcome.UNKNOWN, order_final=True, position_flat=False))

    def test_later_confirmed_fill_transfers_to_owned(self):
        l = self.start()
        l.observe(OrderOutcome.UNKNOWN)
        l.observe(OrderOutcome.FILLED)
        self.assertEqual(l.phase, Phase.OWNED)
        self.assertFalse(l.acquire(reserved=True, claimed=True,
                                   exchange_flat=True, no_open_orders=True))

    def test_ambiguous_response_must_not_be_treated_as_rejection(self):
        l = self.start()
        l.observe(OrderOutcome.UNKNOWN)
        self.assertFalse(l.resolve_rejection(order_final=True, exchange_flat=True))
        self.assertEqual(l.phase, Phase.UNCERTAIN)

    def test_confirmed_rejection_requires_flat_and_final(self):
        l = self.start()
        l.observe(OrderOutcome.REJECTED)
        self.assertFalse(l.resolve_rejection(order_final=True, exchange_flat=False))
        self.assertFalse(l.resolve_rejection(order_final=False, exchange_flat=True))
        self.assertTrue(l.resolve_rejection(order_final=True, exchange_flat=True))

if __name__ == "__main__":
    unittest.main()
