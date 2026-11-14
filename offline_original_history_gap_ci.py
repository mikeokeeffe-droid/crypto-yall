"""Offline-only original history fallback audit and fail-closed review.

The ORIGINAL Daily history helper bodies are extracted as text/AST, never by
importing the signer-capable executor module. They run only against synthetic
Info that denies fill and funding reads. This exposes legacy accounting fallback
semantics; neither a fallback zero nor a local timestamp proves exchange truth.

No real network, SDK, wallet, order, exchange ownership, or dispatch authority.
"""
import ast
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace

_HELPERS = (
    "get_order_fill_totals",
    "get_position_open_time_ms",
    "get_position_funding",
)
_FREE_CALLS = frozenset((
    "str", "int", "float", "print", "range", "sorted", "len",
    "sum", "min", "max", "reversed", "bool",
    "get_position_open_time_ms", "_history_time_ms",
))
_METHODS = frozenset((
    "get", "user_fills", "user_funding_history", "sleep",
    "now", "timestamp",
))
_EXCHANGE_READS = frozenset(("user_fills", "user_funding_history"))
_FORBIDDEN_NAMES = frozenset((
    "get_client", "Exchange", "Account", "eval", "exec", "open",
    "__import__", "compile", "requests", "subprocess", "os",
))


@dataclass(frozen=True)
class OfflineLegacyHistoryReview:
    state: str = "hold"
    reason: str = "independent exchange history unavailable"
    fill_details_present: bool = False
    funding_reported_complete: bool = False
    exchange_origin_authenticated: bool = False
    history_complete: bool = False
    ownership_verified: bool = False
    close_authorized: bool = False
    submit_authorized: bool = False


def review_legacy_history_accounting_offline(*, fill_totals, funding_totals):
    """Flag missing accounting, without converting any data into authority."""
    if type(funding_totals) is not dict:
        return OfflineLegacyHistoryReview(reason="invalid funding result")
    expected = {
        "funding_pnl", "funding_count", "funding_data_complete",
        "funding_start_time_ms",
    }
    if set(funding_totals) != expected:
        return OfflineLegacyHistoryReview(reason="unknown funding schema")
    funding_complete = funding_totals["funding_data_complete"] is True
    fills_present = type(fill_totals) is dict and set(fill_totals) == {
        "closed_pnl", "fee", "fee_tokens", "fill_count",
        "first_time", "last_time",
    }
    if fill_totals is not None and not fills_present:
        return OfflineLegacyHistoryReview(reason="unknown fill schema")
    return OfflineLegacyHistoryReview(
        reason=(
            "legacy history accounting absent or incomplete; cannot infer "
            "zero fills, zero funding, exclusive position size or close rights"
            if not (fills_present and funding_complete) else
            "self-reported legacy accounting is not independent exchange "
            "provenance or position ownership"
        ),
        fill_details_present=fills_present,
        funding_reported_complete=funding_complete,
    )


def extract_original_history_helpers_offline(*, source_root):
    """Load exact reviewed helper bodies into a restricted CI-only namespace."""
    if not isinstance(source_root, Path):
        raise ValueError("local CI Path required")
    source_path = source_root / "hyperliquid_executor.py"
    if source_path.is_symlink() or not source_path.is_file():
        raise ValueError("regular original source required")
    tree = ast.parse(source_path.read_text(encoding="utf-8"))
    selected = [
        node for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name in _HELPERS
    ]
    if len(selected) != len(_HELPERS):
        raise ValueError("original historical helpers changed")
    seen_reads = set()
    for fn in selected:
        if (fn.decorator_list or fn.args.kwonlyargs
                or fn.args.vararg or fn.args.kwarg):
            raise ValueError("unreviewed original history helper signature")
        for node in ast.walk(fn):
            if node is not fn and isinstance(
                node, (ast.Import, ast.ImportFrom, ast.FunctionDef,
                       ast.AsyncFunctionDef, ast.ClassDef, ast.Global,
                       ast.Nonlocal, ast.Lambda, ast.Await,
                       ast.Yield, ast.YieldFrom, ast.With, ast.AsyncWith)):
                raise ValueError("unreviewed history source structure")
            if isinstance(node, ast.Name) and node.id in _FORBIDDEN_NAMES:
                raise ValueError("forbidden signing or runtime capability")
            if (isinstance(node, ast.Attribute)
                    and node.attr.startswith("_")):
                raise ValueError("private attribute in history helper")
            if isinstance(node, ast.Call):
                call = node.func
                if isinstance(call, ast.Name):
                    if call.id not in _FREE_CALLS:
                        raise ValueError("unreviewed history function")
                elif isinstance(call, ast.Attribute):
                    if call.attr not in _METHODS:
                        raise ValueError("unreviewed history method")
                    if call.attr in _EXCHANGE_READS:
                        if (not isinstance(call.value, ast.Name)
                                or call.value.id != "info"):
                            raise ValueError("history reads not on pinned Info")
                        seen_reads.add(call.attr)
                else:
                    raise ValueError("indirect history invocation")
    if seen_reads != _EXCHANGE_READS:
        raise ValueError("history exchange read coverage changed")
    namespace = {
        "__builtins__": {
            "str": str, "int": int, "float": float, "range": range,
            "dict": dict, "tuple": tuple, "list": list, "set": set,
            "sorted": sorted, "len": len, "sum": sum, "min": min,
            "max": max, "reversed": reversed, "bool": bool,
            "Exception": Exception, "TypeError": TypeError,
            "ValueError": ValueError,
            "print": lambda *args, **kwargs: None,
        },
        "time": SimpleNamespace(sleep=lambda _: None),
        "dt": SimpleNamespace(datetime=SimpleNamespace(
            now=lambda _: (_ for _ in ()).throw(
                AssertionError("clock fallback not allowed in CI historical read")
            )
        )),
        "_history_time_ms": lambda _: (_ for _ in ()).throw(
            AssertionError("unreviewed local history timestamp fallback")
        ),
    }
    module = ast.fix_missing_locations(
        ast.Module(body=selected, type_ignores=[]),
    )
    exec(compile(module, "offline-original-history-CI", "exec"), namespace)
    return {name: namespace[name] for name in _HELPERS}
