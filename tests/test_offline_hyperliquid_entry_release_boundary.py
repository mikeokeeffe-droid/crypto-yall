"""Prove that no combination of fake claims releases a trading fence."""
import itertools
import unittest
from offline_hyperliquid_synthetic_pipeline import PipelineReview
from offline_hyperliquid_entry_release_boundary import inspect_synthetic_entry_release_offline

class EntryReleaseBoundaryTests(unittest.TestCase):
    def test_every_boolean_claim_combination_stays_on_hold(self):
        for status in ("review_only", "hold"):
            for claims in itertools.product((False, True), repeat=4):
                with self.subTest(status=status, claims=claims):
                    result = inspect_synthetic_entry_release_offline(
                        pipeline_review=PipelineReview(status, "fake"),
                        claimed_open_orders_empty=claims[0],
                        claimed_position_verified=claims[1],
                        claimed_history_complete=claims[2],
                        claimed_source_authenticated=claims[3],
                    )
                    self.assertEqual(result.status, "hold")
                    self.assertIs(result.allow_entry, False)
                    self.assertIs(result.release_fence, False)

    def test_unknown_and_malformed_claims_hold(self):
        for upstream in (None, object(), PipelineReview("authorized", "fake")):
            result = inspect_synthetic_entry_release_offline(
                pipeline_review=upstream,
                claimed_open_orders_empty=True,
                claimed_position_verified=True,
                claimed_history_complete=True,
                claimed_source_authenticated=True,
            )
            self.assertEqual(result.status, "hold")
            self.assertFalse(result.allow_entry)
            self.assertFalse(result.release_fence)

        result = inspect_synthetic_entry_release_offline(
            pipeline_review=PipelineReview("review_only", "fake"),
            claimed_open_orders_empty=1,
            claimed_position_verified=True,
            claimed_history_complete=True,
            claimed_source_authenticated=True,
        )
        self.assertEqual(result.status, "hold")

if __name__ == "__main__":
    unittest.main()
