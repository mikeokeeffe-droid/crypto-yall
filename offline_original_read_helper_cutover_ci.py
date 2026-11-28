"""CI-only extraction of the ORIGINAL account/market read helpers.

This is a source-level migration seam, not a production import/replacement.
The three original executors still import signer-capable get_client(); this
module NEVER imports them, their dependencies, the signer or network SDK.

Only five reviewed Info-only helper bodies are compiled against a synthetic
read-only Info fixture with deliberately restricted builtins. Any new method
call, global, import or execution path in those bodies fails closed.
This is compatibility evidence, NOT exchange authenticity or ownership.
"""
import ast
from pathlib import Path

_SOURCE = "hyperliquid_executor.py"
_READ_HELPERS = frozenset((
    "get_account_equity", "get_open_positions", "get_mid_price",
    "coin_is_listed", "get_size_decimals",
))
_ALLOWED_INFO = frozenset((
    "user_state", "spot_user_state", "all_mids", "meta",
))
_ALLOWED_CALLS = frozenset(("float", "int", "isinstance", "next"))
_ALLOWED_DICT_CALLS = frozenset(("get",))
_ALLOWED_NAMES = frozenset((
    "info", "address", "coin", "state", "equity", "spot_state",
    "usdc_balance", "b", "p", "pos", "positions", "size",
    "raw_leverage", "leverage", "meta", "universe",
    "float", "int", "isinstance", "dict", "str", "bool", "next",
    "Exception", "TypeError", "ValueError", "True", "False",
))
_SAFE_BUILTINS = {
    "float": float, "int": int, "isinstance": isinstance,
    "next": next, "dict": dict, "str": str, "bool": bool,
    "TypeError": TypeError, "ValueError": ValueError,
}


def extract_original_info_read_helpers_offline(*, source_root):
    """Read and isolate actual legacy helper bodies; reject source drift.

    Returns a dict of callable source-extracted helpers or raises ValueError.
    The source directory is supplied by trusted CI and cannot enable a
    trading client or call any code from the original module's imports.
    """
    if not isinstance(source_root, Path):
        raise ValueError("trusted local CI source Path required")
    source_path = source_root / _SOURCE
    if source_path.is_symlink() or not source_path.is_file():
        raise ValueError("missing regular original executor source")
    tree = ast.parse(source_path.read_text(encoding="utf-8"), filename=_SOURCE)
    selected = [
        node for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name in _READ_HELPERS
    ]
    if len(selected) != len(_READ_HELPERS) or (
        {node.name for node in selected} != _READ_HELPERS
    ):
        raise ValueError("original read-helper entrypoints changed")
    for fn in selected:
        if (fn.decorator_list or fn.args.posonlyargs or fn.args.kwonlyargs
                or fn.args.vararg or fn.args.kwarg or fn.args.defaults
                or fn.args.kw_defaults):
            raise ValueError("unreviewed helper signature")
        for node in ast.walk(fn):
            if isinstance(node, (ast.Import, ast.ImportFrom, ast.Global,
                                 ast.Nonlocal, ast.Lambda, ast.Await,
                                 ast.Yield, ast.YieldFrom,
                                 ast.FunctionDef, ast.AsyncFunctionDef)):
                if node is not fn:
                    raise ValueError("unreviewed read-helper code structure")
            if isinstance(node, ast.Name):
                if node.id not in _ALLOWED_NAMES:
                    raise ValueError("unreviewed helper name " + node.id)
            if isinstance(node, ast.Attribute):
                if node.attr.startswith("_"):
                    raise ValueError("private attribute in source helper")
            if isinstance(node, ast.Call):
                call = node.func
                if isinstance(call, ast.Name):
                    if call.id not in _ALLOWED_CALLS:
                        raise ValueError("unreviewed free function in read helper")
                elif isinstance(call, ast.Attribute):
                    if call.attr not in (_ALLOWED_INFO | _ALLOWED_DICT_CALLS):
                        raise ValueError("unreviewed method in read helper")
                    if (call.attr in _ALLOWED_INFO
                            and (not isinstance(call.value, ast.Name)
                                 or call.value.id != "info")):
                        raise ValueError("read method not attached to pinned Info")
                else:
                    raise ValueError("indirect source call")
    compiled = ast.fix_missing_locations(
        ast.Module(body=selected, type_ignores=[]),
    )
    ns = {"__builtins__": _SAFE_BUILTINS}
    exec(compile(compiled, _SOURCE + ":isolated-info-helpers", "exec"), ns)
    return {name: ns[name] for name in _READ_HELPERS}
