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

    def test_forged_success_labels_and_truthy_claims_never_authorize(self):
        """Future refactors must not accidentally accept a claimed approval."""
        class ForgedReview:
            status = "approved"
            allow_entry = True
            release_fence = True

        for upstream in (
            ForgedReview(),
            {"status": "review_only", "allow_entry": True},
            PipelineReview("success", "synthetic"),
            PipelineReview("release_fence", "synthetic"),
            PipelineReview("review_only", "synthetic"),
        ):
            for suspicious in (1, "true", [], None):
                with self.subTest(upstream=repr(upstream), claim=repr(suspicious)):
                    result = inspect_synthetic_entry_release_offline(
                        pipeline_review=upstream,
                        claimed_open_orders_empty=suspicious,
                        claimed_position_verified=True,
                        claimed_history_complete=True,
                        claimed_source_authenticated=True,
                    )
                    self.assertEqual(result.status, "hold")
                    self.assertIs(result.allow_entry, False)
                    self.assertIs(result.release_fence, False)

    def test_result_flags_are_explicitly_false_even_for_all_positive_claims(self):
        result = inspect_synthetic_entry_release_offline(
            pipeline_review=PipelineReview("review_only", "all synthetic checks passed"),
            claimed_open_orders_empty=True,
            claimed_position_verified=True,
            claimed_history_complete=True,
            claimed_source_authenticated=True,
        )
        self.assertEqual(result.status, "hold")
        self.assertEqual(result.__dict__["allow_entry"], False)
        self.assertEqual(result.__dict__["release_fence"], False)

    def test_hostile_upstream_status_access_fails_closed(self):
        class ExplodingStatus:
            @property
            def status(self):
                raise RuntimeError("malformed synthetic review")

        class UnhashableStatus:
            status = ["review_only"]

        for upstream in (ExplodingStatus(), UnhashableStatus()):
            with self.subTest(upstream=type(upstream).__name__):
                result = inspect_synthetic_entry_release_offline(
                    pipeline_review=upstream,
                    claimed_open_orders_empty=True,
                    claimed_position_verified=True,
                    claimed_history_complete=True,
                    claimed_source_authenticated=True,
                )
                self.assertEqual(result.status, "hold")
                self.assertIs(result.allow_entry, False)
                self.assertIs(result.release_fence, False)

    def test_all_review_statuses_are_non_authorizing(self):
        """A future upstream label must never silently become a release token."""
        for status in ("hold", "review_only", "approved", "success",
                       "filled", "complete", "authorized", "release", "", None,
                       1, True, ["review_only"], {"status": "review_only"}):
            with self.subTest(status=repr(status)):
                upstream = type("SyntheticReview", (), {"status": status})()
                result = inspect_synthetic_entry_release_offline(
                    pipeline_review=upstream,
                    claimed_open_orders_empty=True,
                    claimed_position_verified=True,
                    claimed_history_complete=True,
                    claimed_source_authenticated=True,
                )
                self.assertEqual(result.status, "hold")
                self.assertIs(result.allow_entry, False)
                self.assertIs(result.release_fence, False)

if __name__ == "__main__":
    unittest.main()
