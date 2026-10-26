"""Staging-only orchestration; no scheduler, deployment or trading orders.

The caller MUST provide a read-only exchange client and separately authenticated
reconciler RPC transport. Candidates alone do not mutate database state.
"""
from dataclasses import dataclass
from trusted_reconciler_worker_staging import reconcile_entry
from trusted_reconciler_db_adapter_staging import commit_candidate
from trusted_reconciler_release_staging import release_verified

@dataclass(frozen=True)
class ServiceResult:
    confirmed: bool
    reason: str

def authenticated_rpc(rpc, *, authorized):
    """Fail-closed staging adapter. Caller must validate identity out of band.

    This does not authenticate a remote user or provision credentials.
    """
    if authorized is not True or not callable(rpc):
        raise PermissionError("trusted reconciler authorization required")
    return rpc

def reconcile_submitted_entry(info, address, rpc, *, coin, bot, token,
                              order_id, order_start_ms, clock):
    if bot != "intraday":
        return ServiceResult(False, "only intraday staging trial permitted")
    evidence = reconcile_entry(info, address, coin=coin, order_id=order_id,
                               order_start_ms=order_start_ms, clock=clock)
    if evidence.action != "handoff_candidate":
        return ServiceResult(False, evidence.reason)
    result = commit_candidate(rpc, evidence, coin=coin, bot=bot,
                              token=token, order_id=order_id)
    return ServiceResult(result.committed, result.reason)

def reconcile_flat_owner(info, address, rpc, *, coin, bot, token, clock):
    if bot != "intraday":
        return ServiceResult(False, "only intraday staging trial permitted")
    released = release_verified(info, address, rpc, coin=coin, bot=bot,
                                token=token, clock=clock)
    return ServiceResult(released, "release confirmed" if released else "release held; owner fence retained")
