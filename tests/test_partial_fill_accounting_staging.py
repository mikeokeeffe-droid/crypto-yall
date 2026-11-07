"""Offline partial-fill arithmetic and exposure tests."""
import unittest
from partial_fill_accounting_staging import reconcile_fill_snapshot

class PartialFillAccountingTests(unittest.TestCase):
    def test_partial_fill_has_exposure_but_not_complete(self):
        result = reconcile_fill_snapshot(requested_size=10,
                                         fill_sizes=[2, 3], order_final=False)
        self.assertEqual(result.filled_size, 5)
        self.assertEqual(result.remaining_size, 5)
        self.assertTrue(result.has_exposure)
        self.assertFalse(result.complete)

    def test_multiple_fills_sum_to_complete(self):
        result = reconcile_fill_snapshot(requested_size=10,
                                         fill_sizes=[2, 3, 5], order_final=True)
        self.assertEqual(result.filled_size, 10)
        self.assertTrue(result.complete)

    def test_final_partial_order_still_has_exposure(self):
        result = reconcile_fill_snapshot(requested_size=10,
                                         fill_sizes=[2], order_final=True)
        self.assertTrue(result.has_exposure)
        self.assertFalse(result.complete)

    def test_invalid_and_overfilled_data_fail_closed(self):
        for sizes in ([11], [-1], [float("nan")], ["bad"]):
            with self.subTest(sizes=sizes):
                self.assertIsNone(reconcile_fill_snapshot(
                    requested_size=10, fill_sizes=sizes, order_final=True))

if __name__ == "__main__":
    unittest.main()
