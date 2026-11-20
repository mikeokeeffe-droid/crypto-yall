"""Offline compatibility test: original Info helpers run without a signer.

Loads only the original helper function AST. Never imports executable bot
modules, Hyperliquid SDK, HTTP clients, secrets or a production database.
Passing proves synthetic interface compatibility, not genuine market data.
"""
import ast
from decimal import Decimal
from pathlib import Path
import unittest

from offline_signer_free_info_fixture_ci import (
    OfflineSignerFreeInfoScope, make_signer_free_info_fixture,
)

ROOT = Path(__file__).resolve().parents[1]
ACCOUNT = "0x" + "1" * 40
SCOPE = OfflineSignerFreeInfoScope("mainnet", ACCOUNT)


def snapshot(account=ACCOUNT):
    return {
        "account": account,
        "environment": "mainnet",
        "user_state": {
            "marginSummary": {"accountValue": "150"},
            "assetPositions": [
                {"position": {"coin": "SOL", "szi": "0.025",
                              "entryPx": "100", "unrealizedPnl": "1.25",
                              "leverage": "2"}},
                {"position": {"coin": "AVAX", "szi": "-0.5",
                              "entryPx": "30", "unrealizedPnl": "-1",
                              "leverage": "3"}},
            ],
        },
        "spot_state": {"balances": [{"coin": "USDC", "total": "40"}]},
        "all_mids": {"SOL": "110", "AVAX": "28"},
        "meta": {"universe": [
            {"name": "SOL", "szDecimals": 3},
            {"name": "AVAX", "szDecimals": 2},
        ]},
    }


def helper_from_original(name):
    path = ROOT / "hyperliquid_executor.py"
    source = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    nodes = [node for node in source.body
             if isinstance(node, ast.FunctionDef) and node.name == name]
    if len(nodes) != 1:
        raise AssertionError(f"Expected exactly one original {name} helper")
    node = nodes[0]
    node.decorator_list = []
    code = compile(ast.fix_missing_locations(
        ast.Module(body=[node], type_ignores=[])), str(path), "exec")
    globals_dict = {"Decimal": Decimal}
    exec(code, globals_dict)
    return globals_dict[name]


