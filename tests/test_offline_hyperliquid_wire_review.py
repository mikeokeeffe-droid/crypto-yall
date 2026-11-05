"""Offline fake Hyperliquid /info response fixtures: no HTTP, credentials or DB."""
import unittest

from offline_hyperliquid_wire_review import (
    parse_fills_by_time_offline, parse_order_status_offline,
)

ACCOUNT = "0x" + "a" * 40
OID = 123
SUBMITTED = 100_000


def order_fixture():
    request = {"type": "orderStatus", "user": ACCOUNT, "oid": OID}
    response = {
        "status": "order",
        "order": {
            "status": "filled", "statusTimestamp": 101_000,
            "order": {"coin": "SOL", "oid": OID, "side": "B",
                      "origSz": "2", "sz": "0", "limitPx": "100",
                      "reduceOnly": False, "timestamp": SUBMITTED},
        },
    }
    return request, response


def fill_fixture(tid=12, time=100_500):
    return {"coin": "SOL", "oid": OID, "tid": tid, "time": time,
            "side": "B", "dir": "Open Long", "sz": "1",
            "px": "100", "hash": "0x" + "b" * 64}


def fill_request():
    return {"type": "userFillsByTime", "user": ACCOUNT,
            "startTime": 100_000, "endTime": 102_000,
            "aggregateByTime": False}


class RealShapeOfflineTests(unittest.TestCase):
    def check_order(self, request=None, response=None):
        default_request, default_response = order_fixture()
        return parse_order_status_offline(
            request=default_request if request is None else request,
            response=default_response if response is None else response,
            account=ACCOUNT, coin="SOL", oid=OID, direction="long",
            requested_size="2", submitted_at_ms=SUBMITTED,
        )

    def check_fills(self, request=None, response=None, **kwargs):
        return parse_fills_by_time_offline(
            request=fill_request() if request is None else request,
            response=[fill_fixture()] if response is None else response,
            account=ACCOUNT, start_ms=100_000, end_ms=102_000, **kwargs,
        )

    def test_documented_order_shape_only_parses_untrusted(self):
        self.assertEqual(self.check_order().status, "parsed_untrusted")

    def test_rejected_status_is_not_proof_of_no_fill(self):
        request, response = order_fixture()
        response["order"]["status"] = "rejected"
        result = self.check_order(request, response)
        self.assertEqual(result.status, "parsed_untrusted")
        self.assertIn("unverified", result.reason)

    def test_wrong_account_query_or_order_identity_holds(self):
        for key, value in (("user", "0x" + "c" * 40), ("oid", 999),
                           ("type", "openOrders")):
            with self.subTest(key=key):
                request, response = order_fixture()
                request[key] = value
                self.assertEqual(self.check_order(request, response).status, "hold")
        for field, value in (("coin", "BTC"), ("oid", 999), ("side", "A"),
                             ("origSz", "3"), ("reduceOnly", True),
                             ("timestamp", 99_999), ("limitPx", "NaN")):
            with self.subTest(field=field):
                request, response = order_fixture()
                response["order"]["order"][field] = value
                self.assertEqual(self.check_order(request, response).status, "hold")

    def test_unknown_nonfinal_and_missing_order_hold(self):
        request, response = order_fixture()
        for status in ("open", "canceled", "unknown"):
            response["order"]["status"] = status
            self.assertEqual(self.check_order(request, response).status, "hold")
        self.assertEqual(self.check_order(response={"status": "unknownOid"}).status, "hold")

    def test_documented_fills_keep_same_millisecond_trade_ids(self):
        result = self.check_fills(response=[
            fill_fixture(tid=12), fill_fixture(tid=13),
        ])
        self.assertEqual(result.status, "parsed_untrusted")
        self.assertEqual(len(result.records), 2)

    def test_duplicate_trade_id_and_saturated_page_hold(self):
        self.assertEqual(self.check_fills(
            response=[fill_fixture(), fill_fixture()]).status, "hold")
        self.assertEqual(self.check_fills(
            response=[fill_fixture()], cap=1).status, "hold")

    def test_empty_fill_page_does_not_claim_complete_history(self):
        result = self.check_fills(response=[])
        self.assertEqual(result.status, "parsed_untrusted")
        self.assertIn("unverified", result.reason)

    def test_wrong_fill_request_account_window_or_aggregation_holds(self):
        for field, value in (("user", "0x" + "c" * 40),
                             ("startTime", 99_000),
                             ("endTime", 103_000),
                             ("aggregateByTime", True),
                             ("type", "userFills")):
            with self.subTest(field=field):
                request = fill_request()
                request[field] = value
                self.assertEqual(self.check_fills(request=request).status, "hold")

    def test_malformed_or_outside_window_fill_holds(self):
        for field, value in (("oid", 0), ("tid", 0), ("time", 103_000),
                             ("coin", "BTC-USDC"), ("side", "Z"),
                             ("sz", "0"), ("sz", "NaN"),
                             ("px", "Infinity"), ("hash", "bad")):
            with self.subTest(field=field):
                fill = fill_fixture()
                fill[field] = value
                self.assertEqual(self.check_fills(response=[fill]).status, "hold")

    def test_no_network_or_order_capability_in_module(self):
        import offline_hyperliquid_wire_review as module
        self.assertFalse(hasattr(module, "submit_order"))
        self.assertFalse(hasattr(module, "fetch_page"))


if __name__ == "__main__":
    unittest.main()
