"""Pure, non-network, no-authority testnet history request planning."""
import json
import sys
import unittest
from unittest.mock import patch

from collector_review import testnet_info_https as existing
from collector_review.offline_history_query_plan import (
    OfflineHistoryQueryScope, plan_testnet_history_query_offline,
)

ACCOUNT = "0x" + "1" * 40
SCOPE = OfflineHistoryQueryScope(account=ACCOUNT)


class OfflineHistoryQueryPlanTests(unittest.TestCase):
    def test_three_documented_query_shapes_are_review_plans_only(self):
        cases = (
            ("orderStatus", dict(oid="0x" + "a" * 32), {
                "type": "orderStatus", "user": ACCOUNT, "oid": "0x" + "a" * 32,
            }),
            ("orderStatus", dict(oid=123), {
                "type": "orderStatus", "user": ACCOUNT, "oid": 123,
            }),
            ("userFillsByTime", dict(start_ms=1000, end_ms=2000), {
                "type": "userFillsByTime", "user": ACCOUNT,
                "startTime": 1000, "endTime": 2000,
                "aggregateByTime": False,
            }),
            ("userFunding", dict(start_ms=1000, end_ms=2000), {
                "type": "userFunding", "user": ACCOUNT,
                "startTime": 1000, "endTime": 2000,
            }),
        )
        for kind, parameters, expected in cases:
            with self.subTest(kind=kind, parameters=parameters):
                result = plan_testnet_history_query_offline(
                    scope=SCOPE, request_type=kind, **parameters,
                )
                self.assertEqual(result.state, "plan_only")
                self.assertEqual(result.endpoint,
                                 "https://api.hyperliquid-testnet.xyz/info")
                self.assertEqual(json.loads(result.request_body), expected)
                self.assertFalse(result.network_authorized)
                self.assertFalse(result.transport_verified)
                self.assertFalse(result.origin_authenticated)
                self.assertFalse(result.history_complete)
                self.assertFalse(result.ownership_verified)
                self.assertFalse(result.close_authorized)
                self.assertFalse(result.submit_authorized)

    def test_invalid_account_environment_and_dex_hold(self):
        for scope in (
            OfflineHistoryQueryScope(account="0x"+"a"*39),
            OfflineHistoryQueryScope(account=ACCOUNT.upper()),
            OfflineHistoryQueryScope(account=ACCOUNT, environment="mainnet"),
            OfflineHistoryQueryScope(account=ACCOUNT, dex="spot"),
            None,
            {"account": ACCOUNT},
        ):
            with self.subTest(scope=scope):
                result = plan_testnet_history_query_offline(
                    scope=scope, request_type="orderStatus", oid=1,
                )
                self.assertEqual(result.state, "hold")
                self.assertIsNone(result.request_body)

    def test_tainted_or_invalid_history_bounds_hold(self):
        cases = (
            ("orderStatus", dict()),
            ("orderStatus", dict(oid=0)),
            ("orderStatus", dict(oid=True)),
            ("orderStatus", dict(oid=2**64)),
            ("orderStatus", dict(oid="0x"+"F"*32)),
            ("orderStatus", dict(oid="0x"+"a"*32, start_ms=1)),
            ("orderStatus", dict(oid="1")),
            ("userFillsByTime", dict(start_ms=0, end_ms=1)),
            ("userFillsByTime", dict(start_ms=True, end_ms=200)),
            ("userFillsByTime", dict(start_ms=200, end_ms=100)),
            ("userFillsByTime", dict(start_ms=1, end_ms=3600002)),
            ("userFillsByTime", dict(start_ms=1, end_ms=100, oid=1)),
            ("userFunding", dict(start_ms=1, end_ms=None)),
            ("userFunding", dict(start_ms="1", end_ms=2)),
            ("userFunding", dict(start_ms=1, end_ms=3600002)),
            ("exchange", dict(start_ms=1, end_ms=100)),
            ("clearinghouseState", dict()),
        )
        for kind, data in cases:
            with self.subTest(kind=kind, data=data):
                result = plan_testnet_history_query_offline(
                    scope=SCOPE, request_type=kind, **data,
                )
                self.assertEqual(result.state, "hold")
                self.assertIsNone(result.request_body)
                self.assertFalse(result.network_authorized)

    def test_existing_collector_allowlist_and_transport_unchanged(self):
        self.assertNotIn("userFunding", existing.APPROVED_TYPES)
        self.assertNotIn("userFillsByTime", existing.APPROVED_TYPES)
        self.assertNotIn("orderStatus", existing.APPROVED_TYPES)
        self.assertIsNone(existing.prepare_testnet_info_body(
            account=ACCOUNT, kind="userFillsByTime",
        ))
        for kind in ("orderStatus", "userFillsByTime", "userFunding"):
            with patch.object(existing.http.client, "HTTPSConnection") as sock, \
                 patch.object(existing.ssl, "create_default_context") as tls:
                self.assertEqual(
                    existing.collect_testnet_readonly_review(
                        account=ACCOUNT, kind=kind,
                    ).state,
                    "hold",
                )
                sock.assert_not_called()
                tls.assert_not_called()
        for module in ("eth_account", "hyperliquid.exchange",
                       "hyperliquid_executor", "intraday_executor",
                       "aggressive_executor"):
            self.assertNotIn(module, sys.modules)


if __name__ == "__main__":
    unittest.main()
