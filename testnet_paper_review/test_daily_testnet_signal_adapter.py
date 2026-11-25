"""Offline Daily model signal provenance and freshness regressions."""
from pathlib import Path
from unittest.mock import patch
import unittest

from testnet_paper_review import daily_testnet_signal_adapter as mod

BAR=1700000000 - (1700000000 % mod.BAR_SECONDS)
OBS=BAR + mod.BAR_SECONDS + 4


def clean(**changes):
    data={
        "ticker":"SOL-USD",
        "last_signal":1,
        "prior_signal":0,
        "regime":"Bull",
        "action":"buy",
        "bar_started_at_s":BAR,
        "observed_at_s":OBS,
        "now_s":OBS + 1,
        "legacy_leverage":3.0,
    }
    data.update(changes)
    return data


class TestDailyTestnetSignalAdapter(unittest.TestCase):
    def test_exact_pinned_existing_daily_source(self):
        self.assertIn("HOLD",mod.verify_original_daily_sources())

    def test_new_sol_long_is_review_candidate_not_order(self):
        result=mod.review_daily_signal(**clean())
        self.assertEqual(result.action,"buy")
        self.assertEqual(result.coin,"SOL")
        self.assertEqual(result.mode,"OFFLINE_SIGNAL_REVIEW")
        self.assertFalse(result.may_submit)
        self.assertEqual(result.trial_leverage,1)
        self.assertEqual(result.admission_signal()["action"],"buy")

    def test_new_sol_short_review_candidate(self):
        result=mod.review_daily_signal(**clean(
            last_signal=-1,prior_signal=0,regime="Bear",
            action="enter_short",legacy_leverage=2.0
        ))
        self.assertEqual(result.action,"enter_short")
        self.assertEqual(result.trial_leverage,1)
        self.assertFalse(result.may_submit)

    def test_hold_flat_close_stale_or_conflicting_signal_rejected(self):
        variants=(
            {"action":"hold_long","last_signal":1,"prior_signal":1},
            {"action":"hold_short","last_signal":-1,"prior_signal":-1,"regime":"Bear"},
            {"action":"flat","last_signal":0,"prior_signal":0},
            {"action":"sell_exit","last_signal":0,"prior_signal":1},
            {"action":"buy","last_signal":1,"prior_signal":1},
            {"action":"enter_short","last_signal":-1,"prior_signal":0},
            {"last_signal":1,"prior_signal":0,"regime":"Bear"},
            {"ticker":"BTC-USD"},
            {"legacy_leverage":float("nan")},
            {"legacy_leverage":0},
            {"bar_started_at_s":BAR+60},
            {"bar_started_at_s":BAR+mod.BAR_SECONDS},
            {"observed_at_s":OBS-5},
            {"observed_at_s":OBS+mod.MAX_BAR_LAG_S+1},
            {"now_s":OBS+16},
            {"now_s":OBS-1},
            {"now_s":None},
        )
        for variant in variants:
            with self.subTest(variant=variant),self.assertRaises(mod.SignalReviewHold):
                mod.review_daily_signal(**clean(**variant))

    def test_existing_source_mutation_fails_closed(self):
        with patch.dict(mod.REVIEWED_BLOBS,{"signal_utils.py":"0"*40}):
            with self.assertRaises(mod.SignalReviewHold):
                mod.verify_original_daily_sources()

    def test_no_executor_imports_trading_sdk_or_signer(self):
        import ast
        tree=ast.parse(Path(mod.__file__).read_text())
        imports={node.module.split(".")[0] for node in ast.walk(tree)
                 if isinstance(node,ast.ImportFrom) and node.module}
        imports|={alias.name.split(".")[0] for node in ast.walk(tree)
                  if isinstance(node,ast.Import) for alias in node.names}
        self.assertFalse({
            "hyperliquid","eth_account","requests","socket",
            "http","urllib","subprocess","hyperliquid_executor"
        }.intersection(imports))
        fn={node.name for node in ast.walk(tree) if isinstance(node,ast.FunctionDef)}
        self.assertFalse({"execute_trade","sign","market_open","market_close","submit_order"} & fn)


if __name__=="__main__":
    unittest.main()
