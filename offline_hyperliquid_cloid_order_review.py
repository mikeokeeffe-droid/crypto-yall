"""Offline CLOID-to-OID structural comparison. No HTTP, SDK or trade permissions.

A unique pre-submit CLOID can correlate an intent with an exchange order.
Neither caller-supplied evidence nor an exact match authenticates origin,
proves full account history, grants ownership or authorizes any submission.
All decisions remain HOLD, even for structurally consistent fixtures.
"""
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
import re
import uuid

_ACCOUNT = re.compile(r"0x[0-9a-f]{40}\Z")
_CLOID = re.compile(r"0x[0-9a-f]{32}\Z")
_INTENT_KEYS = frozenset((
    "bot", "environment", "account", "dex", "coin", "action",
    "requested_size", "intent_token", "fence_token",
    "cloid", "submitted_at_ms",
))
_BOTS = frozenset(("daily", "intraday", "aggressive"))
_ACTIONS = {"open_long": "B", "open_short": "A"}


@dataclass(frozen=True)
class CloidOrderReview:
    status: str
    reason: str
    structurally_consistent: bool = False
    observed_oid: int | None = None
    submit_authorized: bool = False


def _positive_decimal(raw):
    if type(raw) is not str or not raw or raw.strip() != raw:
        return None
    try:
        value = Decimal(raw)
    except (ValueError, InvalidOperation):
        return None
    return value if value.is_finite() and value > 0 else None


def _canonical_uuid(raw):
    if type(raw) is not str:
        return False
    try:
        return str(uuid.UUID(raw)) == raw
    except (ValueError, AttributeError):
        return False


def review_cloid_order_lineage_offline(*, intent, request, response, captured_at_ms):
    """Compare only supplied synthetic intent/order fields; never approve a trade."""
    def hold(reason, consistent=False, oid=None):
        return CloidOrderReview("hold", reason, consistent, oid)

    if type(intent) is not dict or set(intent) != _INTENT_KEYS:
        return hold("missing or extra durable intent fields")
    if (intent["bot"] not in _BOTS
            or intent["environment"] not in ("mainnet", "testnet")
            or type(intent["account"]) is not str
            or _ACCOUNT.fullmatch(intent["account"]) is None
            or intent["dex"] != ""
            or type(intent["coin"]) is not str
            or not intent["coin"] or not intent["coin"].isascii()
            or not intent["coin"].isalnum()
            or intent["coin"] != intent["coin"].upper()
            or intent["action"] not in _ACTIONS
            or _positive_decimal(intent["requested_size"]) is None
            or not _canonical_uuid(intent["intent_token"])
            or type(intent["fence_token"]) is not int
            or intent["fence_token"] <= 0
            or type(intent["cloid"]) is not str
            or _CLOID.fullmatch(intent["cloid"]) is None
            or type(intent["submitted_at_ms"]) is not int
            or intent["submitted_at_ms"] <= 0):
        return hold("malformed or incomplete pinned pre-submit intent")

    if (type(request) is not dict
            or set(request) != {"type", "user", "oid"}
            or request["type"] != "orderStatus"
            or request["user"] != intent["account"]
            or request["oid"] != intent["cloid"]):
        return hold("CLOID orderStatus request not bound to pinned account")
    if type(captured_at_ms) is not int or captured_at_ms < intent["submitted_at_ms"]:
        return hold("invalid synthetic capture time")
    if (type(response) is not dict or response.get("status") != "order"
            or type(response.get("order")) is not dict):
        return hold("orderStatus result absent or unknown")
    envelope = response["order"]
    order = envelope.get("order")
    if (type(order) is not dict or envelope.get("status") != "filled"
            or type(envelope.get("statusTimestamp")) is not int
            or type(order.get("timestamp")) is not int
            or not (intent["submitted_at_ms"] <= order["timestamp"]
                    <= envelope["statusTimestamp"] <= captured_at_ms)):
        return hold("order is not final filled or timestamps are inconsistent")
    oid = order.get("oid")
    if (type(oid) is not int or oid <= 0
            or order.get("cloid") != intent["cloid"]
            or order.get("coin") != intent["coin"]
            or order.get("side") != _ACTIONS[intent["action"]]
            or order.get("reduceOnly") is not False
            or _positive_decimal(order.get("origSz"))
               != _positive_decimal(intent["requested_size"])):
        return hold("CLOID, OID, side, coin or size mismatch")
    # 'sz' is remaining order size; it is NOT a fill receipt.
    if type(order.get("sz")) is not str or order["sz"] not in ("0", "0.0", "0.00"):
        return hold("nonzero or malformed remaining order size")

    return hold(
        "synthetic CLOID-to-OID match only; exchange provenance, full fills, "
        "account-wide netting and ownership still unverified",
        consistent=True, oid=oid,
    )
