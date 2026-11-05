"""Offline synthetic shared-close evidence: never authorizes execution."""
import copy
import unittest
from offline_shared_close_evidence_gate import review_shared_close_evidence_offline

def case():
    return {
        "request": dict(bot="daily", account="synthetic-account", coin="SOL",
                        side="long", close_size="1"),
        "order_claims": [
            dict(order_id=101, bot="daily", account="synthetic-account",
                 coin="SOL", side="long", kind="entry", requested_size="2",
                 submitted_at_ms=100_000, status="filled", final=True),
        ],
        "exchange_fills": [
            dict(fill_id="fill-101", order_id=101, account="synthetic-account",
                 coin="SOL", exchange_side="buy", size="2", time_ms=100_500),
        ],
        "snapshot": dict(capture_id="capture-1", account="synthetic-account",
                         coin="SOL", side="long", position_size="2",
                         captured_at_ms=102_000, fills_complete=True,
                         open_orders_empty=True),
        "now_ms": 103_000,
    }

def check(modify=None):
    supplied = case()
    if modify:
        modify(supplied)
    return review_shared_close_evidence_offline(**supplied)

class OfflineCloseEvidenceGateTests(unittest.TestCase):
    def test_complete_consistent_synthetic_case_still_holds(self):
        result = check()
        self.assertEqual(result.status, "hold")
        self.assertTrue(result.structurally_consistent)
        self.assertFalse(result.submit_authorized)

    def test_unauthenticated_metadata_cannot_grant_close(self):
        def amend(c):
            c["snapshot"]["authenticated"] = True
        self.assertFalse(check(amend).structurally_consistent)

    def test_other_bot_claimed_order_holds(self):
        def amend(c):
            c["order_claims"][0]["bot"] = "intraday"
        self.assertFalse(check(amend).structurally_consistent)

    def test_opposite_side_fill_holds(self):
        def amend(c):
            c["exchange_fills"][0]["exchange_side"] = "sell"
        self.assertFalse(check(amend).structurally_consistent)

    def test_duplicate_and_orphaned_fills_hold(self):
        for mode in ("duplicate", "orphan"):
            with self.subTest(mode=mode):
                def amend(c):
                    extra = copy.deepcopy(c["exchange_fills"][0])
                    if mode == "orphan":
                        extra["order_id"] = 999
                        extra["fill_id"] = "other"
                    c["exchange_fills"].append(extra)
                self.assertFalse(check(amend).structurally_consistent)

    def test_partial_fill_holds(self):
        def amend(c):
            c["exchange_fills"][0]["size"] = "1"
        self.assertFalse(check(amend).structurally_consistent)

    def test_stale_or_future_snapshot_holds(self):
        for stamp in (60_000, 200_000):
            with self.subTest(stamp=stamp):
                def amend(c):
                    c["snapshot"]["captured_at_ms"] = stamp
                self.assertFalse(check(amend).structurally_consistent)

    def test_oversized_close_holds(self):
        def amend(c):
            c["request"]["close_size"] = "3"
        self.assertFalse(check(amend).structurally_consistent)

    def test_incomplete_snapshot_holds(self):
        def amend(c):
            c["snapshot"]["fills_complete"] = False
        self.assertFalse(check(amend).structurally_consistent)

    def test_full_entry_then_partial_close_remains_untrusted(self):
        def amend(c):
            c["order_claims"].append(dict(
                order_id=102, bot="daily", account="synthetic-account",
                coin="SOL", side="long", kind="close", requested_size="1",
                submitted_at_ms=101_000, status="filled", final=True))
            c["exchange_fills"].append(dict(
                fill_id="fill-102", order_id=102, account="synthetic-account",
                coin="SOL", exchange_side="sell", size="1", time_ms=101_500))
            c["snapshot"]["position_size"] = "1"
        result = check(amend)
        self.assertTrue(result.structurally_consistent)
        self.assertFalse(result.submit_authorized)

    def test_cross_bot_unexplained_net_position_holds(self):
        def amend(c):
            c["snapshot"]["position_size"] = "3"
        self.assertFalse(check(amend).structurally_consistent)

if __name__ == "__main__":
    unittest.main()
