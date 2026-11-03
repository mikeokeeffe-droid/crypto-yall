"""Synthetic-only strict parser regression tests. No live trading."""
import unittest
from offline_hyperliquid_strict_order_parser import inspect_market_order_response_offline

def response(fill):
    return {"status": "ok", "response": {"type": "order", "data": {
        "statuses": [{"filled": fill}]}}}

class StrictParserTests(unittest.TestCase):
    def test_positive_structural_fill_is_untrusted_not_authorized(self):
        result = inspect_market_order_response_offline(
            response=response({"oid": 123, "totalSz": "1.25", "avgPx": "100.50"}),
            expected_oid=123, requested_size="2")
        self.assertEqual(result.status, "parsed_untrusted")
        self.assertEqual(result.size, "1.25")

    def test_invalid_amount_price_and_oid_hold(self):
        good = {"oid": 123, "totalSz": "1.25", "avgPx": "100.50"}
        for field, values in (
            ("totalSz", ("-1", "0", "NaN", "Infinity", "", " 1", True, [], None)),
            ("avgPx", ("-1", "0", "NaN", "Infinity", "", " 1", True, [], None)),
            ("oid", (0, -1, True, "123", None)),
        ):
            for value in values:
                with self.subTest(field=field, value=value):
                    self.assertEqual(inspect_market_order_response_offline(
                        response=response(dict(good, **{field: value}))).status, "hold")

    def test_ambiguous_or_unexpected_responses_hold(self):
        good = response({"oid": 123, "totalSz": "1", "avgPx": "100"})
        for bad in (
            None, [], {}, {"status": "ok"},
            {"status": "ok", "response": {"type": "order", "data": {"statuses": []}}},
            {"status": "ok", "response": {"type": "order", "data": {"statuses": [{"resting": {"oid": 123}}]}}},
            {"status": "ok", "response": {"type": "order", "data": {"statuses": [
                {"filled": {"oid": 123, "totalSz": "1", "avgPx": "100"}},
                {"filled": {"oid": 124, "totalSz": "1", "avgPx": "100"}}]}}},
            dict(good, response=dict(good["response"], type="unexpected")),
        ):
            with self.subTest(bad=repr(bad)):
                self.assertEqual(inspect_market_order_response_offline(response=bad).status, "hold")

    def test_oid_mismatch_and_overfill_hold(self):
        good = response({"oid": 123, "totalSz": "2", "avgPx": "100"})
        self.assertEqual(inspect_market_order_response_offline(
            response=good, expected_oid=124).status, "hold")
        self.assertEqual(inspect_market_order_response_offline(
            response=good, requested_size="1").status, "hold")

if __name__ == "__main__":
    unittest.main()
