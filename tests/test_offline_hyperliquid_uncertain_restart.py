"""Offline restart uncertainty tests: no order submission or real account access."""
import unittest
from offline_hyperliquid_uncertain_restart import inspect_uncertain_restart_offline

class UncertainRestartTests(unittest.TestCase):
    def test_flat_or_matching_position_never_releases_pending_claim(self):
        pending = {"coin": "SOL", "request_id": "unresolved"}
        for snapshot in ({}, {"SOL": {"size": 0}},
                         {"SOL": {"size": 2}}, {"SOL": {"size": -2}}):
            for absent in (False, True):
                for no_fills in (False, True):
                    with self.subTest(snapshot=snapshot, absent=absent, no_fills=no_fills):
                        review = inspect_uncertain_restart_offline(
                            pending_claim=pending, position_snapshot=snapshot,
                            claimed_order_absent=absent,
                            claimed_no_recent_fills=no_fills)
                        self.assertEqual(review.status, "hold")
                        self.assertIs(review.release_claim, False)
                        self.assertIs(review.allow_new_entry, False)

    def test_malformed_restart_evidence_fails_closed(self):
        for pending, snapshot, absent, no_fills in (
            (None, {}, True, True),
            ({}, {}, True, True),
            ({"coin": "SOL"}, None, True, True),
            ({"coin": "SOL"}, {}, 1, True),
            ({"coin": "SOL"}, {}, True, "true"),
        ):
            review = inspect_uncertain_restart_offline(
                pending_claim=pending, position_snapshot=snapshot,
                claimed_order_absent=absent, claimed_no_recent_fills=no_fills)
            self.assertEqual(review.status, "hold")
            self.assertFalse(review.release_claim)
            self.assertFalse(review.allow_new_entry)

if __name__ == "__main__":
    unittest.main()
