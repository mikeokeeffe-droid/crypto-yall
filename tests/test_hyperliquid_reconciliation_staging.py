import unittest
from hyperliquid_reconciliation_staging import classify_order_evidence, ReconcileState, normalize_executor_order_response


def classify(order, *, size=0, orders=None, fresh=True, oid="42"):
    return classify_order_evidence(
        order_response=order, position_snapshot={"coin": "SOL", "size": size},
        open_orders_snapshot=[] if orders is None else orders,
        expected_coin="SOL", expected_order_id=oid, snapshots_fresh=fresh,
    ).state


class HyperliquidEvidenceTests(unittest.TestCase):
    def test_verified_fill_requires_position_and_order_id(self):
        self.assertEqual(classify({"status": "filled", "oid": "42", "filled_size": "2"}, size=2),
                         ReconcileState.FILLED)
        self.assertEqual(classify({"status": "filled", "oid": "41", "filled_size": "2"}, size=2),
                         ReconcileState.UNKNOWN)

    def test_rejection_only_final_and_flat(self):
        self.assertEqual(classify({"status": "rejected", "oid": "42", "final": True}),
                         ReconcileState.REJECTED_FINAL_FLAT)
        self.assertEqual(classify({"status": "rejected", "oid": "42", "final": False}),
                         ReconcileState.UNKNOWN)
        self.assertEqual(classify({"status": "rejected", "oid": "42", "final": True}, size=1),
                         ReconcileState.UNKNOWN)

    def test_pending_orders_block_release(self):
        self.assertEqual(classify({"status": "rejected", "oid": "42", "final": True},
                                  orders=[{"coin": "SOL"}]), ReconcileState.UNKNOWN)

    def test_stale_or_missing_evidence_stays_fenced(self):
        self.assertEqual(classify({"status": "rejected", "oid": "42", "final": True}, fresh=False),
                         ReconcileState.UNKNOWN)
        self.assertEqual(classify(None), ReconcileState.UNKNOWN)

    def test_actual_executor_fill_shape_is_normalized(self):
        parsed = {"status": "filled", "fill_size": 2.0, "fill_price": 120.0, "oid": 42}
        normalized = normalize_executor_order_response(parsed)
        self.assertEqual(classify(normalized, size=2), ReconcileState.FILLED)

    def test_executor_error_does_not_prove_rejection(self):
        parsed = {"status": "error", "error": "timeout"}
        normalized = normalize_executor_order_response(parsed)
        self.assertEqual(classify(normalized), ReconcileState.UNKNOWN)

    def test_executor_unknown_response_stays_fenced(self):
        self.assertEqual(classify(normalize_executor_order_response(
            {"status": "unknown", "raw": {"status": "ok"}})), ReconcileState.UNKNOWN)

    def test_partial_fill_or_unexpected_status_is_uncertain(self):
        self.assertEqual(classify({"status": "partial", "oid": "42", "filled_size": "1"}, size=1),
                         ReconcileState.UNKNOWN)
        self.assertEqual(classify({"status": "timeout", "oid": "42"}, size=0),
                         ReconcileState.UNKNOWN)


if __name__ == "__main__":
    unittest.main()
