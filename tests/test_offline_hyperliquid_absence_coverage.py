"""Synthetic absence coverage tests; no exchange connection or order submission."""
import unittest
from offline_hyperliquid_absence_coverage import review_absence_evidence_offline

GOOD = dict(intent_created_ms=2000, window_start_ms=1000,
            window_end_ms=3000, history_complete=True,
            account_matches=True, order_id_matches=True,
            no_matching_order=True, no_matching_fill=True)

class AbsenceCoverageTests(unittest.TestCase):
    def test_even_fully_asserted_absence_cannot_clear_intent(self):
        review = review_absence_evidence_offline(**GOOD)
        self.assertEqual(review.status, "hold")
        self.assertFalse(review.release_claim)
        self.assertFalse(review.allow_new_entry)

    def test_partial_windows_and_identity_mismatch_hold(self):
        for change in (
            {"window_start_ms": 2001},
            {"window_end_ms": 1999},
            {"history_complete": False},
            {"account_matches": False},
            {"order_id_matches": False},
            {"no_matching_order": False},
            {"no_matching_fill": False},
            {"intent_created_ms": True},
            {"window_end_ms": -1},
            {"history_complete": "true"},
        ):
            with self.subTest(change=change):
                review = review_absence_evidence_offline(**dict(GOOD, **change))
                self.assertEqual(review.status, "hold")
                self.assertFalse(review.release_claim)
                self.assertFalse(review.allow_new_entry)

if __name__ == "__main__":
    unittest.main()
