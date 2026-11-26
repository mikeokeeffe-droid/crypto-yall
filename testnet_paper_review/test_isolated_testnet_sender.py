"""No-key isolated sender contract tests. Trading remains hard-disabled."""
import unittest
from dataclasses import replace
from testnet_paper_review.isolated_testnet_sender import (
    ACTIVATION_HOLD, ExactOneShotApproval, SenderHold, send_once,
    verify_exact_request
)
from testnet_paper_review.offline_client_order_bundle import build_offline_client_order_bundle
from testnet_paper_review.test_offline_signer_boundary import valid

from testnet_paper_review.testnet_sdk_server_client_preflight import AGENT_ADDRESS
SIGNER=AGENT_ADDRESS

def sample():
    args=valid()
    bundle=build_offline_client_order_bundle(**args)
    approval=ExactOneShotApproval(
        account=bundle.account,endpoint=bundle.endpoint,
        signer_address=SIGNER,code_sha=args["code_sha"],
        request_id=args["intent"].request_id,plan_hash=bundle.plan_hash,
        max_notional="20",expires_at_s=args["now_s"]+30,
        operator_approved=True
    )
    return bundle,approval,args["now_s"]

class TestDisabledSender(unittest.TestCase):
    def test_unconditionally_blocked_no_sdk_or_journal_call(self):
        self.assertTrue(ACTIVATION_HOLD)
        bundle,approval,now_s=sample()
        class NeverUse:
            def __getattr__(self,name):raise AssertionError("unexpected send access")
        with self.assertRaises(SenderHold):
            send_once(exchange=NeverUse(),journal=NeverUse(),
                      bundle=bundle,approval=approval,now_s=now_s)
    def test_review_is_never_permission(self):
        bundle,approval,now_s=sample()
        self.assertIn("HOLD",verify_exact_request(
            bundle=bundle,approval=approval,now_s=now_s))
    def test_mainnet_expired_missing_approval_and_extra_amount_fail(self):
        bundle,approval,now_s=sample()
        variants=(
            {"endpoint":"https://api.hyperliquid.xyz"},
            {"account":"0x"+"0"*40},
            {"operator_approved":False},
            {"max_notional":"21"},
            {"expires_at_s":now_s},
            {"signer_address":bundle.account},
            {"plan_hash":"0"*64},
            {"request_id":"bad/id"},
        )
        for v in variants:
            with self.subTest(v=v),self.assertRaises(SenderHold):
                verify_exact_request(bundle=bundle,
                                     approval=replace(approval,**v),now_s=now_s)
    def test_protected_ack_requires_full_entry_and_both_exit_orders(self):
        from testnet_paper_review.isolated_testnet_sender import acknowledge_exact_protected_order
        bundle,approval,now_s=sample()
        size=bundle.orders[0]["sz"]
        response={"status":"ok","response":{"data":{"statuses":[
            {"filled":{"oid":101,"totalSz":size}},
            {"resting":{"oid":102}},
            {"resting":{"oid":103}}
        ]}}}
        self.assertTrue(acknowledge_exact_protected_order(response=response,bundle=bundle))
        from copy import deepcopy
        variants=[]
        for change in ("partial","missing_stop","duplicate_oid","missing_tp","error",
                       "unknown","bad_total","extra","wrong_type"):
            x=deepcopy(response)
            rows=x["response"]["data"]["statuses"]
            if change=="partial":rows[0]["filled"]["totalSz"]="0.001"
            if change=="missing_stop":rows.pop()
            if change=="duplicate_oid":rows[2]["resting"]["oid"]=102
            if change=="missing_tp":rows[1]={"error":"rejected"}
            if change=="error":x["status"]="err"
            if change=="unknown":x["response"]={}
            if change=="bad_total":rows[0]["filled"]["totalSz"]="NaN"
            if change=="extra":rows.append({"resting":{"oid":104}})
            if change=="wrong_type":rows[2]["resting"]["oid"]="103"
            variants.append((change,x))
        for reason,bad in variants:
            with self.subTest(reason=reason):
                self.assertFalse(acknowledge_exact_protected_order(response=bad,bundle=bundle))

    def test_approval_must_match_bundle_request_identity_and_commit(self):
        bundle,approval,now_s=sample()
        with self.assertRaises(SenderHold):
            verify_exact_request(bundle=bundle,
                approval=replace(approval,request_id="other-request-0001"),now_s=now_s)
        with self.assertRaises(SenderHold):
            verify_exact_request(bundle=bundle,
                approval=replace(approval,code_sha="e"*40),now_s=now_s)

    def test_no_secret_loading_or_entrypoint(self):
        import ast
        from pathlib import Path
        import testnet_paper_review.isolated_testnet_sender as mod
        tree=ast.parse(Path(mod.__file__).read_text())
        imports={n.module for n in ast.walk(tree)
                 if isinstance(n,ast.ImportFrom) and n.module}
        self.assertNotIn("eth_account",imports)
        self.assertNotIn("hyperliquid.info",imports)
        functions={n.name for n in ast.walk(tree) if isinstance(n,ast.FunctionDef)}
        self.assertNotIn("main",functions)

if __name__=="__main__":
    unittest.main()
