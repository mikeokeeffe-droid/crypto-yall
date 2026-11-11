"""Standalone, offline-only testnet collector review tests; no real sockets."""
import hashlib
import json
import unittest
from unittest.mock import patch

from collector_review import testnet_info_https as collector

ACCOUNT = "0x" + "1" * 40


class CollectorReviewTests(unittest.TestCase):
    def test_pinned_read_only_query_bodies(self):
        for kind in sorted(collector.APPROVED_TYPES):
            with self.subTest(kind=kind):
                body = collector.prepare_testnet_info_body(account=ACCOUNT, kind=kind)
                parsed = json.loads(body)
                self.assertEqual(parsed["type"], kind)
                self.assertEqual(parsed.get("user"), ACCOUNT if kind in collector.ACCOUNT_TYPES else None)
                self.assertEqual(parsed.get("dex"), "" if kind in collector.PERP_DEX_TYPES else None)
                self.assertEqual(set(parsed), {"type"} |
                    ({"user"} if kind in collector.ACCOUNT_TYPES else set()) |
                    ({"dex"} if kind in collector.PERP_DEX_TYPES else set()))

    def test_no_network_even_when_internals_called(self):
        plan = collector.prepare_testnet_info_body(account=ACCOUNT, kind="openOrders")
        with patch.object(collector.ssl, "create_default_context") as tls, \
             patch.object(collector.http.client, "HTTPSConnection") as socket:
            outcome = collector.collect_testnet_readonly_review(
                account=ACCOUNT, kind="openOrders")
            self.assertEqual(outcome.state, "hold")
            self.assertEqual(outcome.request_sha256, hashlib.sha256(plan).hexdigest())
            self.assertFalse(outcome.origin_authenticated)
            self.assertFalse(outcome.ownership_verified)
            self.assertFalse(outcome.submit_authorized)
            with self.assertRaises(PermissionError):
                collector._https_post_restricted_review_only(plan)
            with patch.object(collector, "NETWORK_ENABLED", True):
                self.assertEqual(collector.collect_testnet_readonly_review(
                    account=ACCOUNT, kind="openOrders").state, "hold")
                with self.assertRaises(PermissionError):
                    collector._https_post_restricted_review_only(plan)
            tls.assert_not_called()
            socket.assert_not_called()

    def test_network_independent_response_capture_always_untrusted(self):
        body = collector.prepare_testnet_info_body(account=ACCOUNT, kind="openOrders")
        raw = b"[]"
        outcome = collector.review_untrusted_http_capture(
            account=ACCOUNT, kind="openOrders", sent_body=body,
            raw_body=raw, status_code=200, content_type="application/json",
            content_encoding=None, elapsed_ms=200)
        self.assertEqual(outcome.state, "fixture_only")
        self.assertEqual(outcome.response_sha256, hashlib.sha256(raw).hexdigest())
        self.assertFalse(outcome.origin_authenticated)
        self.assertFalse(outcome.history_complete)
        self.assertFalse(outcome.submit_authorized)

    def test_invalid_scope_and_order_actions_hold(self):
        for account, kind in (
            ("0x"+"1"*39, "openOrders"),
            (ACCOUNT.upper(), "openOrders"),
            (ACCOUNT, "exchange"), (ACCOUNT, "market_close"),
            (ACCOUNT, "userFillsByTime"), (ACCOUNT, None),
        ):
            with self.subTest(account=account, kind=kind):
                self.assertIsNone(collector.prepare_testnet_info_body(
                    account=account, kind=kind))
                self.assertEqual(collector.collect_testnet_readonly_review(
                    account=account, kind=kind).state, "hold")

    def test_bad_http_frames_and_malformed_json_hold(self):
        body = collector.prepare_testnet_info_body(account=ACCOUNT, kind="openOrders")
        valid = dict(account=ACCOUNT,kind="openOrders",sent_body=body,
                     raw_body=b"[]",status_code=200,
                     content_type="application/json",
                     content_encoding=None,elapsed_ms=200)
        cases = (
            {"status_code":429}, {"status_code":503},
            {"status_code":302}, {"content_encoding":"gzip"},
            {"content_type":"text/html"}, {"elapsed_ms":5000},
            {"raw_body":b""}, {"raw_body":b" "*(collector.MAX_BYTES+1)},
            {"raw_body":b'{"x":1,"x":2}'}, {"raw_body":b'{"x":NaN}'},
            {"raw_body":b'{"orders":[]}'}, {"raw_body":b'[{},4]'},
            {"sent_body":b'{"type":"exchange"}'},
        )
        for changes in cases:
            with self.subTest(changes=str(changes)[:100]):
                outcome=collector.review_untrusted_http_capture(
                    **dict(valid,**changes))
                self.assertEqual(outcome.state,"hold")
                self.assertFalse(outcome.submit_authorized)


if __name__ == "__main__":
    unittest.main()
