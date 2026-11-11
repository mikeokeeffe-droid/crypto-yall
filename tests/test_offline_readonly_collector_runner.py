"""Offline-only end-to-end collector handoff tests; no HTTP or credentials."""
from dataclasses import replace
import json
import unittest
import uuid

from offline_readonly_collector_contract import (
    OfflineCollectorScope, build_offline_info_plan,
)
from offline_readonly_collector_runner import (
    OfflineFixtureTransportResult, run_offline_info_capture,
)

ACCOUNT = "0x" + "1" * 40
CLOID = "0x" + "a" * 32
TOKEN = uuid.UUID("12345678-1234-4234-8234-123456789abc")
ENDPOINT = "https://api.hyperliquid.xyz/info"


class OfflineCollectorRunnerTests(unittest.TestCase):
    def setUp(self):
        self.scope = OfflineCollectorScope(
            environment="mainnet", account=ACCOUNT, token=TOKEN,
            fence=4, cloid=CLOID,
        )
        self.fills_plan = build_offline_info_plan(
            scope=self.scope, request_type="userFillsByTime",
            start_ms=1000, end_ms=1500,
        )
        self.order_plan = build_offline_info_plan(
            scope=self.scope, request_type="orderStatus",
        )
        self.fill = {
            "coin": "SOL", "oid": 1001, "tid": 42, "time": 1100,
            "side": "B", "dir": "Open Long", "hash": "0x" + "a" * 64,
            "sz": "0.025", "px": "100",
        }
        self.intent = {
            "bot": "daily", "environment": "mainnet",
            "account": ACCOUNT, "dex": "", "coin": "SOL",
            "action": "open_long", "requested_size": "0.025",
            "intent_token": str(TOKEN), "fence_token": 4,
            "cloid": CLOID, "submitted_at_ms": 1000,
        }

    def fixture(self, body=None, **changes):
        if body is None:
            body = json.dumps([self.fill], separators=(",", ":")).encode()
        return replace(OfflineFixtureTransportResult(
            status_code=200, final_url=ENDPOINT, elapsed_ms=200,
            content_type="application/json", body=body,
        ), **changes)

    def review_capture(self, *, plan=None, fixture_result=None,
            captured_at_ms=1150, now_ms=1200, pinned_intent=None):
        return run_offline_info_capture(
            plan=plan or self.fills_plan,
            fixture_result=fixture_result or self.fixture(),
            captured_at_ms=captured_at_ms, now_ms=now_ms,
            pinned_intent=pinned_intent,
        )

    def test_valid_documented_fill_fixture_is_review_only(self):
        result=self.review_capture()
        self.assertEqual(result.state, "review_only")
        self.assertIsNotNone(result.response_sha256)
        self.assertFalse(result.origin_authenticated)
        self.assertFalse(result.history_complete)
        self.assertFalse(result.ownership_verified)
        self.assertFalse(result.submit_authorized)

    def test_cloid_to_oid_structural_match_remains_hold(self):
        response = {
            "status": "order",
            "order": {
                "status": "filled", "statusTimestamp": 1140,
                "order": {
                    "oid": 1001, "coin": "SOL", "side": "B",
                    "cloid": CLOID, "origSz": "0.025", "sz": "0",
                    "reduceOnly": False, "timestamp": 1050,
                },
            },
        }
        result = self.review_capture(
            plan=self.order_plan, pinned_intent=self.intent,
            fixture_result=self.fixture(
                body=json.dumps(response).encode(),
            ),
        )
        self.assertEqual(result.state, "hold")
        self.assertTrue(result.structurally_consistent)
        self.assertEqual(result.observed_oid, 1001)
        self.assertFalse(result.submit_authorized)
        self.assertFalse(result.ownership_verified)

    def test_order_without_intent_or_with_foreign_intent_holds(self):
        self.assertEqual(self.review_capture(
            plan=self.order_plan,
        ).state, "hold")
        foreign = dict(self.intent, account="0x" + "2" * 40)
        self.assertFalse(self.review_capture(
            plan=self.order_plan, pinned_intent=foreign,
        ).structurally_consistent)
        self.assertEqual(self.review_capture(pinned_intent=self.intent).state, "hold")

    def test_network_errors_redirects_proxies_rate_limits_and_tls_hold(self):
        cases = (
            {"network_error": "timeout"},
            {"status_code": 429},
            {"status_code": 500},
            {"redirect_count": 1},
            {"final_url": "https://invalid.example/info"},
            {"tls_verified": False},
            {"content_type": "text/html"},
            {"elapsed_ms": 10001},
            {"proxy_used": True},
            {"network_authorized": True},
        )
        for change in cases:
            with self.subTest(change=change):
                result = self.review_capture(fixture_result=self.fixture(**change))
                self.assertEqual(result.state, "hold")
                self.assertFalse(result.submit_authorized)

    def test_malformed_saturated_and_out_of_window_fills_hold(self):
        wrong_time = dict(self.fill, time=1501)
        inputs = (
            b"[]x",
            b'{"not":"a fill array"}',
            json.dumps([wrong_time]).encode(),
            json.dumps([self.fill, self.fill]).encode(),
            json.dumps([self.fill] * 2000).encode(),
            b"",
            b" " * 262145,
        )
        for body in inputs:
            with self.subTest(size=len(body)):
                result = self.review_capture(fixture_result=self.fixture(body=body))
                self.assertEqual(result.state, "hold")
                self.assertFalse(result.submit_authorized)

    def test_stale_capture_and_wrong_plan_hold(self):
        self.assertEqual(
            self.review_capture(captured_at_ms=100, now_ms=70000).state,
            "hold",
        )
        self.assertEqual(
            self.review_capture(captured_at_ms=1300, now_ms=1200).state,
            "hold",
        )
        other_plan = replace(self.fills_plan,
                             endpoint="https://invalid.example/info")
        self.assertEqual(self.review_capture(plan=other_plan).state, "hold")

    def test_runner_has_no_http_or_exchange_client(self):
        import offline_readonly_collector_runner as module
        for method in ("post", "request", "send_order", "market_open",
                       "market_close", "release_fence", "sign"):
            self.assertFalse(hasattr(module,method))


if __name__ == "__main__":
    unittest.main()
