"""Offline regression tests for Intraday close-only dispatch.

Extract only the executor function from source so no pandas, credentials,
Hyperliquid client, network, or other runtime dependency is imported.
"""
import ast
from pathlib import Path
import unittest
from unittest.mock import Mock


def load_execute_trade():
    source = Path(__file__).resolve().parents[1] / "intraday_executor.py"
    tree = ast.parse(source.read_text(encoding="utf-8"), filename=str(source))
    fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "execute_trade")
    module = ast.fix_missing_locations(ast.Module(body=[fn], type_ignores=[]))
    namespace = {"_parse_response": Mock(return_value={"status": "filled"})}
    exec(compile(module, str(source), "exec"), namespace)
    return namespace["execute_trade"]


class FakeExchange:
    def __init__(self):
        self.closes = []
        self.opens = []

    def market_close(self, coin, sz=None):
        self.closes.append((coin, sz))
        return {"status": "ok"}

    def market_open(self, coin, is_buy, size):
        self.opens.append((coin, is_buy, size))
        raise AssertionError("New entry must never be submitted")


class IntradayCloseOnlyExecutionTests(unittest.TestCase):
    def setUp(self):
        self.exchange = FakeExchange()
        self.execute_trade = load_execute_trade()

    def test_existing_long_close_uses_requested_size(self):
        trade = {"ticker": "SOL-USD", "hl_coin": "SOL", "action": "close",
                 "side": "long", "close_size": 0.4}
        result = self.execute_trade(None, self.exchange, trade, 100, 2)
        self.assertEqual(result["status"], "filled")
        self.assertEqual(self.exchange.closes, [("SOL", 0.4)])
        self.assertEqual(self.exchange.opens, [])

    def test_existing_short_close_uses_requested_size(self):
        trade = {"ticker": "SOL-USD", "hl_coin": "SOL", "action": "close",
                 "side": "short", "close_size": 0.2}
        self.execute_trade(None, self.exchange, trade, 100, 2)
        self.assertEqual(self.exchange.closes, [("SOL", 0.2)])
        self.assertEqual(self.exchange.opens, [])

    def test_entry_trial_guard_is_opt_in_and_precedes_open(self):
        # Inspect the real executor's AST without invoking any entry order.
        source = Path(__file__).resolve().parents[1] / "intraday_executor.py"
        tree = ast.parse(source.read_text(encoding="utf-8"))
        fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef)
                  and n.name == "execute_trade")
        guards = [n for n in ast.walk(fn) if isinstance(n, ast.If)
                  and any(isinstance(x, ast.Constant)
                          and x.value == "INTRADAY_ENTRY_SAFETY_TRIAL"
                          for x in ast.walk(n.test))]
        self.assertEqual(len(guards), 1)
        guard = guards[0]
        self.assertTrue(any(isinstance(n, ast.Return) for n in guard.body))
        opens = [n for n in ast.walk(fn) if isinstance(n, ast.Call)
                 and isinstance(n.func, ast.Attribute)
                 and n.func.attr == "market_open"]
        self.assertEqual(len(opens), 1)
        self.assertLess(guard.lineno, opens[0].lineno)
        self.assertEqual(self.exchange.opens, [])

    def test_exchange_close_failure_propagates(self):
        trade = {"ticker": "SOL-USD", "hl_coin": "SOL", "action": "close",
                 "close_size": 0.3}
        self.exchange.market_close = Mock(side_effect=RuntimeError("offline exchange"))
        with self.assertRaises(RuntimeError):
            self.execute_trade(None, self.exchange, trade, 100, 2)
        self.assertEqual(self.exchange.opens, [])


if __name__ == "__main__":
    unittest.main()
