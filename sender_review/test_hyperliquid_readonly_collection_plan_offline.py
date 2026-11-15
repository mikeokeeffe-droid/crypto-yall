"""No-network tests for proposed Hyperliquid read-only collector boundaries."""
import ast
import json
from pathlib import Path
import unittest

from sender_review.hyperliquid_readonly_collection_plan_offline import (
    plan_offline_readonly_testnet_collection,
    inspect_historical_coverage_fixture_offline,
)

ACCOUNT="0x"+"1"*40
CLOID="0x"+"b"*32


def plan(**kwargs):
    args=dict(account=ACCOUNT,start_time_ms=1000,end_time_ms=2000)
    args.update(kwargs)
    return plan_offline_readonly_testnet_collection(**args)


class OfflineCollectorPlanTests(unittest.TestCase):
    def assert_plan_no_authority(self, result):
        self.assertEqual(result.state,"HOLD")
        for flag in (
            "history_complete","position_ownership_verified",
            "runtime_identity_authenticated","exchange_transport_authenticated",
            "real_readonly_service_deployed","submit_authorized",
            "close_authorized","retry_authorized","signing_enabled",
        ):
            self.assertFalse(getattr(result,flag),flag)
        for envelope in result.queries:
            self.assertFalse(envelope.network_request_performed)
            self.assertFalse(envelope.contains_trading_key)
            self.assertFalse(envelope.authorizes_order)
            self.assertEqual((envelope.scheme,envelope.host,envelope.path,envelope.method),
                             ("https","api.hyperliquid-testnet.xyz","/info","POST"))
            self.assertEqual(envelope.content_type,"application/json")

    def test_exact_allowlisted_read_only_request_sequence(self):
        result=plan()
        self.assert_plan_no_authority(result)
        self.assertEqual([json.loads(x.body_json)["type"] for x in result.queries],[
            "clearinghouseState","openOrders","historicalOrders",
            "userFillsByTime","clearinghouseState",
        ])
        self.assertTrue(all(json.loads(x.body_json)["user"]==ACCOUNT
                            for x in result.queries))
        self.assertEqual(json.loads(result.queries[3].body_json)["startTime"],1000)
        self.assertEqual(json.loads(result.queries[3].body_json)["endTime"],2000)

    def test_optional_order_lookup_is_still_read_only(self):
        result=plan(optional_order_lookup=CLOID)
        self.assert_plan_no_authority(result)
        self.assertEqual([json.loads(x.body_json)["type"] for x in result.queries],[
            "clearinghouseState","openOrders","historicalOrders",
            "userFillsByTime","orderStatus","clearinghouseState",
        ])
        self.assertEqual(json.loads(result.queries[4].body_json)["oid"],CLOID)

    def test_wrong_scope_or_time_or_oid_never_builds_query(self):
        for case in (
            {"account":"0x"+"2"*40},
            {"account":True},
            {"start_time_ms":-1},
            {"start_time_ms":2000},
            {"start_time_ms":True},
            {"end_time_ms":1000},
            {"end_time_ms":9007199254740992},
            {"optional_order_lookup":"0x123"},
            {"optional_order_lookup":123},
        ):
            with self.subTest(case=case):
                result=plan(**case)
                self.assert_plan_no_authority(result)
                self.assertEqual(result.queries,())

    def test_history_caps_and_false_completeness_assertions(self):
        for typ in ("historicalOrders","userFillsByTime"):
            for count in (0,1,1999,2000):
                for claimed_complete in (False,True):
                    with self.subTest(typ=typ,count=count,claimed=claimed_complete):
                        result=inspect_historical_coverage_fixture_offline(
                            request_type=typ,record_count=count,
                            claimed_oldest_reached=True,
                            claimed_full_history=claimed_complete,
                        )
                        self.assertEqual(result.state,"HOLD")
                        self.assertFalse(result.independent_archive_proven)
                        self.assertFalse(result.ownership_verified)
                        self.assertFalse(result.close_authorized)
                        self.assertFalse(result.retry_authorized)
                        self.assertEqual(result.possible_truncation,count==2000)
        extra=inspect_historical_coverage_fixture_offline(
            request_type="userFillsByTime",record_count=2001,
            claimed_oldest_reached=False,claimed_full_history=False,
        )
        self.assertEqual(extra.state,"HOLD")
        self.assertIn("cap exceeded",extra.reason)

    def test_invalid_history_claims_hold(self):
        for args in (
            ("userFills",20,False,False),
            ("historicalOrders",-1,False,False),
            ("historicalOrders",True,False,False),
            ("historicalOrders",20,1,False),
            ("historicalOrders",20,False,"true"),
        ):
            result=inspect_historical_coverage_fixture_offline(
                request_type=args[0],record_count=args[1],
                claimed_oldest_reached=args[2],claimed_full_history=args[3],
            )
            self.assertEqual(result.state,"HOLD")
            self.assertFalse(result.ownership_verified)

    def test_collector_module_imports_no_network_sdk_or_signer(self):
        source=Path(__file__).with_name(
            "hyperliquid_readonly_collection_plan_offline.py").read_text("utf-8")
        modules=set()
        for node in ast.walk(ast.parse(source)):
            if isinstance(node,ast.Import):
                modules.update(x.name for x in node.names)
            elif isinstance(node,ast.ImportFrom):
                modules.add(node.module)
        self.assertEqual(modules,{"dataclasses","json","re"})


if __name__=="__main__":
    unittest.main()