class OfflineSignerFreeInfoCompatibilityTests(unittest.TestCase):
    def test_original_information_helpers_with_no_exchange_or_signer(self):
        client = make_signer_free_info_fixture(scope=SCOPE, snapshot=snapshot())
        self.assertIsNotNone(client)
        self.assertFalse(client.origin_authenticated)
        self.assertFalse(client.ownership_verified)
        self.assertFalse(client.submit_authorized)
        equity = helper_from_original("get_account_equity")
        positions = helper_from_original("get_open_positions")
        mid = helper_from_original("get_mid_price")
        decimals = helper_from_original("get_size_decimals")
        self.assertEqual(equity(client, ACCOUNT), 150.0)
        self.assertEqual(positions(client, ACCOUNT)["SOL"]["size"], 0.025)
        self.assertEqual(positions(client, ACCOUNT)["AVAX"]["size"], -0.5)
        self.assertEqual(positions(client, ACCOUNT)["SOL"]["leverage"], 2.0)
        self.assertEqual(mid(client, "SOL"), 110.0)
        self.assertEqual(decimals(client, "AVAX"), 2)
        self.assertEqual(decimals(client, "BTC"), 3)
        self.assertFalse(hasattr(client, "market_open"))
        self.assertFalse(hasattr(client, "market_close"))
        self.assertFalse(hasattr(client, "update_leverage"))

    def test_spot_fallback_uses_read_only_fixture(self):
        equity = helper_from_original("get_account_equity")
        data = snapshot()
        data["user_state"]["marginSummary"]["accountValue"] = "5"
        client = make_signer_free_info_fixture(scope=SCOPE, snapshot=data)
        self.assertEqual(equity(client, ACCOUNT), 40.0)

    def test_account_pin_and_snapshot_copy_isolation(self):
        data = snapshot()
        client = make_signer_free_info_fixture(scope=SCOPE, snapshot=data)
        self.assertIsNotNone(client)
        with self.assertRaises(PermissionError):
            client.user_state("0x" + "2" * 40)
        with self.assertRaises(PermissionError):
            client.spot_user_state("0x" + "2" * 40)
        data["user_state"]["marginSummary"]["accountValue"] = "99999"
        first = client.user_state(ACCOUNT)
        first["marginSummary"]["accountValue"] = "100000"
        self.assertEqual(client.user_state(ACCOUNT)
                         ["marginSummary"]["accountValue"], "150")
        mids = client.all_mids()
        mids["SOL"] = "99999"
        self.assertEqual(client.all_mids()["SOL"], "110")

    def test_malformed_wrong_scope_and_duplicate_positions_rejected(self):
        bad = []
        wrong = snapshot(account="0x" + "2" * 40)
        bad.append(wrong)
        extra = snapshot()
        extra["private_key"] = "unsafe"
        bad.append(extra)
        unknown = snapshot()
        unknown["user_state"]["assetPositions"][0]["position"]["coin"] = "BTC"
        bad.append(unknown)
        duplicate = snapshot()
        duplicate["user_state"]["assetPositions"].append(
            duplicate["user_state"]["assetPositions"][0]
        )
        bad.append(duplicate)
        invalid = snapshot()
        invalid["all_mids"]["SOL"] = "NaN"
        bad.append(invalid)
        invalid = snapshot()
        invalid["user_state"]["assetPositions"][0]["position"]["szi"] = "Inf"
        bad.append(invalid)
        for value in bad:
            with self.subTest(value=str(value)[:70]):
                self.assertIsNone(
                    make_signer_free_info_fixture(scope=SCOPE, snapshot=value)
                )
        self.assertIsNone(make_signer_free_info_fixture(
            scope=OfflineSignerFreeInfoScope("invalid", ACCOUNT),
            snapshot=snapshot(),
        ))

    def test_object_shaped_hyperliquid_leverage_is_supported(self):
        for kind,value in (("cross",2),("isolated","3")):
            with self.subTest(kind=kind):
                data=snapshot()
                data["user_state"]["assetPositions"][0]["position"]["leverage"]={
                    "type":kind,"value":value,
                }
                client=make_signer_free_info_fixture(scope=SCOPE,snapshot=data)
                self.assertIsNotNone(client)
                positions=helper_from_original("get_open_positions")(
                    client,ACCOUNT,
                )
                self.assertEqual(positions["SOL"]["leverage"],float(value))
                self.assertFalse(client.submit_authorized)
        for invalid in ({"type":"cross","value":0},
                        {"type":"isolated","value":"NaN"},
                        {"type":"unknown","value":"2"},
                        {"type":"cross","value":2,"secret":"unsafe"},
                        True):
            with self.subTest(invalid=invalid):
                data=snapshot()
                data["user_state"]["assetPositions"][0]["position"]["leverage"]=invalid
                self.assertIsNone(make_signer_free_info_fixture(
                    scope=SCOPE,snapshot=data,
                ))

    def test_untrusted_fill_and_funding_history_never_looks_complete(self):
        client=make_signer_free_info_fixture(scope=SCOPE,snapshot=snapshot())
        self.assertIsNotNone(client)
        with self.assertRaises(PermissionError):
            client.user_fills(ACCOUNT)
        with self.assertRaises(PermissionError):
            client.user_fills("0x"+"2"*40)
        with self.assertRaises(PermissionError):
            client.user_funding_history(ACCOUNT,1000,2000)
        with self.assertRaises(PermissionError):
            client.user_funding_history(ACCOUNT,2000,1000)
        with self.assertRaises(PermissionError):
            client.user_funding_history("0x"+"2"*40,1000,2000)
        self.assertFalse(client.origin_authenticated)
        self.assertFalse(client.ownership_verified)
        self.assertFalse(client.submit_authorized)

    def test_does_not_load_live_modules_or_offer_order_method(self):
        import sys
        self.assertNotIn("hyperliquid.exchange", sys.modules)
        self.assertNotIn("hyperliquid_executor", sys.modules)
        self.assertNotIn("intraday_executor", sys.modules)
        self.assertNotIn("aggressive_executor", sys.modules)


if __name__ == "__main__":
    unittest.main()
