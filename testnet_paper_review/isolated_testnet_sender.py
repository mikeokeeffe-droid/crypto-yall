"""Quarantined, TESTNET-only Hyperliquid SDK order transport (DISABLED).

This is a genuine SDK transport adapter, not a runnable bot. Its send_once()
method contains the real bulk_orders() invocation but the hard in-source
ACTIVATION_HOLD keeps it unreachable in this PR and CI. No CLI, workflow,
credential loading, scheduler, network configuration, or Mainnet fallback.

Requirements before a separate security-reviewed cutover:
- independently verified separate TESTNET agent key and owner authorization;
- verified public balance/margin, no foreign/manual positions and no orders;
- exact immutable operator approval, runbook and emergency exit;
- single-host permanent journal on dedicated server (not GitHub Actions);
- write-once prepare+ack evidence before/after the ONE actual order submission;
- live post-ACK independent fill + reduce-only TP/SL reconciliation.
Never set ACTIVATION_HOLD false just because offline CI passes.
"""
from dataclasses import dataclass
from decimal import Decimal
import re

from testnet_paper_review.offline_client_order_bundle import OfflineClientOrderBundle
from testnet_paper_review.one_shot_protection_evidence import (
    WriteOnceProtectionEvidence, EvidenceHold, _validate_pair,
)
from testnet_paper_review.offline_order_guard import TESTNET_ACCOUNT, TESTNET_ENDPOINT
from testnet_paper_review.single_host_live_journal import (
    SingleHostOneShotJournal, PersistentHold
)

ACTIVATION_HOLD = True
CODE_SHA_RE = re.compile(r"[a-f0-9]{40}\Z")
HEX_ADDRESS_RE = re.compile(r"0x[0-9a-fA-F]{40}\Z")


class SenderHold(RuntimeError):
    pass


@dataclass(frozen=True)
class ExactOneShotApproval:
    # This is a *schema*, not a cryptographic authorization. The operator must
    # approve its exact content through an isolated, separately reviewed control.
    account: str
    endpoint: str
    signer_address: str
    code_sha: str
    request_id: str
    plan_hash: str
    max_notional: str
    expires_at_s: int
    operator_approved: bool = False


def verify_exact_request(*, bundle, approval, now_s):
    """Fail closed without reading any wallet, network or environment."""
    if type(bundle) is not OfflineClientOrderBundle or bundle.permits_submission:
        raise SenderHold("HOLD: unsupported reviewed order bundle")
    if type(approval) is not ExactOneShotApproval or approval.operator_approved is not True:
        raise SenderHold("HOLD: absent exact independent manual approval")
    if (bundle.account.lower() != TESTNET_ACCOUNT.lower()
            or approval.account.lower() != TESTNET_ACCOUNT.lower()
            or bundle.endpoint != TESTNET_ENDPOINT
            or approval.endpoint != TESTNET_ENDPOINT):
        raise SenderHold("HOLD: wrong owner or Mainnet endpoint")
    if (bundle.request_id != approval.request_id
            or bundle.code_sha != approval.code_sha):
        raise SenderHold("HOLD: approval request/code identity differs from order bundle")
    if not HEX_ADDRESS_RE.fullmatch(approval.signer_address) \
            or approval.signer_address.lower() == TESTNET_ACCOUNT.lower():
        raise SenderHold("HOLD: dedicated non-owner Testnet signer required")
    if type(approval.code_sha) is not str or not CODE_SHA_RE.fullmatch(approval.code_sha):
        raise SenderHold("HOLD: unknown executable revision")
    if type(approval.plan_hash) is not str or approval.plan_hash != bundle.plan_hash:
        raise SenderHold("HOLD: immutable plan fingerprint mismatch")
    if type(approval.request_id) is not str or not re.fullmatch(
            r"[a-z0-9][a-z0-9-]{7,63}", approval.request_id):
        raise SenderHold("HOLD: invalid one-shot request identifier")
    if type(now_s) is not int or type(approval.expires_at_s) is not int \
            or not 0 < approval.expires_at_s - now_s <= 60:
        raise SenderHold("HOLD: expired or unbounded approval")
    if type(bundle.orders) is not tuple or len(bundle.orders) != 3 \
            or bundle.grouping != "normalTpsl":
        raise SenderHold("HOLD: must group exact protected SOL order")
    if [o.get("reduce_only") for o in bundle.orders] != [False, True, True] \
            or any(o.get("coin") != "SOL" for o in bundle.orders):
        raise SenderHold("HOLD: entry and both reduce-only SOL exits required")
    try:
        requested = Decimal(approval.max_notional)
        entry_size = Decimal(bundle.orders[0]["sz"])
        worst_limit = Decimal(bundle.orders[0]["limit_px"])
    except (ArithmeticError, ValueError, TypeError, KeyError) as exc:
        raise SenderHold("HOLD: invalid order notional") from exc
    if not (requested.is_finite() and Decimal("12") <= requested <= Decimal("20")
            and Decimal("12") <= entry_size * worst_limit <= requested):
        raise SenderHold("HOLD: exceeds approved $20 Testnet size cap")
    if len({o.get("cloid") for o in bundle.orders}) != 3 \
            or any(type(o.get("cloid")) is not str or not re.fullmatch(
                r"0x[0-9a-f]{32}", o["cloid"]) for o in bundle.orders):
        raise SenderHold("HOLD: missing/duplicate client order IDs")
    return "HOLD: exact request shaped correctly; no execution authority"


