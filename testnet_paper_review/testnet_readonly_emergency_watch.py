"""Independent read-only TESTNET SOL emergency exposure watch (manual, not deployed).

No signer, wallet key, /exchange, orders, cancels, closures, timers, or writes.
Reads ONLY pinned Testnet owner /info twice, checks exact matching snapshots,
the on-host consumed entry journal, and optionally immutable ACK evidence.
An ACK + a single matching bracket is still an observation, NOT a guarantee.

Return a nonzero exit code for anything except a verified completely flat
account. That is deliberate: operators must not overlook an exposed position.
This is NOT a deployed automated emergency-exit system or trading approval.
"""
from dataclasses import dataclass,asdict
import argparse
import json
from pathlib import Path
import sys
import time

from testnet_paper_review.offline_order_guard import TESTNET_ACCOUNT, TESTNET_ENDPOINT
from testnet_paper_review.one_shot_protection_evidence import (
    WriteOnceProtectionEvidence, EvidenceHold, PREPARED,ACK,ROOT
)
from testnet_paper_review.single_host_live_journal import (
    SingleHostOneShotJournal, PersistentHold
)
from testnet_paper_review.testnet_one_shot_operator_preview import JOURNAL_PATH
from testnet_paper_review.testnet_post_ack_public_reconciliation import (
    _read_public_snapshot,PostAckPublicHold,MAX_READ_SPAN_S
)
from testnet_paper_review.testnet_daily_readonly_preflight import fetch_public_info,ReadOnlyError
from testnet_paper_review.offline_bracket_reconciliation import (
    assess_observed_bracket,ProtectionObservation,BracketHold
)

class ExposureWatchHold(RuntimeError):
    pass


@dataclass(frozen=True)
class ExposureWatchResult:
    account: str
    coin: str
    position_count: int
    open_order_count: int
    stage: str
    observed_bracket: bool
    needs_operator: bool
    action: str
    may_trade: bool=False
    may_close: bool=False
    status: str="READ_ONLY_TESTNET_EMERGENCY_WATCH_HOLD"


