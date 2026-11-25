"""Mock-only signer boundary contract tests. No secrets, signing or orders."""
from dataclasses import replace
from pathlib import Path
import ast
import unittest

from testnet_paper_review.offline_signer_boundary import (
    build_offline_signer_envelope, BracketHold, REVIEW_MODE
)
from testnet_paper_review.offline_daily_bracket_plan import (
    OfflineBracketPlan, compose_mock_bracket
)
from testnet_paper_review.offline_order_guard import (
    SyntheticIntent, TESTNET_ACCOUNT, TESTNET_ENDPOINT
)
from testnet_paper_review.test_testnet_daily_admission_gate import fixture, NOW


SHA="a"*40


def valid():
    args=fixture()
    args["mid_price"]="66.40"
    plan=compose_mock_bracket(**args)
    intent=SyntheticIntent(
        request_id="review-signer-0001", account=TESTNET_ACCOUNT,
        endpoint=TESTNET_ENDPOINT, symbol="SOL", side="buy",
        notional_usdc="20", leverage=1, expires_at_s=NOW+30
    )
    return {"plan":plan, "intent":intent, "code_sha":SHA, "now_s":NOW}


def modified_order(plan, index, change):
    orders=[dict(x) for x in plan.orders]
    orders[index].update(change)
    return replace(plan,orders=tuple(orders))


class TestnetSignerBoundaryTests(unittest.TestCase):
    def test_valid_fixture_still_cannot_sign_or_send(self):
        d=valid()
        env=build_offline_signer_envelope(**d)
        self.assertEqual(env.mode,REVIEW_MODE)
        self.assertFalse(env.may_sign)
        self.assertFalse(env.may_send)
        self.assertEqual(env.endpoint,TESTNET_ENDPOINT)
        self.assertEqual(env.grouped_order_count,3)
        self.assertEqual(len(env.plan_hash),64)
        self.assertEqual(env,build_offline_signer_envelope(**d))

    def test_change_approved_code_or_request_changes_fingerprint(self):
        base=valid()
        a=build_offline_signer_envelope(**base)
        b=build_offline_signer_envelope(**{**base,"code_sha":"b"*40})
        c=build_offline_signer_envelope(**{
            **base, "intent":replace(base["intent"],request_id="review-signer-0002")
        })
        self.assertNotEqual(a.plan_hash,b.plan_hash)
        self.assertNotEqual(a.plan_hash,c.plan_hash)
        self.assertFalse(b.may_send and c.may_send)

    def test_wrong_endpoint_account_mode_approval_and_expiry_hold(self):
        for change in (
            {"intent":replace(valid()["intent"],endpoint="https://api.hyperliquid.xyz")},
            {"intent":replace(valid()["intent"],account="0x"+"0"*40)},
            {"intent":replace(valid()["intent"],mode="LIVE")},
            {"intent":replace(valid()["intent"],expires_at_s=NOW)},
            {"intent":replace(valid()["intent"],leverage=2)},
            {"intent":replace(valid()["intent"],notional_usdc="10")},
            {"code_sha":"main"},{"code_sha":"A"*40},
            {"now_s":NOW+31},
        ):
            with self.subTest(change=change),self.assertRaises(BracketHold):
                build_offline_signer_envelope(**{**valid(),**change})

    def test_missing_or_broken_attached_protection_holds(self):
        plan=valid()["plan"]
        for changed in (
            replace(plan,grouping="naive"),
            replace(plan,orders=plan.orders[:2]),
            modified_order(plan,1,{"reduce_only":False}),
            modified_order(plan,2,{"reduce_only":False}),
            modified_order(plan,2,{"is_buy":True}),
            modified_order(plan,1,{"sz":"0.01"}),
            modified_order(plan,0,{"coin":"ETH"}),
            modified_order(plan,0,{"order_type":{"limit":{"tif":"Gtc"}}}),
            modified_order(plan,2,{"order_type":{"trigger":{"triggerPx":"65.70","isMarket":False,"tpsl":"sl"}}}),
            modified_order(plan,1,{"order_type":{"trigger":{"triggerPx":"67.73","isMarket":True,"tpsl":"sl"}}}),
            modified_order(plan,0,{"limit_px":"10000"}),
        ):
            with self.subTest(changed=changed),self.assertRaises(BracketHold):
                build_offline_signer_envelope(**{**valid(),"plan":changed})

    def test_wrong_direction_and_unbounded_notional_hold(self):
        plan=valid()["plan"]
        intent=valid()["intent"]
        for trial in (
            replace(intent,side="sell"),
            replace(intent,symbol="ETH"),
            replace(intent,notional_usdc="12"),
            replace(intent,request_id="bad/id"),
        ):
            with self.subTest(trial=trial),self.assertRaises(BracketHold):
                build_offline_signer_envelope(**{**valid(),"intent":trial})

    def test_no_signer_network_secrets_or_order_submission_surface(self):
        import testnet_paper_review.offline_signer_boundary as module
        tree=ast.parse(Path(module.__file__).read_text())
        imports={n.module.split(".")[0] for n in ast.walk(tree)
                 if isinstance(n,ast.ImportFrom) and n.module}
        imports|={a.name.split(".")[0] for n in ast.walk(tree)
                  if isinstance(n,ast.Import) for a in n.names}
        self.assertFalse({"hyperliquid","eth_account","requests","socket",
                          "http","urllib","os","subprocess"} & imports)
        functions={n.name for n in ast.walk(tree) if isinstance(n,ast.FunctionDef)}
        self.assertFalse({"place_order","execute_trade","market_open",
                          "market_close","cancel","main","sign"} & functions)


if __name__ == "__main__":
    unittest.main()
