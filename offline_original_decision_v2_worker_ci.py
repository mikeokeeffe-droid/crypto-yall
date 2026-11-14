"""DISPOSABLE CI worker: original decision calculation -> non-executable V2 review.

Runs in a separate unprivileged Linux UID under a manually restricted CI env.
Loads only the source-extracted decide_trades function (never imports original
executor modules or the exchange SDK), uses synthetic read-only Info, and can
only send a review-only draft over a coordinator-owned Unix socket.

NOT a production bot, trading gateway, endpoint, secret-isolation guarantee,
exchange data source, or an authorized submit/close path.
"""
import ast
import json
import os
from pathlib import Path
import sys

from offline_original_signal_projection_ci import _TICKERS
from offline_signer_free_read_bootstrap_ci import (
    bootstrap_original_read_only_offline,
)
from offline_v2_signer_free_socket_client_ci import (
    request_v2_review_via_unix_socket_offline,
)

ACCOUNT = "0x" + "1" * 40
BOT_FILES = {
    "daily": "hyperliquid_executor.py",
    "intraday": "intraday_executor.py",
    "aggressive": "aggressive_executor.py",
}


def _source_decider(bot, source_root):
    """Extract only existing decision function, rejecting new imports/calls."""
    source = (Path(source_root) / BOT_FILES[bot]).read_text(encoding="utf-8")
    tree = ast.parse(source)
    matches = [n for n in tree.body
               if isinstance(n, ast.FunctionDef)
               and n.name == "decide_trades"]
    if len(matches) != 1:
        raise ValueError("unreviewed original decider change")
    fn = matches[0]
    forbidden = {"get_client", "market_open", "market_close",
                 "update_leverage", "__import__", "exec", "eval",
                 "subprocess", "connect", "send_order", "open"}
    for n in ast.walk(fn):
        if isinstance(n, (ast.Import, ast.ImportFrom)):
            raise ValueError("unreviewed decision-function import")
        if isinstance(n, ast.Call):
            name = (n.func.id if isinstance(n.func, ast.Name)
                    else n.func.attr if isinstance(n.func, ast.Attribute)
                    else None)
            if name in forbidden:
                raise ValueError("unreviewed decision-function call")
    fn.decorator_list = []
    module = ast.fix_missing_locations(ast.Module(body=[fn], type_ignores=[]))
    ns = {"HL_TICKER_MAP": dict(_TICKERS),
          "HL_SYMBOL_MAP": dict(_TICKERS)}
    exec(compile(module, "synthetic-original-decision-ci", "exec"), ns)
    return ns["decide_trades"]


def _synthetic_view(bot):
    snapshot = {
        "environment": "mainnet", "account": ACCOUNT,
        "user_state": {
            "marginSummary": {"accountValue": "150"},
            "assetPositions": [],
        },
        "spot_state": {"balances": [{"coin": "USDC", "total": "40"}]},
        "all_mids": {"SOL": "125"},
        "meta": {"universe": [{"name": "SOL", "szDecimals": 3}]},
    }
    return bootstrap_original_read_only_offline(
        verified_bot=bot, pinned_environment="mainnet",
        pinned_account=ACCOUNT, snapshot=snapshot,
    )


def run_worker(bot, sock_path, group_id, source_root, action="buy"):
    held = {
        "state": "hold",
        "review_recorded": False,
        "submit_authorized": False,
        "leverage_applied": False,
        "signer_imported": False,
        "original_executor_imported": False,
        "trading_secret_present": False,
        "postgres_password_present": False,
    }
    if (bot not in BOT_FILES
            or action not in ("buy", "sell_exit")
            or type(group_id) is not int or group_id <= 0
            or os.environ.get("ISOLATED_POSTGRES_CI") != "1"
            or os.environ.get("PGDATABASE") != "safety_test"
            or os.environ.get("PGHOST") != "localhost"
            or os.environ.get("CI_V2_REVIEW_AUDIT") != "1"
            or "HL_PRIVATE_KEY" in os.environ
            or "PGPASSWORD" in os.environ
            or any(key.startswith("CI_V2_COORDINATOR")
                   for key in os.environ)):
        return held
    decider = _source_decider(bot, source_root)
    view = _synthetic_view(bot)
    if view is None or view.submit_authorized:
        return held
    if action == "sell_exit":
        positions = {"SOL": {"size": 0.5, "unrealized_pnl": 1}}
    else:
        positions = {}
    signals = {
        "SOL-USD": {
            "action": action,
            "bull_conf": 0.8,
            "bear_conf": 0.8,
            "osc": 0.7,
            "pyramid_added": False,
        }
    }
    args = (signals, positions, 1)
    decisions = (decider(*args, {}) if bot == "aggressive"
                 else decider(*args))
    if len(decisions) != 1:
        return held
    review = view.draft_review_from_complete_decision_batch(
        decisions=decisions, selected_index=0,
        rounded_size="1.6", requested_leverage=2,
    )
    if review.state != "review_only" or review.submit_authorized:
        return held
    ack = request_v2_review_via_unix_socket_offline(
        socket_path=sock_path, expected_coordinator_uid=0,
        draft=review, ipc_group_gid=group_id,
    )
    return {
        **held,
        "state": ack.state,
        "review_recorded": ack.review_recorded,
        "submit_authorized": ack.submit_authorized,
        "leverage_applied": ack.leverage_applied,
        "signer_imported": any(
            name in sys.modules for name in ("eth_account", "hyperliquid.exchange")
        ),
        "original_executor_imported": any(
            name in sys.modules for name in (
                "hyperliquid_executor", "intraday_executor",
                "aggressive_executor",
            )
        ),
        "trading_secret_present": "HL_PRIVATE_KEY" in os.environ,
        "postgres_password_present": "PGPASSWORD" in os.environ,
    }


if __name__ == "__main__":
    try:
        if len(sys.argv) != 6:
            raise ValueError("CI worker requires bot/socket/gid/source/action")
        outcome = run_worker(
            sys.argv[1], sys.argv[2], int(sys.argv[3]),
            sys.argv[4], sys.argv[5],
        )
    except Exception:
        outcome = {
            "state": "hold", "review_recorded": False,
            "submit_authorized": False, "leverage_applied": False,
            "worker_error": True,
        }
    print(json.dumps(outcome, sort_keys=True), flush=True)
