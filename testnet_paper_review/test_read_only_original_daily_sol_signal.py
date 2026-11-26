"""Synthetic fixtures only: validate original Daily SOL reader without data downloads.

The original strategy is NEVER run through this test with a real exchange.
"""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
import ast
from pathlib import Path
import unittest

from testnet_paper_review import read_only_original_daily_sol_signal as mod

NOW=datetime(2026,11,26,14,0,tzinfo=timezone.utc)
LAST=NOW.date()-timedelta(days=1)


class FakeIndex(list):
    is_unique=True
    is_monotonic_increasing=True


class FakeRows:
    def __init__(self,length=410,last=LAST):
        self.index=FakeIndex(
            datetime.combine(last-timedelta(days=length-1-i),
                             datetime.min.time())
            for i in range(length)
        )
        self.empty=False
    def __len__(self):return len(self.index)


class FakeSeries:
    def __init__(self,values):self.values=values
    @property
    def iloc(self):return self
    def __getitem__(self,key):return self.values[key]
    def __len__(self):return 410


class FakeFrame:
    def __len__(self):return 410


def fake_run(*,last=1,prior=0,regime="Bull",last_date=LAST,
             allow_short=False,leverage=1.5,source_check=lambda:True):
    raw=FakeRows(last=last_date)
    frames=FakeFrame()
    r=FakeSeries([regime]*410)
    s={
        "Signal":FakeSeries([0]*408+[prior,last]),
        "Leverage":FakeSeries([0]*409+[leverage]),
    }
    class Signals:
        def __getitem__(self,key):return s[key]
    return mod.model_observation(
        reader=lambda **kw:{"SOL-USD":raw},
        indicator_fn=lambda raw:frames,
        regime_fn=lambda frame:(r,FakeSeries([.7]*410),FakeSeries([.1]*410)),
        strategy_fn=lambda *args,**kw:Signals(),
        profile_fn=lambda ticker:{
            "allow_short":allow_short,
            "max_bull_leverage":1.5,"atr_mult":4.0
        },
        clock=lambda:NOW.timestamp(),
        source_check=source_check
    )


class DailySolReaderTests(unittest.TestCase):
    def test_pinned_source_hashes_validate(self):
        self.assertTrue(mod.verify_readonly_daily_model_sources())

    def test_real_daily_buy_candidate_remains_no_trade(self):
        x=fake_run()
        self.assertEqual(x.action,"buy")
        self.assertTrue(x.is_new_daily_sol_buy)
        self.assertEqual(x.trial_leverage,1)
        self.assertFalse(x.may_send)
        self.assertEqual(x.status,"NEW_SOL_BUY_REVIEW_ONLY_HOLD")

    def test_daily_hold_is_not_a_new_entry(self):
        x=fake_run(last=1,prior=1)
        self.assertEqual(x.action,"hold_long")
        self.assertFalse(x.is_new_daily_sol_buy)
        self.assertFalse(x.may_send)

    def test_no_short_even_if_legacy_signal_looks_short(self):
        with self.assertRaises(mod.DailySignalEvidenceHold):
            fake_run(last=-1,prior=0,regime="Bear")

    def test_yesterday_bar_and_no_future_candle_required(self):
        for day in (LAST-timedelta(days=1),LAST+timedelta(days=1)):
            with self.subTest(day=day),self.assertRaises(mod.DailySignalEvidenceHold):
                fake_run(last_date=day)

    def test_unreviewed_profile_or_dependency_source_rejected(self):
        with self.assertRaises(mod.DailySignalEvidenceHold):
            fake_run(allow_short=True)
        with self.assertRaises(mod.DailySignalEvidenceHold):
            fake_run(source_check=lambda:False)

    def test_no_order_functions_or_signer_imports(self):
        tree=ast.parse(Path(mod.__file__).read_text())
        imported={x.module for x in ast.walk(tree)
                  if isinstance(x,ast.ImportFrom) and x.module}
        self.assertFalse(any(x.startswith(("hyperliquid","eth_account",
                             "hyperliquid_executor")) for x in imported))
        names={n.name for n in ast.walk(tree) if isinstance(n,ast.FunctionDef)}
        self.assertFalse({"place_order","execute_trade","send_once",
                          "bulk_orders","market_open","market_close"} & names)
        self.assertEqual(mod.main([]),2)

if __name__=="__main__":
    unittest.main()
