"""Isolated SDK encoding tests. No wallet, no network and no orders."""
import unittest
from dataclasses import replace

from testnet_paper_review.testnet_sdk_wire_adapter import (
    compile_unsigned_sdk_wire, HoldError, SDK_VERSION_REVIEWED
)
from testnet_paper_review.test_offline_signer_boundary import valid


def metadata(decimals=3):
    return {"universe":[
        {"name":"BTC","szDecimals":5},
        {"name":"SOL","szDecimals":decimals,"maxLeverage":10},
        {"name":"ETH","szDecimals":4}
    ]}


class TestSDKWireAdapter(unittest.TestCase):
    def test_exact_3_orders_sdk_shape_no_signing(self):
        result=compile_unsigned_sdk_wire(**valid(),meta=metadata())
        self.assertFalse(result.may_sign)
        self.assertFalse(result.may_send)
        self.assertEqual(SDK_VERSION_REVIEWED,"0.24.0")
        self.assertEqual(result.asset_id,1)
        self.assertEqual(result.grouping,"normalTpsl")
        self.assertEqual(result.action["type"],"order")
        entry,tp,sl=result.action["orders"]
        self.assertEqual([e["r"] for e in (entry,tp,sl)],[False,True,True])
        self.assertEqual([e["a"] for e in (entry,tp,sl)],[1,1,1])
        self.assertEqual(entry["t"],{"limit":{"tif":"Ioc"}})
        self.assertEqual(tp["t"]["trigger"]["tpsl"],"tp")
        self.assertEqual(sl["t"]["trigger"]["tpsl"],"sl")
        self.assertTrue(tp["t"]["trigger"]["isMarket"])
        self.assertTrue(sl["t"]["trigger"]["isMarket"])
        self.assertEqual(len({e["c"] for e in (entry,tp,sl)}),3)
        self.assertTrue(all(len(e["c"])==34 for e in (entry,tp,sl)))
        self.assertEqual([e["s"] for e in (entry,tp,sl)],[entry["s"]]*3)

    def test_bad_metadata_and_duplicate_symbol_hold(self):
        for meta in (
            {},{"universe":[]},{"universe":[{"name":"SOL","szDecimals":3}]*2},
            metadata(decimals=6),metadata(decimals=True)
        ):
            with self.subTest(meta=meta),self.assertRaises(HoldError):
                compile_unsigned_sdk_wire(**valid(),meta=meta)

    def test_broken_protection_is_rejected_before_sdk(self):
        args=valid()
        entry,tp,sl=args["plan"].orders
        for p in (
            replace(args["plan"],orders=(entry,tp,{**sl,"reduce_only":False})),
            replace(args["plan"],orders=(entry,tp)),
            replace(args["plan"],grouping="na")
        ):
            with self.subTest(plan=p),self.assertRaises((HoldError,ValueError)):
                compile_unsigned_sdk_wire(**{**args,"plan":p},meta=metadata())

    def test_wrong_network_is_blocked(self):
        args=valid()
        args["intent"]=replace(args["intent"],endpoint="https://api.hyperliquid.xyz")
        with self.assertRaises(HoldError):
            compile_unsigned_sdk_wire(**args,meta=metadata())

    def test_no_signing_transport_or_secret_usage(self):
        import ast
        from pathlib import Path
        import testnet_paper_review.testnet_sdk_wire_adapter as mod
        tree=ast.parse(Path(mod.__file__).read_text())
        imports={n.module for n in ast.walk(tree)
                 if isinstance(n,ast.ImportFrom) and n.module}
        self.assertNotIn("hyperliquid.exchange",imports)
        self.assertNotIn("hyperliquid.info",imports)
        self.assertNotIn("eth_account",imports)
        names={n.name for n in ast.walk(tree) if isinstance(n,ast.FunctionDef)}
        self.assertFalse({"sign","submit_order","execute_trade","market_open","market_close"} & names)

if __name__=="__main__":
    unittest.main()
