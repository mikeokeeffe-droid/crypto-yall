"""Exercise actual source-extracted trade sizing through an offline HOLD sink.

No imports of original executors, Hyperliquid SDK, signer, or network.
These are calculations from source syntax run against a synthetic fixture,
not proof that real workloads have been converted or protected.
"""
import ast
import os
from pathlib import Path
import unittest
from unittest.mock import patch

from offline_original_executor_mutation_sink_ci import (
    OfflineOriginalExecutorMutationSink,
)

ROOT = Path(__file__).resolve().parents[1]
ACCOUNT = "0x" + "1" * 40
BOT_FILES = {
    "daily": "hyperliquid_executor.py",
    "intraday": "intraday_executor.py",
    "aggressive": "aggressive_executor.py",
}


def source_extracted_execute_trade(bot):
    path = BOT_FILES[bot]
    source = (ROOT / path).read_text(encoding="utf-8")
    tree = ast.parse(source, filename=path)
    candidates = [node for node in tree.body
                  if isinstance(node, ast.FunctionDef)
                  and node.name == "execute_trade"]
    if len(candidates) != 1:
        raise AssertionError("executor function changed")
    node = candidates[0]
    node.decorator_list = []
    standalone = ast.fix_missing_locations(
        ast.Module(body=[node], type_ignores=[]))
    namespace = {
        "os": os,
        "POSITION_SIZE_PCT": 0.10,
        "PYRAMID_SIZE_PCT": 0.05,
        "TESTNET_MIN_ORDER_NOTIONAL": 10.0,
        "MAINNET_MIN_ORDER_NOTIONAL": 10.0,
        "MIN_ORDER_NOTIONAL": 10.0,
        "get_mid_price": lambda info, coin: 100.0,
        "get_size_decimals": lambda info, coin: 3,
        "round_size": lambda size, decimals: round(size, decimals),
        "_parse_response": lambda trade, resp, info, coin: {
            **trade, "status": "synthetic_hold",
            "source_ack": resp.get("status"),
        },
    }
    exec(compile(standalone, path, "exec"), namespace)
    return namespace["execute_trade"]


class OriginalExecutorMutationSinkTests(unittest.TestCase):
    def run_original(self, bot, action, *, close_size=None):
        trade = {"hl_coin": "SOL", "action": action}
        if close_size is not None:
            trade["close_size"] = close_size
        sink = OfflineOriginalExecutorMutationSink(
            bot=bot, trade=trade, account=ACCOUNT, environment="mainnet")
        fn = source_extracted_execute_trade(bot)
        with patch.dict(os.environ, {"HL_TESTNET": "false"}, clear=True):
            result = fn(None, sink, trade, 1000, 2)
        return sink, result

    def test_original_new_entry_sizing_only_produces_request_preview(self):
        for bot in BOT_FILES:
            for action in ("open_long", "open_short"):
                with self.subTest(bot=bot, action=action):
                    sink, result = self.run_original(bot, action)
                    self.assertEqual(result["status"], "synthetic_hold")
                    self.assertEqual(result["source_ack"], "offline_hold")
                    self.assertEqual([e[0] for e in sink.events],
                                     ["leverage_hold", "entry_request_only"])
                    self.assertEqual(sink.last_review.state, "request_only")
                    self.assertIn('"rounded_size":"2"', sink.last_review.request_json)
                    self.assertFalse(sink.last_review.submit_authorized)
                    self.assertFalse(sink.last_review.ownership_verified)

    def test_aggressive_pyramids_never_become_entry_requests(self):
        for action in ("pyramid_long", "pyramid_short"):
            with self.subTest(action=action):
                sink, result = self.run_original("aggressive", action)
                self.assertEqual(result["status"], "synthetic_hold")
                self.assertEqual([e[0] for e in sink.events],
                                 ["leverage_hold", "entry_hold"])
                self.assertEqual(sink.last_review.action_class,
                                 "pyramid_increase")
                self.assertEqual(sink.last_review.state, "hold")
                self.assertIsNone(sink.last_review.request_json)

    def test_original_sized_and_unsized_closes_remain_held(self):
        for bot in BOT_FILES:
            for size in (None, 0.5):
                with self.subTest(bot=bot, size=size):
                    sink, result = self.run_original(
                        bot, "close", close_size=size)
                    self.assertEqual(result["source_ack"], "offline_hold")
                    self.assertEqual(sink.events, [("close_hold", "SOL", size)])
                    self.assertEqual(sink.last_review.state, "hold")
                    self.assertEqual(sink.last_review.action_class, "close")
                    self.assertFalse(sink.last_review.close_authorized)
                    self.assertIsNone(sink.last_review.request_json)

    def test_sink_rejects_call_direction_mismatch(self):
        sink = OfflineOriginalExecutorMutationSink(
            bot="daily", trade={"hl_coin": "SOL", "action": "open_short"},
            account=ACCOUNT, environment="mainnet")
        reply = sink.market_open("SOL", True, 1.0)
        self.assertEqual(reply["status"], "offline_hold")
        self.assertEqual(sink.last_review.state, "hold")
        self.assertIsNone(sink.last_review.request_json)

    def test_no_signing_or_original_executor_imports(self):
        import sys
        for name in (*[x.removesuffix(".py") for x in BOT_FILES.values()],
                     "hyperliquid.exchange"):
            self.assertNotIn(name, sys.modules)


if __name__ == "__main__":
    unittest.main()
