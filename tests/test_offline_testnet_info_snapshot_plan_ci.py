"""Offline-only testnet read query plans; no HTTP, wallet, database or orders."""
from dataclasses import replace
import json
import unittest

from offline_testnet_info_snapshot_plan_ci import (
    build_offline_testnet_snapshot_request,
    preflight_testnet_info_transport_offline,
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


    def test_network_disabled_transport_preflight(self):
        import hashlib
        for kind, weight in (
            ("clearinghouseState", 2),
            ("openOrders", 20),
            ("allMids", 2),
            ("meta", 20),
            ("spotClearinghouseState", 2),
        ):
            with self.subTest(kind=kind):
                plan = self.plan(kind)
                preflight = preflight_testnet_info_transport_offline(
                    plan=plan, expected_account=ACCOUNT,
                    expected_request_type=kind,
                )
                self.assertEqual(preflight.state, "dry_run_only")
                self.assertEqual(preflight.method, "POST")
                self.assertEqual(preflight.endpoint,
                                 "https://api.hyperliquid-testnet.xyz/info")
                self.assertEqual(preflight.estimated_ip_weight, weight)
                self.assertEqual(preflight.timeout_ms, 4000)
                self.assertEqual(preflight.max_response_bytes, 262144)
                self.assertEqual(
                    preflight.canonical_request_sha256,
                    hashlib.sha256(plan.request_json.encode()).hexdigest(),
                )
                for field in (
                    "redirects_allowed", "inherited_proxies_allowed",
                    "automatic_retries_allowed", "network_authorized",
                    "origin_authenticated", "history_complete",
                    "ownership_verified", "submit_authorized",
                ):
                    self.assertFalse(getattr(preflight, field))

    def test_preflight_rejects_network_request_spoofing_and_replay_scope(self):
        from dataclasses import replace
        plan = self.plan("openOrders")
        cases = [
            {"plan": plan, "allow_network": True},
            {"plan": plan, "expected_account": "0x" + "2" * 40},
            {"plan": plan, "expected_request_type": "market_open"},
            {"plan": replace(plan, endpoint="https://attacker.invalid/info")},
            {"plan": replace(plan, request_json='{"type":"exchange"}')},
            {"plan": replace(plan, network_authorized=True)},
            {"plan": replace(plan, origin_authenticated=True)},
            {"plan": replace(plan, submit_authorized=True)},
            {"plan": replace(plan, request_type="allMids")},
        ]
        for changes in cases:
            with self.subTest(changes=changes):
                args = {
                    "plan": plan, "expected_account": ACCOUNT,
                    "expected_request_type": "openOrders",
                }
                args.update(changes)
                result = preflight_testnet_info_transport_offline(**args)
                self.assertEqual(result.state, "hold")
                self.assertIsNone(result.endpoint)
                self.assertFalse(result.network_authorized)
                self.assertFalse(result.submit_authorized)



if __name__ == "__main__":
    unittest.main()
