"""Fake-only tests for the offline Hyperliquid retention review gate."""
import unittest

from offline_hyperliquid_retention_gate import inspect_retention_evidence_offline


def review(**changes):
    args = dict(
        required_start_ms=100, required_end_ms=200,
        earliest_proven_ms=90, latest_proven_ms=210,
        source="independently_archived_fill_log",
        truncated=False, retention_unknown=False,
    )
    args.update(changes)
    return inspect_retention_evidence_offline(**args)


class RetentionGateTests(unittest.TestCase):
    def test_positive_archive_claim_is_only_review_not_authorization(self):
        result = review()
        self.assertEqual(result.status, "review_only")
        self.assertIn("unverified", result.reason)

    def test_recent_history_alone_cannot_establish_old_fills(self):
        for source in ("userFillsByTime", "userFills", "", None):
            with self.subTest(source=source):
                self.assertEqual(review(source=source).status, "hold")

    def test_unknown_or_truncated_history_holds(self):
        for changes in ({"truncated": True},
                        {"retention_unknown": True},
                        {"truncated": None},
                        {"retention_unknown": None}):
            with self.subTest(changes=changes):
                self.assertEqual(review(**changes).status, "hold")

    def test_missing_pre_submit_or_recent_coverage_holds(self):
        self.assertEqual(review(earliest_proven_ms=101).status, "hold")
        self.assertEqual(review(latest_proven_ms=199).status, "hold")

    def test_invalid_evidence_boundaries_hold(self):
        for changes in ({"required_start_ms": 0},
                        {"required_end_ms": 99},
                        {"earliest_proven_ms": 0},
                        {"latest_proven_ms": 89}):
            with self.subTest(changes=changes):
                self.assertEqual(review(**changes).status, "hold")


if __name__ == "__main__":
    unittest.main()
