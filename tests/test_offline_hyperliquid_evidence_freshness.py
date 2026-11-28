"""Offline synthetic timestamp freshness checks."""
import unittest
from offline_hyperliquid_evidence_freshness import inspect_evidence_freshness_offline

def inspect(**changes):
    args=dict(query_started_ms=100000, response_received_ms=101000,
              review_now_ms=102000, maximum_age_ms=30000,
              maximum_duration_ms=10000)
    args.update(changes)
    return inspect_evidence_freshness_offline(**args)

class EvidenceFreshnessTests(unittest.TestCase):
    def test_fresh_synthetic_capture_is_only_reviewable(self):
        result=inspect()
        self.assertEqual(result.status,"review_only")
        self.assertIn("unverified",result.reason)

    def test_stale_future_reversed_and_slow_holds(self):
        for changes in (
            {"review_now_ms":132000},
            {"review_now_ms":100500},
            {"response_received_ms":99999},
            {"response_received_ms":112000},
            {"query_started_ms":103000},
            {"review_now_ms":0},
            {"maximum_age_ms":0},
            {"maximum_duration_ms":True},
        ):
            with self.subTest(changes=changes):
                self.assertEqual(inspect(**changes).status,"hold")

if __name__=="__main__":
    unittest.main()
