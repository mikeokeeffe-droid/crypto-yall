"""Deterministic order IDs for an *offline* Testnet-only grouped-order review.

The Hyperliquid SDK accepts a 16-byte cloid per order. We derive separate
client IDs for entry, take-profit and stop-loss from the pinned review
envelope. A stable identifier supports later reconciliation, but it DOES NOT
make retries safe, grant signing rights or prove uniqueness across hosts.

No Exchange instance, network, signer, account keys, or send function exists.
"""
from dataclasses import dataclass
import hashlib
import re

from testnet_paper_review.offline_signer_boundary import (
    build_offline_signer_envelope, OfflineSignerEnvelope
)
from testnet_paper_review.offline_daily_bracket_plan import (
    OfflineBracketPlan, BracketHold
)

_ROLE = ("entry", "take_profit", "stop_loss")


@dataclass(frozen=True)
class OfflineClientOrderBundle:
    plan_hash: str
    account: str
    endpoint: str
    request_id: str
    code_sha: str
    grouping: str
    orders: tuple[dict, dict, dict]
    status: str = "HOLD_OFFLINE_SDK_SHAPE_ONLY"

    @property
    def permits_submission(self):
        return False


def build_offline_client_order_bundle(*, plan, intent, code_sha, now_s):
    """Return three SDK-shaped order fixtures with distinct 0x + 32 hex cloids.

    Requires all signer boundary validations to succeed again, including
    exact version/request/account/side/size/both reduce-only protective orders.
    """
    envelope = build_offline_signer_envelope(
        plan=plan, intent=intent, code_sha=code_sha, now_s=now_s)
    if type(envelope) is not OfflineSignerEnvelope or envelope.may_sign \
            or envelope.may_send:
        raise BracketHold("HOLD: signer envelope has unexpected authority")
    if type(plan) is not OfflineBracketPlan or plan.permits_submission:
        raise BracketHold("HOLD: unreviewed order bundle")
    items = []
    for role, source in zip(_ROLE, plan.orders, strict=True):
        # This digest is solely an identifier, NOT an authentication token.
        raw = f"{envelope.plan_hash}:{role}".encode("ascii")
        cloid = "0x" + hashlib.sha256(raw).hexdigest()[:32]
        if not re.fullmatch(r"0x[0-9a-f]{32}", cloid):
            raise BracketHold("HOLD: invalid SDK client order identifier")
        item = {**source, "cloid": cloid}
        items.append(item)
    if len({x["cloid"] for x in items}) != 3:
        raise BracketHold("HOLD: duplicate entry or protection order id")
    return OfflineClientOrderBundle(
        plan_hash=envelope.plan_hash,
        account=envelope.account,
        endpoint=envelope.endpoint,
        request_id=envelope.request_id,
        code_sha=envelope.code_sha,
        grouping=plan.grouping,
        orders=tuple(items),
    )
