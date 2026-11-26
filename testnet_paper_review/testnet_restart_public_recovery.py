"""Read-only TESTNET SOL crash/restart reconciliation of the one-shot bracket.

No order submission, closing, cancelling, credentials, or journal mutation.
An empty journal is a safe 'no attempt' state only when no evidence exists.
A consumed claim must be permanently frozen and match the fsynced trade
identity. A known ACK is compared against TWO consecutive PUBLIC Testnet
/info snapshots and the precise entry/TP/SL order IDs, size and triggers.

A matching snapshot is an observation, NOT a durable protection guarantee.
Missing stops, missing ACK, unknown request, or anything else is a HOLD.
This is not a continuous watchdog and cannot rescue a live unprotected trade.
"""
from dataclasses import dataclass, asdict
import argparse
import json
from pathlib import Path
import sys

from testnet_paper_review.one_shot_protection_evidence import (
    WriteOnceProtectionEvidence, EvidenceHold, PREPARED, ACK, ROOT
)
from testnet_paper_review.single_host_live_journal import (
    SingleHostOneShotJournal, PersistentHold
)
from testnet_paper_review.testnet_one_shot_operator_preview import JOURNAL_PATH
from testnet_paper_review.testnet_post_ack_public_reconciliation import (
    review_public_post_ack_once, PostAckPublicHold, PostAckPublicReceipt
)
from testnet_paper_review.offline_order_guard import (
    TESTNET_ACCOUNT, TESTNET_ENDPOINT
)
from testnet_paper_review.isolated_testnet_sender import (
    ACTIVATION_HOLD as ENTRY_LOCKED
)
from testnet_paper_review.isolated_testnet_emergency_sender import (
    ACTIVATION_HOLD as RESCUE_LOCKED
)


class RecoveryHold(RuntimeError):
    pass


@dataclass(frozen=True)
class RecoveryReceipt:
    account: str
    coin: str
    stage: str
    bracket_observed: bool
    entry_oid: int|None
    take_profit_oid: int|None
    stop_loss_oid: int|None
    may_send: bool=False
    status: str="RESTART_REVIEW_ONLY_HOLD_NO_ORDER"


def check_restart_recovery(*, journal_factory=SingleHostOneShotJournal,
                           evidence_factory=WriteOnceProtectionEvidence,
                           public_review=review_public_post_ack_once,
                           entry_locked=None, rescue_locked=None):
    """Review both permanent evidence and independent Testnet public data."""
    try:
        if entry_locked is None:entry_locked=ENTRY_LOCKED
        if rescue_locked is None:rescue_locked=RESCUE_LOCKED
        if entry_locked is not True or rescue_locked is not True:
            raise RecoveryHold("HOLD: order sender no longer disabled")
        # No files or API calls in the no-attempt case; a stale witness when
        # the journal is empty is an inconsistent state requiring intervention.
        with journal_factory(JOURNAL_PATH) as journal:
            state=journal.view()
        if type(state) is not dict or set(state)!={"frozen","claim"}:
            raise RecoveryHold("HOLD: unknown entry journal state")
        claim=state["claim"]
        if claim is None:
            if state["frozen"] is not False:
                raise RecoveryHold("HOLD: frozen entry journal with no claim")
            path=Path(ROOT)
            if (path/PREPARED).exists() or (path/ACK).exists():
                raise RecoveryHold("HOLD: evidence exists without entry claim")
            return RecoveryReceipt(
                account=TESTNET_ACCOUNT,coin="SOL",stage="NO_ENTRY_ATTEMPT",
                bracket_observed=False,entry_oid=None,
                take_profit_oid=None,stop_loss_oid=None,
                status="NO_ENTRY_ATTEMPT_SENDER_STILL_DISABLED"
            )
        if (state["frozen"] is not True or type(claim) is not tuple
                or len(claim)!=4 or claim[3]!="RESPONSE_SEEN"):
            raise RecoveryHold(
                "HOLD: consumed journal without independently confirmed full ACK"
            )
        evidence=evidence_factory()
        recorded=evidence.read_restart_state()
        if (recorded.ack_present is not True or recorded.response is None
                or recorded.may_trade is not False
                or recorded.bundle.account.lower()!=TESTNET_ACCOUNT.lower()
                or recorded.bundle.endpoint!=TESTNET_ENDPOINT
                or recorded.bundle.request_id!=claim[0]
                or recorded.bundle.plan_hash!=claim[1]
                or recorded.bundle.code_sha!=claim[2]):
            raise RecoveryHold("HOLD: stored ACK and durable journal disagree")
        observed=public_review(
            plan=recorded.plan,response=recorded.response
        )
        if (type(observed) is not PostAckPublicReceipt
                or observed.account.lower()!=TESTNET_ACCOUNT.lower()
                or observed.network!="hyperliquid-testnet"
                or observed.position_count!=1
                or observed.open_protection_count!=2
                or observed.may_send is not False):
            raise RecoveryHold("HOLD: independent position and exits unverified")
        return RecoveryReceipt(
            account=TESTNET_ACCOUNT,coin="SOL",
            stage="RESPONSE_SEEN",bracket_observed=True,
            entry_oid=observed.entry_oid,
            take_profit_oid=observed.take_profit_oid,
            stop_loss_oid=observed.stop_loss_oid,
            status="BRACKET_SEEN_ONCE_STILL_HOLD_NOT_A_LIVE_STOP_GUARANTEE"
        )
    except (EvidenceHold,PersistentHold,PostAckPublicHold,RecoveryHold,
            OSError,AttributeError,KeyError,ValueError,TypeError) as exc:
        raise RecoveryHold(
            "HOLD: Testnet restart reconciliation incomplete; do NOT retry "
            "or enter a second trade; inspect exposure manually"
        ) from exc


def main(argv=None):
    parser=argparse.ArgumentParser(
        description="Read-only journal+public TESTNET bracket restart review"
    )
    parser.add_argument("--read-only-recovery",action="store_true")
    args=parser.parse_args(argv)
    if not args.read_only_recovery:
        print("HOLD: explicit read-only-recovery required",file=sys.stderr)
        return 2
    try:
        receipt=check_restart_recovery()
    except RecoveryHold as exc:
        print(str(exc),file=sys.stderr)
        return 2
    print(json.dumps(asdict(receipt),sort_keys=True))
    print("HOLD: never place an order or treat a once-seen stop as guaranteed")
    return 0


if __name__=="__main__":
    raise SystemExit(main())
