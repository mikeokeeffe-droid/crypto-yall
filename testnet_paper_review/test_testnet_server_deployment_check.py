"""Server preparation diagnostics never need signing, trading, or secrets."""
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from testnet_paper_review.testnet_server_deployment_check import (
    inspect_server_public_testnet, HostPredeployHold, main
)


def sources(*, funds="1003.10", mode="unifiedAccount", positions=0,
            orders=0, agent_count=1, market_coin="SOL", delta=0):
    def account():
        return {"decision":SimpleNamespace(status="HOLD", allows_order=False),
                "positions":positions,"open_orders":orders}
    def spot():
        return {"balances":[{"coin":"USDC","total":funds,"hold":"0"}]}
    def agents():
        rows=[{"address":"0xa65e6f1495c95300E7364A1e68D8cfF3d2954FcC",
               "valid_until_ms":2000000000000,"role_matches_owner":True}]
        if agent_count>=2:
            rows.append({"address":"0x"+"1"*40,
                         "valid_until_ms":2000000000000,"role_matches_owner":True})
        if agent_count==0:
            rows=[]
        return {"trading_authorized":False,"agents":rows,
                "active_named_owner_agents":len(rows)}
    def market():
        return SimpleNamespace(symbol=market_coin,allows_trading=False,
                               size_decimals=3,mid_price="66.40")
    timestamps=iter((100,100+delta))
    return {"account_reader":account,"mode_reader":lambda:mode,
            "spot_reader":spot,"agent_reader":agents,"market_reader":market,
            "clock":lambda:next(timestamps)}


class ServerPreparationTests(unittest.TestCase):
    def test_public_readiness_still_cannot_trade_or_verify_secret(self):
        v=inspect_server_public_testnet(**sources())
        self.assertEqual(v.mode,"unifiedAccount")
        self.assertEqual(v.spot_usdc_available,"1003.10")
        self.assertEqual(v.open_orders,0)
        self.assertFalse(v.may_send)
        self.assertFalse(v.verifies_private_signer)
        self.assertEqual(inspect_server_public_testnet(**sources(agent_count=2)).testnet_named_owner_agents,2)

    def test_missing_funds_agents_or_clear_position_holds(self):
        changes=(
            {"funds":"19.99"},{"funds":"NaN"},{"mode":"portfolioMargin"},
            {"mode":"disabled"},{"positions":1},{"orders":1},
            {"agent_count":0},
            {"market_coin":"ETH"},{"delta":19},
        )
        for change in changes:
            with self.subTest(change=change),self.assertRaises(HostPredeployHold):
                inspect_server_public_testnet(**sources(**change))

    def test_only_unverified_or_expired_new_agent_holds(self):
        for variant in ("missing","mismatch","expired"):
            args=sources(agent_count=2)
            old=args["agent_reader"]
            def bad(variant=variant):
                data=old()
                new=data["agents"][0]
                if variant=="missing":new["address"]="0x"+"2"*40
                if variant=="mismatch":new["role_matches_owner"]=False
                if variant=="expired":new["valid_until_ms"]=99999
                return data
            args["agent_reader"]=bad
            with self.subTest(variant=variant),self.assertRaises(HostPredeployHold):
                inspect_server_public_testnet(**args)

    def test_read_failure_holds(self):
        args=sources()
        args["account_reader"]=lambda:(_ for _ in ()).throw(TimeoutError())
        with self.assertRaises(HostPredeployHold):
            inspect_server_public_testnet(**args)

    def test_no_implicit_execution_or_network_without_operator_switch(self):
        self.assertEqual(main([]),2)
        import ast
        from pathlib import Path
        import testnet_paper_review.testnet_server_deployment_check as check
        tree=ast.parse(Path(check.__file__).read_text())
        imports={n.module for n in ast.walk(tree)
                 if isinstance(n,ast.ImportFrom) and n.module}
        self.assertNotIn("hyperliquid.exchange",imports)
        self.assertNotIn("eth_account",imports)
        names={n.name for n in ast.walk(tree) if isinstance(n,ast.FunctionDef)}
        self.assertFalse({"order","send_once","submit","market_close","start_service"} & names)

if __name__=="__main__":
    unittest.main()
