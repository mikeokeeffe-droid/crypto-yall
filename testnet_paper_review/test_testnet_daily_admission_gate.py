"""Offline guard tests; no network, signing or trade-submission imports."""
from dataclasses import replace
import unittest
from testnet_paper_review import testnet_daily_admission_gate as gate

NOW = 1700000000
def fixture():
    return {
        "account": gate.EXPECTED_ACCOUNT,
        "network": gate.EXPECTED_NETWORK,
        "state": {"assetPositions": [], "withdrawable":"1000.00",
                  "marginSummary":{"accountValue":"1000.00"}},
        "open_orders": [],
        "signal": {"coin":"SOL", "action":"buy", "mode":"OFFLINE_SIGNAL_REVIEW",
                   "observed_at_s":NOW-1},
        "now_s":NOW,
        "snapshot_at_s":NOW-1,
        "notional_usdc":"20",
        "leverage":1,
    }

class TestnetDailyAdmissionTests(unittest.TestCase):
    def test_clean_synthetic_state_is_review_only(self):
        v=gate.assess(**fixture())
        self.assertEqual(v.status,"READY_FOR_REVIEW")
        self.assertFalse(v.allows_order)

    def test_manual_sol_position_blocks(self):
        d=fixture()
        d["state"]["assetPositions"]=[{"position":{"coin":"SOL","szi":"0.30"}}]
        v=gate.assess(**d)
        self.assertEqual(v.status,"HOLD")
        self.assertFalse(v.allows_order)

    def test_protective_orders_block_even_without_positions(self):
        d=fixture()
        d["open_orders"]=[
            {"coin":"SOL","reduceOnly":True,"orderType":"Take Profit Market"},
            {"coin":"SOL","reduceOnly":True,"orderType":"Stop Market"},
        ]
        self.assertEqual(gate.assess(**d).status,"HOLD")

    def test_foreign_coin_position_or_order_blocks(self):
        d=fixture()
        d["state"]["assetPositions"]=[{"position":{"coin":"BTC","szi":"0.1"}}]
        self.assertEqual(gate.assess(**d).status,"HOLD")
        d=fixture()
        d["open_orders"]=[{"coin":"BTC","oid":1}]
        self.assertEqual(gate.assess(**d).status,"HOLD")

    def test_fail_closed_missing_or_corrupt_account_state(self):
        variants=(
            {"state":None},{"state":{}},{"state":{"assetPositions":[]}},
            {"open_orders":None},{"open_orders":{}},
            {"state":{"assetPositions":None,"withdrawable":"1000",
                      "marginSummary":{"accountValue":"1000"}}},
        )
        for variant in variants:
            d=fixture();d.update(variant)
            with self.subTest(variant=variant):
                self.assertEqual(gate.assess(**d).status,"HOLD")

    def test_wrong_network_identity_stale_snapshots(self):
        for changes in (
            {"network":"mainnet"},{"network":""},
            {"account":"0x"+"0"*40},
            {"snapshot_at_s":NOW-16},{"snapshot_at_s":NOW+1},
            {"snapshot_at_s":None},
        ):
            d=fixture();d.update(changes)
            with self.subTest(changes=changes):
                self.assertEqual(gate.assess(**d).status,"HOLD")

    def test_unverified_collateral_and_limits(self):
        for withdrawable,equity in (("19","1000"),("1000","19"),
                                    ("nan","1000"),("-1","1000"),
                                    ("1000",None)):
            d=fixture()
            d["state"]["withdrawable"]=withdrawable
            d["state"]["marginSummary"]["accountValue"]=equity
            with self.subTest(withdrawable=withdrawable,equity=equity):
                self.assertEqual(gate.assess(**d).status,"HOLD")
        for value in ("11.99","25.01","1e9","",None):
            d=fixture();d["notional_usdc"]=value
            with self.subTest(value=value):
                self.assertEqual(gate.assess(**d).status,"HOLD")
        for lev in (0,2,True,"1"):
            d=fixture();d["leverage"]=lev
            with self.subTest(lev=lev):
                self.assertEqual(gate.assess(**d).status,"HOLD")

    def test_signal_not_an_automatic_trade(self):
        for signal in (
            None, {}, {"coin":"BTC","action":"buy","mode":"OFFLINE_SIGNAL_REVIEW","observed_at_s":NOW},
            {"coin":"SOL","action":"hold_long","mode":"OFFLINE_SIGNAL_REVIEW","observed_at_s":NOW},
            {"coin":"SOL","action":"buy","mode":"LIVE","observed_at_s":NOW},
            {"coin":"SOL","action":"buy","mode":"OFFLINE_SIGNAL_REVIEW","observed_at_s":NOW-16},
        ):
            d=fixture();d["signal"]=signal
            with self.subTest(signal=signal):
                self.assertEqual(gate.assess(**d).status,"HOLD")

    def test_never_exposes_order_submitting_function(self):
        import ast
        from pathlib import Path
        tree=ast.parse(Path(gate.__file__).read_text())
        imports={n.module.split(".")[0] for n in ast.walk(tree)
                 if isinstance(n,ast.ImportFrom) and n.module}
        imports|={a.name.split(".")[0] for n in ast.walk(tree)
                  if isinstance(n,ast.Import) for a in n.names}
        self.assertFalse({"requests","socket","http","hyperliquid",
                          "eth_account","subprocess","urllib"}.intersection(imports))
        self.assertFalse({"order","submit","market_open","main"}.intersection({
            n.name for n in ast.walk(tree) if isinstance(n,ast.FunctionDef)}))

if __name__=="__main__":
    unittest.main()