def _sdk_order_list(bundle):
    """Exact official SDK inputs, including Cloid objects and numeric types."""
    from hyperliquid.utils.types import Cloid
    from hyperliquid.utils.signing import order_request_to_order_wire
    out = []
    for row in bundle.orders:
        order_type = row["order_type"]
        if "trigger" in order_type:
            t = order_type["trigger"]
            order_type = {"trigger": {
                "triggerPx": float(t["triggerPx"]),
                "isMarket": t["isMarket"], "tpsl": t["tpsl"]
            }}
        item = {
            "coin": "SOL", "is_buy": row["is_buy"],
            "sz": float(row["sz"]), "limit_px": float(row["limit_px"]),
            "order_type": order_type, "reduce_only": row["reduce_only"],
            "cloid": Cloid.from_str(row["cloid"])
        }
        # Locally verify wire prices/sizes for SDK's expected SOL asset type.
        # The separately verified SOL asset ID must be confirmed at runtime.
        out.append(item)
    return out


def send_once(*, exchange, journal, bundle, approval, now_s, plan=None, evidence=None):
    """REAL SDK bulk_orders path, ALWAYS BLOCKED while ACTIVATION_HOLD=True.

    The method is deliberately not a runnable entrypoint. Future operator
    authorization and independent security review must be implemented before
    activation; this code alone does not verify agent role or protective exits.
    """
    if ACTIVATION_HOLD:
        raise SenderHold("HOLD: testnet sender is not activated or security reviewed")
    verify_exact_request(bundle=bundle, approval=approval, now_s=now_s)
    try:
        from hyperliquid.exchange import Exchange
    except ImportError as exc:
        raise SenderHold("HOLD: pinned Hyperliquid SDK missing") from exc
    if type(exchange) is not Exchange:
        raise SenderHold("HOLD: only actual SDK Exchange allowed")
    if (exchange.base_url != TESTNET_ENDPOINT
            or exchange.info.base_url != TESTNET_ENDPOINT
            or exchange.account_address.lower() != TESTNET_ACCOUNT.lower()
            or exchange.wallet.address.lower() != approval.signer_address.lower()):
        raise SenderHold("HOLD: SDK endpoint/owner/signer mismatch")
    if type(journal) is not SingleHostOneShotJournal:
        raise SenderHold("HOLD: dedicated permanent journal missing")
    if journal.view()["frozen"] or journal.view()["claim"] is not None:
        raise SenderHold("HOLD: persistent one-shot already consumed")
    # Require the immutable original SOL Daily long-only three-order plan.
    # A filesystem witness is mandatory: a response without complete order
    # identities is impossible to audit safely after a crash.
    if type(evidence) is not WriteOnceProtectionEvidence:
        raise SenderHold("HOLD: missing private write-once protection evidence")
    try:
        _validate_pair(plan, bundle)
    except EvidenceHold as exc:
        raise SenderHold("HOLD: invalid SOL Daily plan/evidence pairing") from exc
    orders = _sdk_order_list(bundle)
    # Persist the irreversible database claim BEFORE writing the plan witness.
    # Any failure from here onwards consumes the single allowed attempt;
    # neither a missing witness nor an unknown ACK permits a retry.
    journal.reserve(request_id=approval.request_id,
                    request_hash=bundle.plan_hash, code_sha=approval.code_sha)
    try:
        written = evidence.prepare_before_order(plan=plan, bundle=bundle)
        if written != "PREPARED_DURABLE_BEFORE_ORDER_NO_RETRY":
            raise EvidenceHold("HOLD: witness not durably prepared")
    except Exception as exc:
        journal.freeze()
        raise SenderHold(
            "HOLD: pre-send durable evidence failed; order NOT sent; no retry"
        ) from exc
    try:
        # Exactly one grouped submission; NEVER retry on unknown ACK/timeout.
        response = exchange.bulk_orders(orders, grouping="normalTpsl")
    except Exception as exc:
        try:
            journal.report_response(request_id=approval.request_id, known_success=False)
        finally:
            journal.freeze()
        raise SenderHold(
            "HOLD: send outcome unknown; examine prepared witness, never retry"
        ) from exc
    # An apparent OK is NOT confirmation that both exits are active.
    if not acknowledge_exact_protected_order(response=response,bundle=bundle):
        try:
            journal.report_response(request_id=approval.request_id, known_success=False)
        finally:
            journal.freeze()
        raise SenderHold("HOLD: exchange response ambiguous; no retry")
    try:
        # ACK is written ONCE and fsynced; still requires independent /info
        # validation of the live position and both reduce-only exits.
        stored=evidence.write_exact_ack(bundle=bundle,response=response)
        if stored != "ACK_DURABLE_NOT_PROOF_OF_LIVE_STOPS":
            raise EvidenceHold("HOLD: acknowledgement witness not durable")
    except Exception as exc:
        try:
            journal.report_response(request_id=approval.request_id, known_success=False)
        finally:
            journal.freeze()
        raise SenderHold(
            "HOLD: ACK evidence storage unknown; never retry the entry"
        ) from exc
    try:
        journal.report_response(request_id=approval.request_id, known_success=True)
    finally:
        journal.freeze()
    return {
        "status":"POST_ACK_HOLD_NO_MORE_ORDERS",
        "ack_evidence_persisted":True,
        "needs_independent_position_stop_reconciliation":True
    }


