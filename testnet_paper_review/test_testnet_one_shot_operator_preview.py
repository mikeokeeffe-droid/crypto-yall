"""No-network tests for the owner-only SOL TESTNET operator price preview."""
from dataclasses import replace
from decimal import Decimal
from types import SimpleNamespace
import ast
from pathlib import Path
import unittest

from testnet_paper_review.testnet_one_shot_operator_preview import (
    inspect_one_shot_preview, preview_side, main, OneShotPreviewHold,
    JOURNAL_PATH, NOTIONAL
)
from testnet_paper_review.testnet_server_deployment_check import HostReadOnlyReceipt
from testnet_paper_review.testnet_sdk_server_client_preflight import (
    ClientPreflight, AGENT_ADDRESS
)
from testnet_paper_review.offline_order_guard import TESTNET_ACCOUNT, TESTNET_ENDPOINT


def market_receipt(**changes):
    base=HostReadOnlyReceipt(
        owner=TESTNET_ACCOUNT,mode="unifiedAccount",
        spot_usdc_available="1003.103047",positions=0,open_orders=0,
        testnet_named_owner_agents=2,sol_mid="70.5755",sol_size_decimals=2
    )
    return replace(base,**changes)


def sdk_receipt(**changes):
    base=ClientPreflight(
        owner=TESTNET_ACCOUNT,agent=AGENT_ADDRESS,
        testnet_endpoint=TESTNET_ENDPOINT,sol_asset_id=5
    )
    return replace(base,**changes)


class StubJournal:
    def __init__(self,path,*,state=None):
        if path!=JOURNAL_PATH:raise AssertionError("incorrect journal")
        self.state=state if state is not None else {"frozen":False,"claim":None}
    def __enter__(self):return self
    def __exit__(self,*args):pass
    def view(self):return self.state


def inspect(*,pub=None,sdk=None,journal=None):
    return inspect_one_shot_preview(
        public_check=lambda:pub or market_receipt(),
        wallet_loader=lambda:SimpleNamespace(address=AGENT_ADDRESS),
        sdk_check=lambda **kw:sdk or sdk_receipt(),
        journal_factory=lambda path:StubJournal(path,state=journal)
    )


class OperatorPreviewTests(unittest.TestCase):
    def test_long_and_short_are_read_only(self):
        x=inspect()
        self.assertFalse(x.may_send)
        self.assertFalse(x.actual_leverage_verified)
        self.assertFalse(x.exchange_exits_verified)
        self.assertFalse(x.original_daily_signal_verified)
        self.assertTrue(x.journal_empty)
        for side in (x.long,x.short):
            self.assertEqual(side.permissions,"NO_TRADING_AUTHORITY")
            self.assertEqual(side.coin,"SOL")
            self.assertTrue(side.reduce_only_exits_required)
            self.assertLessEqual(Decimal(side.worst_case_entry_notional_usdc),NOTIONAL)
            self.assertGreaterEqual(Decimal(side.worst_case_entry_notional_usdc),Decimal("12"))
        self.assertGreater(Decimal(x.long.indicative_entry_limit),
                           Decimal(x.current_testnet_mid))
        self.assertLess(Decimal(x.short.indicative_entry_limit),
                        Decimal(x.current_testnet_mid))
        self.assertLess(Decimal(x.long.indicative_stop_loss_trigger),
                        Decimal(x.current_testnet_mid))
        self.assertGreater(Decimal(x.short.indicative_stop_loss_trigger),
                           Decimal(x.current_testnet_mid))
        self.assertEqual(main([]),2)

    def test_used_frozen_or_broken_journal_holds(self):
        for state in (
            {"frozen":True,"claim":None},
            {"frozen":False,"claim":("already-used",)},
            {},
        ):
            with self.subTest(state=state),self.assertRaises(OneShotPreviewHold):
                inspect(journal=state)

    def test_unexpected_public_owner_funds_or_existing_orders_holds(self):
        for changes in (
            {"owner":"0x"+"0"*40},
            {"mode":"disabled"},
            {"positions":1},
            {"open_orders":1},
            {"spot_usdc_available":"0"},
        ):
            with self.subTest(changes=changes),self.assertRaises(OneShotPreviewHold):
                inspect(pub=market_receipt(**changes))

    def test_wrong_sdk_endpoint_and_agent_holds(self):
        with self.assertRaises(OneShotPreviewHold):
            inspect(sdk=sdk_receipt(testnet_endpoint="https://api.hyperliquid.xyz"))
        with self.assertRaises(OneShotPreviewHold):
            inspect(sdk=sdk_receipt(owner="0x"+"0"*40))

    def test_invalid_market_quote_or_size_holds(self):
        for mid in ("NaN","0","0.1","10001"):
            with self.subTest(mid=mid),self.assertRaises(OneShotPreviewHold):
                inspect(pub=market_receipt(sol_mid=mid))
        for dec in (-1,6,True):
            with self.subTest(dec=dec),self.assertRaises(OneShotPreviewHold):
                inspect(pub=market_receipt(sol_size_decimals=dec))

    def test_no_signer_order_or_state_mutation(self):
        import testnet_paper_review.testnet_one_shot_operator_preview as module
        tree=ast.parse(Path(module.__file__).read_text())
        methods={n.name for n in ast.walk(tree) if isinstance(n,ast.FunctionDef)}
        self.assertFalse({"send_once","place_order","market_open","market_close",
                          "reserve","freeze","initialize","bulk_orders","sign"} & methods)
        self.assertFalse(any(isinstance(n,ast.Attribute) and n.attr in (
            "bulk_orders","order","market_close","update_leverage","reserve","freeze")
            for n in ast.walk(tree)))

if __name__=="__main__":
    unittest.main()
