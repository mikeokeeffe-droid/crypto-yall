"""S1: strict bot-to-sender REQUEST contract. NO EXECUTION.

This is production-oriented input validation code, not production auth:
a future trusted remote service must independently authenticate the workload,
pin account/network/DEX, and persist a unique nonce/fence in a transaction.
The network-facing service does not exist. NEVER treat the passed bot identity,
a valid request, or a review record as authorization to sign, trade or close.

No network, SDK, credentials, database access, dynamic import or exchange call.
"""
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
import json
import re

_BOTS = frozenset(("daily", "intraday", "aggressive"))
_ENTRY_ACTIONS = frozenset(("open_long", "open_short"))
_COIN = re.compile(r"[A-Z][A-Z0-9]{0,23}\Z", re.ASCII)
_DECIMAL = re.compile(r"(?:0|[1-9][0-9]*)(?:\.[0-9]{1,8})?\Z", re.ASCII)
_NONCE = re.compile(r"[0-9a-f]{32}\Z", re.ASCII)
_FIELDS = frozenset((
    "version", "action", "side", "coin", "rounded_size",
    "requested_leverage", "request_nonce",
))
_MAX_BODY_BYTES = 1024


@dataclass(frozen=True)
class SenderRequestReview:
    state: str = "hold"
    reason: str = "sender approval not implemented"
    parsed_action: str | None = None
    parsed_coin: str | None = None
    parsed_size: str | None = None
    workload_identity_authenticated: bool = False
    account_scope_verified: bool = False
    nonce_reserved: bool = False
    request_authorized: bool = False
    submit_authorized: bool = False
    close_authorized: bool = False
    signing_enabled: bool = False


def _unique_pairs(pairs):
    data = {}
    for key, value in pairs:
        if key in data:
            raise ValueError("duplicate request key")
        data[key] = value
    return data


def _reject_constant(_value):
    raise ValueError("non-finite request value")


def inspect_sender_entry_request_offline(*, body, asserted_bot=None):
    """Validate exact canonical entry intent; no claimed identity is trusted.

    Non-entry actions (closes, pyramids, leverage changes) are explicitly
    withheld until separately reviewed service-side policy. The caller's
    identity claim is never used for permission. A syntactically valid entry
    results in REVIEW_ONLY, not an executable order.
    """
    hold = SenderRequestReview()
    if (type(body) is not bytes or not 0 < len(body) <= _MAX_BODY_BYTES
            or asserted_bot is not None and (
                type(asserted_bot) is not str or asserted_bot not in _BOTS
            )):
        return hold
    try:
        doc = json.loads(
            body.decode("utf-8"),
            object_pairs_hook=_unique_pairs,
            parse_constant=_reject_constant,
        )
    except (ValueError, TypeError, UnicodeError):
        return hold
    if (type(doc) is not dict or set(doc) != _FIELDS
            or type(doc["version"]) is not int or doc["version"] != 1
            or type(doc["action"]) is not str
            or doc["action"] not in _ENTRY_ACTIONS
            or type(doc["side"]) is not str
            or doc["side"] != (
                "long" if doc["action"] == "open_long" else "short"
            )
            or type(doc["coin"]) is not str
            or _COIN.fullmatch(doc["coin"]) is None
            or type(doc["rounded_size"]) is not str
            or _DECIMAL.fullmatch(doc["rounded_size"]) is None
            or type(doc["requested_leverage"]) is not int
            or not 1 <= doc["requested_leverage"] <= 5
            or type(doc["request_nonce"]) is not str
            or _NONCE.fullmatch(doc["request_nonce"]) is None):
        return hold
    try:
        size = Decimal(doc["rounded_size"])
    except (InvalidOperation, ValueError):
        return hold
    if not size.is_finite() or not Decimal("0") < size <= Decimal("1000000"):
        return hold
    return SenderRequestReview(
        state="review_only",
        reason="entry request parsed; remote identity, server-scoped account, "
               "nonce persistence, risk approval and signing unavailable",
        parsed_action=doc["action"],
        parsed_coin=doc["coin"],
        parsed_size=doc["rounded_size"],
    )
