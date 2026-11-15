"""Proposed signer-free *offline* intent interfaces for three trading bots.

This module is NOT a sender: no I/O, JWT validation, exchange/DB SDK,
credentials, signing, runtime identity or order dispatch. A successful
parse means a request is structurally REVIEWABLE but always in HOLD.
Only a future independently authenticated server may decide whether
an order is permissible; this code cannot and does not authorize one.

Do not reuse these untrusted caller-side snapshot/ownership assertions as
facts when designing a protective close.
"""
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
import json
import re

from sender_review.request_contract import inspect_sender_entry_request_offline

_BOTS = frozenset(("daily", "intraday", "aggressive"))
_COINS = re.compile(r"[A-Z][A-Z0-9]{0,23}\Z", re.ASCII)
_DECIMALS = re.compile(r"(?:0|[1-9][0-9]*)(?:\.[0-9]{1,8})?\Z", re.ASCII)
_NONCE = re.compile(r"[0-9a-f]{32}\Z", re.ASCII)
_REF = re.compile(r"[0-9a-f]{32}\Z", re.ASCII)
_ENTRY = frozenset(("open_long", "open_short"))
_PYRAMID = frozenset(("pyramid_long", "pyramid_short"))
_EXIT_REASONS = frozenset((
    "signal_exit", "profit_floor", "trailing_protection", "usd_loss_cap",
))
_COMMON = frozenset(("version", "action", "side", "coin", "request_nonce"))
_ENTRY_FIELDS = _COMMON | {"rounded_size", "requested_leverage"}
_PYRAMID_FIELDS = _ENTRY_FIELDS | {"parent_position_ref"}
_PROTECT_FIELDS = _COMMON | {
    "close_size", "observed_position_size", "position_ref",
    "exit_reason", "reduce_only",
}
_LEVERAGE_FIELDS = _COMMON | {"requested_leverage", "parent_position_ref"}
_MAX_BODY_BYTES = 1024


@dataclass(frozen=True)
class ProposedIntentReview:
    state: str = "hold"
    reason: str = "no authenticated sender or execution authority"
    fixture_bot: str | None = None
    parsed_action: str | None = None
    parsed_coin: str | None = None
    parsed_size: str | None = None
    requested_reduce_only: bool = False
    identity_authenticated: bool = False
    position_ownership_verified: bool = False
    exchange_snapshot_verified: bool = False
    effective_reduce_only_verified: bool = False
    account_scope_verified: bool = False
    nonce_reserved: bool = False
    request_authorized: bool = False
    submit_authorized: bool = False
    close_authorized: bool = False
    leverage_authorized: bool = False
    signing_enabled: bool = False


def _unique_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate key")
        result[key] = value
    return result


def _deny_nonfinite(_value):
    raise ValueError("non-finite number")


def _valid_size(text):
    if type(text) is not str or _DECIMALS.fullmatch(text) is None:
        return None
    try:
        number = Decimal(text)
    except (InvalidOperation, ValueError):
        return None
    if not number.is_finite() or not Decimal("0") < number <= Decimal("1000000"):
        return None
    return number


def _valid_leverage(value):
    return type(value) is int and 1 <= value <= 5


def _valid_common(doc):
    return (
        type(doc) is dict
        and type(doc.get("version")) is int and doc["version"] == 1
        and type(doc.get("coin")) is str
        and _COINS.fullmatch(doc["coin"]) is not None
        and type(doc.get("request_nonce")) is str
        and _NONCE.fullmatch(doc["request_nonce"]) is not None
        and type(doc.get("side")) is str
        and doc["side"] in ("long", "short")
        and type(doc.get("action")) is str
    )


def inspect_proposed_intent_offline(*, body, fixture_bot):
    """Parse proposed paths separately from the S1 entry-only contract.

    fixture_bot is untrusted testing context, NOT a runtime authorization
    credential. No parsed request may enter a signer or trusted journal.
    """
    hold = ProposedIntentReview()
    if (
        type(body) is not bytes or not (0 < len(body) <= _MAX_BODY_BYTES)
        or type(fixture_bot) is not str or fixture_bot not in _BOTS
    ):
        return hold
    try:
        doc = json.loads(
            body.decode("utf-8"),
            object_pairs_hook=_unique_pairs,
            parse_constant=_deny_nonfinite,
        )
    except (ValueError, TypeError, UnicodeError):
        return hold
    if not _valid_common(doc):
        return hold

    action = doc["action"]
    side = doc["side"]
    if action in _ENTRY:
        if set(doc) != _ENTRY_FIELDS:
            return hold
        # Retain the existing independently tested S1 entry contract.
        entry = inspect_sender_entry_request_offline(body=body)
        if entry.state != "review_only":
            return hold
        parsed_size = entry.parsed_size
        reduce_only = False
    elif action in _PYRAMID:
        # Only the Aggressive fixture can describe pyramiding; this is
        # NOT proof of real bot identity, ownership or remaining risk budget.
        if (
            fixture_bot != "aggressive" or set(doc) != _PYRAMID_FIELDS
            or side != ("long" if action == "pyramid_long" else "short")
            or _valid_size(doc["rounded_size"]) is None
            or not _valid_leverage(doc["requested_leverage"])
            or type(doc["parent_position_ref"]) is not str
            or _REF.fullmatch(doc["parent_position_ref"]) is None
        ):
            return hold
        parsed_size = doc["rounded_size"]
        reduce_only = False
    elif action == "protective_close":
        # A close must be explicit-size and REQUEST reduce-only. The caller's
        # snapshot/ownership assertion MUST be re-checked against real,
        # current exchange state by a future independently trusted server.
        if set(doc) != _PROTECT_FIELDS or doc.get("reduce_only") is not True:
            return hold
        close_size = _valid_size(doc["close_size"])
        observed = _valid_size(doc["observed_position_size"])
        if (
            close_size is None or observed is None or close_size > observed
            or type(doc["position_ref"]) is not str
            or _REF.fullmatch(doc["position_ref"]) is None
            or type(doc["exit_reason"]) is not str
            or doc["exit_reason"] not in _EXIT_REASONS
        ):
            return hold
        parsed_size = doc["close_size"]
        reduce_only = True
    elif action == "request_leverage":
        # Keep this separate from order entry. Client-proposed leverage
        # is never effective account leverage or an executable command.
        if (
            set(doc) != _LEVERAGE_FIELDS
            or not _valid_leverage(doc["requested_leverage"])
            or type(doc["parent_position_ref"]) is not str
            or _REF.fullmatch(doc["parent_position_ref"]) is None
        ):
            return hold
        parsed_size = None
        reduce_only = False
    else:
        return hold

    if action in _ENTRY and side != (
        "long" if action == "open_long" else "short"
    ):
        return hold

    return ProposedIntentReview(
        state="parsed_review_only_HOLD",
        reason="format only; no verified account/position or signing",
        fixture_bot=fixture_bot,
        parsed_action=action,
        parsed_coin=doc["coin"],
        parsed_size=parsed_size,
        requested_reduce_only=reduce_only,
    )
