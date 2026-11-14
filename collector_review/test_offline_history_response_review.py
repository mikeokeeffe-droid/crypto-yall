"""Fixture-only response validation: no network, ownership or order rights."""
import json
import unittest
from dataclasses import replace
from unittest.mock import patch

from collector_review.offline_history_query_plan import (
    OfflineHistoryQueryScope, plan_testnet_history_query_offline,
)
from collector_review.offline_history_response_review import (
    inspect_history_fixture_response_offline,
)
from collector_review import testnet_info_https as original_collector

ACCOUNT = "0x" + "1" * 40
CLOID = "0x" + "a" * 32
HASH = "0x" + "b" * 64
SCOPE = OfflineHistoryQueryScope(account=ACCOUNT)


def plan(kind, **kwargs):
    return plan_testnet_history_query_offline(
        scope=SCOPE, request_type=kind, **kwargs,
    )


def valid_order():
    return {
        "status": "order",
        "order": {
            "order": {
                "oid": 42, "cloid": CLOID, "coin": "SOL",
                "side": "B", "timestamp": 1200, "origSz": "0.1",
                "sz": "0", "limitPx": "125",
                "reduceOnly": False,
            },
            "status": "filled", "statusTimestamp": 1300,
        },
    }


def valid_fill(tid=1, timestamp=1500):
    return {
        "coin": "SOL", "oid": 42, "tid": tid, "time": timestamp,
        "side": "B", "dir": "Open Long", "crossed": True,
        "sz": "0.1", "px": "125", "startPosition": "0",
        "closedPnl": "0", "fee": "0.001", "feeToken": "USDC",
        "hash": HASH,
    }


def valid_funding(timestamp=1500):
    return {
        "time": timestamp, "hash": HASH,
        "delta": {
            "type": "funding", "coin": "SOL", "usdc": "-0.02",
            "szi": "0.1", "fundingRate": "0.00001",
            "nSamples": None,
        },
    }


def inspect(kind, payload, **kwargs):
    parameters = (
        {"oid": CLOID} if kind == "orderStatus"
        else {"start_ms": 1000, "end_ms": 2000}
    )
    reviewed_plan = plan(kind, **parameters)
    options = dict(
        plan=reviewed_plan,
        pinned_scope=SCOPE,
        pinned_request_type=kind,
        pinned_oid=parameters.get("oid"),
        pinned_start_ms=parameters.get("start_ms"),
        pinned_end_ms=parameters.get("end_ms"),
        raw_body=json.dumps(payload).encode(),
        status_code=200, content_type="application/json",
    )
    options.update(kwargs)
    return inspect_history_fixture_response_offline(**options)