def acknowledge_exact_protected_order(*, response, bundle):
    """Strictly validate THREE exchange ACKs; this is never stop-live evidence.

    Even a matched response needs independent live position and open-order
    reconciliation before being called protected. Any partial IOC fill, missing
    child, error, duplicate order ID, or malformed reply is unknown and HOLD.
    """
    if type(bundle) is not OfflineClientOrderBundle \
            or type(response) is not dict or response.get("status") != "ok":
        return False
    container = response.get("response")
    if type(container) is not dict or type(container.get("data")) is not dict:
        return False
    statuses = container["data"].get("statuses")
    if type(statuses) is not list or len(statuses) != 3:
        return False
    entry, take, stop = statuses
    if any(type(x) is not dict for x in (entry,take,stop)):
        return False
    if (set(entry) != {"filled"} or set(take) != {"resting"}
            or set(stop) != {"resting"}):
        return False
    try:
        fill, tp, sl = entry["filled"], take["resting"], stop["resting"]
        if any(type(x) is not dict for x in (fill,tp,sl)):
            return False
        oids = [fill.get("oid"),tp.get("oid"),sl.get("oid")]
        if any(type(i) is not int or i <= 0 for i in oids) or len(set(oids)) != 3:
            return False
        total_sz = fill.get("totalSz")
        if type(total_sz) is not str or not re.fullmatch(
                r"(?:0|[1-9][0-9]*)(?:\.[0-9]{1,8})?",total_sz):
            return False
        if Decimal(total_sz) != Decimal(bundle.orders[0]["sz"]):
            return False
    except (ArithmeticError,KeyError,ValueError,TypeError,IndexError):
        return False
    return True
