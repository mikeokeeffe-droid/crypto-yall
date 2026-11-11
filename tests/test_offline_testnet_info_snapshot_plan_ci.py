"""Offline-only testnet read query plans; no HTTP, wallet, database or orders."""
from dataclasses import replace
import json
import unittest

from offline_testnet_info_snapshot_plan_ci import (
    build_offline_testnet_snapshot_request,
)

ACCOUNT = "0x" + "1" * 40


class OfflineSnapshotRequestTests(unittest.TestCase):
    def plan(self, kind, **changes):
        return build_offline_testnet_snapshot_request(
            pinned_account=changes.pop("pinned_account", ACCOUNT),
            request_type=kind, **changes,
        )

    def test_read_only_testnet_snapshot_allowlist(self):
        expected = {
            "clearinghouseState": {"type":"clearinghouseState", "user":ACCOUNT,"dex":""},
            "openOrders": {"type":"openOrders","user":ACCOUNT,"dex":""},
            "allMids": {"type":"allMids","dex":""},
            "meta": {"type":"meta","dex":""},
            "spotClearinghouseState": {"type":"spotClearinghouseState","user":ACCOUNT},
        }
        for kind, body in expected.items():
            with self.subTest(kind=kind):
                result = self.plan(kind)
                self.assertEqual(result.state,"query_only")
                self.assertEqual(result.endpoint,"https://api.hyperliquid-testnet.xyz/info")
                self.assertEqual(json.loads(result.request_json),body)
                self.assertFalse(result.network_authorized)
                self.assertFalse(result.origin_authenticated)
                self.assertFalse(result.history_complete)
                self.assertFalse(result.ownership_verified)
                self.assertFalse(result.submit_authorized)

    def test_invalid_account_mainnet_dex_and_trading_actions_hold(self):
        cases = (
            ("clearinghouseState",{"pinned_account":"0x"+"2"*39}),
            ("clearinghouseState",{"pinned_account":ACCOUNT.upper()}),
            ("clearinghouseState",{"pinned_environment":"mainnet"}),
            ("clearinghouseState",{"pinned_dex":"other"}),
            ("clearinghouseState",{"pinned_dex":None}),
            ("exchange",{}),("market_open",{}),("market_close",{}),
            ("updateLeverage",{}),("cancel",{}),("orderStatus",{}),
            ("userFillsByTime",{}),(None,{}),("",{}),
        )
        for kind, change in cases:
            with self.subTest(kind=kind, change=change):
                r=self.plan(kind,**change)
                self.assertEqual(r.state,"hold")
                self.assertIsNone(r.request_json)
                self.assertFalse(r.network_authorized)
                self.assertFalse(r.submit_authorized)

    def test_cannot_construct_custom_network_host_or_order_parameters(self):
        r=self.plan("openOrders")
        self.assertFalse(hasattr(r,"http_client"))
        self.assertFalse(hasattr(r,"send"))
        self.assertFalse(hasattr(r,"post"))
        self.assertFalse(hasattr(r,"sign"))
        self.assertFalse(hasattr(r,"market_close"))
        self.assertNotIn("private",r.request_json)
        self.assertNotIn("/exchange",r.endpoint)


if __name__ == "__main__":
    unittest.main()