class OfflineHistoryResponseTests(unittest.TestCase):
    def assert_untrusted(self, outcome):
        self.assertFalse(outcome.origin_authenticated)
        self.assertFalse(outcome.history_complete)
        self.assertFalse(outcome.ownership_verified)
        self.assertFalse(outcome.close_authorized)
        self.assertFalse(outcome.submit_authorized)

    def test_valid_documented_shape_is_only_fixture(self):
        for kind, payload in (
            ("orderStatus", valid_order()),
            ("userFillsByTime", [valid_fill()]),
            ("userFunding", [valid_funding()]),
        ):
            with self.subTest(kind=kind):
                outcome = inspect(kind, payload)
                self.assertEqual(outcome.state, "fixture_only")
                self.assertIsNotNone(outcome.response_sha256)
                self.assert_untrusted(outcome)

    def test_empty_history_is_not_proof_of_zero_activity(self):
        for kind in ("userFillsByTime", "userFunding"):
            with self.subTest(kind=kind):
                outcome = inspect(kind, [])
                self.assertEqual(outcome.state, "fixture_only")
                self.assertEqual(outcome.record_count, 0)
                self.assert_untrusted(outcome)

    def test_reject_wrong_order_cloid_and_ambiguous_status(self):
        for bad in (
            {"status": "unknownOid"},
            {**valid_order(), "status": "unknown"},
            {**valid_order(), "order": {
                **valid_order()["order"], "status": "unknownFutureStatus"}},
            {**valid_order(), "order": {
                **valid_order()["order"], "order": {
                    **valid_order()["order"]["order"], "cloid": "0x" + "c"*32}}},
            {**valid_order(), "order": {
                **valid_order()["order"], "order": {
                    **valid_order()["order"]["order"], "oid": True}}},
        ):
            with self.subTest(bad=bad):
                r = inspect("orderStatus", bad)
                self.assertEqual(r.state, "hold")
                self.assert_untrusted(r)

    def test_fill_overlap_duplicate_and_saturated_page_hold(self):
        for bad in (
            [valid_fill(1), valid_fill(1)],
            [valid_fill(timestamp=2001)],
            [{**valid_fill(), "sz": "NaN"}],
            [{**valid_fill(), "tid": True}],
            [{**valid_fill(), "hash": "0x123"}],
            [valid_fill(i + 1) for i in range(2000)],
        ):
            with self.subTest(count=len(bad)):
                r = inspect("userFillsByTime", bad)
                self.assertEqual(r.state, "hold")
                self.assert_untrusted(r)

    def test_funding_schema_duplicates_and_saturated_page_hold(self):
        for bad in (
            [valid_funding(), valid_funding()],
            [valid_funding(timestamp=2200)],
            [{**valid_funding(), "delta": {
                **valid_funding()["delta"], "usdc": "NaN"}}],
            [{**valid_funding(), "delta": {
                **valid_funding()["delta"], "type": "transfer"}}],
            [valid_funding(1500 + i) for i in range(500)],
        ):
            with self.subTest(count=len(bad)):
                r = inspect("userFunding", bad)
                self.assertEqual(r.state, "hold")
                self.assert_untrusted(r)

    def test_invalid_transport_frame_or_tampered_plan_hold(self):
        good = valid_order()
        good_plan = plan("orderStatus", oid=CLOID)
        for changes in (
            {"status_code": 429},
            {"status_code": 500},
            {"status_code": 302},
            {"content_encoding": "gzip"},
            {"content_type": "text/html"},
            {"raw_body": b""},
            {"raw_body": b'{"status":"order","status":"order"}'},
            {"raw_body": b'{"data": NaN}'},
            {"plan": replace(good_plan, request_type="userFunding")},
            {"plan": replace(good_plan, network_authorized=True)},
            {"plan": replace(good_plan, transport_verified=True)},
        ):
            with self.subTest(changes=str(changes)[:80]):
                r = inspect("orderStatus", good, **changes)
                self.assertEqual(r.state, "hold")
                self.assert_untrusted(r)

    def test_valid_plan_cannot_replace_independently_pinned_request(self):
        for kind, pinned, mismatches in (
            ("orderStatus", {"oid": CLOID}, (
                {"oid": "0x" + "c" * 32},
                {"oid": 42},
            )),
            ("userFillsByTime", {"start_ms": 1000, "end_ms": 2000}, (
                {"start_ms": 1001, "end_ms": 2000},
                {"start_ms": 1000, "end_ms": 1999},
            )),
            ("userFunding", {"start_ms": 1000, "end_ms": 2000}, (
                {"start_ms": 1001, "end_ms": 2000},
                {"start_ms": 1000, "end_ms": 1999},
            )),
        ):
            payload = (
                valid_order() if kind == "orderStatus" else
                [valid_fill()] if kind == "userFillsByTime" else
                [valid_funding()]
            )
            baseline = plan(kind, **pinned)
            good = inspect_history_fixture_response_offline(
                plan=baseline, pinned_scope=SCOPE,
                pinned_request_type=kind,
                pinned_oid=pinned.get("oid"),
                pinned_start_ms=pinned.get("start_ms"),
                pinned_end_ms=pinned.get("end_ms"),
                raw_body=json.dumps(payload).encode(),
                status_code=200, content_type="application/json",
            )
            self.assertEqual(good.state, "fixture_only")
            self.assert_untrusted(good)
            for changes in mismatches:
                with self.subTest(kind=kind, changes=changes):
                    forged = plan(kind, **changes)
                    result = inspect_history_fixture_response_offline(
                        plan=forged, pinned_scope=SCOPE,
                        pinned_request_type=kind,
                        pinned_oid=pinned.get("oid"),
                        pinned_start_ms=pinned.get("start_ms"),
                        pinned_end_ms=pinned.get("end_ms"),
                        raw_body=json.dumps(payload).encode(),
                        status_code=200, content_type="application/json",
                    )
                    self.assertEqual(result.state, "hold")
                    self.assert_untrusted(result)

    def test_self_consistent_wrong_account_and_type_do_not_override_pins(self):
        forged_scope = OfflineHistoryQueryScope(account="0x" + "2" * 40)
        variants = (
            (plan_testnet_history_query_offline(
                scope=forged_scope, request_type="orderStatus", oid=CLOID,
            ), SCOPE, "orderStatus", CLOID, None, None),
            (plan("userFunding", start_ms=1000, end_ms=2000),
             SCOPE, "userFillsByTime", None, 1000, 2000),
        )
        for forged, scope, kind, oid, start, end in variants:
            with self.subTest(kind=kind):
                r = inspect_history_fixture_response_offline(
                    plan=forged, pinned_scope=scope,
                    pinned_request_type=kind, pinned_oid=oid,
                    pinned_start_ms=start, pinned_end_ms=end,
                    raw_body=b"[]", status_code=200,
                    content_type="application/json",
                )
                self.assertEqual(r.state, "hold")
                self.assert_untrusted(r)

    def test_real_collector_remains_unreachable(self):
        with patch.object(original_collector.http.client, "HTTPSConnection") as socket, \
             patch.object(original_collector.ssl, "create_default_context") as tls:
            self.assertEqual(
                original_collector.collect_testnet_readonly_review(
                    account=ACCOUNT, kind="userFillsByTime",
                ).state, "hold",
            )
            socket.assert_not_called()
            tls.assert_not_called()


if __name__ == "__main__":
    unittest.main()
