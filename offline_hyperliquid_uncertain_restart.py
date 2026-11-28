"""Offline-only restart uncertainty boundary.

A timeout, crash, or lost response is not proof of no order. Position
snapshots, even flat ones, cannot release a pending entry claim. No live IO.
"""
from dataclasses import dataclass

@dataclass(frozen=True)
class RestartReview:
    status: str
    reason: str
    release_claim: bool = False
    allow_new_entry: bool = False

def inspect_uncertain_restart_offline(*, pending_claim, position_snapshot,
                                      claimed_order_absent,
                                      claimed_no_recent_fills):
    def hold(reason):
        return RestartReview("hold", reason)
    if type(pending_claim) is not dict or not pending_claim:
        return hold("no durable pending intent supplied")
    if type(position_snapshot) is not dict:
        return hold("invalid position snapshot")
    if type(claimed_order_absent) is not bool or type(claimed_no_recent_fills) is not bool:
        return hold("invalid reconciliation claims")
    return hold("restart snapshots and absence claims cannot prove order nonexecution")
