"""Offline bridge from a read-only watch receipt to watchdog alert policy.

No public API call, scheduler, service start, notification transport or order
authority. The caller must supply a receipt from an independently trusted
read-only process. This rehearsal does not authenticate that process.
"""
from testnet_paper_review.offline_order_guard import TESTNET_ACCOUNT
from testnet_paper_review.testnet_readonly_emergency_watch import ExposureWatchResult
from testnet_paper_review.offline_watchdog_policy import advance, rehearsal_alert

def classify(receipt):
    if (type(receipt) is not ExposureWatchResult
            or receipt.account != TESTNET_ACCOUNT or receipt.coin != "SOL"
            or receipt.may_trade is not False or receipt.may_close is not False
            or type(receipt.position_count) is not int or receipt.position_count < 0
            or type(receipt.open_order_count) is not int or receipt.open_order_count < 0
            or type(receipt.needs_operator) is not bool
            or type(receipt.observed_bracket) is not bool):
        return "UNVERIFIED"
    if receipt.stage in ("NO_ATTEMPT","ENTRY_CONSUMED_BUT_FLAT"):
        if (receipt.position_count == receipt.open_order_count == 0
                and not receipt.needs_operator and not receipt.observed_bracket):
            return "FLAT"
        return "UNVERIFIED"
    if receipt.stage == "BRACKET_MATCHED_ONE_OBSERVATION":
        if (receipt.position_count == 1 and receipt.open_order_count == 2
                and receipt.needs_operator and receipt.observed_bracket):
            return "BRACKET_OBSERVED"
        return "UNVERIFIED"
    if not receipt.needs_operator or receipt.observed_bracket:
        return "UNVERIFIED"
    return {
        "UNOWNED_EXPOSURE":"FOREIGN_EXPOSURE",
        "UNKNOWN_ACK_OR_UNRESOLVED_ENTRY":"UNKNOWN_ACK",
        "UNVERIFIED_PROTECTIVE_ORDERS":"UNVERIFIED",
        "EMERGENCY_ATTEMPT_REQUIRES_REVIEW":"EMERGENCY_ATTEMPT",
    }.get(receipt.stage,"UNVERIFIED")

def rehearse_tick(state, *, now, sampled_at, receipt):
    # A missing receipt is an actual read failure, not a clean flat sample.
    outcome = "READ_FAILED" if receipt is None else classify(receipt)
    updated = advance(state, now=now, sampled_at=sampled_at, outcome=outcome)
    return updated, rehearsal_alert(updated)
