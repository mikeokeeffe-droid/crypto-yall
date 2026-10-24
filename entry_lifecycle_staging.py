"""Offline entry lifecycle simulator. No live executor imports.

This intentionally models the conservative fail-closed path; it does not
place orders, reconcile real exchange data, or mutate Supabase.
"""
from dataclasses import dataclass
from enum import Enum

from order_reconciliation_staging import (
    OrderOutcome, can_resolve_entry_intent, may_submit_new_entry,
)


class Phase(Enum):
    IDLE = "idle"
    FENCED = "fenced"
    SUBMITTED = "submitted"
    UNCERTAIN = "uncertain"
    OWNED = "owned"
    RELEASED = "released"


@dataclass
class EntryLifecycle:
    phase: Phase = Phase.IDLE

    def acquire(self, *, reserved: bool, claimed: bool,
                exchange_flat: bool, no_open_orders: bool) -> bool:
        if self.phase is not Phase.IDLE:
            return False
        if not may_submit_new_entry(
            has_reservation=reserved, has_durable_intent=claimed,
            exchange_position_flat=exchange_flat,
            exchange_orders_clear=no_open_orders,
        ):
            return False
        self.phase = Phase.FENCED
        return True

    def submit(self) -> bool:
        if self.phase is not Phase.FENCED:
            return False
        self.phase = Phase.SUBMITTED
        return True

    def observe(self, outcome: OrderOutcome) -> None:
        if self.phase not in (Phase.SUBMITTED, Phase.UNCERTAIN):
            raise ValueError("no submitted order to observe")
        if outcome is OrderOutcome.FILLED:
            self.phase = Phase.OWNED
        elif outcome is OrderOutcome.UNKNOWN:
            self.phase = Phase.UNCERTAIN
        else:
            # Rejection still requires independent final/flat verification.
            self.phase = Phase.FENCED

    def resolve_rejection(self, *, order_final: bool,
                          exchange_flat: bool) -> bool:
        if self.phase is not Phase.FENCED:
            return False
        if not can_resolve_entry_intent(
            OrderOutcome.REJECTED,
            order_final=order_final, position_flat=exchange_flat,
        ):
            return False
        self.phase = Phase.RELEASED
        return True
