"""Offline-only synthetic coverage and partial fill tests."""
import unittest
from offline_hyperliquid_retention_gate import RetentionReview
from offline_hyperliquid_partial_coverage import inspect_partial_fill_coverage_offline

def inspect(**changes):
    args = dict(requested_size="2", observed_fill_sizes=("1", "1"),
                required_start_ms=100, required_end_ms=200,
                queried_start_ms=100, queried_end_ms=200,
                archive_review=RetentionReview("review_only", "fake archive claim"),
                saturated=False, missing_windows=False, order_status="filled")
    args.update(changes)
    return inspect_partial_fill_coverage_offline(**args)

class PartialCoverageTests(unittest.TestCase):
    def test_matching_synthetic_claim_is_review_only(self):
        result = inspect()
        self.assertEqual(result.status, "review_only")
        self.assertIn("unverified", result.reason)

    def test_partial_empty_or_excess_fills_hold(self):
        for fills in ((), ("1",), ("3",), ("1", "2")):
            with self.subTest(fills=fills):
                self.assertEqual(inspect(observed_fill_sizes=fills).status, "hold")

    def test_missing_window_or_archive_holds(self):
        for changes in (
            {"queried_start_ms": 101}, {"queried_end_ms": 199},
            {"archive_review": RetentionReview("hold", "no archive")},
            {"archive_review": None}, {"missing_windows": True},
            {"saturated": True},
        ):
            with self.subTest(changes=changes):
                self.assertEqual(inspect(**changes).status, "hold")

    def test_rejected_or_nonterminal_status_holds(self):
        self.assertEqual(inspect(order_status="rejected").status, "hold")
        self.assertEqual(inspect(order_status="open").status, "hold")

    def test_invalid_sizes_hold(self):
        for fills in (("NaN",), ("0",), (1,), ("Infinity",)):
            with self.subTest(fills=fills):
                self.assertEqual(inspect(observed_fill_sizes=fills).status, "hold")

if __name__ == "__main__":
    unittest.main()
