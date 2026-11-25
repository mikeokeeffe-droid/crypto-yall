"""Staging-only orchestration; no scheduler, deployment or trading orders.

The caller MUST provide a read-only exchange client and separately authenticated
reconciler RPC transport. Candidates alone do not mutate database state.
"""
from dataclasses import dataclass
from trusted_reconciler_worker_staging import reconcile_entry
from trusted_reconciler_worker_staging import reconcile_unfilled_entry
from trusted_reconciler_db_adapter_staging import (
    commit_candidate,
    release_resolved_no_fill,
)
from trusted_reconciler_release_staging import release_verified
from hyperliquid_order_status_staging import read_order_status
from staging_executor_gateway_contract import BOTS

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
                              order_id, order_start_ms, requested_size, clock):
    if bot not in BOTS:
        return ServiceResult(False, "unsupported staging bot")
    evidence = reconcile_entry(
        info, address, coin=coin, order_id=order_id,
        order_start_ms=order_start_ms, requested_size=requested_size,
        clock=clock,
    )
    if evidence.action == "handoff_candidate":
        result = commit_candidate(
            rpc, evidence, coin=coin, bot=bot, token=token, order_id=order_id
        )
        return ServiceResult(result.committed, result.reason)

    final_status = read_order_status(
        info, address, coin=coin, order_id=order_id
    )
    if final_status not in {"canceled", "cancelled", "rejected", "expired"}:
        return ServiceResult(False, evidence.reason)
    no_fill = reconcile_unfilled_entry(
        info, address, coin=coin, order_id=order_id,
        order_start_ms=order_start_ms, requested_size=requested_size,
        clock=clock,
    )
    if no_fill.action != "resolved_no_fill_candidate":
        return ServiceResult(False, no_fill.reason)
    second_check = reconcile_unfilled_entry(
        info, address, coin=coin, order_id=order_id,
        order_start_ms=order_start_ms, requested_size=requested_size,
        clock=clock,
    )
    if (second_check.action != "resolved_no_fill_candidate"
            or read_order_status(info, address, coin=coin, order_id=order_id)
            != final_status):
        return ServiceResult(False, "resolution evidence changed; durable intent retained")
    result = release_resolved_no_fill(
        rpc, second_check, coin=coin, bot=bot, token=token,
        order_id=order_id, final_status=final_status,
    )
    return ServiceResult(result.committed, result.reason)

def reconcile_flat_owner(info, address, rpc, *, coin, bot, token, clock):
    if bot not in BOTS:
        return ServiceResult(False, "unsupported staging bot")
    released = release_verified(info, address, rpc, coin=coin, bot=bot,
                                token=token, clock=clock)
    return ServiceResult(released, "release confirmed" if released else "release held; owner fence retained")

def authorized_reconcile_submitted_entry(info, address, rpc, *, authorized=False, **kwargs):
    """Opt-in staging entry point; authorization must precede any evidence read."""
    guarded_rpc = authenticated_rpc(rpc, authorized=authorized)
    return reconcile_submitted_entry(info, address, guarded_rpc, **kwargs)


def authorized_reconcile_flat_owner(info, address, rpc, *, authorized=False, **kwargs):
    """Opt-in staging release entry point; authorization must precede evidence read."""
    guarded_rpc = authenticated_rpc(rpc, authorized=authorized)
    return reconcile_flat_owner(info, address, guarded_rpc, **kwargs)
