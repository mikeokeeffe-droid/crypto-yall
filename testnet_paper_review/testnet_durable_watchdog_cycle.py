"""Read-only Testnet watchdog cycle with a separate durable incident ledger.

No signing, orders, cancellation, trade journal mutation or notification
transport. Not a scheduler or deployment authorization. The ledger must
already exist. The service supervisor must independently detect missed
cycles, process death and unavailable alerts.
"""
from dataclasses import dataclass
import argparse
import sys
import time
from testnet_paper_review.watchdog_incident_ledger import WatchdogLedger
from testnet_paper_review.offline_watchdog_receipt_bridge import classify
from testnet_paper_review.testnet_readonly_emergency_watch import inspect_one_shot_exposure

STATE_DIRECTORY = "/home/testadmin/crypto-yall-watchdog-state"
MAX_CYCLE_SECONDS = 10

@dataclass(frozen=True)
class CycleReceipt:
    outcome: str
    incident: str | None
    needs_operator: bool
    may_trade: bool = False
    may_close: bool = False

def run_cycle(directory, *, inspect=inspect_one_shot_exposure, clock=time.monotonic):
    # Commit pending BEFORE the observation. Failure to open/begin the
    # ledger prevents a reassuring receipt. A killed process leaves pending.
    with WatchdogLedger(directory) as ledger:
        ledger.begin()
        try:
            started = clock()
            receipt = inspect()
            ended = clock()
            if not 0 <= ended - started <= MAX_CYCLE_SECONDS:
                outcome = "STALE_OBSERVATION"
            else:
                outcome = "READ_FAILED" if receipt is None else classify(receipt)
        except Exception:
            outcome = "READ_FAILED"
        incident = ledger.finish(outcome)
        return CycleReceipt(outcome, incident,
                            incident is not None or outcome != "FLAT")

def main(argv=None):
    parser = argparse.ArgumentParser(description="One durable read-only Testnet watchdog cycle")
    parser.add_argument("--read-only-cycle", action="store_true")
    args = parser.parse_args(argv)
    if not args.read_only_cycle:
        print("HOLD: explicit read-only-cycle required", file=sys.stderr)
        return 2
    try:
        receipt = run_cycle(STATE_DIRECTORY)
    except Exception:
        print("CRITICAL: watchdog state unavailable; inspect Testnet manually; no retry",
              file=sys.stderr)
        return 2
    # Do not log arbitrary persisted incident strings, account data or exceptions.
    if receipt.incident is not None:
        print("CRITICAL: persistent watchdog incident; operator inspection required")
        return 3
    if receipt.needs_operator:
        print("ATTENTION: position observed; stop execution not guaranteed")
        return 3
    print("READ_ONLY_WATCHDOG_FLAT_HOLD_NO_TRADING_AUTHORITY")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
