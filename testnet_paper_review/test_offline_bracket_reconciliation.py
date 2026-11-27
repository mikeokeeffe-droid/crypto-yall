"""Mock-only protected order reconciliation tests; no trade or network calls."""
import unittest

from testnet_paper_review.offline_bracket_reconciliation import (
    assess_observed_bracket, ProtectionObservation
)
from testnet_paper_review.offline_daily_bracket_plan import (
    compose_mock_bracket, BracketHold
)
from testnet_paper_review.test_testnet_daily_admission_gate import fixture, NOW


def proof():
    args=fixture()
    args["mid_price"]="66.40"
    plan=compose_mock_bracket(**args)
    sz=plan.orders[0]["sz"]
    tp=plan.orders[1]["order_type"]["trigger"]["triggerPx"]
    sl=plan.orders[2]["order_type"]["trigger"]["triggerPx"]
    reverse="A" if plan.direction=="long" else "B"
    def row(oid, trigger, kind):
        return {
            "oid":oid, "coin":"SOL", "side":reverse, "sz":sz,
            "reduceOnly":True, "isTrigger":True, "orderType":kind,
            "triggerPx":trigger, "origSz":sz,
        }
    tp_row=row(102,tp,"Take Profit Market")
    sl_row=row(103,sl,"Stop Market")
    position={
        "position":{
            "coin":"SOL", "szi":sz, "entryPx":"66.40",
            "leverage":{"type":"isolated","value":1}
        }
    }
    response={"status":"ok","response":{"data":{"statuses":[
        {"filled":{"oid":101,"totalSz":sz}},
        {"resting":{"oid":102}},
        {"resting":{"oid":103}},
    ]}}}
    return {
        "plan":plan,
        "account":plan.account,
        "network":"hyperliquid-testnet",
        "response":response,
        "positions":[position],
        "open_orders":[{"oid":x["oid"],"coin":"SOL","side":reverse,"sz":sz}
                       for x in (tp_row,sl_row)],
        "frontend_open_orders":[tp_row,sl_row],
        "observation_started_s":NOW-3,
        "observation_finished_s":NOW-1,
        "now_s":NOW,
    }


class BracketReconciliationReviewTests(unittest.TestCase):
    def test_matching_protection_is_still_not_permission(self):
        d=proof()
        result=assess_observed_bracket(**d)
        self.assertIsInstance(result,ProtectionObservation)
        self.assertEqual(result.status,"MATCHED_OFFLINE_EVIDENCE_REVIEW_ONLY")
        self.assertFalse(result.allows_trading)
        self.assertEqual((result.entry_oid,result.take_profit_oid,result.stop_loss_oid),
                         (101,102,103))

    def test_missing_stop_tp_or_missing_full_frontend_view_holds(self):
        for field in ("open_orders","frontend_open_orders"):
            for index in (0,1):
                d=proof()
                d[field].pop(index)
                with self.subTest(field=field,index=index),self.assertRaises(BracketHold):
                    assess_observed_bracket(**d)
        d=proof()
        d["frontend_open_orders"]=None
        with self.assertRaises(BracketHold):
            assess_observed_bracket(**d)

    def test_bad_reduce_only_trigger_type_side_and_trigger_price_holds(self):
        for field,value in (
            ("reduceOnly",False),("reduceOnly",None),("isTrigger",False),
            ("orderType","Limit"),("orderType","Take Profit Market"),
            ("side","B"),("coin","BTC"),("triggerPx","64.00"),
            ("sz","0.01"),("origSz","0.01"),
        ):
            d=proof()
            d["frontend_open_orders"][1][field]=value
            with self.subTest(field=field,value=value),self.assertRaises(BracketHold):
                assess_observed_bracket(**d)

    def test_partial_and_wrong_fill_holds(self):
        for value in ("0.10",None,"0.31","-1","NaN"):
            d=proof()
            d["response"]["response"]["data"]["statuses"][0]["filled"]["totalSz"]=value
            with self.subTest(totalSz=value),self.assertRaises(BracketHold):
                assess_observed_bracket(**d)
        d=proof()
        d["response"]["response"]["data"]["statuses"].pop()
        with self.assertRaises(BracketHold):
            assess_observed_bracket(**d)

    def test_rejected_and_unknown_response_holds(self):
        for response in (None,{},{"status":"error"},
                         {"status":"ok","response":{"data":{"statuses":[]}}}):
            d=proof()
            d["response"]=response
            with self.subTest(response=response),self.assertRaises(BracketHold):
                assess_observed_bracket(**d)

    def test_partial_flipped_foreign_and_unexpected_position_holds(self):
        for change in (
            {"szi":"0.10"},{"szi":"-0.30"},{"coin":"ETH"},
            {"leverage":{"type":"cross","value":1}},
            {"leverage":{"type":"isolated","value":2}},
            {"entryPx":None}
        ):
            d=proof()
            d["positions"][0]["position"].update(change)
            with self.subTest(change=change),self.assertRaises(BracketHold):
                assess_observed_bracket(**d)
        d=proof()
        d["positions"].append({"position":{"coin":"ETH","szi":"1"}})
        with self.assertRaises(BracketHold):
            assess_observed_bracket(**d)

    def test_duplicate_extra_or_missing_order_holds(self):
        for field in ("open_orders","frontend_open_orders"):
            d=proof()
            d[field].append(dict(d[field][0]))
            with self.subTest(field=field),self.assertRaises(BracketHold):
                assess_observed_bracket(**d)
        d=proof()
        d["frontend_open_orders"].append({"oid":999})
        with self.assertRaises(BracketHold):
            assess_observed_bracket(**d)
        d=proof()
        d["response"]["response"]["data"]["statuses"][2]["resting"]["oid"]=102
        with self.assertRaises(BracketHold):
            assess_observed_bracket(**d)

    def test_wrong_account_network_or_stale_observation_holds(self):
        for change in (
            {"network":"mainnet"},{"account":"0x"+"0"*40},
            {"observation_started_s":NOW-11},
            {"observation_finished_s":NOW+1},
            {"observation_started_s":NOW+1},
            {"now_s":NOW-20},
            {"observation_finished_s":None},
        ):
            d=proof()
            d.update(change)
            with self.subTest(change=change),self.assertRaises(BracketHold):
                assess_observed_bracket(**d)

    def test_no_network_or_signing_capability(self):
        import ast
        from pathlib import Path
        import testnet_paper_review.offline_bracket_reconciliation as mod
        tree=ast.parse(Path(mod.__file__).read_text())
        imports={n.module.split(".")[0] for n in ast.walk(tree)
                 if isinstance(n,ast.ImportFrom) and n.module}
        imports|={a.name.split(".")[0] for n in ast.walk(tree)
                  if isinstance(n,ast.Import) for a in n.names}
        self.assertFalse({
            "requests","hyperliquid","eth_account","http","socket","urllib",
            "subprocess","sqlite3"
        }.intersection(imports))
        functions={n.name for n in ast.walk(tree) if isinstance(n,ast.FunctionDef)}
        self.assertFalse({
            "place_order","execute_trade","market_open","market_close","cancel"
        }.intersection(functions))


if __name__ == "__main__":
    unittest.main()
