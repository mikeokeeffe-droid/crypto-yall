"""OFFLINE integration of durable claim and bracket evidence verification.

No signer, /exchange client, order submission, cancellation, deployment or
network. This is NOT a production durable ownership mechanism. The only DB
allowed is DisposableReviewJournal's explicit temporary test fixture.
A read-only observation can mark a synthetic claim RECONCILED_HOLD but can
NEVER release the one-shot or grant authority for another order.
"""
from dataclasses import dataclass

from testnet_paper_review.offline_order_guard import (
    HoldError, SyntheticIntent, SyntheticSnapshot, REVIEW_WRITER
)
from testnet_paper_review.offline_durable_restart_journal import DisposableReviewJournal
from testnet_paper_review.offline_daily_bracket_plan import OfflineBracketPlan, BracketHold
from testnet_paper_review.offline_bracket_reconciliation import assess_observed_bracket


@dataclass(frozen=True)
class OfflineLifecycleResult:
    state: str
    reason: str

    @property
    def may_send(self):
        # A simulator must never return an order-submit capability.
        return False


def stage_synthetic_bracket(path, *, intent, snapshot, plan, now_s,
                            writer_id=REVIEW_WRITER):
    """Persist one synthetic claim. Never sign or send an order.

    Stage ONLY a plan and an intent that identify the same mock transaction.
    Failure to re-open the existing journal is a hard HOLD, not a fresh start.
    """
    if type(intent) is not SyntheticIntent or type(snapshot) is not SyntheticSnapshot:
        raise HoldError("HOLD: incorrect synthetic input types")
    if type(plan) is not OfflineBracketPlan or plan.permits_submission:
        raise HoldError("HOLD: protected plan must be offline only")
    if (intent.account.lower() != plan.account.lower()
            or intent.symbol != plan.symbol
            or (intent.side == "buy") != (plan.direction == "long")
            or intent.side not in ("buy", "sell")):
        raise HoldError("HOLD: journal intent and bracket identity disagree")
    if len(plan.orders) != 3 or plan.grouping != "normalTpsl":
        raise HoldError("HOLD: protected bracket composition mismatch")
    if plan.orders[0]["reduce_only"] is not False or any(
            child["reduce_only"] is not True for child in plan.orders[1:]):
        raise HoldError("HOLD: take-profit and stop-loss must both reduce exposure")
    # An independently computed parent notional can differ slightly from
    # intended due to rounding and bounded slippage; it MUST NOT exceed the
    # synthetic intent's approved $ amount or any hard limit.
    from decimal import Decimal
    if Decimal(plan.effective_notional) > Decimal(intent.notional_usdc):
        raise HoldError("HOLD: rounded parent exceeds approved synthetic intent notional")
    with DisposableReviewJournal(path) as journal:
        msg = journal.stage(
            intent, snapshot, now_s=now_s, writer_id=writer_id
        )
        if journal.view() != (
                intent.request_id, intent.symbol, writer_id, "STAGED_HOLD"):
            raise HoldError("HOLD: persisted synthetic claim cannot be verified")
    return OfflineLifecycleResult("STAGED_HOLD", msg)


def reconcile_synthetic_bracket(path, *, request_id, plan, observation):
    """Simulate an uncertain exchange ACK and reconcile independent *fixtures*.

    - Claim must be already persisted before the simulated exchange action.
    - Record UNKNOWN_ACK_HOLD before considering any response.
    - Bad/missing/partial fill or protection freezes the disposable journal.
    - Good evidence permanently consumes the synthetic claim anyway.
    - No function can unlock a claim or schedule a second simulated send.
    """
    with DisposableReviewJournal(path) as journal:
        previous = journal.view()
        if previous is None or previous[0] != request_id \
                or previous[3] != "STAGED_HOLD":
            raise HoldError("HOLD: no matching staged synthetic transaction")
        journal.simulated_ack(request_id, "unknown")
        try:
            if type(observation) is not dict:
                raise BracketHold("HOLD: missing independent observation")
            matched = assess_observed_bracket(plan=plan, **observation)
            if matched.allows_trading:
                raise HoldError("HOLD: read-only matching evidence cannot authorize orders")
        except (BracketHold, HoldError, ValueError, TypeError, KeyError) as exc:
            journal.reconcile_fixture(
                request_id, evidence_fresh=False, exact_match=False
            )
            journal.freeze_review()
            raise HoldError(
                "HOLD: unknown/partial exchange acknowledgment or incomplete "
                "TP/SL evidence; synthetic journal permanently frozen"
            ) from exc
        journal.reconcile_fixture(
            request_id, evidence_fresh=True, exact_match=True
        )
        if journal.view()[3] != "RECONCILED_HOLD":
            raise HoldError("HOLD: synthetic reconciliation was not persisted")
        return OfflineLifecycleResult(
            "RECONCILED_HOLD",
            "HOLD: synthetic fill and bracket reconciled; one-shot permanently consumed"
        )
