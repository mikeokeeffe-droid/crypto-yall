"""Staging-only trusted reconciler DB RPC adapter.

Inject an authenticated RPC transport belonging to the dedicated reconciler
identity. Never use routine executor credentials. This module does not connect
to production, manage secrets or submit exchange orders.
"""
from dataclasses import dataclass

@dataclass(frozen=True)
class CommitResult:
    committed: bool
    reason: str

def commit_candidate(rpc, decision, *, coin, bot, token, order_id=None):
    if decision is None or getattr(decision, "action", None) not in {"handoff_candidate", "release_candidate"}:
        return CommitResult(False, "exchange verification did not authorize transition")
    if not coin or bot != "intraday" or not token:
        return CommitResult(False, "invalid durable owner identity")
    if decision.action == "handoff_candidate":
        if order_id is None or not str(order_id).strip():
            return CommitResult(False, "missing verified exchange order ID")
        function = "record_bot_position_owner"
        params = {"p_coin": coin, "p_bot": bot, "p_token": token,
                  "p_exchange_order_id": str(order_id), "p_fill_verified": True}
    else:
        # Release requires a separate mark-closed transaction and a fresh
        # second exchange verification. Do not shortcut both steps.
        return CommitResult(False, "release requires two-stage verified workflow")
    try:
        response = rpc(function, params)
    except Exception:
        return CommitResult(False, "trusted RPC transport failed; retain intent")
    if response is not True:
        return CommitResult(False, "database did not confirm transition")
    return CommitResult(True, "trusted RPC confirmed ownership handoff")
