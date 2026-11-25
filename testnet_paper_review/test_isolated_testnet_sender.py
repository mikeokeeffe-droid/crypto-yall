"""No-key isolated sender contract tests. Trading remains hard-disabled."""
import unittest
from dataclasses import replace
from testnet_paper_review.isolated_testnet_sender import (
    ACTIVATION_HOLD, ExactOneShotApproval, SenderHold, send_once,
    verify_exact_request
)
from testnet_paper_review.offline_client_order_bundle import build_offline_client_order_bundle
from testnet_paper_review.test_offline_signer_boundary import valid

SIGNER="0x1234567890abcdef1234567890ABCDEF12345678"

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
