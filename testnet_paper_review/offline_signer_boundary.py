"""OFFLINE Testnet-only signer *boundary contract*, with NO signer.

This validates the exact account, code identity, one-shot intent and complete
parent+reduce-only TP/SL plan before an eventual independently reviewed adapter
could receive them. It never imports a wallet, reads secrets, signs, sends,
creates a GitHub Actions job, or grants execution permission.

No environment variable, argument or payload can override the TESTNET host.
A plan fingerprint is for an independent human review, NOT authorization.
"""
from dataclasses import dataclass
from decimal import Decimal
import hashlib
import json
import re

from testnet_paper_review.offline_daily_bracket_plan import (
    OfflineBracketPlan, BracketHold
)
from testnet_paper_review.offline_order_guard import (
    SyntheticIntent, TESTNET_ACCOUNT, TESTNET_ENDPOINT
)

REVIEW_MODE = "SIGNER_BOUNDARY_REVIEW_ONLY"
APPROVED_GROUPING = "normalTpsl"
ALLOWED_COIN = "SOL"
CODE_SHA_PATTERN = re.compile(r"[a-f0-9]{40}\Z")
REQUEST_PATTERN = re.compile(r"[a-z0-9][a-z0-9-]{7,63}\Z")


@dataclass(frozen=True)
class OfflineSignerEnvelope:
    account: str
    endpoint: str
    mode: str
    code_sha: str
    request_id: str
    plan_hash: str
    grouped_order_count: int

    @property
    def may_sign(self):
        return False

    @property
    def may_send(self):
        return False


def _same_size(plan):
    orders = plan.orders
    if type(orders) is not tuple or len(orders) != 3:
        raise BracketHold("HOLD: must use exactly one parent and two attached exits")
    if any(type(order) is not dict for order in orders):
        raise BracketHold("HOLD: malformed bracket order")
    if any(set(o) != {
        "coin", "is_buy", "sz", "limit_px", "order_type", "reduce_only"
    } for o in orders):
        raise BracketHold("HOLD: unexpected order fields")
    entry, tp, sl = orders
    for o in orders:
        if o["coin"] != ALLOWED_COIN:
            raise BracketHold("HOLD: foreign market in grouped order")
        if type(o["is_buy"]) is not bool or type(o["reduce_only"]) is not bool:
            raise BracketHold("HOLD: invalid side/reduce-only order field")
        if type(o["sz"]) is not str or type(o["limit_px"]) is not str:
            raise BracketHold("HOLD: unreviewed size or price type")
        if not re.fullmatch(r"(?:0|[1-9]\d*)(?:\.\d{1,8})?", o["sz"]):
            raise BracketHold("HOLD: invalid size")
        if not re.fullmatch(r"(?:0|[1-9]\d*)(?:\.\d{1,8})?", o["limit_px"]):
            raise BracketHold("HOLD: invalid price")
        if Decimal(o["sz"]) <= 0 or Decimal(o["limit_px"]) <= 0:
            raise BracketHold("HOLD: nonpositive order size or price")
    if any(o["sz"] != entry["sz"] for o in (tp, sl)):
        raise BracketHold("HOLD: protective size does not match entry")
    if entry["reduce_only"] is not False or tp["reduce_only"] is not True \
            or sl["reduce_only"] is not True:
        raise BracketHold("HOLD: protective order must be reduce-only")
    if tp["is_buy"] != sl["is_buy"] or tp["is_buy"] == entry["is_buy"]:
        raise BracketHold("HOLD: TP/SL must be opposite entry side")
    if entry["order_type"] != {"limit": {"tif": "Ioc"}}:
        raise BracketHold("HOLD: entry must be strictly bounded IOC")
    for child, trigger in ((tp, "tp"), (sl, "sl")):
        if type(child["order_type"]) is not dict \
                or set(child["order_type"]) != {"trigger"}:
            raise BracketHold("HOLD: protection must be a market trigger")
        t = child["order_type"]["trigger"]
        if type(t) is not dict or set(t) != {"triggerPx", "isMarket", "tpsl"} \
                or t["isMarket"] is not True or t["tpsl"] != trigger \
                or t["triggerPx"] != child["limit_px"]:
            raise BracketHold("HOLD: malformed take-profit/stop-loss protection")
    if plan.direction not in ("long", "short") or (plan.direction == "long") != entry["is_buy"]:
        raise BracketHold("HOLD: direction does not match parent order")
    sl_px, tp_px = Decimal(sl["limit_px"]), Decimal(tp["limit_px"])
    entry_px = Decimal(plan.reference_price)
    if not (sl_px < entry_px < tp_px if plan.direction == "long"
            else tp_px < entry_px < sl_px):
        raise BracketHold("HOLD: TP and SL price orientation incorrect")
    worst_case_usd = Decimal(entry["limit_px"]) * Decimal(entry["sz"])
    if worst_case_usd > Decimal(plan.effective_notional):
        raise BracketHold("HOLD: plan understates worst-case entry cost")
    if not Decimal("12") <= worst_case_usd <= Decimal("25"):
        raise BracketHold("HOLD: bounded first order is not $12-$25")


