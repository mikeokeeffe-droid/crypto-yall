"""Network-disabled read-only collector contract regression tests."""
from dataclasses import replace
import hashlib
import json
import unittest
import uuid

from offline_readonly_collector_contract import (
    OfflineCollectorScope, build_offline_info_plan,
    record_fixture_response_offline, inspect_fixture_response_offline,
)

ACCOUNT="0x"+"1"*40
CLOID="0x"+"a"*32
TOKEN=uuid.UUID("12345678-1234-4234-8234-123456789abc")
BODY_ORDER=b'{"status":"fixture"}'
BODY_FILLS=b'[{"tid":42}]'


class OfflineCollectorContractTests(unittest.TestCase):
    def setUp(self):
        self.scope=OfflineCollectorScope(
            environment="mainnet",account=ACCOUNT,token=TOKEN,
            fence=4,cloid=CLOID,
        )

    def plan(self, kind="orderStatus", **changes):
        return build_offline_info_plan(
            scope=changes.pop("scope",self.scope),
            request_type=kind, **changes,
        )

    def capture(self, plan=None, raw=BODY_ORDER, stamp=1100, status=200):
        plan=plan or self.plan()
        return record_fixture_response_offline(
            plan=plan,raw_response=raw,captured_at_ms=stamp,
            status_code=status,
        )

    def test_fixed_order_query_pins_account_and_preallocated_cloid(self):
        q=self.plan()
        self.assertEqual(q.status,"query_only")
        self.assertFalse(q.network_authorized)
        self.assertEqual(q.endpoint,"https://api.hyperliquid.xyz/info")
        self.assertEqual(json.loads(q.request_json),{
            "type":"orderStatus","user":ACCOUNT,"oid":CLOID,
        })
        self.assertNotIn("exchange",q.endpoint)

    def test_bounded_inclusive_fill_query(self):
        q=self.plan("userFillsByTime",start_ms=1000,end_ms=1500)
        self.assertEqual(q.status,"query_only")
        self.assertEqual(json.loads(q.request_json),{
            "type":"userFillsByTime","user":ACCOUNT,
            "startTime":1000,"endTime":1500,"aggregateByTime":False,
        })
        c=self.capture(q,raw=BODY_FILLS)
        self.assertEqual(c.request_sha256,
                         hashlib.sha256(q.request_json.encode()).hexdigest())
        result=inspect_fixture_response_offline(
            plan=q,envelope=c,now_ms=1200,
        )
        self.assertEqual(result.status,"review_only")
        self.assertFalse(result.origin_authenticated)
        self.assertFalse(result.history_complete)
        self.assertFalse(result.ownership_verified)
        self.assertFalse(result.submit_authorized)

    def test_scope_and_query_allowlist_fail_closed(self):
        bad_scopes=(
            replace(self.scope,environment="unknown"),
            replace(self.scope,account="0x"+"2"*39),
            replace(self.scope,dex="other"),
            replace(self.scope,token="not-a-uuid"),
            replace(self.scope,fence=0),
            replace(self.scope,cloid="0x"+"b"*31),
        )
        for scope in bad_scopes:
            with self.subTest(scope=scope):
                self.assertEqual(self.plan(scope=scope).status,"hold")
        for kind in ("exchange","openOrders","userRole","",None):
            with self.subTest(kind=kind):
                self.assertEqual(self.plan(kind).status,"hold")
        self.assertEqual(self.plan(start_ms=1,end_ms=2).status,"hold")
        self.assertEqual(self.plan(
            "userFillsByTime",start_ms=1000,end_ms=3601001
        ).status,"hold")
        self.assertEqual(self.plan(
            "userFillsByTime",start_ms=True,end_ms=5
        ).status,"hold")

    def test_tampering_plan_response_or_manifest_never_upgrades(self):
        q=self.plan()
        good=self.capture(q)
        self.assertEqual(
            inspect_fixture_response_offline(
                plan=q,envelope=good,now_ms=1200,
            ).status,"review_only",
        )
        for bad_plan in (
            replace(q,request_json='{"type":"exchange"}'),
            replace(q,endpoint="https://attacker.invalid/info"),
            replace(q,network_authorized=True),
            replace(q,request_type="exchange"),
        ):
            with self.subTest(plan=bad_plan):
                self.assertEqual(inspect_fixture_response_offline(
                    plan=bad_plan,envelope=good,now_ms=1200,
                ).status,"hold")
        altered=replace(good,raw_response=b'{"status":"changed"}')
        self.assertEqual(inspect_fixture_response_offline(
            plan=q,envelope=altered,now_ms=1200,
        ).status,"hold")
        for key,val in (
            ("account","0x"+"2"*40),("origin","hyperliquid"),
            ("transport_verified",True),("status_code",429),
        ):
            with self.subTest(key=key):
                invalid=replace(good,manifest=dict(good.manifest,**{key:val}))
                self.assertEqual(inspect_fixture_response_offline(
                    plan=q,envelope=invalid,now_ms=1200,
                ).status,"hold")

    def test_stale_and_malformed_responses_fail_closed(self):
        q=self.plan()
        for raw in (b"",b"{",b"[]",b'{"x":NaN}',
                    b'{"x":1,"x":2}'):
            with self.subTest(raw=raw):
                capture=self.capture(q,raw=raw)
                if raw:
                    self.assertIsNotNone(capture)
                    self.assertEqual(inspect_fixture_response_offline(
                        plan=q,envelope=capture,now_ms=1200,
                    ).status,"hold")
                else:
                    self.assertIsNone(capture)
        old=self.capture(q,stamp=1)
        self.assertEqual(inspect_fixture_response_offline(
            plan=q,envelope=old,now_ms=70000,
        ).status,"hold")
        self.assertIsNone(self.capture(
            replace(q,network_authorized=True),
        ))

    def test_collector_has_no_network_or_signer_capability(self):
        import offline_readonly_collector_contract as module
        for name in ("send_order","market_open","request","post",
                     "close_position","release_fence","sign"):
            self.assertFalse(hasattr(module,name))


if __name__=="__main__":
    unittest.main()
