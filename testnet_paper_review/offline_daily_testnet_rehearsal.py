"""Crypto Y'all original Daily-bot order-path rehearsal — OFFLINE ONLY.

The exact reviewed Daily execute_trade() body is extracted from main, but
market_open, market_close, update_leverage, quotes and metadata are all MOCKED.
Never imports executors/Hyperliquid, uses secrets, contacts an API, updates
Gists, starts a GitHub workflow or authorizes any actual order.

The source hash is pinned. Any change to the original executor requires
new review before a rehearsal can run. Passing this DOES NOT mean the bot is
safe to operate live or that cross-bot ownership is verified.
"""
import ast
import hashlib
import os
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
ORIGINAL_DAILY = ROOT / "hyperliquid_executor.py"
EXPECTED_GIT_BLOB_SHA = "d98cba6e73507192f5155dfd7f2e414dddc7fcb4"
REVIEWED_COIN = "SOL"
FAKE_MID_PRICE = 100.0
FAKE_MIN_ORDER_NOTIONAL = 12.0


class OfflineHold(ValueError):
    pass


class FakeExchange:
    def __init__(self):
        self.calls = []

    def update_leverage(self, leverage, coin, cross):
        self.calls.append(("fake_leverage", leverage, coin, cross))

    def market_open(self, coin, is_buy, size):
        self.calls.append(("fake_open", coin, is_buy, size))
        return {"status": "FAKE_ONLY"}

    def market_close(self, coin, sz=None):
        self.calls.append(("fake_close", coin, sz))
        return {"status": "FAKE_ONLY"}


def reviewed_daily_function():
    payload = ORIGINAL_DAILY.read_bytes()
    expected = hashlib.sha1(
        b"blob " + str(len(payload)).encode("ascii") + b"\0" + payload
    ).hexdigest()
    if expected != EXPECTED_GIT_BLOB_SHA:
        raise OfflineHold("Daily executor changed: independent re-review required")
    tree = ast.parse(payload.decode("utf-8"), filename=str(ORIGINAL_DAILY))
    funcs = [
        node for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "execute_trade"
    ]
    if len(funcs) != 1:
        raise OfflineHold("reviewed execute_trade function not found")
    fn = funcs[0]
    if fn.decorator_list or any(isinstance(n, (
        ast.Import, ast.ImportFrom, ast.Global, ast.Nonlocal,
    )) for n in ast.walk(fn)):
        raise OfflineHold("unexpected dependency in Daily order function")

    safe_globals = {
        "__builtins__": {
            "float": float, "int": int, "max": max, "print": print,
            "Exception": Exception
        },
        "os": os,
        "POSITION_SIZE_PCT": 0.01,
        "MIN_ORDER_NOTIONAL": FAKE_MIN_ORDER_NOTIONAL,
        "get_mid_price": lambda info, coin: FAKE_MID_PRICE,
        "get_size_decimals": lambda info, coin: 3,
        "round_size": lambda value, decimals: round(value, decimals),
        "_parse_response": lambda trade, resp, info, coin: {
            **trade, "status": "MOCK_OFFLINE_ONLY",
        },
    }
    module = ast.fix_missing_locations(ast.Module(body=[fn], type_ignores=[]))
    exec(compile(module, str(ORIGINAL_DAILY), "exec"), safe_globals)
    return safe_globals["execute_trade"]


def rehearse_one_daily_action(action, *, allocated_capital=100.0, leverage=1.0):
    """Run just one REVIEW fixture through a fake exchange; no order authority."""
    if action not in ("open_long", "open_short", "close"):
        raise OfflineHold("unreviewed synthetic Daily action")
    if (type(allocated_capital) not in (int, float)
            or type(leverage) not in (int, float)
            or not 0 < allocated_capital <= 100 or leverage != 1):
        raise OfflineHold("synthetic capital/leverage outside reviewed range")
    fake = FakeExchange()
    trade = {"hl_coin": REVIEWED_COIN, "action": action}
    # Only inside mock AST function execution; never exported to a workflow,
    # executor, process, network client, or GitHub repository variable.
    with patch.dict(os.environ, {"HL_TESTNET": "true"}):
        result = reviewed_daily_function()(
            None, fake, trade, allocated_capital, leverage
        )
    return result, fake.calls