def inspect_one_shot_exposure(*,
                              reader=fetch_public_info,
                              journal_factory=SingleHostOneShotJournal,
                              evidence_factory=WriteOnceProtectionEvidence,
                              clock=None,
                              evidence_root=None):
    """Observe public owner even if local journal says empty (foreign exposure)."""
    if clock is None:
        clock=lambda:int(time.time())
    if evidence_root is None:
        evidence_root=ROOT
    try:
        # The two complete account-wide reads must agree; the fixed Testnet
        # transport has a single HTTPS timeout and no retry/redirect.
        start=clock()
        a=_read_public_snapshot(reader)
        b=_read_public_snapshot(reader)
        finish=clock()
        if (type(start) is not int or type(finish) is not int
                or not 0<=finish-start<=MAX_READ_SPAN_S
                or a!=b):
            raise ExposureWatchHold("HOLD: stale or changing Testnet exposure")
        positions=b["positions"]
        orders=b["basic_orders"]
        with journal_factory(JOURNAL_PATH) as journal:
            state=journal.view()
        if type(state) is not dict or set(state)!={"frozen","claim"}:
            raise ExposureWatchHold("HOLD: invalid entry journal")
        claim=state["claim"]
        clean=(len(positions)==0 and len(orders)==0)
        if claim is None:
            if state["frozen"] is not False:
                raise ExposureWatchHold("HOLD: frozen journal without a claim")
            root=Path(evidence_root)
            if (root/PREPARED).exists() or (root/ACK).exists():
                raise ExposureWatchHold("HOLD: orphaned trade plan without a journal claim")
            if clean:
                return ExposureWatchResult(
                    account=TESTNET_ACCOUNT,coin="SOL",position_count=0,
                    open_order_count=0,stage="NO_ATTEMPT",
                    observed_bracket=False,needs_operator=False,
                    action="NO_POSITION_NO_ORDER_TRADING_DISABLED",
                    status="PUBLIC_TESTNET_FLAT_READ_ONLY_HOLD"
                )
            return ExposureWatchResult(
                account=TESTNET_ACCOUNT,coin="SOL",
                position_count=len(positions),open_order_count=len(orders),
                stage="UNOWNED_EXPOSURE",observed_bracket=False,
                needs_operator=True,
                action="CHECK_TESTNET_UI_IMMEDIATELY_NO_AUTOMATED_CLOSE"
            )
        if (state["frozen"] is not True
                or type(claim) is not tuple or len(claim)!=4):
            raise ExposureWatchHold("HOLD: unsafe claimed journal state")
        # No attempt to read or trust a secret, and never retry a trade.
        # Unknown ACK is urgent even if the account currently looks flat.
        if claim[3]!="RESPONSE_SEEN":
            return ExposureWatchResult(
                account=TESTNET_ACCOUNT,coin="SOL",
                position_count=len(positions),open_order_count=len(orders),
                stage="UNKNOWN_ACK_OR_UNRESOLVED_ENTRY",
                observed_bracket=False,needs_operator=True,
                action="INSPECT_TESTNET_POSITION_AND_ORDERS_NO_RETRY"
            )
        evidence=evidence_factory()
        recorded=evidence.read_restart_state()
        if (recorded.ack_present is not True
                or recorded.may_trade is not False
                or recorded.bundle.account.lower()!=TESTNET_ACCOUNT.lower()
                or recorded.bundle.endpoint!=TESTNET_ENDPOINT
                or (recorded.bundle.request_id,recorded.bundle.plan_hash,
                    recorded.bundle.code_sha)!=claim[:3]):
            raise ExposureWatchHold("HOLD: stored ACK not owned by journal")
        if clean:
            return ExposureWatchResult(
                account=TESTNET_ACCOUNT,coin="SOL",position_count=0,
                open_order_count=0,stage="ENTRY_CONSUMED_BUT_FLAT",
                observed_bracket=False,needs_operator=False,
                action="FLAT_CONFIRMED_KEEP_SENDER_DISABLED",
                status="PUBLIC_TESTNET_FLAT_ENTRY_SPENT_HOLD"
            )
        try:
            observation=assess_observed_bracket(
                plan=recorded.plan,account=TESTNET_ACCOUNT,
                network="hyperliquid-testnet",
                response=recorded.response,
                positions=positions,open_orders=orders,
                frontend_open_orders=b["detailed_orders"],
                observation_started_s=start,observation_finished_s=finish,
                now_s=finish
            )
            if (type(observation) is not ProtectionObservation
                    or observation.allows_trading is not False):
                raise BracketHold("HOLD: invalid protection evidence")
        except (BracketHold,TypeError,KeyError,ValueError):
            return ExposureWatchResult(
                account=TESTNET_ACCOUNT,coin="SOL",
                position_count=len(positions),open_order_count=len(orders),
                stage="UNVERIFIED_PROTECTIVE_ORDERS",
                observed_bracket=False,needs_operator=True,
                action="INSPECT_TESTNET_UI_FOR_MISSING_STOP_NOW_NO_BLIND_RETRY"
            )
        return ExposureWatchResult(
            account=TESTNET_ACCOUNT,coin="SOL",
            position_count=len(positions),open_order_count=len(orders),
            stage="BRACKET_MATCHED_ONE_OBSERVATION",
            observed_bracket=True,needs_operator=True,
            action="KEEP_WATCHING_NO_STOP_GUARANTEE_NO_NEW_ENTRY"
        )
    except (ExposureWatchHold,PersistentHold,EvidenceHold,PostAckPublicHold,
            ReadOnlyError,OSError,TimeoutError,AttributeError,KeyError,
            ValueError,TypeError) as exc:
        raise ExposureWatchHold(
            "HOLD: Testnet exposure could not be verified; inspect Testnet "
            "manually; do NOT retry an order or assume the stop exists"
        ) from exc


def main(argv=None):
    parser=argparse.ArgumentParser(
        description="Manual read-only one-shot SOL TESTNET exposure watch"
    )
    parser.add_argument("--read-only-watch",action="store_true")
    args=parser.parse_args(argv)
    if not args.read_only_watch:
        print("HOLD: explicit --read-only-watch required",file=sys.stderr)
        return 2
    try:
        result=inspect_one_shot_exposure()
    except ExposureWatchHold as exc:
        print(str(exc),file=sys.stderr)
        return 2
    print(json.dumps(asdict(result),sort_keys=True))
    if result.needs_operator:
        print("ALERT: human TESTNET inspection required. No automated close or cancel.")
        return 3
    print("HOLD: public account flat; senders remain disabled; no trading authority")
    return 0


if __name__=="__main__":
    raise SystemExit(main())
