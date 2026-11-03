"""No-network consistency checks for synthetic order and fill evidence."""
import unittest
from offline_hyperliquid_wire_review import WireReview
from offline_hyperliquid_order_fill_conflicts import inspect_order_fill_consistency_offline

def inspect(status="filled", sizes=("1", "1"), **changes):
    order = WireReview("parsed_untrusted", "fake", ((123, status, 100, 200),))
    fills = WireReview("parsed_untrusted", "fake", tuple(
        ("SOL", 123, i + 1, 150 + i, "B", "Open Long", sz)
        for i, sz in enumerate(sizes)
    ))
    args = dict(order_review=order, fills_review=fills, oid=123,
                coin="SOL", direction="long", size="2",
                submitted_at_ms=100, start_ms=100, end_ms=200)
    args.update(changes)
    return inspect_order_fill_consistency_offline(**args)

class ConflictTests(unittest.TestCase):
    def test_matching_fake_evidence_still_review_only(self):
        result = inspect()
        self.assertEqual(result.status, "review_only")
        self.assertIn("unverified", result.reason)

    def test_missing_partial_or_excess_fills_hold(self):
        for sizes in ((), ("1",), ("3",), ("1", "2")):
            with self.subTest(sizes=sizes):
                self.assertEqual(inspect(sizes=sizes).status, "hold")

    def test_rejected_never_proves_no_fill(self):
        self.assertEqual(inspect(status="rejected", sizes=()).status, "hold")
        self.assertEqual(inspect(status="rejected").status, "hold")

    def test_wrong_side_coin_or_time_holds(self):
        for field, value in ((4, "A"), (0, "BTC"), (3, 99), (3, 201)):
            order = WireReview("parsed_untrusted", "fake", ((123, "filled", 100, 200),))
            fill = ["SOL", 123, 1, 150, "B", "Open Long", "2"]
            fill[field] = value
            fills = WireReview("parsed_untrusted", "fake", (tuple(fill),))
            with self.subTest(field=field):
                self.assertEqual(inspect(
                    order_review=order, fills_review=fills).status, "hold")

    def test_missing_window_or_wrong_oid_holds(self):
        self.assertEqual(inspect(end_ms=199).status, "hold")
        self.assertEqual(inspect(oid=999).status, "hold")

    def test_duplicate_trade_ids_hold(self):
        fills = WireReview("parsed_untrusted", "fake", (
            ("SOL", 123, 1, 150, "B", "Open Long", "1"),
            ("SOL", 123, 1, 151, "B", "Open Long", "1"),
        ))
        self.assertEqual(inspect(fills_review=fills).status, "hold")

if __name__ == "__main__":
    unittest.main()
