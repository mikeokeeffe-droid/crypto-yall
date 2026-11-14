"""Offline integration of actual original price/size helpers and trade logic.

Extract only specified function ASTs from the three ORIGINAL executors; use
a pinned synthetic Info fixture and a permanently non-signing HOLD sink.
This is not a live bot process, an authenticated source, or a real sender.
All actions remain unauthorized and no Hyperliquid SDK or credentials load.
"""
import ast
from decimal import Decimal, ROUND_DOWN
import json
import os
from pathlib import Path
import unittest
from unittest.mock import patch

from offline_original_executor_mutation_sink_ci import (
    OfflineOriginalExecutorMutationSink,
)
from offline_signer_free_info_fixture_ci import (
    OfflineSignerFreeInfoScope, make_signer_free_info_fixture,
)

ROOT = Path(__file__).resolve().parents[1]
ACCOUNT = "0x" + "1" * 40
ORIGINALS = {
    "daily": "hyperliquid_executor.py",
    "intraday": "intraday_executor.py",
    "aggressive": "aggressive_executor.py",
}
COMMON_HELPERS = (
    "get_account_equity", "get_open_positions", "get_mid_price",
    "get_size_decimals", "round_size",
)


def fake_snapshot():
    return {
        "account": ACCOUNT,
        "environment": "mainnet",
        "user_state": {
            "marginSummary": {"accountValue": "150"},
            "assetPositions": [
                {"position": {
                    "coin": "SOL", "szi": "0.5", "entryPx": "110",
                    "unrealizedPnl": "1.5",
                    "leverage": {"type": "cross", "value": 2},
                }},
            ],
        },
        "spot_state": {"balances": [{"coin": "USDC", "total": "40"}]},
        "all_mids": {"SOL": "125", "AVAX": "28"},
        "meta": {"universe": [
            {"name": "SOL", "szDecimals": 3},
            {"name": "AVAX", "szDecimals": 2},
        ]},
    }


def extract_functions(path, names):
    tree = ast.parse((ROOT / path).read_text(encoding="utf-8"), path)
    picked = []
    for name in names:
        candidates = [node for node in tree.body
                      if isinstance(node, ast.FunctionDef) and node.name == name]
        if len(candidates) != 1:
            raise AssertionError(f"Unreviewed {path} helper {name}")
        node = candidates[0]
        node.decorator_list = []
        picked.append(node)
    return ast.fix_missing_locations(ast.Module(body=picked, type_ignores=[]))


def original_trade_fn(bot):
    path = ORIGINALS[bot]
    # All market/decimal helpers remain SOURCE-EXTRACTED from actual Daily.
    common = extract_functions("hyperliquid_executor.py", COMMON_HELPERS)
    trade = extract_functions(path, ("execute_trade",))
    namespace = {
        "Decimal": Decimal, "ROUND_DOWN": ROUND_DOWN, "os": os,
        "POSITION_SIZE_PCT": 0.10, "PYRAMID_SIZE_PCT": 0.05,
        "MAINNET_MIN_ORDER_NOTIONAL": 10.0,
        "TESTNET_MIN_ORDER_NOTIONAL": 10.0,
        "MIN_ORDER_NOTIONAL": 10.0,
        "_parse_response": lambda trade, response, info, coin: {
            **trade, "status": "synthetic_hold",
            "source_ack": response.get("status"),
        },
    }
    exec(compile(common, "source-extracted-common", "exec"), namespace)
    exec(compile(trade, f"source-extracted-{bot}", "exec"), namespace)
    return namespace


