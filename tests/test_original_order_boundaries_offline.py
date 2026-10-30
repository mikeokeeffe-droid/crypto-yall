"""Offline characterization of ORIGINAL main-branch executor order boundaries.

These tests load ONLY execute_trade() syntax from the three original source
files; no trading modules are imported and no Hyperliquid/Gist/Supabase clients
are constructed. Fake exchange objects collect calls, never place orders.

Passing these tests is baseline behaviour evidence, NOT authorization to trade,
and NOT proof of a shared cross-bot reservation or crash-safe protection.
"""
import ast
import os
from pathlib import Path
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
EXECUTORS = {
    "aggressive": "aggressive_executor.py",
    "intraday": "intraday_executor.py",
    "daily": "hyperliquid_executor.py",
}


class FakeExchange:
    def __init__(self):
        self.calls = []

    def market_open(self, coin, is_buy, size):
        self.calls.append(("open", coin, is_buy, size))
        return {"status": "ok", "fake": True}

    def market_close(self, coin, sz=None):
        self.calls.append(("close", coin, sz))
        return {"status": "ok", "fake": True}

    def update_leverage(self, leverage, coin, cross):
        self.calls.append(("leverage", leverage, coin, cross))


def isolated_function(path, function_name):
    """Extract one function without importing source-module side effects."""
    tree = ast.parse((ROOT / path).read_text(encoding="utf-8"), filename=path)
    candidates = [
        node for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == function_name
    ]
    if len(candidates) != 1:
        raise AssertionError(f"Expected exactly one {function_name} in {path}")
    fn = candidates[0]
    fn.decorator_list = []
    module = ast.fix_missing_locations(ast.Module(body=[fn], type_ignores=[]))
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
            **trade,
            "status": "simulated",
            "exchange_response": resp,
        },
    }
    exec(compile(module, path, "exec"), namespace)
    return namespace[function_name]


class OriginalExecutorOrderBoundaryTests(unittest.TestCase):
    def run_trade(self, bot, action, *, capital=1000, leverage=2,
                  close_size=None, testnet=False):
        env = {"HL_TESTNET": "true" if testnet else "false"}
        exchange = FakeExchange()
        trade = {"hl_coin": "SOL", "action": action}
        if close_size is not None:
            trade["close_size"] = close_size
        fn = isolated_function(EXECUTORS[bot], "execute_trade")
        with patch.dict(os.environ, env, clear=True):
            result = fn(None, exchange, trade, capital, leverage)
        return result, exchange.calls

    def test_original_long_and_short_entries_have_one_order_call(self):
        for bot in EXECUTORS:
            for action, is_buy in (("open_long", True), ("open_short", False)):
                with self.subTest(bot=bot, action=action):
                    result, calls = self.run_trade(bot, action)
                    self.assertEqual(result["status"], "simulated")
                    self.assertEqual(calls[0], ("leverage", 2, "SOL", True))
                    self.assertEqual(calls[1], ("open", "SOL", is_buy, 2.0))
                    self.assertEqual(len(calls), 2)

    def test_partial_and_full_closes_do_not_modify_leverage_or_open(self):
        for bot in EXECUTORS:
            for close_size, expected in ((1.25, 1.25), (None, None)):
                with self.subTest(bot=bot, close_size=close_size):
                    result, calls = self.run_trade(
                        bot, "close", capital=0, leverage=1,
                        close_size=close_size,
                    )
                    self.assertEqual(result["status"], "simulated")
                    self.assertEqual(calls, [("close", "SOL", expected)])

    def test_mainnet_undersized_entries_are_skipped(self):
        for bot in EXECUTORS:
            with self.subTest(bot=bot):
                result, calls = self.run_trade(
                    bot, "open_long", capital=10, leverage=1
                )
                self.assertEqual(result["status"], "skipped")
                self.assertEqual(calls, [])

    def test_testnet_minimum_baseline_without_real_orders(self):
        for bot in EXECUTORS:
            with self.subTest(bot=bot):
                result, calls = self.run_trade(
                    bot, "open_long", capital=50, leverage=1, testnet=True
                )
                self.assertEqual(result["status"], "simulated")
                self.assertEqual(calls, [
                    ("leverage", 1, "SOL", True),
                    ("open", "SOL", True, 0.1),
                ])

    def test_aggressive_pyramids_are_increasing_orders_with_smaller_size(self):
        for action, is_buy in (("pyramid_long", True), ("pyramid_short", False)):
            with self.subTest(action=action):
                result, calls = self.run_trade("aggressive", action)
                self.assertEqual(result["status"], "simulated")
                self.assertEqual(calls, [
                    ("leverage", 2, "SOL", True),
                    ("open", "SOL", is_buy, 1.0),
                ])

    def test_existing_dispatch_has_no_shared_atomic_entry_fence(self):
        # Characterize a known safety gap, NOT a passing concurrency safety test.
        # Calling these original submitters separately can create two entries;
        # a future gate must deny one using durable shared state before submit.
        first, calls_a = self.run_trade("aggressive", "open_long")
        second, calls_b = self.run_trade("intraday", "open_long")
        self.assertEqual(first["status"], "simulated")
        self.assertEqual(second["status"], "simulated")
        self.assertEqual(sum(call[0] == "open" for call in calls_a + calls_b), 2)

    def test_original_order_calls_are_confined_to_expected_function(self):
        for bot, path in EXECUTORS.items():
            with self.subTest(bot=bot):
                tree = ast.parse((ROOT / path).read_text(encoding="utf-8"))
                market_open_calls = []
                for node in ast.walk(tree):
                    if (
                        isinstance(node, ast.Call)
                        and isinstance(node.func, ast.Attribute)
                        and node.func.attr == "market_open"
                    ):
                        market_open_calls.append(node.lineno)
                self.assertEqual(
                    len(market_open_calls), 1,
                    f"Review new/alternate market_open path in {path}",
                )

    def test_current_kill_switch_exits_before_exchange_client(self):
        # This documents a separate risk: a disabled executor currently cannot
        # proceed to protective closes. No kill-switch logic is changed here.
        names = {
            "aggressive": "kill_switch_off",
            "intraday": "kill_switch_off",
            "daily": "check_kill_switch",
        }
        for bot, path in EXECUTORS.items():
            with self.subTest(bot=bot):
                tree = ast.parse((ROOT / path).read_text(encoding="utf-8"))
                main = next(
                    n for n in tree.body
                    if isinstance(n, ast.FunctionDef) and n.name == "main"
                )
                calls = [
                    (n.func.id, n.lineno)
                    for n in ast.walk(main)
                    if isinstance(n, ast.Call)
                    and isinstance(n.func, ast.Name)
                ]
                switch_lines = [
                    ln for name, ln in calls if name == names[bot]
                ]
                client_lines = [ln for name, ln in calls if name == "get_client"]
                self.assertTrue(switch_lines and client_lines)
                self.assertLess(min(switch_lines), min(client_lines))


if __name__ == "__main__":
    unittest.main()