def build_offline_signer_envelope(*, plan, intent, code_sha, now_s):
    """Emit a deterministic reviewed-content fingerprint, never a signature."""
    if type(plan) is not OfflineBracketPlan or plan.permits_submission:
        raise BracketHold("HOLD: only review-only plans may be examined")
    if plan.status != "HOLD_OFFLINE_REVIEW_ONLY":
        raise BracketHold("HOLD: plan has unexpected execution mode")
    if type(intent) is not SyntheticIntent or intent.mode != "OFFLINE_FIXTURE_ONLY":
        raise BracketHold("HOLD: real execution intent forbidden")
    if type(intent.account) is not str or intent.account.lower() != TESTNET_ACCOUNT.lower() \
            or plan.account.lower() != TESTNET_ACCOUNT.lower():
        raise BracketHold("HOLD: wrong owner account")
    if intent.endpoint != TESTNET_ENDPOINT or plan.symbol != ALLOWED_COIN:
        raise BracketHold("HOLD: Mainnet endpoint or foreign market")
    if plan.grouping != APPROVED_GROUPING:
        raise BracketHold("HOLD: must submit entry and bracket as one group")
    if type(intent.leverage) is not int or intent.leverage != 1:
        raise BracketHold("HOLD: Testnet paper limit is exactly 1x")
    if type(intent.notional_usdc) is not str \
            or not re.fullmatch(r"(?:0|[1-9]\d*)(?:\.\d{1,6})?",intent.notional_usdc):
        raise BracketHold("HOLD: invalid operator-approved notional")
    if type(code_sha) is not str or not CODE_SHA_PATTERN.fullmatch(code_sha):
        raise BracketHold("HOLD: exact code SHA must be pinned for review")
    if type(intent.request_id) is not str or not REQUEST_PATTERN.fullmatch(intent.request_id):
        raise BracketHold("HOLD: invalid immutable request id")
    if type(now_s) is not int or type(intent.expires_at_s) is not int \
            or not 0 < intent.expires_at_s - now_s <= 60:
        raise BracketHold("HOLD: expired or unbounded one-shot")
    if intent.symbol != ALLOWED_COIN or intent.side not in ("buy", "sell") \
            or (intent.side == "buy") != (plan.direction == "long"):
        raise BracketHold("HOLD: intent and grouped order mismatch")
    _same_size(plan)
    size = Decimal(plan.orders[0]["sz"])
    limit = Decimal(plan.orders[0]["limit_px"])
    if size * limit > Decimal(intent.notional_usdc):
        raise BracketHold("HOLD: entry exceeds intent's max notional")
    record = {
        "account": TESTNET_ACCOUNT.lower(),
        "endpoint": TESTNET_ENDPOINT,
        "code_sha": code_sha,
        "request_id": intent.request_id,
        "expires_at_s": intent.expires_at_s,
        "leverage": 1,
        "grouping": plan.grouping,
        "orders": plan.orders
    }
    fingerprint = hashlib.sha256(
        json.dumps(record, sort_keys=True, separators=(",", ":"),
                   allow_nan=False).encode("utf-8")
    ).hexdigest()
    return OfflineSignerEnvelope(
        account=TESTNET_ACCOUNT,
        endpoint=TESTNET_ENDPOINT,
        mode=REVIEW_MODE,
        code_sha=code_sha,
        request_id=intent.request_id,
        plan_hash=fingerprint,
        grouped_order_count=3
    )