class OfflineOriginalSignerFreePipelineTests(unittest.TestCase):
    def setUp(self):
        self.info = make_signer_free_info_fixture(
            scope=OfflineSignerFreeInfoScope("mainnet", ACCOUNT),
            snapshot=fake_snapshot(),
        )
        self.assertIsNotNone(self.info)
        self.assertFalse(self.info.submit_authorized)
        self.assertFalse(self.info.ownership_verified)

    def run_original(self, bot, action, coin="SOL", *, close_size=None):
        ns = original_trade_fn(bot)
        trade = {"hl_coin": coin, "action": action}
        if close_size is not None:
            trade["close_size"] = close_size
        sink = OfflineOriginalExecutorMutationSink(
            bot=bot, trade=trade, environment="mainnet", account=ACCOUNT,
        )
        with patch.dict(os.environ, {"HL_TESTNET": "false"}, clear=True):
            result = ns["execute_trade"](self.info, sink, trade, 1000, 2)
        return ns, sink, result

    def test_read_only_original_helpers_can_calculate_from_pinned_info(self):
        helpers = original_trade_fn("daily")
        self.assertEqual(helpers["get_account_equity"](self.info, ACCOUNT), 150.)
        self.assertEqual(helpers["get_open_positions"](self.info, ACCOUNT)
                         ["SOL"]["size"], .5)
        self.assertEqual(helpers["get_mid_price"](self.info, "SOL"), 125.)
        self.assertEqual(helpers["get_size_decimals"](self.info, "AVAX"), 2)
        with self.assertRaises(PermissionError):
            self.info.user_state("0x" + "2" * 40)

    def test_three_bots_preserve_original_decimal_rounding_only_to_preview(self):
        # A SOL order's exact original rounding differs from AVAX metadata;
        # no submit capability exists even after a valid-size request preview.
        for bot in ORIGINALS:
            for coin, expected in (("SOL", "1.6"), ("AVAX", "7.14")):
                for action in ("open_long", "open_short"):
                    with self.subTest(bot=bot, coin=coin, action=action):
                        _, sink, outcome = self.run_original(bot, action, coin)
                        self.assertEqual(outcome["source_ack"], "offline_hold")
                        self.assertEqual(
                            [e[0] for e in sink.events],
                            ["leverage_hold", "entry_request_only"],
                        )
                        review = sink.last_review
                        self.assertEqual(review.state, "request_only")
                        wire = json.loads(review.request_json)
                        self.assertEqual(wire["rounded_size"], expected)
                        self.assertEqual(wire["hl_coin"], coin)
                        self.assertFalse(review.submit_authorized)
                        self.assertFalse(review.ownership_verified)

    def test_original_aggressive_pyramid_and_all_closes_stay_held(self):
        for action in ("pyramid_long", "pyramid_short"):
            _, sink, result = self.run_original("aggressive", action, "AVAX")
            self.assertEqual(result["source_ack"], "offline_hold")
            self.assertEqual(sink.last_review.action_class, "pyramid_increase")
            self.assertEqual(sink.last_review.state, "hold")
            self.assertIsNone(sink.last_review.request_json)
        for bot in ORIGINALS:
            for close_size in (None, .25):
                _, sink, result = self.run_original(
                    bot, "close", close_size=close_size,
                )
                self.assertEqual(result["source_ack"], "offline_hold")
                self.assertEqual(sink.last_review.action_class, "close")
                self.assertEqual(sink.last_review.state, "hold")
                self.assertFalse(sink.last_review.close_authorized)
                self.assertIsNone(sink.last_review.request_json)

    def test_wrong_or_missing_synthetic_market_metadata_fails_closed(self):
        data = fake_snapshot()
        data["all_mids"]["AVAX"] = "NaN"
        self.assertIsNone(make_signer_free_info_fixture(
            scope=OfflineSignerFreeInfoScope("mainnet", ACCOUNT),
            snapshot=data,
        ))
        with self.assertRaises(KeyError):
            # Original helper raises rather than fabricating a market price.
            original_trade_fn("daily")["get_mid_price"](self.info, "UNKNOWN")

    def test_live_bot_modules_and_signing_client_not_imported(self):
        import sys
        for name in (
            "hyperliquid_executor", "intraday_executor",
            "aggressive_executor", "hyperliquid.exchange",
        ):
            self.assertNotIn(name, sys.modules)


if __name__ == "__main__":
    unittest.main()
