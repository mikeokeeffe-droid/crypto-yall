"""End-to-end fake JSON through offline guards; no trading authorization."""
import json
import unittest
from offline_hyperliquid_synthetic_pipeline import inspect_synthetic_order_pipeline_offline
from offline_hyperliquid_entry_release_boundary import inspect_synthetic_entry_release_offline

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
    order_bytes = json.dumps(order).encode()
    fills_bytes = json.dumps(fills).encode()
    envelope = dict(status_code=200, elapsed_ms=100, body_bytes=len(order_bytes),
                    redirect_count=0, tls_verified=True,
                    expected_url=URL, final_url=URL)
    timeline = dict(query_started_ms=100000, response_received_ms=100100,
                    review_now_ms=100200)
    args = dict(order_bytes=order_bytes,
                fills_bytes=fills_bytes,
                order_request={"type": "orderStatus", "user": ACCOUNT, "oid": 123},
                fills_request={"type": "userFillsByTime", "user": ACCOUNT,
                               "startTime": 100, "endTime": 200,
                               "aggregateByTime": False},
                account=ACCOUNT, coin="SOL", oid=123, direction="long",
                size="2", submitted_at_ms=100, start_ms=100, end_ms=200,
                http_envelopes=(envelope, dict(envelope, body_bytes=len(fills_bytes))),
                capture_times=(timeline, timeline),
                open_orders_known_empty=True, position_snapshot_verified=True)
    args.update(changes)
    # Keep metadata consistent when testing semantic parser failures; otherwise
    # a length mismatch would HOLD before the intended branch is exercised.
    if "http_envelopes" not in changes:
        args["http_envelopes"] = tuple(
            dict(envelope, body_bytes=len(body))
            for envelope, body in zip(
                args["http_envelopes"], (args["order_bytes"], args["fills_bytes"])
            )
        )
    return inspect_synthetic_order_pipeline_offline(**args)

class SyntheticPipelineTests(unittest.TestCase):
    def test_complete_fake_fixture_never_authorizes(self):
        result = fixture()
        self.assertEqual(result.status, "hold")
        self.assertIn("not independently verified", result.reason)
        self.assertNotIn("authorized", result.status)

    def test_full_pipeline_cannot_release_fence_even_with_all_positive_claims(self):
        upstream = fixture()
        result = inspect_synthetic_entry_release_offline(
            pipeline_review=upstream,
            claimed_open_orders_empty=True,
            claimed_position_verified=True,
            claimed_history_complete=True,
            claimed_source_authenticated=True,
        )
        self.assertEqual(upstream.status, "hold")
        self.assertEqual(result.status, "hold")
        self.assertIs(result.allow_entry, False)
        self.assertIs(result.release_fence, False)

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

    def test_body_length_and_capture_duration_mismatch_hold(self):
        valid_order = fixture()
        self.assertEqual(valid_order.status, "hold")
        self.assertIn("not independently verified", valid_order.reason)
        bad = dict(status_code=200, elapsed_ms=100, body_bytes=1,
                   redirect_count=0, tls_verified=True,
                   expected_url=URL, final_url=URL)
        self.assertEqual(fixture(http_envelopes=(bad, bad)).status, "hold")
        slow = dict(query_started_ms=100000, response_received_ms=100101,
                    review_now_ms=100200)
        normal = dict(query_started_ms=100000, response_received_ms=100100,
                      review_now_ms=100200)
        self.assertEqual(fixture(capture_times=(slow, normal)).status, "hold")

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

    def test_other_coin_account_fill_holds_even_with_valid_envelope(self):
        fills = [
            {"coin": "SOL", "oid": 123, "tid": 1, "time": 151,
             "side": "B", "dir": "Open Long", "hash": "0x" + "b"*64,
             "sz": "2", "px": "100"},
            {"coin": "BTC", "oid": 999, "tid": 2, "time": 152,
             "side": "A", "dir": "Close Long", "hash": "0x" + "c"*64,
             "sz": "1", "px": "100"},
        ]
        result = fixture(fills_bytes=json.dumps(fills).encode())
        self.assertEqual(result.status, "hold")
        self.assertIn("account-level", result.reason)

    def test_order_and_fill_requests_cannot_switch_accounts(self):
        wrong_account = "0x" + "f" * 40
        result = fixture(order_request={
            "type": "orderStatus", "user": wrong_account, "oid": 123})
        self.assertEqual(result.status, "hold")
        self.assertIn("order/fill", result.reason)
        result = fixture(fills_request={
            "type": "userFillsByTime", "user": wrong_account,
            "startTime": 100, "endTime": 200, "aggregateByTime": False})
        self.assertEqual(result.status, "hold")
        self.assertIn("order/fill", result.reason)

    def test_order_id_and_fill_window_cannot_be_replayed(self):
        result = fixture(order_request={
            "type": "orderStatus", "user": ACCOUNT, "oid": 999})
        self.assertEqual(result.status, "hold")
        self.assertIn("order/fill", result.reason)
        result = fixture(fills_request={
            "type": "userFillsByTime", "user": ACCOUNT,
            "startTime": 101, "endTime": 200, "aggregateByTime": False})
        self.assertEqual(result.status, "hold")
        self.assertIn("order/fill", result.reason)

    def test_capture_and_http_claims_cannot_be_swapped(self):
        timeline = dict(query_started_ms=100000, response_received_ms=100099,
                        review_now_ms=100200)
        normal = dict(query_started_ms=100000, response_received_ms=100100,
                      review_now_ms=100200)
        result = fixture(capture_times=(timeline, normal))
        self.assertEqual(result.status, "hold")
        self.assertIn("duration", result.reason)

if __name__ == "__main__":
    unittest.main()
