"""End-to-end fake JSON through offline guards; no trading authorization."""
import json
import unittest
from offline_hyperliquid_synthetic_pipeline import inspect_synthetic_order_pipeline_offline

ACCOUNT = "0x" + "a" * 40
URL = "https://api.hyperliquid.xyz/info"

def fixture(**changes):
    order = {"status": "order", "order": {
        "status": "filled", "statusTimestamp": 200,
        "order": {"oid": 123, "coin": "SOL", "side": "B",
                  "reduceOnly": False, "timestamp": 100,
                  "origSz": "2", "limitPx": "100"}}}
    fills = [{"coin": "SOL", "oid": 123, "tid": i, "time": 150+i,
              "side": "B", "dir": "Open Long", "hash": "0x" + "b"*64,
              "sz": "1", "px": "100"} for i in (1, 2)]
    envelope = dict(status_code=200, elapsed_ms=100, body_bytes=500,
                    redirect_count=0, tls_verified=True,
                    expected_url=URL, final_url=URL)
    timeline = dict(query_started_ms=100000, response_received_ms=100100,
                    review_now_ms=100200)
    args = dict(order_bytes=json.dumps(order).encode(),
                fills_bytes=json.dumps(fills).encode(),
                order_request={"type": "orderStatus", "user": ACCOUNT, "oid": 123},
                fills_request={"type": "userFillsByTime", "user": ACCOUNT,
                               "startTime": 100, "endTime": 200,
                               "aggregateByTime": False},
                account=ACCOUNT, coin="SOL", oid=123, direction="long",
                size="2", submitted_at_ms=100, start_ms=100, end_ms=200,
                http_envelopes=(envelope, envelope),
                capture_times=(timeline, timeline),
                open_orders_known_empty=True, position_snapshot_verified=True)
    args.update(changes)
    return inspect_synthetic_order_pipeline_offline(**args)

class SyntheticPipelineTests(unittest.TestCase):
    def test_complete_fake_fixture_never_authorizes(self):
        result = fixture()
        self.assertEqual(result.status, "review_only")
        self.assertIn("no provenance", result.reason)
        self.assertNotIn("authorized", result.status)

    def test_unverified_account_state_holds(self):
        self.assertEqual(fixture(open_orders_known_empty=False).status, "hold")
        self.assertEqual(fixture(position_snapshot_verified=False).status, "hold")

    def test_bad_json_or_http_or_timing_holds(self):
        self.assertEqual(fixture(order_bytes=b'{"status":1,"status":2}').status, "hold")
        self.assertEqual(fixture(fills_bytes=b"[]").status, "hold")
        self.assertEqual(fixture(http_envelopes=(
            dict(status_code=429, elapsed_ms=100, body_bytes=0,
                 redirect_count=0, tls_verified=True,
                 expected_url=URL, final_url=URL),
            dict(status_code=200, elapsed_ms=100, body_bytes=500,
                 redirect_count=0, tls_verified=True,
                 expected_url=URL, final_url=URL))).status, "hold")
        self.assertEqual(fixture(capture_times=(
            dict(query_started_ms=100000, response_received_ms=100100,
                 review_now_ms=200000),
            dict(query_started_ms=100000, response_received_ms=100100,
                 review_now_ms=100200))).status, "hold")

    def test_rejected_order_cannot_be_relabelled_filled(self):
        order = {"status": "order", "order": {
            "status": "rejected", "statusTimestamp": 200,
            "order": {"oid": 123, "coin": "SOL", "side": "B",
                      "reduceOnly": False, "timestamp": 100,
                      "origSz": "2", "limitPx": "100"}}}
        result = fixture(order_bytes=json.dumps(order).encode())
        self.assertEqual(result.status, "hold")

    def test_other_order_same_coin_holds(self):
        fills = [{"coin": "SOL", "oid": 123, "tid": 1, "time": 151,
                  "side": "B", "dir": "Open Long", "hash": "0x"+"b"*64,
                  "sz": "2", "px": "100"},
                 {"coin": "SOL", "oid": 999, "tid": 2, "time": 152,
                  "side": "A", "dir": "Close Long", "hash": "0x"+"c"*64,
                  "sz": "1", "px": "100"}]
        self.assertEqual(fixture(fills_bytes=json.dumps(fills).encode()).status, "hold")

if __name__ == "__main__":
    unittest.main()
