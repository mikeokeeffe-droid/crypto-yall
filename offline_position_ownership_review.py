"""Offline-only position ownership reconciliation fixture.

Never authorizes live closes or sends orders. All exchange evidence is
synthetic; no SDK, network, credentials or production integrations.
"""
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

@dataclass(frozen=True)
class OfflineOwnershipEvidence:
    authenticated_bot: str
    claim_bot: str
    account_matches: bool
    coin_matches: bool
    side_matches: bool
    history_complete: bool
    history_fresh: bool
    fills_attributable: bool
    unknown_or_manual_fills: bool
    other_bot_activity: bool
    attributable_remaining: str
    current_position_size: str
    requested_close_size: str

@dataclass(frozen=True)
class OfflineOwnershipDecision:
    state: str
    reason: str
    submit_authorized: bool = False

def review_offline_ownership(evidence):
    if type(evidence) is not OfflineOwnershipEvidence:
        return OfflineOwnershipDecision("hold","invalid evidence")
    if evidence.authenticated_bot not in ("daily","intraday","aggressive"):
        return OfflineOwnershipDecision("hold","unverified bot")
    if evidence.authenticated_bot != evidence.claim_bot:
        return OfflineOwnershipDecision("hold","different bot owner")
    if not all((evidence.account_matches,evidence.coin_matches,
                evidence.side_matches,evidence.history_complete,
                evidence.history_fresh,evidence.fills_attributable)):
        return OfflineOwnershipDecision("hold","missing or mismatched provenance")
    if evidence.unknown_or_manual_fills or evidence.other_bot_activity:
        return OfflineOwnershipDecision("hold","unattributed account activity")
    try:
        amounts=[Decimal(x) for x in (
            evidence.attributable_remaining,evidence.current_position_size,
            evidence.requested_close_size)]
    except (InvalidOperation,ValueError,TypeError):
        return OfflineOwnershipDecision("hold","invalid quantity")
    if any(not x.is_finite() or x<=0 for x in amounts):
        return OfflineOwnershipDecision("hold","nonpositive or nonfinite quantity")
    owned,position,requested=amounts
    if requested>owned or requested>position:
        return OfflineOwnershipDecision("hold","requested close exceeds safe bound")
    # This is a review-only positive assessment, never an order approval.
    return OfflineOwnershipDecision("review","synthetic evidence internally consistent")
