"""Disposable CI sizing path: original execute_trade source -> V2 preview.

Only the original function bodies (execute_trade and Daily round_size) are
extracted, never the signer-capable executor modules or Hyperliquid SDK.
Every original exchange mutation is intercepted by an offline HOLD sink.
The input is synthetic; this module cannot authorize an order or verify fills.
Source drift in call shapes fails closed. It is not a Python sandbox for
untrusted repositories, a real-client replacement, or a production service.
"""
import ast
from dataclasses import dataclass
from decimal import Decimal, ROUND_DOWN
import json
from pathlib import Path
from types import MappingProxyType, SimpleNamespace

from offline_leverage_bound_entry_draft_ci import (
    OfflineLeverageBoundEntrySink,
)
from offline_original_signal_projection_ci import (
    project_original_entry_candidate_offline,
)
from offline_original_read_helper_cutover_ci import (
    extract_original_info_read_helpers_offline,
)

_FILES = {
    "daily": "hyperliquid_executor.py",
    "intraday": "intraday_executor.py",
    "aggressive": "aggressive_executor.py",
}
_ALLOWED_FREE_CALLS = {
    "float", "int", "str", "max", "min", "Decimal", "get_mid_price",
    "get_size_decimals", "round_size", "_parse_response", "print",
}
_ALLOWED_METHODS = {
    "get", "lower", "startswith", "scaleb", "quantize",
    "market_open", "market_close", "update_leverage",
}
_MUTATIONS = {"market_open", "market_close", "update_leverage"}
_SOURCE_CONFIG = {
    "daily": ("POSITION_SIZE_PCT", "MIN_ORDER_NOTIONAL"),
    "intraday": ("POSITION_SIZE_PCT", "TESTNET_MIN_ORDER_NOTIONAL",
                 "MAINNET_MIN_ORDER_NOTIONAL"),
    "aggressive": ("POSITION_SIZE_PCT", "PYRAMID_SIZE_PCT",
                   "TESTNET_MIN_ORDER_NOTIONAL"),
}
_CI_CAPITAL = 1000.0
_CI_LEVERAGE = 2


@dataclass(frozen=True)
class OriginalSizingPreview:
    state: str = "hold"
    rounded_size: str | None = None
    v2_json: str | None = None
    requested_leverage: int | None = None
    submit_authorized: bool = False
    leverage_applied: bool = False


def _read_literal_constants(tree, bot):
    output = {}
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            if (isinstance(target, ast.Name)
                    and target.id in _SOURCE_CONFIG[bot]):
                if target.id in output:
                    raise ValueError("ambiguous sizing configuration")
                number = ast.literal_eval(node.value)
                if (type(number) is not float
                        or not 0 < number <= 100):
                    raise ValueError("unreviewed original sizing constant")
                output[target.id] = number
    if set(output) != set(_SOURCE_CONFIG[bot]):
        raise ValueError("missing original sizing constants")
    return output


def _checked_function(tree, name, *, sizing=False):
    nodes = [
        node for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == name
    ]
    if len(nodes) != 1:
        raise ValueError("missing or duplicate original function")
    fn = nodes[0]
    if (fn.decorator_list or fn.args.defaults or fn.args.kw_defaults
            or fn.args.vararg or fn.args.kwarg
            or fn.args.kwonlyargs or fn.args.posonlyargs):
        raise ValueError("changed original sizing function signature")
    counts = {name: 0 for name in _MUTATIONS}
    for node in ast.walk(fn):
        if (node is not fn and isinstance(
                node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Import,
                       ast.ImportFrom, ast.Global, ast.Nonlocal, ast.Lambda,
                       ast.Await, ast.Yield, ast.YieldFrom, ast.ClassDef,
                       ast.With, ast.AsyncWith))):
            raise ValueError("unreviewed source structure")
        if isinstance(node, ast.Attribute) and (
                node.attr.startswith("_") or
                node.attr not in (_ALLOWED_METHODS | {"environ"})):
            raise ValueError("unreviewed source attribute")
        if isinstance(node, ast.Call):
            target = node.func
            if isinstance(target, ast.Name):
                if target.id not in _ALLOWED_FREE_CALLS:
                    raise ValueError("unreviewed sizing call")
            elif isinstance(target, ast.Attribute):
                if target.attr not in _ALLOWED_METHODS:
                    raise ValueError("unreviewed sizing method call")
                if target.attr in _MUTATIONS:
                    if (not isinstance(target.value, ast.Name)
                            or target.value.id != "exchange"):
                        raise ValueError("exchange call outside HOLD sink")
                    counts[target.attr] += 1
                if target.attr == "get" and isinstance(
                        target.value, ast.Attribute):
                    if (target.value.attr != "environ"
                            or not isinstance(target.value.value, ast.Name)
                            or target.value.value.id != "os"):
                        raise ValueError("unreviewed source environment")
            else:
                raise ValueError("indirect sizing call")
        if (isinstance(node, ast.Name)
                and node.id in ("__import__", "open", "get_client",
                                "eval", "exec", "compile", "globals",
                                "locals", "getattr", "setattr", "delattr")):
            raise ValueError("unreviewed source capability")
    if sizing and counts != {
            "market_open": 1, "market_close": 2, "update_leverage": 1}:
        raise ValueError("mutation callsites changed")
    if not sizing and any(counts.values()):
        raise ValueError("rounding function gained mutation call")
    fn.decorator_list = []
    return fn


