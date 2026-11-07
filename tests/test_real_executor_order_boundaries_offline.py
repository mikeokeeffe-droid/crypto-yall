"""Offline contract tests of the *real* execute_trade functions, never live clients.

Extract only the function AST: importing the executor modules could initialize
credentials or unrelated runtime services. Exchange and price feeds are fakes.
"""
import ast
import os
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
FILES = ("aggressive_executor.py", "intraday_executor.py", "hyperliquid_executor.py")

class FakeExchange:
    def __init__(self):
        self.calls = []
    def market_open(self, *args, **kwargs):
        self.calls.append(("open", args, kwargs))
        return {"status": "ok"}
    def market_close(self, *args, **kwargs):
        self.calls.append(("close", args, kwargs))
        return {"status": "ok"}
    def update_leverage(self, *args, **kwargs):
        self.calls.append(("leverage", args, kwargs))

def load_function(filename):
    source = (ROOT / filename).read_text()
    tree = ast.parse(source)
    fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef)
              and n.name == "execute_trade")
    isolated = ast.Module(body=[fn], type_ignores=[])
    ast.fix_missing_locations(isolated)
    namespace = {
        "os": os,
        "POSITION_SIZE_PCT": 0.1,
        "PYRAMID_SIZE_PCT": 0.05,
        "TESTNET_MIN_ORDER_NOTIONAL": 11.0,
        "MAINNET_MIN_ORDER_NOTIONAL": 10.0,
        "MIN_ORDER_NOTIONAL": 10.0,
        "get_mid_price": lambda info, coin: 100.0,
        "get_size_decimals": lambda info, coin: 3,
        "round_size": lambda size, decimals: round(size, decimals),
        "_parse_response": lambda trade, response, info, coin: {**trade, "status": "filled"},
    }
    exec(compile(isolated, filename, "exec"), namespace)
    return namespace["execute_trade"]

class RealExecutorOrderBoundaryTests(TestCase):
    def test_closes_do_not_open_new_positions(self):
        for filename in FILES:
            with self.subTest(filename=filename):
                exchange = FakeExchange()
                result = load_function(filename)(
                    object(), exchange, {"hl_coin": "SOL", "action": "close"},
                    100.0, 1.0)
                self.assertEqual(result["status"], "filled")
                self.assertEqual([call[0] for call in exchange.calls], ["close"])

    def test_entries_and_pyramids_are_blocked_without_reservation_fence(self):
        for filename in FILES:
            for action in ("open_long", "open_short", "pyramid_long", "pyramid_short"):
                with self.subTest(filename=filename, action=action):
                    exchange = FakeExchange()
                    result = load_function(filename)(
                        object(), exchange, {"hl_coin": "SOL", "action": action},
                        100.0, 1.0)
                    self.assertEqual(result["status"], "blocked")
                    self.assertIn("gateway is not configured", result["reason"])
                    self.assertFalse(any(call[0] in ("open", "leverage") for call in exchange.calls))

    def test_successful_staging_claim_still_blocks_open_and_leverage(self):
        for filename in FILES:
            for action in ("open_long", "open_short", "pyramid_long", "pyramid_short"):
                with self.subTest(filename=filename, action=action):
                    exchange = FakeExchange()
                    requests = []

                    def gateway(**request):
                        requests.append(request)
                        return {
                            "reservation_claimed": True,
                            "intent_claimed": True,
                        }

                    result = load_function(filename)(
                        object(), exchange, {"hl_coin": "SOL", "action": action},
                        100.0, 1.0, entry_gateway=gateway)
                    self.assertEqual(result["status"], "blocked")
                    self.assertTrue(result["staging_claimed"])
                    self.assertEqual(len(requests), 1)
                    self.assertEqual(exchange.calls, [])

    def test_failed_or_malformed_staging_claim_never_reaches_exchange(self):
        outcomes = (
            False,
            {"reservation_claimed": True, "intent_claimed": False},
            {"reservation_claimed": True, "intent_claimed": True,
             "live_order_authorized": True},
        )
        for filename in FILES:
            for outcome in outcomes:
                with self.subTest(filename=filename, outcome=outcome):
                    exchange = FakeExchange()
                    result = load_function(filename)(
                        object(), exchange,
                        {"hl_coin": "SOL", "action": "open_long"},
                        100.0, 1.0,
                        entry_gateway=lambda **request: outcome)
                    self.assertEqual(result["status"], "blocked")
                    self.assertFalse(result["staging_claimed"])
                    self.assertEqual(exchange.calls, [])

            exchange = FakeExchange()

            def unavailable(**request):
                raise ConnectionError("synthetic outage")

            result = load_function(filename)(
                object(), exchange,
                {"hl_coin": "SOL", "action": "open_long"},
                100.0, 1.0, entry_gateway=unavailable)
            self.assertEqual(result["status"], "blocked")
            self.assertIn("ConnectionError", result["reason"])
            self.assertEqual(exchange.calls, [])

    def test_partial_close_remains_independent_of_gateway(self):
        for filename in FILES:
            with self.subTest(filename=filename):
                exchange = FakeExchange()
                calls = []
                result = load_function(filename)(
                    object(), exchange,
                    {"hl_coin": "SOL", "action": "close", "close_size": 0.25},
                    100.0, 1.0,
                    entry_gateway=lambda **request: calls.append(request))
                self.assertEqual(result["status"], "filled")
                self.assertEqual(calls, [])
                self.assertEqual([call[0] for call in exchange.calls], ["close"])

    def test_mainnet_entries_remain_blocked(self):
        for filename in FILES:
            with self.subTest(filename=filename):
                exchange = FakeExchange()
                with patch.dict(os.environ, {
                    "HL_TESTNET": "false",
                    "AGGRESSIVE_TEST_NOTIONAL": "0",
                    "INTRADAY_TEST_NOTIONAL": "0",
                }):
                    result = load_function(filename)(
                        object(), exchange, {"hl_coin": "SOL", "action": "open_long"},
                        1.0, 1.0)
                self.assertEqual(result["status"], "blocked")
                self.assertFalse(any(call[0] == "open" for call in exchange.calls))
