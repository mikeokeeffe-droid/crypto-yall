"""Hard-disabled one-shot SOL TESTNET emergency CLOSE-ONLY transport.

There is NO executable CLI, deployed daemon, or configured schedule.
ACTIVATION_HOLD stays True in this branch. This code cannot execute a real
order until separate security-reviewed activation and genuine proof that the
missing-stop position belongs exclusively to this experiment are implemented.

One tightly bounded reduce-only IOC close can fail to fill. ACK never means
flat. A timeout is UNKNOWN; never repeat without independent operator review.
"""
from dataclasses import dataclass
from decimal import Decimal
import hashlib
import re

from testnet_paper_review.offline_order_guard import (
    TESTNET_ACCOUNT, TESTNET_ENDPOINT
)
from testnet_paper_review.testnet_emergency_close_review import EmergencyCloseReview
from testnet_paper_review.emergency_close_one_shot_journal import (
    EmergencyCloseJournal
)
from testnet_paper_review.single_host_live_journal import SingleHostOneShotJournal
from testnet_paper_review.testnet_sdk_server_client_preflight import AGENT_ADDRESS

ACTIVATION_HOLD=True
HEX32=re.compile(r"0x[0-9a-f]{32}\Z")
REQ=re.compile(r"[a-z0-9][a-z0-9-]{7,63}\Z")


class EmergencySenderHold(RuntimeError):
    pass


@dataclass(frozen=True)
class EmergencyCloseApproval:
    """Schema only; NEVER treat a Python bool as secure operator approval."""
    request_id: str
    original_request_id: str
    plan_hash: str
    signer: str
    owner: str
    endpoint: str
    observed_position_size: str
    expires_at_s: int
    operator_approved: bool=False


def verify_close_only(*, proposal, approval, entry_journal, emergency_journal,
                      now_s):
    if (type(proposal) is not EmergencyCloseReview
            or proposal.may_send is not False
            or proposal.missing_stop is not True):
        raise EmergencySenderHold("HOLD: no independently reviewed missing stop")
    if type(approval) is not EmergencyCloseApproval or approval.operator_approved is not True:
        raise EmergencySenderHold("HOLD: exact operator approval absent")
    if (proposal.account.lower()!=TESTNET_ACCOUNT.lower()
            or approval.owner.lower()!=TESTNET_ACCOUNT.lower()
            or proposal.network!="hyperliquid-testnet"
            or approval.endpoint!=TESTNET_ENDPOINT
            or approval.signer.lower()!=AGENT_ADDRESS.lower()):
        raise EmergencySenderHold("HOLD: Testnet owner, signer or endpoint mismatch")
    if (type(approval.request_id) is not str or not REQ.fullmatch(approval.request_id)
            or approval.original_request_id!=proposal.request_id
            or type(approval.plan_hash) is not str
            or not re.fullmatch(r"[a-f0-9]{64}",approval.plan_hash)):
        raise EmergencySenderHold("HOLD: wrong immutable rescue request")
    if (type(now_s) is not int or type(approval.expires_at_s) is not int
            or not 0<approval.expires_at_s-now_s<=30):
        raise EmergencySenderHold("HOLD: stale or unbounded rescue approval")
    if (type(entry_journal) is not SingleHostOneShotJournal
            or type(emergency_journal) is not EmergencyCloseJournal):
        raise EmergencySenderHold("HOLD: permanent entry and rescue journals required")
    entry=entry_journal.view()
    if (entry["frozen"] is not True or entry["claim"] is None
            or entry["claim"][0]!=approval.original_request_id
            or entry["claim"][1]!=approval.plan_hash
            or emergency_journal.view() is not None):
        raise EmergencySenderHold("HOLD: entry not consumed or rescue already attempted")
    order=proposal.close_order
    if type(order) is not dict or set(order)!={
        "coin","is_buy","sz","limit_px","order_type","reduce_only","cloid"
    }:
        raise EmergencySenderHold("HOLD: malformed close-only order")
    if (order["coin"]!="SOL" or type(order["is_buy"]) is not bool
            or order["reduce_only"] is not True
            or order["order_type"]!={"limit":{"tif":"Ioc"}}
            or type(order["cloid"]) is not str
            or not HEX32.fullmatch(order["cloid"])):
        raise EmergencySenderHold("HOLD: non-reduce-only or non-IOC close rejected")
    try:
        sz=Decimal(order["sz"])
        limit=Decimal(order["limit_px"])
        observed=Decimal(proposal.observed_position_size)
        approved_size=Decimal(approval.observed_position_size)
    except (ValueError,TypeError,ArithmeticError) as exc:
        raise EmergencySenderHold("HOLD: malformed emergency size/price") from exc
    if (not all(x.is_finite() for x in (sz,limit,observed,approved_size))
            or sz<=0 or limit<=0
            or abs(observed)!=sz or approved_size!=observed
            or (order["is_buy"]!=(observed<0))
            or sz*limit>Decimal("25")):
        raise EmergencySenderHold("HOLD: wrong exposure, direction or size > $25")
    digest=hashlib.sha256(
        (approval.original_request_id+":"+approval.request_id+":"
         +approval.plan_hash+":"+order["cloid"]+":"+order["sz"]
         +":"+order["limit_px"]).encode("ascii")
    ).hexdigest()
    return digest


