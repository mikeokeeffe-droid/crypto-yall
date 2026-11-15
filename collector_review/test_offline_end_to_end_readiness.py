"""Cross-module end-to-end OFFLINE collector review.

Combines canonical /info request creation, response-shape inspection,
hash-chained fixture audit, and transport denial. No network requests,
real account data, host inspection, credentials, order signing or DB access.
"""
import hashlib
import json
import unittest
from unittest.mock import patch

from collector_review import testnet_info_https as collector
from collector_review.offline_capture_audit import (
    append_offline_audit_event, review_offline_audit_chain,
)

ACCOUNT = "0x" + "1" * 40
OTHER_ACCOUNT = "0x" + "2" * 40


class TestnetOfflineEndToEndTests(unittest.TestCase):
    def test_canonical_request_shape_fixture_audit_and_no_authority(self):
        body = collector.prepare_testnet_info_body(account=ACCOUNT, kind="openOrders")
        self.assertIsInstance(body, bytes)
        self.assertEqual(json.loads(body), {
            "type": "openOrders", "user": ACCOUNT, "dex": "",
        })
        # These synthetic bytes are intentionally NOT authenticated exchange data.
        response = json.dumps([{
            "coin": "SOL", "oid": 123, "timestamp": 1700000000000,
            "side": "B", "sz": "0.5", "limitPx": "120",
        }], separators=(",", ":")).encode()
        with patch.object(collector.ssl, "create_default_context") as tls, \\
             patch.object(collector.http.client, "HTTPSConnection") as socket:
            checked = collector.review_untrusted_http_capture(
                account=ACCOUNT, kind="openOrders", sent_body=body,
                raw_body=response, status_code=200,
                content_type="application/json", content_encoding=None,
                elapsed_ms=100,
            )
            self.assertEqual(checked.state, "fixture_only")
            self.assertFalse(checked.origin_authenticated)
            self.assertFalse(checked.history_complete)
            self.assertFalse(checked.submit_authorized)
            first = append_offline_audit_event(
                account=ACCOUNT, kind="openOrders", request_body=body,
                response_body=response, status_code=200,
                content_type="application/json", content_encoding=None,
                elapsed_ms=100, observed_at_ms=1000, sequence=1,
            )
            self.assertIsNotNone(first)
            second = append_offline_audit_event(
                account=ACCOUNT, kind="openOrders", request_body=body,
                response_body=response, status_code=200,
                content_type="application/json", content_encoding=None,
                elapsed_ms=100, observed_at_ms=2000, sequence=2,
                previous=first,
            )
            self.assertIsNotNone(second)
            chain = review_offline_audit_chain(
                events=[first, second], expected_account=ACCOUNT,
                expected_head_sha256=second.event_sha256,
            )
            self.assertEqual(chain.state, "fixture_only")
            self.assertEqual(chain.events, 2)
            self.assertFalse(chain.origin_authenticated)
            self.assertFalse(chain.ownership_verified)
            self.assertFalse(chain.submit_authorized)
            public = collector.collect_testnet_readonly_review(
                account=ACCOUNT, kind="openOrders",
            )
            self.assertEqual(public.state, "hold")
            with self.assertRaises(PermissionError):
                collector._https_post_restricted_review_only(body)
            with patch.object(collector, "NETWORK_ENABLED", True):
                self.assertEqual(
                    collector.collect_testnet_readonly_review(
                        account=ACCOUNT, kind="openOrders",
                    ).state, "hold",
                )
                with self.assertRaises(PermissionError):
                    collector._https_post_restricted_review_only(body)
            tls.assert_not_called()
            socket.assert_not_called()

    def test_unauthorized_kind_and_account_never_create_capture_or_network(self):
        valid_response = b"[]"
        for account, kind in (
            (ACCOUNT, "exchange"),
            (ACCOUNT, "historicalOrders"),
            (ACCOUNT, "market_close"),
            (OTHER_ACCOUNT.upper(), "openOrders"),
            (ACCOUNT[:-1], "openOrders"),
        ):
            with self.subTest(kind=kind, account=account):
                self.assertIsNone(collector.prepare_testnet_info_body(
                    account=account, kind=kind,
                ))
                self.assertEqual(
                    collector.collect_testnet_readonly_review(
                        account=account, kind=kind,
                    ).state, "hold",
                )
                self.assertIsNone(append_offline_audit_event(
                    account=account, kind=kind,
                    request_body=b"{}", response_body=valid_response,
                    status_code=200, content_type="application/json",
                    content_encoding=None, elapsed_ms=100,
                    observed_at_ms=1000, sequence=1,
                ))

    def test_http_failure_never_promotes_audit_to_trusted(self):
        body = collector.prepare_testnet_info_body(
            account=ACCOUNT, kind="openOrders",
        )
        event = append_offline_audit_event(
            account=ACCOUNT, kind="openOrders", request_body=body,
            response_body=b'{"error":"rate limited"}', status_code=429,
            content_type="application/json", content_encoding=None,
            elapsed_ms=100, observed_at_ms=1000, sequence=1,
        )
        self.assertIsNotNone(event)
        result = review_offline_audit_chain(
            events=[event], expected_account=ACCOUNT,
        )
        self.assertEqual(result.state, "hold")
        self.assertFalse(result.origin_authenticated)
        self.assertFalse(result.submit_authorized)


if __name__ == "__main__":
    unittest.main()
