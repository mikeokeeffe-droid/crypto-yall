"""Candidate read-only transport contract remains inert, without HTTP."""
import ast
from dataclasses import replace
from pathlib import Path
import unittest

from offline_testnet_info_snapshot_plan_ci import (
    build_offline_testnet_snapshot_request,
)
from offline_testnet_https_transport_candidate_ci import (
    collect_testnet_info_candidate_offline,
    review_candidate_http_response_offline,
)

ACCOUNT = "0x" + "1" * 40
PATH = Path(__file__).resolve().parents[1] / "offline_testnet_https_transport_candidate_ci.py"


class InertTestnetHTTPSCandidateTests(unittest.TestCase):
    def test_valid_query_stays_hold_even_when_canonical(self):
        for kind in ("openOrders", "allMids", "clearinghouseState",
                     "meta", "spotClearinghouseState"):
            with self.subTest(kind=kind):
                plan=build_offline_testnet_snapshot_request(
                    pinned_account=ACCOUNT, request_type=kind)
                r=collect_testnet_info_candidate_offline(
                    plan=plan,expected_account=ACCOUNT,
                    expected_request_type=kind)
                self.assertEqual(r.state,"hold")
                self.assertIsNotNone(r.request_sha256)
                self.assertFalse(r.submit_authorized)
                self.assertFalse(r.origin_authenticated)
                self.assertFalse(r.ownership_verified)
                self.assertFalse(r.history_complete)
                self.assertIsNone(r.response_sha256)

    def test_mutated_account_and_plan_never_gain_authority(self):
        plan=build_offline_testnet_snapshot_request(
            pinned_account=ACCOUNT,request_type="openOrders")
        for change in (
            {"expected_account":"0x"+"2"*40},
            {"expected_request_type":"market_open"},
            {"plan":replace(plan,network_authorized=True)},
            {"plan":replace(plan,endpoint="https://evil.invalid/info")},
            {"plan":replace(plan,request_json='{"type":"exchange"}')},
            {"plan":object()},
        ):
            with self.subTest(change=change):
                args=dict(plan=plan,expected_account=ACCOUNT,
                          expected_request_type="openOrders")
                args.update(change)
                result=collect_testnet_info_candidate_offline(**args)
                self.assertEqual(result.state,"hold")
                self.assertIsNone(result.request_sha256)
                self.assertFalse(result.submit_authorized)

    def test_mock_response_envelope_bounds(self):
        valid=dict(status=200,content_type="application/json",
                   content_encoding=None,response_bytes=b"[]",
                   expected_response_limit=262144)
        self.assertTrue(review_candidate_http_response_offline(**valid))
        for change in (
            {"status":429},{"status":302},{"content_type":"text/html"},
            {"content_encoding":"gzip"},{"response_bytes":b""},
            {"response_bytes":b" "*262145},
            {"response_bytes":None},{"expected_response_limit":None},
            {"expected_response_limit":1024},
        ):
            with self.subTest(change=change):
                self.assertFalse(review_candidate_http_response_offline(
                    **dict(valid,**change)))

    def test_candidate_source_has_no_network_or_executor_imports(self):
        tree=ast.parse(PATH.read_text(encoding="utf-8"))
        imports=[]
        for node in ast.walk(tree):
            if isinstance(node,ast.Import):
                imports.extend(alias.name for alias in node.names)
            if isinstance(node,ast.ImportFrom):
                imports.append(node.module)
        for name in imports:
            self.assertNotIn(name.split(".")[0],(
                "socket","requests","http","ssl","urllib","hyperliquid",
                "subprocess","eth_account","intraday_executor",
                "aggressive_executor","hyperliquid_executor"))
        self.assertFalse(hasattr(__import__(
            "offline_testnet_https_transport_candidate_ci"),"send_order"))


if __name__=="__main__":
    unittest.main()
