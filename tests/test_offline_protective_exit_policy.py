"""Synthetic protective close review tests; no orders or exchange connection."""
import unittest
from offline_protective_exit_policy import review_protective_exit_offline

VALID = dict(action="close", reduce_only=True, account_verified=True,
             position_owned=True, position_side="long", position_size="2.5",
             close_size="1.25", snapshot_fresh=True, entries_disabled=True)

class ProtectiveExitReviewTests(unittest.TestCase):
    def test_valid_synthetic_close_is_review_only_not_execution_approval(self):
        result = review_protective_exit_offline(**VALID)
        self.assertEqual(result.status, "review_only")
        self.assertFalse(result.submit_authorized)

    def test_unknown_or_unsafe_closes_are_held(self):
        changes = (
            {"action": "open_long"}, {"action": "pyramid_short"},
            {"reduce_only": False}, {"reduce_only": "true"},
            {"account_verified": False}, {"position_owned": False},
            {"snapshot_fresh": False}, {"entries_disabled": False},
            {"position_side": "flat"}, {"position_size": "NaN"},
            {"position_size": "-1"}, {"close_size": "0"},
            {"close_size": "Infinity"}, {"close_size": "2.6"},
            {"close_size": 1.25}, {"account_verified": "true"},
        )
        for change in changes:
            with self.subTest(change=change):
                result = review_protective_exit_offline(**dict(VALID, **change))
                self.assertEqual(result.status, "hold")
                self.assertFalse(result.submit_authorized)

    def test_exact_size_and_short_close_remain_review_only(self):
        result = review_protective_exit_offline(
            **dict(VALID, position_side="short", close_size="2.5"))
        self.assertEqual(result.status, "review_only")
        self.assertFalse(result.submit_authorized)

if __name__ == "__main__":
    unittest.main()
