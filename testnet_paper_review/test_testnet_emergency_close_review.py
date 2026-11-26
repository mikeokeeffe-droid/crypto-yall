"""Synthetic Testnet missing-stop exit planning; no keys or exchange calls."""
import unittest
from copy import deepcopy
from testnet_paper_review.testnet_emergency_close_review import (
    review_missing_stop_close,EmergencyHold
)
from testnet_paper_review.test_offline_bracket_reconciliation import proof
from testnet_paper_review.test_testnet_daily_admission_gate import NOW


def scenario():
    d=proof()
    # Missing SL but still have correctly matching TP in both account views.
    d["open_orders"]=d["open_orders"][:1]
    d["frontend_open_orders"]=d["frontend_open_orders"][:1]
    return {
        "plan":d["plan"],"request_id":"manual-sol-000001",
        "state":{"assetPositions":d["positions"]},
        "open_orders":d["open_orders"],"frontend_open_orders":d["frontend_open_orders"],
        "mid_price":"66.40","size_decimals":2,"px_decimals":2,
        "account":d["account"],"network":d["network"],
        "snapshot_at_s":NOW-1,"now_s":NOW,
    }


class EmergencyPlanTests(unittest.TestCase):
    def test_long_without_stop_proposes_only_reduce_only_sell(self):
        d=scenario()
        result=review_missing_stop_close(**d)
        self.assertFalse(result.may_send)
        self.assertTrue(result.missing_stop)
        order=result.close_order
        self.assertEqual(order["coin"],"SOL")
        self.assertFalse(order["is_buy"])
        self.assertTrue(order["reduce_only"])
        self.assertEqual(order["order_type"],{"limit":{"tif":"Ioc"}})
        self.assertEqual(order["sz"],d["state"]["assetPositions"][0]["position"]["szi"])
        self.assertLess(float(order["limit_px"]),float(d["mid_price"]))

    def test_no_orders_still_manual_review_only(self):
        d=scenario();d["open_orders"]=[];d["frontend_open_orders"]=[]
        self.assertFalse(review_missing_stop_close(**d).may_send)

    def test_would_not_close_foreign_or_increased_or_unverified_position(self):
        cases=[
            ("foreign",{"coin":"BTC"}),("flipped",{"szi":"-0.30"}),
            ("increased",{"szi":"2.00"}),("flat",{"szi":"0"}),
            ("cross",{"leverage":{"type":"cross","value":1}}),
            ("leverage",{"leverage":{"type":"isolated","value":2}}),
        ]
        for name,mut in cases:
            d=scenario()
            d["state"]["assetPositions"][0]["position"].update(mut)
            with self.subTest(name=name),self.assertRaises(EmergencyHold):
                review_missing_stop_close(**d)

    def test_existing_stop_wrong_orders_and_races_hold(self):
        for change in ("existing_stop","bad_owner","stale","unrelated_order","mismatch"):
            d=scenario()
            if change=="existing_stop":
                original=proof()
                d["open_orders"]=original["open_orders"]
                d["frontend_open_orders"]=original["frontend_open_orders"]
            elif change=="bad_owner":d["account"]="0x"+"0"*40
            elif change=="stale":d["snapshot_at_s"]=NOW-6
            elif change=="unrelated_order":
                d["open_orders"][0]["coin"]="BTC"
                d["frontend_open_orders"][0]["coin"]="BTC"
            else:d["frontend_open_orders"][0]["sz"]="0.01"
            with self.subTest(change=change),self.assertRaises(EmergencyHold):
                review_missing_stop_close(**d)

    def test_unexpected_extra_position_or_order_holds(self):
        d=scenario()
        d["state"]["assetPositions"].append({"position":{"coin":"ETH","szi":"1"}})
        with self.assertRaises(EmergencyHold):
            review_missing_stop_close(**d)
        d=scenario()
        d["open_orders"].append(dict(d["open_orders"][0]))
        d["frontend_open_orders"].append(dict(d["frontend_open_orders"][0]))
        with self.assertRaises(EmergencyHold):
            review_missing_stop_close(**d)

    def test_invalid_trigger_values_raise_review_hold(self):
        for value in (None, "", "NaN", "Infinity", "-1", "0", 99, {}, []):
            d=scenario()
            d["open_orders"][0]["triggerPx"]=value
            d["frontend_open_orders"][0]["triggerPx"]=value
            with self.subTest(value=value), self.assertRaises(EmergencyHold):
                review_missing_stop_close(**d)

    def test_no_wallet_or_sender_imports(self):
        import ast
        from pathlib import Path
        import testnet_paper_review.testnet_emergency_close_review as mod
        tree=ast.parse(Path(mod.__file__).read_text())
        imports={n.module for n in ast.walk(tree)
                 if isinstance(n,ast.ImportFrom) and n.module}
        self.assertFalse(any(name.startswith(("hyperliquid","eth_account","testnet_paper_review.isolated_testnet_sender"))
                             for name in imports))

if __name__=="__main__":
    unittest.main()
