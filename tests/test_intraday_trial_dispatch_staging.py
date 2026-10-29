"""Contract: staging claims never authorize Intraday live entry orders."""
import ast
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]

class IntradayProductionIsolationTests(unittest.TestCase):
    def test_live_executor_has_no_staging_trial_guard(self):
        tree = ast.parse((ROOT / "intraday_executor.py").read_text())
        fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef)
                  and n.name == "execute_trade")
        self.assertFalse(any(isinstance(n, ast.Constant)
                             and n.value == "INTRADAY_ENTRY_SAFETY_TRIAL"
                             for n in ast.walk(fn)))
        self.assertFalse(any(isinstance(n, ast.Name)
                             and n.id == "observe_intraday_entry"
                             for n in ast.walk(fn)))
        self.assertTrue(any(
            isinstance(n, ast.ImportFrom)
            and n.module == "executor_staging_entry_integration"
            and any(alias.name == "staging_entry_dispatch_result"
                    for alias in n.names)
            for n in ast.walk(fn)
        ))
        self.assertFalse(any(
            isinstance(n, ast.Call)
            and isinstance(n.func, ast.Attribute)
            and n.func.attr in ("market_open", "update_leverage")
            for n in ast.walk(fn)
        ))

        class FakeExchange:
            def __init__(self):
                self.calls = []

            def market_open(self, *args, **kwargs):
                self.calls.append(("market_open", args, kwargs))

            def update_leverage(self, *args, **kwargs):
                self.calls.append(("update_leverage", args, kwargs))

            def market_close(self, *args, **kwargs):
                self.calls.append(("market_close", args, kwargs))
                return {"status": "ok"}

        isolated = ast.Module(body=[fn], type_ignores=[])
        ast.fix_missing_locations(isolated)
        namespace = {
            "_parse_response": lambda trade, response, info, coin: {
                **trade, "status": "filled"
            },
        }
        exec(compile(isolated, "intraday_executor.py", "exec"), namespace)
        execute_trade = namespace["execute_trade"]

        for action in ("open_long", "open_short", "pyramid_long", "pyramid_short"):
            with self.subTest(action=action):
                exchange = FakeExchange()
                gateway_calls = []

                def successful_staging_claim(**request):
                    gateway_calls.append(request)
                    return {
                        "reservation_claimed": True,
                        "intent_claimed": True,
                    }

                result = execute_trade(
                    object(), exchange,
                    {"hl_coin": "BTC", "action": action},
                    1000.0, 3.0,
                    entry_gateway=successful_staging_claim,
                )
                self.assertEqual(result["status"], "blocked")
                self.assertTrue(result["staging_claimed"])
                self.assertEqual(exchange.calls, [])
                self.assertEqual(gateway_calls, [{
                    "bot": "intraday",
                    "coin": "BTC",
                    "action": action,
                }])

        for close_size in (None, 0.25):
            with self.subTest(close_size=close_size):
                exchange = FakeExchange()

                def forbidden_gateway(**request):
                    self.fail("close path must not call the staging gateway")

                trade = {"hl_coin": "BTC", "action": "close"}
                if close_size is not None:
                    trade["close_size"] = close_size
                result = execute_trade(
                    object(), exchange, trade, 1000.0, 3.0,
                    entry_gateway=forbidden_gateway,
                )
                self.assertEqual(result["status"], "filled")
                self.assertEqual(len(exchange.calls), 1)
                self.assertEqual(exchange.calls[0][0], "market_close")
                if close_size is None:
                    self.assertEqual(exchange.calls[0][1:], (("BTC",), {}))
                else:
                    self.assertEqual(exchange.calls[0][1:], (
                        ("BTC",), {"sz": close_size}
                    ))

if __name__ == "__main__":
    unittest.main()
