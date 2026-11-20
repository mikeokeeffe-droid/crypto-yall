"""Offline evidence-review tests: no exchange calls and no database writes."""
import unittest
from entry_reconciliation_review_offline import review_final_no_fill


class EntryReconciliationReviewTests(unittest.TestCase):
    def evidence(self):
        order = dict(coin="SOL", order_id="12345", status="rejected",
                     final=True, complete=True, filled_size=0)
        first = dict(coin="SOL", fresh=True, complete=True, fills_complete=True,
                     observed_at_ms=2100, position_size=0,
                     open_orders=[], fills=[])
        second = dict(first, observed_at_ms=2300)
        return dict(coin="SOL", order_id="12345", submitted_at_ms=2000,
                    order=order, first=first, second=second)

    def decision(self, **changed):
        evidence = self.evidence()
        evidence.update(changed)
        return review_final_no_fill(**evidence)

    def test_complete_two_snapshot_final_rejection_is_review_only(self):
        result = self.decision()
        self.assertEqual(result.status, "review_candidate")
        self.assertNotIn("released", result.status)

    def test_missing_order_identity_or_final_proof_blocks(self):
        base = self.evidence()
        for changed in (
            {"order_id": None},
            {"order": dict(base["order"], status="unknown")},
            {"order": dict(base["order"], status="filled")},
            {"order": dict(base["order"], final=False)},
            {"order": dict(base["order"], complete=False)},
            {"order": dict(base["order"], filled_size=0.01)},
            {"order": dict(base["order"], filled_size=float("nan"))},
            {"order": dict(base["order"], order_id="wrong")},
        ):
            with self.subTest(changed=changed):
                self.assertEqual(self.decision(**changed).status, "hold")

    def test_partial_stale_or_ambiguous_snapshots_block(self):
        base = self.evidence()
        for idx in ("first", "second"):
            for changed in (
                {"fresh": False},
                {"complete": False},
                {"fills_complete": False},
                {"position_size": 0.1},
                {"position_size": float("nan")},
                {"open_orders": None},
                {"open_orders": [{"coin": "SOL"}]},
                {"fills": None},
                {"fills": [{"coin": "SOL", "order_id": "12345"}]},
            ):
                with self.subTest(snapshot=idx, changed=changed):
                    snapshot = dict(base[idx], **changed)
                    self.assertEqual(self.decision(**{idx: snapshot}).status, "hold")
        self.assertEqual(self.decision(second=dict(base["second"], observed_at_ms=2100)).status, "hold")
        self.assertEqual(self.decision(first=dict(base["first"], observed_at_ms=2000)).status, "hold")

    def test_reviewer_does_not_accept_orderless_timeout(self):
        self.assertEqual(self.decision(order=None).status, "hold")


if __name__ == "__main__":
    unittest.main()
