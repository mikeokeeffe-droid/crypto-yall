"""Post-ACK Testnet SOL bracket reconciliation using pinned public /info reads.

No signing, keys, Exchange client, /exchange endpoint, cancels, closes,
retry logic, journals, credential loading, Mainnet override or order-sending
ability. This code only obtains and compares two public account observations
and applies the already-reviewed exact bracket evidence validator.

The first passing observation is NOT a stop guarantee: markets can change,
stops can fail during volatility, and future live automation must include a
separate operator-approved emergency close/recovery path and continuous
monitoring. It does not authorize trading or release a journal freeze.
"""
from dataclasses import dataclass
import time

from testnet_paper_review.offline_bracket_reconciliation import (
    assess_observed_bracket, BracketHold, ProtectionObservation
)
from testnet_paper_review.offline_daily_bracket_plan import OfflineBracketPlan
from testnet_paper_review.testnet_daily_admission_gate import (
    EXPECTED_ACCOUNT, EXPECTED_NETWORK
)
from testnet_paper_review.testnet_daily_readonly_preflight import (
    fetch_public_info, verify_consistent_order_views, ReadOnlyError
)

MAX_READ_SPAN_S = 10


class PostAckPublicHold(RuntimeError):
    """Missing, stale, changed or inconsistent exchange evidence is HOLD."""


@dataclass(frozen=True)
class PostAckPublicReceipt:
    account: str
    network: str
    position_count: int
    open_protection_count: int
    entry_oid: int
    take_profit_oid: int
    stop_loss_oid: int
    status: str = "PUBLIC_TESTNET_POST_ACK_PROTECTION_REVIEW_HOLD"

    @property
    def may_send(self):
        return False

    @property
    def guarantees_stop_execution(self):
        return False


def _read_public_snapshot(read):
    """Three public /info queries; no independent actor's orders adopted."""
    state = read("clearinghouseState")
    basic = read("openOrders")
    detailed = read("frontendOpenOrders")
    if (type(state) is not dict
            or type(state.get("assetPositions")) is not list
            or type(basic) is not list or type(detailed) is not list):
        raise PostAckPublicHold("HOLD: absent or malformed TESTNET account snapshot")
    verify_consistent_order_views(basic, detailed)
    return {
        "positions": state["assetPositions"],
        "basic_orders": basic,
        "detailed_orders": detailed,
    }


def review_public_post_ack_once(*, plan, response, account=EXPECTED_ACCOUNT,
                                network=EXPECTED_NETWORK,
                                reader=fetch_public_info, clock=None):
    """Observe pinned Testnet account twice and require the exact live bracket.

    The ACK is supplied by the isolated sender/operator separately; this
    reader makes no order submission and never treats the ACK as a trade
    outcome on its own. An unknown ACK is HOLD even if orders are visible.
    """
    if type(plan) is not OfflineBracketPlan or plan.permits_submission:
        raise PostAckPublicHold("HOLD: unapproved offline bracket")
    if type(account) is not str or account.lower() != EXPECTED_ACCOUNT.lower() \
            or network != EXPECTED_NETWORK:
        raise PostAckPublicHold("HOLD: wrong owner or not TESTNET")
    if clock is None:
        clock = lambda: int(time.time())
    try:
        begin = clock()
        first = _read_public_snapshot(reader)
        second = _read_public_snapshot(reader)
        end = clock()
        if (type(begin) is not int or type(end) is not int
                or not 0 <= end - begin <= MAX_READ_SPAN_S):
            raise PostAckPublicHold("HOLD: stale or invalid observation clock")
        if first != second:
            raise PostAckPublicHold(
                "HOLD: positions or protective orders changed during public observation"
            )
        reviewed = assess_observed_bracket(
            plan=plan, account=account, network=network, response=response,
            positions=second["positions"],
            open_orders=second["basic_orders"],
            frontend_open_orders=second["detailed_orders"],
            observation_started_s=begin,
            observation_finished_s=end,
            now_s=end,
        )
        if type(reviewed) is not ProtectionObservation or reviewed.allows_trading:
            raise PostAckPublicHold("HOLD: unsupported protection review result")
        return PostAckPublicReceipt(
            account=EXPECTED_ACCOUNT, network=EXPECTED_NETWORK,
            position_count=len(second["positions"]),
            open_protection_count=len(second["basic_orders"]),
            entry_oid=reviewed.entry_oid,
            take_profit_oid=reviewed.take_profit_oid,
            stop_loss_oid=reviewed.stop_loss_oid
        )
    except (PostAckPublicHold, ReadOnlyError, BracketHold,
            OSError, TimeoutError, TypeError, ValueError, KeyError) as exc:
        raise PostAckPublicHold(
            "HOLD: TESTNET post-ACK independent public protection not verified"
        ) from exc
