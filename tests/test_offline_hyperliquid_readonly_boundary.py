"""Tests never contact Hyperliquid, connect wallets, or place orders."""
import unittest

from offline_hyperliquid_readonly_boundary import (
    build_order_status_query_offline, build_fills_query_offline,
    inspect_order_response_offline, inspect_fills_response_offline,
)

ACCOUNT = "0x" + "a" * 40


class ReadonlyBoundaryTests(unittest.TestCase):
    def test_builds_unexecuted_order_query(self):
        q = build_order_status_query_offline(account=ACCOUNT, oid=12)
        self.assertEqual(q.status, "query_only")
        self.assertEqual(q.request, {"type": "orderStatus",
                                     "user": ACCOUNT, "oid": 12})

    def test_builds_unexecuted_time_bounded_fills_query(self):
        q = build_fills_query_offline(account=ACCOUNT,
                                     start_ms=100, end_ms=200)
        self.assertEqual(q.status, "query_only")
        self.assertEqual(q.request["type"], "userFillsByTime")
        self.assertIs(q.request["aggregateByTime"], False)

    def test_rejects_unpinned_or_invalid_query(self):
        self.assertEqual(build_order_status_query_offline(
            account="invalid", oid=12).status, "hold")
        self.assertEqual(build_order_status_query_offline(
            account=ACCOUNT, oid=True).status, "hold")
        self.assertEqual(build_fills_query_offline(
            account=ACCOUNT, start_ms=201, end_ms=200).status, "hold")

    def test_order_inspection_is_untrusted_even_for_matching_fake(self):
        q = build_order_status_query_offline(account=ACCOUNT, oid=12)
        response = {"status": "order", "order": {
            "status": "filled", "statusTimestamp": 110,
            "order": {"oid": 12, "coin": "SOL", "side": "B",
                      "origSz": "2", "sz": "0", "limitPx": "100",
                      "reduceOnly": False, "timestamp": 100},
        }}
        result = inspect_order_response_offline(
            query=q, response=response, account=ACCOUNT, coin="SOL",
            oid=12, direction="long", requested_size="2",
            submitted_at_ms=100,
        )
        self.assertEqual(result.status, "parsed_untrusted")
        self.assertNotEqual(result.status, "authorized")

    def test_missing_order_is_hold(self):
        q = build_order_status_query_offline(account=ACCOUNT, oid=12)
        result = inspect_order_response_offline(
            query=q, response={"status": "unknownOid"}, account=ACCOUNT,
            coin="SOL", oid=12, direction="long",
            requested_size="2", submitted_at_ms=100,
        )
        self.assertEqual(result.status, "hold")

    def test_empty_fills_do_not_prove_no_fill(self):
        q = build_fills_query_offline(account=ACCOUNT,
                                     start_ms=100, end_ms=200)
        result = inspect_fills_response_offline(
            query=q, response=[], account=ACCOUNT,
            start_ms=100, end_ms=200,
        )
        self.assertEqual(result.status, "parsed_untrusted")
        self.assertIn("unverified", result.reason)

    def test_wrong_account_or_window_holds(self):
        q = build_fills_query_offline(account=ACCOUNT,
                                     start_ms=100, end_ms=200)
        result = inspect_fills_response_offline(
            query=q, response=[], account="0x" + "b" * 40,
            start_ms=100, end_ms=200,
        )
        self.assertEqual(result.status, "hold")
        result = inspect_fills_response_offline(
            query=q, response=[], account=ACCOUNT,
            start_ms=101, end_ms=200,
        )
        self.assertEqual(result.status, "hold")

    def test_module_has_no_transport_or_order_execution(self):
        import offline_hyperliquid_readonly_boundary as module
        self.assertFalse(hasattr(module, "send"))
        self.assertFalse(hasattr(module, "place_order"))
        self.assertFalse(hasattr(module, "http_client"))


if __name__ == "__main__":
    unittest.main()
