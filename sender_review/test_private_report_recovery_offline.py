"""Offline crash/ambiguous commit regression: no private report publication."""
import unittest

from sender_review.private_report_cas_preview_offline import SimulatedPrivateHead
from sender_review.private_report_recovery_offline import (
    classify_interrupted_private_publish_offline,
)

BEFORE = SimulatedPrivateHead(7, "a" * 64)
AFTER = SimulatedPrivateHead(8, "b" * 64)


def review(observed, prior=BEFORE, proposed=AFTER):
    return classify_interrupted_private_publish_offline(
        prior=prior, proposed=proposed, observed_after_failure=observed,
    )


class PrivateReportRecoveryTests(unittest.TestCase):
    def assert_no_authority(self, result):
        self.assertFalse(result.publish_complete_verified)
        self.assertFalse(result.automatic_retry_authorized)
        self.assertFalse(result.rollback_authorized)
        self.assertFalse(result.last_good_restored_verified)
        self.assertFalse(result.external_private_store_verified)
        self.assertFalse(result.restart_authorized)
        self.assertFalse(result.trading_authorized)

    def test_ambiguous_crash_with_unavailable_head_must_hold(self):
        for observed in (None, {}, "latest", 7):
            with self.subTest(observed=observed):
                result = review(observed)
                self.assertEqual(result.verdict, "UNKNOWN_OUTCOME_HOLD")
                self.assert_no_authority(result)

    def test_crash_before_commit_does_not_authorize_retry(self):
        result = review(BEFORE)
        self.assertEqual(result.verdict, "OLD_HEAD_OBSERVED_HOLD")
        self.assert_no_authority(result)

    def test_crash_after_commit_does_not_claim_durable_success(self):
        result = review(AFTER)
        self.assertEqual(result.verdict, "PROPOSED_HEAD_OBSERVED_HOLD")
        self.assert_no_authority(result)

    def test_conflicting_writer_or_corruption_requires_independent_review(self):
        for observed in (
            SimulatedPrivateHead(8, "c" * 64),
            SimulatedPrivateHead(9, "b" * 64),
            SimulatedPrivateHead(6, "a" * 64),
        ):
            with self.subTest(observed=observed.version):
                result = review(observed)
                self.assertEqual(result.verdict, "CONFLICT_OR_CORRUPTION_HOLD")
                self.assert_no_authority(result)

    def test_stale_duplicate_or_malformed_candidate_cannot_claim_recovery(self):
        invalid = (
            BEFORE,
            SimulatedPrivateHead(8, "a" * 64),
            SimulatedPrivateHead(10, "b" * 64),
            SimulatedPrivateHead(True, "b" * 64),
            SimulatedPrivateHead(8, "not-hex"),
        )
        for proposed in invalid:
            with self.subTest(proposed=proposed.version):
                result = review(None, proposed=proposed)
                self.assertIn(
                    result.verdict, ("INVALID_PROPOSAL_HOLD", "UNKNOWN_OUTCOME_HOLD")
                )
                self.assert_no_authority(result)

    def test_result_does_not_expose_report_content(self):
        result = review(AFTER)
        self.assertNotIn("PRIVATE_TRADING_REPORT", repr(result))
        self.assert_no_authority(result)


if __name__ == "__main__":
    unittest.main()
