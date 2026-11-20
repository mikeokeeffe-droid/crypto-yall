"""Synthetic stale-claim tests. No real clock, orders, or production state."""
import unittest
from offline_hyperliquid_stale_claim import inspect_stale_claim_offline

CLAIM = {"intent_id": "synthetic", "fence_token": 7,
         "created_ms": 1000, "state": "uncertain"}

class StaleClaimTests(unittest.TestCase):
    def test_expired_claim_never_releases_even_with_absence_claims(self):
        for age in (0, 999, 1000, 1001, 10**12):
            for absent in (False, True):
                for flat in (False, True):
                    with self.subTest(age=age, absent=absent, flat=flat):
                        review = inspect_stale_claim_offline(
                            claim=CLAIM, now_ms=1000 + age, ttl_ms=1000,
                            claimed_order_absent=absent,
                            claimed_flat_position=flat)
                        self.assertEqual(review.status, "hold")
                        self.assertFalse(review.release_claim)
                        self.assertFalse(review.allow_new_entry)

    def test_pending_claim_also_never_expires_automatically(self):
        review = inspect_stale_claim_offline(
            claim=dict(CLAIM, state="pending"), now_ms=999999999,
            ttl_ms=1000, claimed_order_absent=True,
            claimed_flat_position=True)
        self.assertEqual(review.status, "hold")
        self.assertFalse(review.release_claim)

    def test_malformed_claim_and_clock_hold(self):
        cases = (
            (None, 2000, 1000, True, True),
            ({}, 2000, 1000, True, True),
            (dict(CLAIM, fence_token=True), 2000, 1000, True, True),
            (dict(CLAIM, state="released"), 2000, 1000, True, True),
            (CLAIM, 999, 1000, True, True),
            (CLAIM, True, 1000, True, True),
            (CLAIM, 2000, 0, True, True),
            (CLAIM, 2000, 1000, "true", True),
        )
        for claim, now, ttl, absent, flat in cases:
            with self.subTest(claim=repr(claim), now=now, ttl=ttl):
                review = inspect_stale_claim_offline(
                    claim=claim, now_ms=now, ttl_ms=ttl,
                    claimed_order_absent=absent,
                    claimed_flat_position=flat)
                self.assertEqual(review.status, "hold")
                self.assertFalse(review.allow_new_entry)

    def test_freshness_claim_does_not_unlock_old_unresolved_intent(self):
        from offline_hyperliquid_evidence_freshness import (
            inspect_evidence_freshness_offline)
        freshness = inspect_evidence_freshness_offline(
            query_started_ms=999_990, response_received_ms=999_995,
            review_now_ms=1_000_000)
        self.assertEqual(freshness.status, "review_only")
        review = inspect_stale_claim_offline(
            claim=CLAIM, now_ms=1_000_000, ttl_ms=1000,
            claimed_order_absent=True, claimed_flat_position=True)
        self.assertEqual(review.status, "hold")
        self.assertFalse(review.release_claim)
        self.assertFalse(review.allow_new_entry)

    def test_partial_history_claim_does_not_unlock_old_intent(self):
        from offline_hyperliquid_partial_coverage import (
            inspect_partial_fill_coverage_offline)
        class SyntheticArchive:
            status = "review_only"
        coverage = inspect_partial_fill_coverage_offline(
            requested_size="1", observed_fill_sizes=("1",),
            required_start_ms=1000, required_end_ms=2000,
            queried_start_ms=1000, queried_end_ms=2000,
            archive_review=SyntheticArchive(), saturated=False,
            missing_windows=False, order_status="filled")
        self.assertEqual(coverage.status, "review_only")
        review = inspect_stale_claim_offline(
            claim=CLAIM, now_ms=1_000_000, ttl_ms=1000,
            claimed_order_absent=False, claimed_flat_position=True)
        self.assertEqual(review.status, "hold")
        self.assertFalse(review.release_claim)
        self.assertFalse(review.allow_new_entry)

if __name__ == "__main__":
    unittest.main()
