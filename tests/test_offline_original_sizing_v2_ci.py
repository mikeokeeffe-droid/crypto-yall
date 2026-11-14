"""Original Daily/Intraday/Aggressive source sizing to non-executable V2.

The original executor functions are AST-extracted but never imported with
their signing dependencies. Every exchange mutation goes to an offline HOLD
sink. A green test does not demonstrate a safe live adapter or trading access.
"""
import json
from pathlib import Path
import sys
import tempfile
import unittest

from offline_original_sizing_v2_ci import (
    preview_original_sizing_for_v2_offline,
)
from test_offline_real_original_decisions_to_v2_ci import decide, view

ROOT = Path(__file__).resolve().parents[1]
BOT_FILES = {
    "daily": "hyperliquid_executor.py",
    "intraday": "intraday_executor.py",
    "aggressive": "aggressive_executor.py",
}


def original_candidate(bot, action="buy"):
    candidates = decide(bot, {
        "SOL-USD": {
            "action": action, "bull_conf": 0.85, "bear_conf": 0.8,
            "osc": 0.7, "pyramid_added": False,
        }
    })
    if len(candidates) != 1:
        raise AssertionError("original candidate unexpectedly changed")
    return candidates[0]


def preview(bot, candidate=None, source_root=ROOT, **changes):
    return preview_original_sizing_for_v2_offline(
        bot=bot, source_root=source_root, view=view(bot),
        original_candidate=(
            original_candidate(bot) if candidate is None else candidate
        ),
        **changes,
    )


class OriginalSizingV2Tests(unittest.TestCase):
    def test_three_original_mainnet_entry_sizes(self):
        for bot, expected in (
            ("daily", "0.16"),
            ("intraday", "0.16"),
            ("aggressive", "0.24"),
        ):
            for action, side in (("buy", "long"), ("enter_short", "short")):
                with self.subTest(bot=bot, action=action):
                    original = original_candidate(bot, action)
                    result = preview(bot, original)
                    self.assertEqual(result.state, "review_only")
                    self.assertEqual(result.rounded_size, expected)
                    self.assertEqual(result.requested_leverage, 2)
                    self.assertFalse(result.submit_authorized)
                    self.assertFalse(result.leverage_applied)
                    doc = json.loads(result.v2_json)
                    self.assertEqual(doc, {
                        "operation": "review_entry_leverage_v2",
                        "action": original["action"],
                        "side": side,
                        "hl_coin": "SOL",
                        "rounded_size": expected,
                        "requested_leverage": 2,
                        "cross_margin_requested": True,
                    })

    def test_unreviewed_metadata_and_wrong_sizing_parameters_hold(self):
        candidate = original_candidate("daily")
        for params in (
            {"capital": 1200.0},
            {"capital": True},
            {"requested_leverage": 3},
            {"requested_leverage": 2.0},
            {"original_candidate": dict(candidate, submit_authorized=True)},
            {"original_candidate": dict(candidate, close_size="1")},
            {"original_candidate": dict(candidate, action="close")},
            {"original_candidate": dict(candidate, action="pyramid_long")},
        ):
            with self.subTest(params=params):
                input_candidate = params.pop("original_candidate", candidate)
                result = preview("daily", input_candidate, **params)
                self.assertEqual(result.state, "hold")
                self.assertIsNone(result.v2_json)
                self.assertFalse(result.submit_authorized)

    def test_original_strategy_constant_change_fails_closed(self):
        daily = (ROOT / "hyperliquid_executor.py").read_text("utf-8")
        intraday = (ROOT / "intraday_executor.py").read_text("utf-8")
        aggressive = (ROOT / "aggressive_executor.py").read_text("utf-8")
        mutated = daily.replace(
            "POSITION_SIZE_PCT = 0.01",
            "POSITION_SIZE_PCT = 999.0", 1,
        )
        self.assertNotEqual(mutated, daily)
        with tempfile.TemporaryDirectory() as td:
            target = Path(td)
            (target / "hyperliquid_executor.py").write_text(mutated)
            (target / "intraday_executor.py").write_text(intraday)
            (target / "aggressive_executor.py").write_text(aggressive)
            result = preview("daily", source_root=target)
            self.assertEqual(result.state, "hold")
            self.assertIsNone(result.v2_json)

    def test_source_helper_injection_rejected(self):
        daily = (ROOT / "hyperliquid_executor.py").read_text("utf-8")
        altered = daily.replace(
            "exchange.market_open(coin, is_buy, size)",
            "exchange.unsafe_send_order(coin, is_buy, size)", 1,
        )
        self.assertNotEqual(altered, daily)
        with tempfile.TemporaryDirectory() as td:
            source = Path(td) / "hyperliquid_executor.py"
            source.write_text(altered)
            result = preview("daily", source_root=Path(td))
            self.assertEqual(result.state, "hold")

    def test_never_imports_original_executors_or_signers(self):
        preview("aggressive")
        for module in (
            "hyperliquid_executor", "intraday_executor",
            "aggressive_executor", "eth_account", "hyperliquid.exchange",
        ):
            self.assertNotIn(module, sys.modules)


if __name__ == "__main__":
    unittest.main()