def send_emergency_once(*, exchange, proposal, approval, entry_journal,
                        emergency_journal, now_s):
    """REAL order() seam, intentionally unreachable while activation HOLD."""
    if ACTIVATION_HOLD:
        raise EmergencySenderHold("HOLD: emergency close sender is NOT activated")
    fingerprint=verify_close_only(
        proposal=proposal,approval=approval,entry_journal=entry_journal,
        emergency_journal=emergency_journal,now_s=now_s
    )
    from hyperliquid.exchange import Exchange
    if (type(exchange) is not Exchange
            or exchange.base_url!=TESTNET_ENDPOINT
            or exchange.info.base_url!=TESTNET_ENDPOINT
            or exchange.account_address.lower()!=TESTNET_ACCOUNT.lower()
            or exchange.wallet.address.lower()!=AGENT_ADDRESS.lower()
            or exchange.vault_address is not None):
        raise EmergencySenderHold("HOLD: non-Testnet exchange or wallet")
    from hyperliquid.utils.types import Cloid
    o=proposal.close_order
    emergency_journal.reserve(request_id=approval.request_id,plan_hash=fingerprint)
    try:
        # EXACTLY one attempt. Network failure/unknown response consumes rescue.
        response=exchange.order(
            "SOL",o["is_buy"],float(o["sz"]),float(o["limit_px"]),
            {"limit":{"tif":"Ioc"}},reduce_only=True,
            cloid=Cloid.from_str(o["cloid"])
        )
    except Exception as exc:
        emergency_journal.note_ack(request_id=approval.request_id,known_ack=False)
        raise EmergencySenderHold(
            "HOLD: unknown emergency close outcome; do NOT retry"
        ) from exc
    statuses=(response.get("response",{}).get("data",{}).get("statuses")
              if type(response) is dict else None)
    if (type(response) is not dict or response.get("status")!="ok"
            or type(statuses) is not list or len(statuses)!=1
            or type(statuses[0]) is not dict
            or set(statuses[0])!={"filled"}
            or type(statuses[0]["filled"]) is not dict
            or type(statuses[0]["filled"].get("oid")) is not int
            or type(statuses[0]["filled"].get("totalSz")) is not str
            or statuses[0]["filled"]["totalSz"] != o["sz"]):
        emergency_journal.note_ack(request_id=approval.request_id,known_ack=False)
        raise EmergencySenderHold(
            "HOLD: close not confirmed; inspect account, do NOT retry"
        )
    emergency_journal.note_ack(request_id=approval.request_id,known_ack=True)
    return {
        "status":"EMERGENCY_ACK_HOLD_VERIFY_FLAT_INDEPENDENTLY",
        "may_retry":False,
        "needs_independent_zero_position_and_order_check":True
    }
