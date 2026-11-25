"""Composable, signer-free shadow worker: synthetic decision preview ONLY.

Integration seam for the three existing strategies, Intraday/Aggressive
profit-protection rules and the conservative account-wide lock review.

There is NO network, environment, signer, order client, server, database,
wallet, privileged identity, time source, or capability to submit a trade.
The supplied snapshots, signals and lock states are untrusted fixtures.
The output is a REVIEW CANDIDATE, NEVER an executable trading instruction.

Important safety divergence: legacy decide_trades can propose both closing
and reopening one coin in the same run. This composer parks EVERY entry
for a coin that has a proposed close, even when another local rule proposes
the opposite direction. A close proposal is not proof that it was filled.
The durable single-writer coordinator must later reconcile real closes,
position ownership, open orders, and safe reduce-only exit semantics.
"""
from dataclasses import dataclass

from sender_review.signer_free_account_view_offline import (
    extract_signer_free_account_view_offline,
)
from sender_review.pure_strategy_decisions_offline import (
    TICKER_TO_COIN, inspect_pure_strategy_decisions_offline,
)
from sender_review.pure_profit_protection_offline import (
    SyntheticProtectionRules, inspect_pure_profit_protection_offline,
)
from sender_review.reentry_lock_transition_review_offline import (
    inspect_reentry_lock_transition_offline,
)

_ENTRY = frozenset(("open_long", "open_short", "pyramid_long", "pyramid_short"))


@dataclass(frozen=True)
class ShadowWorkerCycle:
    state: str = "HOLD"
    reason: str = "no authenticated account, signal or protected sender"
    review_ready: bool = False
    close_review_proposals: tuple[dict, ...] = ()
    deferred_entry_proposals: tuple[dict, ...] = ()
    deferred_flip_entry_proposals: tuple[dict, ...] = ()
    locked_review_proposals: tuple[dict, ...] = ()
    other_review_proposals: tuple[dict, ...] = ()
    reentry_lock_coins: tuple[str, ...] = ()
    possible_pending_lock_marks: tuple[tuple[str, str], ...] = ()
    additional_spot_read_needed: bool = False
    exchange_origin_authenticated: bool = False
    account_scope_verified: bool = False
    position_ownership_verified: bool = False
    protective_close_verified: bool = False
    durable_fence_reserved: bool = False
    request_authorized: bool = False
    submit_authorized: bool = False
    close_authorized: bool = False
    signing_enabled: bool = False


def inspect_shadow_worker_cycle_offline(
    *, bot, user_state, signals, max_positions, locks=(),
    synthetic_now_epoch, peak_returns=None, pyramid_state=None,
    protection_only=False, protection_enabled=True,
    protection_rules=SyntheticProtectionRules(), spot_user_state=None,
):
    """Compose pure offline decisions, then conservatively park re-entries.

    No actions are forwarded to a transport or journal. Even unaffected
    proposals are outputs for reviewer inspection, never GO permissions.
    """
    denied = ShadowWorkerCycle()
    if (type(bot) is not str or bot not in ("daily", "intraday", "aggressive")
            or type(protection_only) is not bool
            or type(protection_enabled) is not bool
            or type(peak_returns) not in (dict, type(None))
            or type(pyramid_state) not in (dict, type(None))):
        return denied
    view = extract_signer_free_account_view_offline(
        user_state=user_state, spot_user_state=spot_user_state,
    )
    if not view.fixture_parsed or view.state != "PARSED_READONLY_FIXTURE_HOLD":
        return ShadowWorkerCycle(
            reason="untrusted or incomplete account snapshot: " + view.reason,
            additional_spot_read_needed=view.additional_spot_read_needed,
        )
    if set(view.positions) - set(TICKER_TO_COIN.values()):
        return ShadowWorkerCycle(
            reason="unrecognized account-wide position requires separate ownership review"
        )
    if bot != "daily" and not protection_enabled:
        return ShadowWorkerCycle(
            reason="profit protection disabled; cannot treat strategy cycle as covered"
        )
    base = inspect_pure_strategy_decisions_offline(
        bot=bot, signals=signals, account_view=view,
        max_positions=max_positions, pyramid_state=pyramid_state,
    )
    if not base.local_decisions_compared:
        return ShadowWorkerCycle(reason="invalid synthetic signal decisions")
    proposed = base.proposed_actions
    marks = ()
    if bot in ("intraday", "aggressive"):
        protection = inspect_pure_profit_protection_offline(
            bot=bot, account_view=view, peak_returns=peak_returns or {},
            initial_actions=proposed, protection_only=protection_only,
            enabled=protection_enabled, rules=protection_rules,
        )
        if not protection.local_trigger_reviewable:
            return ShadowWorkerCycle(reason="invalid synthetic protection inputs")
        proposed = protection.proposals
        marks = protection.proposed_lock_marks
    elif protection_only:
        # No Daily replacement for protective-close wrapper has been proved.
        # Never call it equivalent to the two supported wrappers.
        return ShadowWorkerCycle(reason="daily protection-only is not implemented")
    signal_by_coin = {
        TICKER_TO_COIN[ticker]: signal.get("action")
        for ticker, signal in signals.items()
    }
    # The lock reducer is deliberately account-wide across three bot
    # identities and all proposed modifications, including possible closes.
    gate = inspect_reentry_lock_transition_offline(
        requesting_bot=bot, locks=locks, proposals=proposed,
        signal_by_coin=signal_by_coin, synthetic_now_epoch=synthetic_now_epoch,
    )
    if not gate.fixture_valid:
        return ShadowWorkerCycle(reason="invalid or ambiguous lock fixture")

    # Reconcile-before-reenter is stricter than the old local signal function.
    # A proposed close (including an exit created by protection) is never
    # equivalent to an exchange ACK or a confirmed flat account.
    untrusted_closes = {
        a["hl_coin"] for a in gate.unaffected_review_proposals
        if a["action"] == "close"
    }
    closes, deferred, flips, others = [], [], [], []
    for action in gate.unaffected_review_proposals:
        if action["action"] == "close":
            closes.append(action)
        elif action["action"] in _ENTRY:
            # All local entries are REVIEW ONLY. Entries on a close coin
            # are explicitly deferred; other entries remain untrusted too.
            deferred.append(action)
            if action["hl_coin"] in untrusted_closes:
                flips.append(action)
        else:
            others.append(action)
    # Locked closes MUST NOT be mislabeled as deferred entries; no blocked
    # mutation is a callable rescue, even if it is a protective close.
    reason = (
        "all proposals are inert; close-before-reentry, account-wide "
        "ownership, exchange ACK, risk caps, durable locks and real "
        "protection remain unverified"
    )
    if untrusted_closes:
        reason += "; same-coin reentry requires later reconciliation"
    return ShadowWorkerCycle(
        state="COMPOSED_SYNTHETIC_WORKER_HOLD",
        reason=reason, review_ready=True,
        close_review_proposals=tuple(closes),
        deferred_entry_proposals=tuple(deferred),
        deferred_flip_entry_proposals=tuple(flips),
        locked_review_proposals=gate.blocked_actions,
        other_review_proposals=tuple(others),
        reentry_lock_coins=gate.held_coins,
        possible_pending_lock_marks=marks,
    )
