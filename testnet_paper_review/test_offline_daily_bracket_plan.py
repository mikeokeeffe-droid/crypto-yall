"""Offline tests of grouped Testnet entry+reduce-only TP+SL plan."""
import unittest
from dataclasses import replace
from testnet_paper_review.offline_daily_bracket_plan import (
    compose_mock_bracket, review_exchange_reply, BracketHold
)
from testnet_paper_review.test_testnet_daily_admission_gate import fixture, NOW


def make(**changes):
    data=fixture()
    data["mid_price"]="66.40"
    data.update(changes)
    return data


class BracketPlanReviewTests(unittest.TestCase):
    def test_long_one_shot_group_has_two_reduce_only_protections(self):
        plan=compose_mock_bracket(**make())
        self.assertEqual(plan.status,"HOLD_OFFLINE_REVIEW_ONLY")
        self.assertFalse(plan.permits_submission)
        self.assertEqual(plan.grouping,"normalTpsl")
        self.assertEqual(len(plan.orders),3)
        entry,tp,sl=plan.orders
        self.assertEqual([entry["reduce_only"],tp["reduce_only"],sl["reduce_only"]],[False,True,True])
        self.assertEqual([x["coin"] for x in plan.orders],["SOL"]*3)
        self.assertEqual([x["is_buy"] for x in plan.orders],[True,False,False])
        self.assertEqual([x["sz"] for x in plan.orders],[entry["sz"]]*3)
        self.assertEqual(entry["order_type"],{"limit":{"tif":"Ioc"}})
        self.assertEqual(tp["order_type"]["trigger"]["tpsl"],"tp")
        self.assertEqual(sl["order_type"]["trigger"]["tpsl"],"sl")
        self.assertLess(float(sl["limit_px"]),float(plan.reference_price))
        self.assertGreater(float(tp["limit_px"]),float(plan.reference_price))
        self.assertLessEqual(float(plan.effective_notional),25)

    def test_short_protection_is_opposite_side(self):
        data=make()
        data["signal"]["action"]="enter_short"
        plan=compose_mock_bracket(**data)
        entry,tp,sl=plan.orders
        self.assertEqual([x["is_buy"] for x in plan.orders],[False,True,True])
        self.assertLess(float(tp["limit_px"]),float(plan.reference_price))
        self.assertGreater(float(sl["limit_px"]),float(plan.reference_price))

    def test_manual_position_and_tp_sl_still_block(self):
        data=make()
        data["state"]["assetPositions"]=[{"position":{"coin":"SOL","szi":"0.30"}}]
        with self.assertRaises(BracketHold):compose_mock_bracket(**data)
        data=make()
        data["open_orders"]=[{"reduceOnly":True,"coin":"SOL"}]
        with self.assertRaises(BracketHold):compose_mock_bracket(**data)

    def test_bad_price_notional_leverage_signal_and_precision(self):
        for changes in (
            {"mid_price":"0"}, {"mid_price":"nan"},
            {"mid_price":"66.4e1"}, {"mid_price":"-1"},
            {"mid_price":"10000000"}, {"notional_usdc":"25.01"},
            {"notional_usdc":"11"}, {"leverage":2},
            {"size_decimals":-1}, {"size_decimals":7},
            {"px_decimals":-1}, {"px_decimals":8},
            {"network":"mainnet"}, {"account":"0x"+"0"*40},
            {"snapshot_at_s":NOW-17}, {"signal":{}},
        ):
            with self.subTest(changes=changes),self.assertRaises(BracketHold):
                compose_mock_bracket(**make(**changes))

    def test_price_size_rounding_must_stay_below_cap(self):
        with self.assertRaises(BracketHold):
            compose_mock_bracket(**make(notional_usdc="25",mid_price="66.40",size_decimals=0))
        with self.assertRaises(BracketHold):
            compose_mock_bracket(**make(notional_usdc="12",mid_price="66.40",size_decimals=0))

    def test_no_ack_or_partial_protection_always_hold(self):
        plan=compose_mock_bracket(**make())
        for response in (
            None,
            {},
            {"status":"error"},
            {"status":"ok","response":{"data":{"statuses":[{"filled":{}}]}}},
            {"status":"ok","response":{"data":{"statuses":[
                {"filled":{}},{"resting":{"oid":7}},{"error":"stop failed"}]}}},
        ):
            with self.subTest(response=response),self.assertRaises(BracketHold):
                review_exchange_reply(response=response,actual_positions=[],
                                      actual_open_orders=[],plan=plan)
        plausible={"status":"ok","response":{"data":{"statuses":[
            {"filled":{"oid":1}},{"resting":{"oid":2}},{"resting":{"oid":3}}]}}}
        self.assertIn("HOLD",review_exchange_reply(
            response=plausible,actual_positions=[],actual_open_orders=[],plan=plan
        ))

    def test_no_signer_network_or_exchange_sdk(self):
        import ast
        from pathlib import Path
        import testnet_paper_review.offline_daily_bracket_plan as module
        tree=ast.parse(Path(module.__file__).read_text())
        imports={n.module.split(".")[0] for n in ast.walk(tree)
                 if isinstance(n,ast.ImportFrom) and n.module}
        imports|={alias.name.split(".")[0] for n in ast.walk(tree)
                  if isinstance(n,ast.Import) for alias in n.names}
        self.assertFalse({"requests","hyperliquid","eth_account","http","socket",
                          "urllib","subprocess"}.intersection(imports))
        names={n.name for n in ast.walk(tree) if isinstance(n,ast.FunctionDef)}
        self.assertTrue({"submit_order","market_open","market_close","main","execute_trade"}.isdisjoint(names))


if __name__=="__main__":
    unittest.main()
