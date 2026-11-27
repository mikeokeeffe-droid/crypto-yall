"""Offline review of READ_FAILED watchdog recovery. No CLI or live caller.

This module only constructs a recovery proposal. It never writes the ledger,
clears a latch, emits a heartbeat, or authorizes orders. The future operator
adapter must authenticate approval, verify backup and exclusivity, and bind
fresh observations to the exact incident before an atomic archive/clear.
"""
from dataclasses import dataclass
import re
from testnet_paper_review.offline_watchdog_receipt_bridge import classify

MAX_AGE_SECONDS = 30

@dataclass(frozen=True)
class RecoveryProposal:
    incident: str
    backup_sha256: str
    first_sample_s: int
    second_sample_s: int
    may_clear: bool = False
    may_trade: bool = False
    may_close: bool = False

class RecoveryHold(ValueError):
    pass

def review_recovery(*, ledger_view, backup_sha256, first_receipt,
                    second_receipt, first_sample_s, second_sample_s, now_s):
    # Only the unconsumed, flat READ_FAILED incident is in scope. Never
    # generalize this policy to missing stops, unknown ACK or interrupted work.
    if (type(ledger_view) is not tuple or len(ledger_view) != 2
            or type(ledger_view[0]) is not int
            or ledger_view != (0, "READ_FAILED")):
        raise RecoveryHold("HOLD: incident not eligible for this review")
    if (type(backup_sha256) is not str
            or re.fullmatch(r"[0-9a-f]{64}", backup_sha256) is None):
        raise RecoveryHold("HOLD: missing backup digest")
    if any(type(t) is not int for t in (first_sample_s,second_sample_s,now_s)):
        raise RecoveryHold("HOLD: invalid observation times")
    if not (0 < first_sample_s < second_sample_s <= now_s
            and now_s-first_sample_s <= MAX_AGE_SECONDS):
        raise RecoveryHold("HOLD: stale or replayed observation")
    for receipt in (first_receipt,second_receipt):
        if classify(receipt) != "FLAT" or receipt.stage != "NO_ATTEMPT":
            raise RecoveryHold("HOLD: account not verified flat and unused")
    return RecoveryProposal("READ_FAILED",backup_sha256,first_sample_s,second_sample_s)