def _build_original_executor_offline(bot, source_root, helpers):
    if bot not in _FILES or not isinstance(source_root, Path):
        raise ValueError("unsupported original sizing source")
    path = source_root / _FILES[bot]
    daily = source_root / _FILES["daily"]
    if (not path.is_file() or path.is_symlink()
            or not daily.is_file() or daily.is_symlink()):
        raise ValueError("missing regular source files")
    tree = ast.parse(path.read_text(encoding="utf-8"))
    daily_tree = ast.parse(daily.read_text(encoding="utf-8"))
    config = _read_literal_constants(tree, bot)
    executor = _checked_function(tree, "execute_trade", sizing=True)
    rounding = _checked_function(daily_tree, "round_size")
    # No worker signing env, even accidentally. The original source sees
    # only a read-only, deterministic synthetic mainnet sizing configuration.
    fake_os = SimpleNamespace(environ=MappingProxyType({
        "HL_TESTNET": "false",
        "INTRADAY_TEST_NOTIONAL": "0",
        "AGGRESSIVE_TEST_NOTIONAL": "0",
    }))
    def hold_reply(trade, resp, info, coin):
        return {"status": "synthetic_hold",
                "source_ack": resp.get("status")}
    allowed = {
        "__builtins__": {
            "float": float, "int": int, "str": str, "dict": dict,
            "max": max, "min": min, "Exception": Exception,
            "print": lambda *args, **kwargs: None,
        },
        "os": fake_os, "Decimal": Decimal, "ROUND_DOWN": ROUND_DOWN,
        "get_mid_price": helpers["get_mid_price"],
        "get_size_decimals": helpers["get_size_decimals"],
        "_parse_response": hold_reply, **config,
    }
    round_module = ast.fix_missing_locations(
        ast.Module(body=[rounding], type_ignores=[]),
    )
    exec(compile(round_module, "offline-original-round", "exec"), allowed)
    exec_module = ast.fix_missing_locations(
        ast.Module(body=[executor], type_ignores=[]),
    )
    exec(compile(exec_module, "offline-original-sizing", "exec"), allowed)
    return allowed["execute_trade"]


def preview_original_sizing_for_v2_offline(
    *, bot, source_root, view, original_candidate,
    capital=_CI_CAPITAL, requested_leverage=_CI_LEVERAGE,
):
    """Compute source-shaped, size+leverage review data; no order authority."""
    hold = OriginalSizingPreview()
    if (bot not in _FILES
            or type(capital) is not float or capital != _CI_CAPITAL
            or type(requested_leverage) is not int
            or requested_leverage != _CI_LEVERAGE
            or view is None or view.bot != bot
            or view.origin_authenticated or view.ownership_verified
            or view.submit_authorized
            or type(original_candidate) is not dict):
        return hold
    projection = project_original_entry_candidate_offline(
        verified_bot=bot, candidate=original_candidate,
    )
    if (projection.state != "projected_review_only"
            or projection.submit_authorized
            or projection.ownership_verified):
        return hold
    try:
        helpers = extract_original_info_read_helpers_offline(
            source_root=source_root,
        )
        fn = _build_original_executor_offline(bot, source_root, helpers)
        trade = json.loads(projection.trade_json)
        sink = OfflineLeverageBoundEntrySink(
            bot=bot, trade=trade,
            environment=view.environment, account=view.account,
        )
        response = fn(
            view.info, sink, trade, capital, requested_leverage,
        )
        draft = sink.last_draft
        if (type(response) is not dict
                or response != {
                    "status": "synthetic_hold", "source_ack": "offline_hold"
                }
                or sink.leverage_attempts != 1
                or sink.requested_leverage != requested_leverage
                or sink.cross_margin_requested is not True
                or [event[0] for event in sink.events] != [
                    "leverage_hold", "entry_request_only"
                ]
                or draft.state != "review_only" or draft.submit_authorized
                or draft.leverage_applied
                or type(draft.review_json) is not str):
            return hold
        payload = json.loads(draft.review_json)
        if (type(payload) is not dict
                or set(payload) != {
                    "operation", "action", "side", "hl_coin",
                    "rounded_size", "requested_leverage",
                    "cross_margin_requested"
                } or payload["operation"] != "review_entry_leverage_v2"
                or payload["action"] != trade["action"]
                or payload["side"] != trade["side"]
                or payload["hl_coin"] != trade["hl_coin"]
                or payload["requested_leverage"] != requested_leverage
                or payload["cross_margin_requested"] is not True
                or type(payload["rounded_size"]) is not str):
            return hold
        return OriginalSizingPreview(
            state="review_only",
            rounded_size=payload["rounded_size"],
            v2_json=draft.review_json,
            requested_leverage=requested_leverage,
        )
    except (OSError, ValueError, KeyError, TypeError,
            OverflowError, ArithmeticError):
        return hold
