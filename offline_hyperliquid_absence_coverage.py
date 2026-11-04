"""Offline-only review of incomplete exchange absence evidence.

Never clears a claim or authorizes new entries. No live access.
"""
from dataclasses import dataclass

@dataclass(frozen=True)
class CoverageReview:
    status: str
    reason: str
    release_claim: bool = False
    allow_new_entry: bool = False

def review_absence_evidence_offline(*, intent_created_ms, window_start_ms,
                                    window_end_ms, history_complete,
                                    account_matches, order_id_matches,
                                    no_matching_order, no_matching_fill):
    def hold(reason):
        return CoverageReview("hold", reason)
    times = (intent_created_ms, window_start_ms, window_end_ms)
    if any(type(value) is not int or value < 0 for value in times):
        return hold("invalid evidence timestamps")
    if any(type(value) is not bool for value in (
            history_complete, account_matches, order_id_matches,
            no_matching_order, no_matching_fill)):
        return hold("invalid evidence assertions")
    if window_start_ms > intent_created_ms or window_end_ms < intent_created_ms:
        return hold("evidence does not cover intent creation")
    if not history_complete:
        return hold("history may be truncated or paginated")
    if not account_matches or not order_id_matches:
        return hold("exchange account or order identity unverified")
    if not no_matching_order or not no_matching_fill:
        return hold("order or fill may exist")
    return hold("absence assertions alone cannot authenticate nonexecution")
